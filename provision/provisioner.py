"""
provisioner.py
==============
Microservicio de aprovisionamiento: Fase 3 del Laboratorio de Integración.

Responsabilidades:
  1. Leer la tabla `usuarios` en PostgreSQL (fuente de la verdad de midPoint).
  2. Para cada usuario con rol 'AgenteCallCenter' y activo=TRUE:
       - Generar (o reutilizar) una extensión SIP y una contraseña segura.
       - Escribir/actualizar la tabla `extensiones_sip`.
  3. Regenerar el archivo `/etc/asterisk/agents/pjsip_agents.conf`
     (triadas endpoint/auth/aor, formato PJSIP).
  4. Notificar a Asterisk vía AMI ("pjsip reload") para que recargue
     la configuración PJSIP en caliente.
  5. Registrar cada acción en la tabla `auditoria` (ISO 27001 – A.8.16).
  6. Repetir cada POLL_INTERVAL segundos (modo demonio).
"""

import os
import time
import secrets
import string
import socket
import logging
import hashlib
from datetime import datetime

import psycopg2
import psycopg2.extras

# ─────────────────────────────────────────────
# Configuración (desde variables de entorno)
# ─────────────────────────────────────────────
DB_HOST      = os.getenv("DB_HOST",      "postgres")
DB_PORT      = int(os.getenv("DB_PORT",  "5432"))
DB_NAME      = os.getenv("DB_NAME",      "telecom")
DB_USER      = os.getenv("DB_USER",      "telecom")
DB_PASSWORD  = os.getenv("DB_PASSWORD",  "telecom123")

AMI_HOST     = os.getenv("AMI_HOST",     "asterisk")
AMI_PORT     = int(os.getenv("AMI_PORT", "5038"))
AMI_USER     = os.getenv("AMI_USER",     "provisioner")
AMI_SECRET   = os.getenv("AMI_SECRET",   "prov1234")

POLL_INTERVAL      = int(os.getenv("POLL_INTERVAL", "30"))
SIP_AGENTS_PATH = os.getenv("SIP_AGENTS_PATH", "/etc/asterisk/agents/pjsip_agents.conf")

# Rango de extensiones asignadas automáticamente
EXTENSION_START = 1001
EXTENSION_END   = 1099

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("provisioner")


# ─────────────────────────────────────────────
# Helpers de base de datos
# ─────────────────────────────────────────────

def get_db_connection():
    """Retorna una conexión psycopg2 al PostgreSQL del laboratorio."""
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
    )


def get_agentes_activos(conn) -> list[dict]:
    """
    Consulta todos los usuarios con rol 'AgenteCallCenter' y activo=TRUE.
    Regla de negocio principal (testeada en tests/test_provisioner.py).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, username, nombre, email
            FROM   usuarios
            WHERE  rol    = 'AgenteCallCenter'
              AND  activo = TRUE
            ORDER  BY id
        """)
        return cur.fetchall()


