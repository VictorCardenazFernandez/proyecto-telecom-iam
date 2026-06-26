# Fase 4: Migración a PJSIP y Validación de Calidad/Seguridad

**Rol:** Tester / QA (Todos)
**Sesión:** 4 de 5

---

## Resumen ejecutivo

Al iniciar la Fase 4 se detectó que el entorno heredado de la Fase 3 estaba construido sobre `chan_sip`, el canal SIP clásico de Asterisk. La imagen Docker usada en este proyecto (`andrius/asterisk:latest`) empaqueta **Asterisk 22.x**, versión en la que `chan_sip` ya **no existe** en el binario (Asterisk lo retiró del core a partir de la rama 21). Esto se manifestó como el error `No such command 'sip show peers'`.

Se migró toda la pila de configuración de `chan_sip` a **PJSIP** (el único canal SIP soportado en esta versión), y durante la verificación funcional con softphones reales se identificaron y corrigieron tres problemas adicionales de red/NAT propios de correr Docker Desktop sobre Windows. Al cierre de esta fase, el sistema fue verificado **end-to-end**: registro de extensiones, llamada real con audio bidireccional entre dos extensiones, y CDR persistido correctamente.

---

## 1. Migración de chan_sip a PJSIP

### Archivos modificados / creados / eliminados

| Archivo | Acción | Motivo |
|---|---|---|
| `asterisk/sip.conf` | **Eliminado** | `chan_sip` no existe en Asterisk 22; el archivo ya no aplica |
| `asterisk/pjsip.conf` | **Creado** | Reemplaza a `sip.conf`: transporte UDP 5062 + include de extensiones generadas |
| `asterisk/extensions.conf` | Modificado | `Dial(SIP/${EXTEN})` → `Dial(PJSIP/${EXTEN})` |
| `asterisk/manager.conf` | Modificado | Se agregó la clase de privilegio `command` al usuario AMI del provisioner (sin ella, `Action: Command` devuelve "Permission denied") |
| `docker-compose.yml` | Modificado | El volumen monta `pjsip.conf` en vez de `sip.conf` |
| `provision/provisioner.py` | Modificado | Genera 3 secciones PJSIP por agente (`type=endpoint` / `type=auth` / `type=aor`) en vez de una sola `type=friend` de chan_sip; escribe a `pjsip_agents.conf`; el AMI ejecuta `pjsip reload` en vez de `sip reload` |
| `tests/test_provisioner.py` | Modificado | Se actualizó el test que verificaba el formato de chan_sip. **Las 22 pruebas siguen pasando.** |

### Detalle de `pjsip.conf`

Cada agente provisionado por midPoint genera, en `pjsip_agents.conf`, una tríada de objetos PJSIP (a diferencia de chan_sip, que usaba una sola sección `type=friend`):

```ini
[1001]
type=endpoint
context=interno
disallow=all
allow=ulaw
allow=alaw
auth=1001
aors=1001
...

[1001]
type=auth
auth_type=userpass
username=1001
password=<sip_secret>

[1001]
type=aor
max_contacts=1
remove_existing=yes
```

---

## 2. Corrección de NAT/RTP para pruebas con softphones reales

Una vez migrado a PJSIP, el registro de extensiones funcionó, pero las llamadas de prueba (incluyendo la extensión de eco `9999`) **no tenían audio**, a pesar de conectar correctamente. Se diagnosticó paso a paso:

### Bitácora de diagnóstico

| Síntoma | Causa raíz | Corrección |
|---|---|---|
| Rango RTP no coincidía con lo publicado en Docker (Asterisk usa 10000-20000 por defecto; Docker solo publica 10000-10100) | No existía `rtp.conf` | Se creó `asterisk/rtp.conf` fijando `rtpstart=10000` / `rtpend=10100` |
| Aun con el rango correcto, cero paquetes RTP llegaban al contenedor (confirmado con `rtp set debug on`) | Asterisk anunciaba en el SDP su **IP interna de Docker** (ej. `172.20.0.2`), inalcanzable desde Windows. El registro SIP sí funcionaba porque usa `rport`/aprendizaje automático, pero el audio requiere que Asterisk declare explícitamente una dirección alcanzable | Se agregó `external_media_address=127.0.0.1` y `external_signaling_address=127.0.0.1` en `[transport-udp]` de `pjsip.conf` |
| Error transitorio `405 Method Not Allowed` en ambos softphones tras varios intentos fallidos de un cliente | Estado de transacción SIP atascado en PJSIP por reintentos previos fallidos (certificado TLS, timeout) | `docker compose restart asterisk` limpió el estado; tras reconfigurar el cliente (transporte UDP forzado, STUN desactivado) el registro volvió a funcionar |

