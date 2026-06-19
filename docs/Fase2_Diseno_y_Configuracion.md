# Fase 2: Diseño y Configuración
## Laboratorio de Integración de Sistemas — Infraestructura Unificada de Comunicaciones y Gestión de Identidad

**Rol responsable de esta sesión:** Arquitecto DevOps (2 integrantes)
**Sesión:** 2 de 5
**Entregable según guía:** Configuración de los Dockerfile para Asterisk y midPoint. Configuración de redes virtuales entre contenedores.

---

## 1. Objetivo de la Sesión

Pasar de la planificación (Fase 1) a un **entorno técnico levantado**: los tres servicios base del laboratorio (`postgres`, `midpoint`, `asterisk`) ejecutándose como contenedores Docker, comunicándose entre sí, listos para que en la Fase 3 el Integrador conecte la lógica de aprovisionamiento automático.

> En esta sesión **no** se implementa todavía la sincronización midPoint ↔ Asterisk (eso es Fase 3). El objetivo es exclusivamente **infraestructura**: que los contenedores existan, se vean entre sí en la red Docker, y cada uno cargue su configuración mínima de arranque.

---

## 2. Decisiones de Arquitectura Tomadas en esta Sesión

| Decisión | Detalle | Justificación |
|---|---|---|
| Motor de base de datos | Se usó **PostgreSQL 16** en lugar de MariaDB (sugerido originalmente en la guía) | El equipo priorizó PostgreSQL por compatibilidad nativa con el conector `DatabaseTable` de midPoint y por ser el motor recomendado oficialmente por Evolveum para producción. |
| Imagen de Asterisk | Se usó la imagen pública `andrius/asterisk:latest` en lugar de compilar una imagen propia sobre `debian:bullseye` | Acelera el levantamiento inicial del entorno; ya trae Asterisk compilado con los módulos `chan_sip` necesarios para esta fase. *(Nota: se podrá migrar a una imagen personalizada en fases posteriores si se requiere PJSIP o módulos adicionales).* |
| Imagen de midPoint | Imagen oficial `evolveum/midpoint:latest`, con `Dockerfile` propio para futuras extensiones | Permite, en fases siguientes, copiar recursos (XMLs) o scripts de arranque sin modificar la imagen base. |
| Red Docker | Red `bridge` por defecto de Docker Compose (`networks.default`) | Suficiente para esta fase: los tres contenedores se resuelven entre sí por nombre de servicio (`postgres`, `midpoint`, `asterisk`). En fases posteriores se evaluará una red dedicada (`backend-net`) para mayor aislamiento. |
| Orden de arranque | `midpoint` depende de `postgres` (`condition: service_healthy`); `asterisk` depende de `midpoint` | Evita que midPoint intente conectarse a una base de datos que aún no aceptó conexiones, y refleja la dependencia lógica (Asterisk recibirá las cuentas SIP gestionadas por midPoint en fases posteriores). |

---

## 3. Componentes Configurados

### 3.1 Servicio `postgres`

```yaml
postgres:
  image: postgres:16
  container_name: postgres
  environment:
    POSTGRES_DB: telecom
    POSTGRES_USER: telecom
    POSTGRES_PASSWORD: telecom123
  ports:
    - "5432:5432"
  volumes:
    - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U telecom -d telecom"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 30s
```

**Qué hace:**
- Levanta PostgreSQL con una base de datos `telecom` y un usuario `telecom`.
- Ejecuta `db/init.sql` automáticamente en el primer arranque (mecanismo nativo de la imagen oficial de Postgres: todo `.sql` en `/docker-entrypoint-initdb.d/` se corre una sola vez, al crear el volumen de datos).
- Incluye un **healthcheck** con `pg_isready`, usado por `midpoint` para esperar a que la base esté realmente lista antes de intentar conectarse (no solo que el contenedor haya iniciado).

**`db/init.sql` (estado al cierre de la Fase 2):**

```sql
-- BD de negocio: usuarios del call center
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    password VARCHAR(100) NOT NULL,
    rol VARCHAR(50) NOT NULL
);

INSERT INTO usuarios (username, password, rol) VALUES
  ('agente1', '123456', 'AgenteCallCenter'),
  ('agente2', '123456', 'AgenteCallCenter');

-- BD separada para midPoint (él crea sus propias tablas al arrancar)
CREATE DATABASE midpoint;
```