def get_extension_existente(conn, usuario_id: int) -> dict | None:
    """Devuelve la extensión SIP ya aprovisionada para un usuario, o None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM extensiones_sip WHERE usuario_id = %s",
            (usuario_id,)
        )
        return cur.fetchone()


def get_extensiones_en_uso(conn) -> set[str]:
    """Retorna el conjunto de extensiones ya asignadas."""
    with conn.cursor() as cur:
        cur.execute("SELECT extension FROM extensiones_sip")
        return {row["extension"] for row in cur.fetchall()}


def siguiente_extension_libre(extensiones_en_uso: set[str]) -> str:
    """
    Asigna la próxima extensión libre en el rango [EXTENSION_START, EXTENSION_END].
    Regla de negocio testeada (ver test_asignacion_extension).
    """
    for num in range(EXTENSION_START, EXTENSION_END + 1):
        ext = str(num)
        if ext not in extensiones_en_uso:
            return ext
    raise RuntimeError(
        f"No hay extensiones libres en el rango {EXTENSION_START}-{EXTENSION_END}"
    )


def generar_sip_secret(username: str) -> str:
    """
    Genera una contraseña SIP de 16 caracteres alfanuméricos.
    Determinista en base al username (para reproducibilidad en el lab).
    En producción se usaría secrets.token_urlsafe(16).
    """
    alphabet = string.ascii_letters + string.digits
    seed = hashlib.sha256(f"{username}:telecom-lab-salt".encode()).hexdigest()
    # Usar los primeros 16 caracteres del hash filtrados al alfabeto válido
    chars = [c for c in seed if c in alphabet]
    return "".join(chars[:16])


def crear_extension(conn, usuario_id: int, extension: str, sip_secret: str):
    """Inserta un nuevo registro en extensiones_sip y registra auditoría."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO extensiones_sip
                (usuario_id, extension, sip_secret, estado, aprovisionado_en, updated_at)
            VALUES (%s, %s, %s, 'APROVISIONADO', NOW(), NOW())
        """, (usuario_id, extension, sip_secret))
        registrar_auditoria(conn, cur, "CREAR_EXTENSION", usuario_id,
                            f"Extension {extension} creada", "OK")
    conn.commit()


def actualizar_estado_extension(conn, ext_id: int, estado: str, usuario_id: int):
    """Actualiza el estado de una extensión existente."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE extensiones_sip
            SET    estado = %s, updated_at = NOW()
            WHERE  id = %s
        """, (estado, ext_id))
        registrar_auditoria(conn, cur, f"ACTUALIZAR_EXTENSION_{estado}",
                            usuario_id, f"Estado -> {estado}", "OK")
    conn.commit()


def registrar_auditoria(conn, cur, accion: str, usuario_id: int | None,
                        detalle: str, resultado: str):
    """
    Inserta un registro en la tabla de auditoría.
    Cumple con ISO 27001 Control A.8.16 (Monitoreo de actividades).
    """
    cur.execute("""
        INSERT INTO auditoria (actor, accion, usuario_id, detalle, resultado)
        VALUES ('provisioner', %s, %s, %s, %s)
    """, (accion, usuario_id, detalle, resultado))


# ─────────────────────────────────────────────
# Generación de pjsip_agents.conf
# ─────────────────────────────────────────────

def generar_sip_agents_conf(agentes_con_extension: list[dict]) -> str:
    """
    Genera el contenido de pjsip_agents.conf a partir de los datos
    sincronizados. PJSIP requiere, por cada agente, tres secciones
    sorcery (mismo nombre de sección, distinguidas por 'type='):
      - type=endpoint : políticas de medios, contexto, codecs, callerid.
      - type=auth      : credenciales (equivalente al 'secret' de chan_sip).
      - type=aor       : dirección de contacto dinámica (equivalente a
                          host=dynamic en chan_sip).

    Regla de negocio: solo usuarios APROVISIONADOS y activos aparecen aquí.
    Esta función es la principal candidata a tests unitarios.

    Nota: el nombre de la función se mantiene (generar_sip_agents_conf)
    por compatibilidad con el resto del código y los tests, aunque desde
    la migración a PJSIP el contenido que produce y el archivo donde se
    escribe (pjsip_agents.conf) usan la sintaxis PJSIP.
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    lineas = [
        f"; pjsip_agents.conf — Generado automáticamente por el provisioner",
        f"; Última actualización: {timestamp}",
        f"; NO EDITAR MANUALMENTE — los cambios serán sobreescritos.",
        "",
    ]

    for agente in agentes_con_extension:
        ext        = agente["extension"]
        secret     = agente["sip_secret"]
        username   = agente["username"]
        nombre     = agente.get("nombre") or username

        lineas += [
            f"; Agente: {nombre} ({username})",
            f"[{ext}]",
            f"type=endpoint",
            f"context=interno",
            f"disallow=all",
            f"allow=ulaw",
            f"allow=alaw",
            f"auth={ext}",
            f"aors={ext}",
            f"callerid={nombre} <{ext}>",
            f"dtmf_mode=rfc4733",
            f"direct_media=no",
            f"rtp_symmetric=yes",
            f"force_rport=yes",
            f"rewrite_contact=yes",
            "",
            f"[{ext}]",
            f"type=auth",
            f"auth_type=userpass",
            f"username={ext}",
            f"password={secret}",
            "",
            f"[{ext}]",
            f"type=aor",
            f"max_contacts=1",
            f"remove_existing=yes",
            "",
        ]

    return "\n".join(lineas)


def escribir_sip_agents_conf(contenido: str):
    """Escribe el archivo generado en el volumen compartido con Asterisk."""
    os.makedirs(os.path.dirname(SIP_AGENTS_PATH), exist_ok=True)
    with open(SIP_AGENTS_PATH, "w", encoding="utf-8") as f:
        f.write(contenido)
    log.info(f"pjsip_agents.conf escrito en {SIP_AGENTS_PATH}")