### Archivos modificados / creados

| Archivo | Acción |
|---|---|
| `asterisk/rtp.conf` | **Creado** — `rtpstart=10000`, `rtpend=10100`, `strictrtp=no` |
| `asterisk/pjsip.conf` | Modificado — se agregó `external_media_address` / `external_signaling_address` en `[transport-udp]` |
| `docker-compose.yml` | Modificado — se monta `./asterisk/rtp.conf` |

> **Nota técnica:** `strictrtp=no` se dejó activo por estabilidad en este entorno de laboratorio (NAT de Docker Desktop). El ajuste que realmente resolvió el problema fue `external_media_address`; `strictrtp=yes` (el valor por defecto, más seguro) podría volver a probarse ahora que la dirección anunciada es correcta, como mejora opcional de seguridad para el informe de cumplimiento.

> **Importante para el equipo:** `external_media_address=127.0.0.1` asume que el softphone de prueba corre **en la misma máquina** donde corre Docker (que es el escenario validado). Si alguien del equipo prueba con un softphone en otro dispositivo de su red local, este valor tendría que apuntar a la IP LAN de su máquina en lugar de `127.0.0.1` — no es necesario para correr el proyecto, pero es bueno saberlo si alguien quiere repetir la prueba desde un celular.

---

## 3. Corrección del CDR (Call Detail Records)

Al verificar que las llamadas quedaran registradas en `/var/log/asterisk/cdr-csv/Master.csv` (paso de verificación pedido en el PDF del laboratorio), se encontraron dos problemas en cadena:

1. El directorio `cdr-csv` no existía dentro del contenedor → Asterisk fallaba con `Unable to open file ... No such file or directory`.
2. Al crear el directorio manualmente, quedaba con dueño `root` (por defecto en `docker exec`), pero el proceso de Asterisk corre como usuario `asterisk` → `Permission denied`.

### Solución permanente

Se agregó un servicio de inicialización (`asterisk-init`) en `docker-compose.yml` que corre **una sola vez**, antes de que arranque Asterisk, y crea el directorio con los permisos correctos. Esto evita que cada integrante del equipo tenga que ejecutar `mkdir`/`chown` manualmente al clonar el repo.

```yaml
asterisk-init:
  image: andrius/asterisk:latest
  container_name: asterisk-init
  entrypoint: ["sh", "-c", "mkdir -p /var/log/asterisk/cdr-csv && chown -R asterisk:asterisk /var/log/asterisk/cdr-csv && echo 'cdr-csv listo'"]
  volumes:
    - asterisk_logs:/var/log/asterisk
  networks:
    - backend-net
```

El servicio `asterisk` ahora depende de que `asterisk-init` termine exitosamente (`condition: service_completed_successfully`) antes de arrancar, y comparte el mismo volumen `asterisk_logs` (que también hace que el CDR **persista** entre reinicios del contenedor — relevante para el criterio de evaluación "los contenedores... persisten datos").

### Archivo modificado

| Archivo | Acción |
|---|---|
| `docker-compose.yml` | Modificado — nuevo servicio `asterisk-init`, nuevo volumen `asterisk_logs` montado en `asterisk`, se quitó la línea `version` obsoleta |

---

## 4. Cómo levantar el entorno completo (Fase 4)

Para cualquier integrante del equipo que clone el repo desde cero:

```bash
# 1. Levantar todos los servicios (incluye el init de permisos del CDR)
docker compose up -d --build

# 2. Verificar que todo esté arriba
docker compose ps

# 3. Confirmar el rango RTP cargado
docker exec -it asterisk asterisk -rx "rtp show settings"
# Esperado: Port start: 10000 / Port end: 10100

# 4. Ver extensiones provisionadas en la BD
docker exec -it postgres psql -U telecom -d telecom -c \
  "SELECT u.username, u.nombre, e.extension, e.sip_secret, e.estado FROM usuarios u JOIN extensiones_sip e ON u.id = e.usuario_id;"

# 5. Confirmar endpoints PJSIP creados
docker exec -it asterisk asterisk -rx "pjsip show endpoints"
```

### Configurar un softphone de prueba (MicroSIP, Zoiper, Linphone — cualquiera con soporte PJSIP/UDP)

| Campo | Valor |
|---|---|
| Username | el `extension` de la tabla (ej. `1001`) |
| Password | el `sip_secret` de la tabla |
| Domain/Host | `127.0.0.1` (si el softphone corre en la misma máquina que Docker) |
| Puerto | `5062` |
| Transporte | **UDP** (forzarlo explícitamente; algunos clientes intentan TLS por defecto) |
| STUN | Desactivado (innecesario en pruebas locales, puede causar fallos de registro) |