En esta fase se crea la tabla `usuarios` con datos de prueba mínimos y se reserva una base de datos `midpoint` separada, para que el repositorio interno de midPoint no se mezcle con las tablas de negocio del call center.

> ⚠️ **Nota de seguridad para Fase 4:** las contraseñas (`123456`, `telecom123`) están en texto plano. Esto es aceptable como placeholder de laboratorio en esta fase, pero debe corregirse antes de la auditoría de seguridad ISO 27001 (hashing de contraseñas, variables `.env`, secretos fuera del repositorio).

---

### 3.2 Servicio `midpoint`

```yaml
midpoint:
  build:
    context: ./midpoint
  container_name: midpoint
  environment:
    MP_SET_midpoint_repository_jdbcUrl: "jdbc:postgresql://postgres:5432/midpoint"
    MP_SET_midpoint_repository_jdbcUsername: "telecom"
    MP_SET_midpoint_repository_jdbcPassword: "telecom123"
    MP_SET_midpoint_repository_database: "postgresql"
    JAVA_OPTS: "-Xmx2048m"
  ports:
    - "8080:8080"
  depends_on:
    postgres:
      condition: service_healthy
```

**`midpoint/Dockerfile`:**

```dockerfile
FROM evolveum/midpoint:latest

EXPOSE 8080
```

**Qué hace:**
- Construye una imagen propia (aunque por ahora idéntica a la oficial) para tener un punto de extensión propio del equipo.
- Configura midPoint, vía variables de entorno `MP_SET_*` (mecanismo nativo de la imagen de Evolveum para sobreescribir `config.xml`), para que su repositorio interno use **PostgreSQL** en lugar de la base H2 embebida por defecto.
- Expone la consola web de administración en el puerto `8080` (`http://localhost:8080/midpoint`).
- Espera a que `postgres` esté saludable (`service_healthy`) antes de arrancar.

> 🐞 **Incidencia detectada y corregida:** en el primer intento de configuración, la variable `MP_SET_midpoint_repository_jdbcUrl` contenía un error de copiado/pegado de un comando de terminal (`jdbc:postgresql://postgres:543docker exec -it midpoint bash2/midpoint`), lo que impedía que midPoint se conectara a la base de datos. Se corrigió a `jdbc:postgresql://postgres:5432/midpoint`. Esta corrección se documenta como parte de la lección aprendida en gestión de configuración (control de versiones, revisión de PR antes de merge).

---

### 3.3 Servicio `asterisk`

```yaml
asterisk:
  image: andrius/asterisk:latest
  container_name: asterisk
  ports:
    - "5060:5060/udp"
    - "10000-10100:10000-10100/udp"
  volumes:
    - ./asterisk/sip.conf:/etc/asterisk/sip.conf
    - ./asterisk/extensions.conf:/etc/asterisk/extensions.conf
  depends_on:
    - midpoint
```

**`asterisk/sip.conf` (configuración manual de prueba):**

```ini
[general]
context=default
allowguest=no
bindport=5060
bindaddr=0.0.0.0

[1001]
type=friend
secret=1234
host=dynamic
context=interno

[1002]
type=friend
secret=1234
host=dynamic
context=interno
```

**`asterisk/extensions.conf` (dialplan de prueba):**

```ini
[interno]

exten => 1001,1,Dial(SIP/1001,20)
 same => n,Hangup()

exten => 1002,1,Dial(SIP/1002,20)
 same => n,Hangup()
```

**Qué hace:**
- Define **dos extensiones SIP de prueba** (`1001` y `1002`) creadas manualmente, con contraseña fija `1234`, para validar que el motor de telefonía funciona de extremo a extremo (registro + llamada) **antes** de automatizar la creación de cuentas en la Fase 3.
- Publica los puertos `5060/udp` (señalización SIP) y el rango `10000-10100/udp` (medios RTP, audio) hacia el host, necesarios para que softphones externos al contenedor (en la máquina del agente) puedan registrarse y transmitir audio.
- El dialplan permite que la extensión `1001` llame a la `1002` y viceversa, con un timeout de 20 segundos.

> ⚠️ **Deuda técnica conocida para Fase 3:** las credenciales `1001/1234` y `1002/1234` están hardcodeadas en el archivo de configuración. Este es exactamente el problema que la Fase 3 resuelve: reemplazar estas entradas manuales por un archivo `sip_agents.conf` generado automáticamente a partir de lo que midPoint sincroniza desde la base de datos.