# ─────────────────────────────────────────────
# Notificación a Asterisk vía AMI
# ─────────────────────────────────────────────

def ami_reload_sip():
    """
    Conecta al AMI de Asterisk y ejecuta un reload del módulo PJSIP
    para que Asterisk lea el nuevo pjsip_agents.conf sin reiniciarse.

    Requiere que el usuario AMI tenga la clase de privilegio 'command'
    en manager.conf (write = ...,command), o Asterisk responderá
    "Permission denied" aunque el login sea exitoso.
    """
    try:
        with socket.create_connection((AMI_HOST, AMI_PORT), timeout=5) as sock:
            banner = sock.recv(1024).decode()
            log.debug(f"AMI banner: {banner.strip()}")

            # Login
            login_cmd = (
                f"Action: Login\r\n"
                f"Username: {AMI_USER}\r\n"
                f"Secret: {AMI_SECRET}\r\n"
                f"\r\n"
            )
            sock.sendall(login_cmd.encode())
            resp = sock.recv(1024).decode()
            if "Success" not in resp:
                log.error(f"AMI login fallido: {resp.strip()}")
                return False

            # PJSIP Reload
            reload_cmd = "Action: Command\r\nCommand: pjsip reload\r\n\r\n"
            sock.sendall(reload_cmd.encode())
            sock.recv(1024)

            # Logoff
            sock.sendall(b"Action: Logoff\r\n\r\n")
            log.info("AMI: pjsip reload ejecutado exitosamente")
            return True

    except (ConnectionRefusedError, OSError) as e:
        log.warning(f"No se pudo conectar al AMI de Asterisk: {e}. "
                    f"Asterisk puede no estar listo todavía.")
        return False


# ─────────────────────────────────────────────
# Ciclo principal de sincronización
# ─────────────────────────────────────────────

def sincronizar(conn):
    """
    Ejecuta un ciclo completo de sincronización:
      1. Lee agentes activos de la BD.
      2. Asigna extensiones a los que no tienen.
      3. Regenera pjsip_agents.conf.
      4. Recarga Asterisk.
    """
    agentes = get_agentes_activos(conn)
    log.info(f"Agentes activos encontrados: {len(agentes)}")

    extensiones_en_uso = get_extensiones_en_uso(conn)
    agentes_con_ext = []

    for agente in agentes:
        ext_existente = get_extension_existente(conn, agente["id"])

        if ext_existente is None:
            # Nueva extensión: asignar y crear
            nueva_ext    = siguiente_extension_libre(extensiones_en_uso)
            sip_secret   = generar_sip_secret(agente["username"])
            crear_extension(conn, agente["id"], nueva_ext, sip_secret)
            extensiones_en_uso.add(nueva_ext)
            log.info(f"[NUEVO] {agente['username']} → extensión {nueva_ext}")
            agentes_con_ext.append({
                **agente,
                "extension":  nueva_ext,
                "sip_secret": sip_secret,
            })

        elif ext_existente["estado"] == "APROVISIONADO":
            # Ya aprovisionado: incluir en el conf sin cambios
            agentes_con_ext.append({
                **agente,
                "extension":  ext_existente["extension"],
                "sip_secret": ext_existente["sip_secret"],
            })

        else:
            log.info(f"[SKIP] {agente['username']} tiene extensión en estado "
                     f"{ext_existente['estado']}")

    # Generar y escribir el archivo
    contenido = generar_sip_agents_conf(agentes_con_ext)
    escribir_sip_agents_conf(contenido)

    # Notificar a Asterisk
    ami_reload_sip()

    # Log de auditoría del ciclo
    with conn.cursor() as cur:
        registrar_auditoria(conn, cur, "SYNC_COMPLETO", None,
                            f"{len(agentes_con_ext)} extensiones activas", "OK")
    conn.commit()
    return len(agentes_con_ext)


def main():
    log.info("=== Provisioner iniciado ===")
    log.info(f"Sincronizando cada {POLL_INTERVAL}s | BD: {DB_HOST}:{DB_PORT}/{DB_NAME}")

    while True:
        try:
            conn = get_db_connection()
            total = sincronizar(conn)
            log.info(f"Ciclo completado — {total} extensiones aprovisionadas.")
            conn.close()

        except psycopg2.OperationalError as e:
            log.warning(f"BD no disponible: {e}. Reintentando en {POLL_INTERVAL}s...")
        except Exception as e:
            log.error(f"Error inesperado: {e}", exc_info=True)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()