### Verificar la llamada y el CDR

```bash
# Marcar 9999 desde un softphone = prueba de eco (debe escucharse la propia voz)
# Marcar entre dos extensiones registradas = llamada real

# Verificar el CDR (en Windows/Git Bash, anteponer MSYS_NO_PATHCONV=1)
MSYS_NO_PATHCONV=1 docker exec -it asterisk cat /var/log/asterisk/cdr-csv/Master.csv
```

### Nota para integrantes en Windows (Git Bash / MINGW64)

Git Bash convierte automáticamente rutas que empiezan con `/` a rutas de Windows antes de pasarlas a `docker exec`, lo que rompe comandos como `cat /var/log/...`. Si ven un error con una ruta tipo `C:/Program Files/Git/...`, antepongan `MSYS_NO_PATHCONV=1` al comando, o ejecuten una sola vez por sesión:

```bash
export MSYS_NO_PATHCONV=1
```

---

## 5. Verificación funcional realizada (evidencia)

- ✅ `pjsip show endpoints` — extensiones `1001` y `1002` creadas automáticamente por el provisioner a partir de los roles asignados en midPoint.
- ✅ Registro exitoso de dos softphones distintos (MicroSIP y Zoiper) contra las extensiones provisionadas.
- ✅ Prueba de audio en extensión de eco (`9999`) — audio bidireccional confirmado.
- ✅ Llamada real entre `1001` y `1002` — conectada, con audio, colgada normalmente.
- ✅ CDR verificado en `/var/log/asterisk/cdr-csv/Master.csv` con el detalle de la llamada (origen, destino, duración).
- ✅ Las 22 pruebas unitarias de `provisioner.py` siguen pasando tras la migración a PJSIP.

**Pendiente de captura para el informe final:** screenshots de `docker compose ps`, del log de arranque de midPoint, del softphone en estado "Registrado", de `pjsip show endpoints`, del `Master.csv`, y video de 2-3 min de la llamada (Prueba de Concepto pedida en el PDF).

---

## 6. Pendiente de la Fase 4 (próximos pasos)

Con la infraestructura ya validada funcionalmente, falta cubrir el resto de los entregables de "Pruebas de Seguridad y Calidad" pedidos en el PDF:

1. **Análisis de calidad de código** — SonarQube (contenedorizado) sobre `provision/provisioner.py` y `tests/test_provisioner.py`.
2. **Análisis de vulnerabilidades de imágenes Docker** — Trivy sobre `andrius/asterisk`, `evolveum/midpoint`, `postgres:16` y la imagen propia del `provisioner`.
3. **Auditoría de seguridad** — confirmar que las contraseñas no aparecen en texto plano en los logs; generar reporte de auditoría desde midPoint (Audit Log Viewer) cubriendo el control ISO 27001 **A.8.16**.
4. **Pruebas básicas de carga/penetración** — contra el propio entorno (ej. SIPp para simular llamadas, `nmap` para confirmar que solo los puertos necesarios están expuestos).
5. **Tabla de cumplimiento ISO 27001 / ISO 25010** para el informe final, relacionando cada componente (Docker, PJSIP, midPoint, `external_media_address`, el servicio `asterisk-init`, etc.) con una cláusula/métrica concreta.

---

## 7. Checklist para subir a GitHub

Archivos que deben quedar en el repositorio (commit) para que el resto del equipo pueda clonar y levantar el entorno sin repetir este proceso de depuración:

```
asterisk/pjsip.conf          (nuevo)
asterisk/rtp.conf            (nuevo)
asterisk/extensions.conf     (modificado)
asterisk/manager.conf        (modificado)
docker-compose.yml           (modificado)
provision/provisioner.py     (modificado)
tests/test_provisioner.py    (modificado)
docs/Fase4_Validacion.md     (nuevo — este documento)
```

Archivo que debe **eliminarse** del repositorio:

```
asterisk/sip.conf            (eliminar — ya no se usa, chan_sip no existe en Asterisk 22)
```

```bash
git rm asterisk/sip.conf
git add asterisk/pjsip.conf asterisk/rtp.conf asterisk/extensions.conf \
        asterisk/manager.conf docker-compose.yml provision/provisioner.py \
        tests/test_provisioner.py docs/Fase4_Validacion.md
git commit -m "Fase 4: migración chan_sip -> PJSIP, fix NAT/RTP y CDR persistente"
git push
```