---

## 4. Configuración de Red entre Contenedores

En esta fase se usó la red `bridge` por defecto que Docker Compose crea automáticamente para el proyecto (`networks: default: driver: bridge`). Esto es suficiente para que:

- `midpoint` resuelva `postgres` por nombre de servicio (DNS interno de Docker).
- `asterisk` dependa de que `midpoint` haya iniciado (aunque en esta fase aún no exista comunicación funcional directa entre ambos; esa integración llega en la Fase 3).
- Los tres contenedores compartan el mismo namespace de red del proyecto, sin necesidad de IPs fijas.

```
        red "default" (bridge, autogenerada por Docker Compose)
   ┌───────────────────────────────────────────────────────┐
   │                                                          │
   │   ┌───────────┐      ┌────────────┐      ┌───────────┐  │
   │   │ postgres   │◄────│  midpoint   │      │ asterisk   │  │
   │   │ :5432      │     │  :8080      │      │ :5060/udp  │  │
   │   └───────────┘      └────────────┘      │ :10000-     │  │
   │                                            │ 10100/udp  │  │
   │                                            └───────────┘  │
   └───────────────────────────────────────────────────────┘
              ▲                    ▲                  ▲
              │                    │                  │
         host:5432            host:8080         host:5060/udp
                                                  host:10000-10100/udp
```

**Validación de red realizada en esta sesión:**

```bash
docker-compose up --build -d
docker ps                                    # los 3 contenedores en estado "Up"
docker exec -it midpoint ping -c 2 postgres  # resuelve por nombre de servicio
docker logs postgres                          # confirma "database system is ready to accept connections"
docker logs midpoint                          # confirma conexión exitosa al repositorio
docker logs asterisk                          # confirma arranque sin errores de sip.conf
```

---

## 5. Estado del Proyecto al Cierre de la Fase 2

| Componente | Estado | Pendiente para Fase 3 |
|---|---|---|
| `postgres` | ✅ Levantado, con tabla `usuarios` y BD `midpoint` creadas | Ampliar esquema (tablas `extensiones_sip`, `cdr`, `auditoria`) |
| `midpoint` | ✅ Levantado, conectado a PostgreSQL, consola accesible en `:8080` | Importar recurso (`resource-db-usuarios.xml`) y rol `AgenteCallCenter` |
| `asterisk` | ✅ Levantado, con 2 extensiones de prueba hardcodeadas (`1001`, `1002`) | Reemplazar por generación automática vía `sip_agents.conf` + AMI |
| Red Docker | ✅ Red `bridge` funcional, contenedores se resuelven por nombre | Evaluar red dedicada `backend-net` y restricción de puertos expuestos |
| Integración midPoint ↔ Asterisk | ❌ No existe aún (fuera de alcance de esta fase) | Es el entregable central de la Fase 3 |

---

## 6. Commits realizados en esta sesión (control de versiones)

```
9113964  Readme y docker compose inicial
6ac7996  Fase1 corregida
d2db174  PostgreSQL levantado, midpoint levantado, asterisk levantado
efa57c5  Merge pull request #1 (rama devOps)
```

> Se recomienda para la Fase 3 en adelante usar un commit por historia de usuario del backlog (HU-01, HU-02, etc.) para facilitar la trazabilidad exigida en el criterio de evaluación de "Metodología y Calidad".

---

## 7. Cómo levantar el entorno de esta fase

```bash
git clone <url-del-repositorio>
cd proyecto-telecom-iam
docker-compose up --build -d
docker ps
```

- Consola midPoint: http://localhost:8080/midpoint
- Asterisk SIP: configurar un softphone (Zoiper/Linphone/MicroSIP) con servidor = IP del host, puerto `5060`, extensión `1001` o `1002`, contraseña `1234`.

---

## 8. Transición a Fase 3

Con la infraestructura base verificada, la Fase 3 (Integrador) toma este `docker-compose.yml` como punto de partida para:

1. Corregir el typo en la URL JDBC de midPoint.
2. Agregar el microservicio `provisioner` que automatiza lo que aquí se hizo manualmente en `sip.conf`.
3. Ampliar `db/init.sql` con las tablas de soporte (`extensiones_sip`, `cdr`, `auditoria`).
4. Habilitar el AMI de Asterisk (`manager.conf`) para permitir recargas de configuración en caliente.
