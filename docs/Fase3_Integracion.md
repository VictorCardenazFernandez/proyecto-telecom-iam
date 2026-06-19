# Fase 3: Desarrollo / Configuración de Integración 

**Rol:** Integrador + Soporte
**Sesión:** 3 de 5
**Estado:** ✅ Entorno verificado y operativo (171 objetos iniciales importados, 0 errores)

---

## 1. Resumen Ejecutivo

Esta fase tomó la infraestructura básica de la Fase 2 (contenedores `postgres`, `midpoint` y `asterisk` levantados pero sin comunicación entre sí) y construyó la **integración real**: un microservicio `provisioner` que lee usuarios desde PostgreSQL y aprovisiona automáticamente sus extensiones SIP en Asterisk, con midPoint como gobernanza de identidad.

Durante el levantamiento se encontraron y resolvieron **5 problemas en cadena**, típicos de integrar un sistema complejo (midPoint) con un repositorio de base de datos nativo por primera vez. Esta sección documenta cada uno como parte de la trazabilidad del SDLC, ya que todos dejaron una corrección permanente en el código del proyecto.

---

## 2. Bitácora de Incidencias y Resolución (Troubleshooting Log)

> Documentar esta bitácora es parte del entregable de calidad de la Fase 4 (ISO/IEC 25010 — Fiabilidad) y de la auditoría ISO 27001 (gestión de cambios).

### Incidencia 1 — URL JDBC mal formada (heredada de Fase 2)

**Síntoma:** midPoint no lograba conectarse a PostgreSQL; la URL contenía texto de un comando de terminal pegado por error (`jdbc:postgresql://postgres:543docker exec -it midpoint bash2/midpoint`).

**Diagnóstico:** revisión manual del `docker-compose.yml`.

**Corrección:**
```yaml
MP_SET_midpoint_repository_jdbcUrl: "jdbc:postgresql://postgres:5432/midpoint"
```

---

### Incidencia 2 — Esquema de base de datos inexistente

**Síntoma:**
```
ERROR: relation "m_global_metadata" does not exist
```

**Diagnóstico:** midPoint 4.10.3 usa el repositorio nativo **Sqale** (PostgreSQL nativo), que —a diferencia del repositorio legacy basado en Hibernate— **no genera su esquema automáticamente** al primer arranque. El esquema debe cargarse manualmente desde los scripts SQL que la propia imagen de midPoint incluye en `/opt/midpoint/doc/config/sql/native/`.

**Corrección:** se extrajeron de la imagen oficial y se incorporaron al proyecto:
- `postgres-schema.sql` (esquema principal, objetos `m_*`)
- `postgres-quartz.sql` (tablas del scheduler `qrtz_*`)
- `postgres-audit.sql` (tablas de auditoría `ma_audit_event` y relacionadas)

```powershell
docker create --name temp-midpoint evolveum/midpoint:latest
docker cp temp-midpoint:/opt/midpoint/doc/config/sql/native/postgres.sql ./db/postgres-schema.sql
docker cp temp-midpoint:/opt/midpoint/doc/config/sql/native/postgres-quartz.sql ./db/postgres-quartz.sql
docker cp temp-midpoint:/opt/midpoint/doc/config/sql/native/postgres-audit.sql ./db/postgres-audit.sql
docker rm -f temp-midpoint
```

---

### Incidencia 3 — Tabla de auditoría faltante bloqueaba la importación inicial

**Síntoma:**
```
Caught PSQLException for insert into ma_audit_event (...)
Couldn't import systemConfiguration:00000000-0000-0000-0000-000000000001
```

**Diagnóstico:** al arrancar, midPoint intenta crear el objeto `SystemConfiguration` y, **en la misma transacción**, escribir un registro de auditoría. Como `postgres-audit.sql` aún no se había incorporado en ese momento, la tabla `ma_audit_event` no existía, la transacción completa fallaba (`FATAL_ERROR`) y el objeto `SystemConfiguration` nunca se creaba — dejando el sistema en un estado "a medias" (otros objetos sí se crearon, pero el núcleo de configuración no).

**Corrección:** incorporación de `postgres-audit.sql` al proceso de carga (ver Incidencia 2).

---

### Incidencia 4 — Doble ejecución de los scripts SQL (causa raíz de la inestabilidad)

**Síntoma:** Postgres se caía (`Exited (3)`) justo después de cargar el esquema, con el error:
```
ERROR: type "objecttype" already exists
```

**Diagnóstico — la causa raíz real de toda la inestabilidad observada:** Postgres **ejecuta automáticamente** cualquier archivo `.sql` que encuentre en `/docker-entrypoint-initdb.d/`. Como `postgres-schema.sql`, `postgres-quartz.sql` y `postgres-audit.sql` estaban montados *directamente* en esa carpeta, Postgres los corría por su cuenta — y **además**, nuestro propio script `02-load-midpoint-schema.sh` (que también vive ahí) los volvía a ejecutar manualmente vía `psql -f`. Resultado: cada script corría dos veces, el segundo intento chocaba con objetos ya creados, y el proceso de inicialización de Postgres abortaba con el contenedor completo.

**Corrección:** los 3 archivos `.sql` se montan en una **subcarpeta** (`sql-source/`) dentro de `docker-entrypoint-initdb.d/`. Postgres **ignora automáticamente las subcarpetas** (confirmado en el log: `ignoring /docker-entrypoint-initdb.d/sql-source`), por lo que solo nuestro script los ejecuta, una única vez, en el orden correcto.

---

### Incidencia 5 — `UnknownHostException: postgres` (síntoma, no causa)

**Síntoma:** midPoint no podía resolver el nombre `postgres` por DNS interno de Docker.

**Diagnóstico:** no era un problema de red ni de DNS — `postgres` simplemente **no estaba corriendo** en ese momento (consecuencia directa de la Incidencia 4). Confirmado con `docker ps -a`, que mostró `postgres` en estado `Exited (3)`.

**Corrección:** al resolver la Incidencia 4, este síntoma desapareció — es la prueba de que diagnosticar por la causa raíz (y no solo reiniciar servicios) era el camino correcto.

---

## 3. Arquitectura Final de Aprovisionamiento

```
PostgreSQL (telecom + midpoint)
   │
   ├─ BD "telecom": tabla usuarios, extensiones_sip, cdr, auditoria
   └─ BD "midpoint": esquema nativo Sqale (m_*, qrtz_*, ma_audit_event)
            │
            ▼
   midPoint (IAM / RBAC)
   - SystemConfiguration ✅
   - 171 objetos iniciales (conectores, roles base, dashboards) ✅
   - Recurso "BD Usuarios" (pendiente de importar)
            │
            ▼
   provisioner (microservicio Python)
   - Lee usuarios con rol AgenteCallCenter + activo=TRUE
   - Asigna extensión SIP (1001-1099) + secret
   - Genera sip_agents.conf
   - Notifica a Asterisk vía AMI (sip reload)
            │
            ▼
   Asterisk (PBX)
   - Carga sip_agents.conf dinámicamente
   - Softphones se registran y llaman entre extensiones
```

---

## 4. Estructura Final del Proyecto

```
proyecto-telecom-iam/
├── docker-compose.yml              ← corregido (JDBC + montaje sql-source/)
├── db/
│   ├── init.sql                    ← tablas de negocio (usuarios, extensiones_sip, cdr, auditoria)
│   ├── postgres-schema.sql         ← NUEVO — esquema nativo midPoint
│   ├── postgres-quartz.sql         ← NUEVO — tablas del scheduler
│   ├── postgres-audit.sql          ← NUEVO — tablas de auditoría
│   └── 02-load-midpoint-schema.sh  ← NUEVO — orquesta la carga, una sola vez
├── asterisk/
│   ├── sip.conf
│   ├── extensions.conf
│   └── manager.conf
├── midpoint/
│   ├── Dockerfile
│   └── resources/
│       ├── resource-db-usuarios.xml
│       └── role-agente-call-center.xml
├── provision/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── provisioner.py
├── tests/
│   ├── requirements-test.txt
│   └── test_provisioner.py
└── docs/
    └── Fase3_Integracion.md (este documento)
```

---

## 5. `docker-compose.yml` Final (servicio `postgres`)

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
      - db_data:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/01-init.sql
      - ./db/02-load-midpoint-schema.sh:/docker-entrypoint-initdb.d/02-load-midpoint-schema.sh
      # Los .sql de midPoint van en una subcarpeta para que Postgres
      # NO los auto-ejecute (Postgres ignora subcarpetas).
      # Solo 02-load-midpoint-schema.sh los invoca, una única vez.
      - ./db/postgres-schema.sql:/docker-entrypoint-initdb.d/sql-source/postgres-schema.sql
      - ./db/postgres-quartz.sql:/docker-entrypoint-initdb.d/sql-source/postgres-quartz.sql
      - ./db/postgres-audit.sql:/docker-entrypoint-initdb.d/sql-source/postgres-audit.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U telecom -d telecom"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - backend-net

  midpoint:
    build:
      context: ./midpoint
    container_name: midpoint
    environment:
      MP_SET_midpoint_repository_jdbcUrl: "jdbc:postgresql://postgres:5432/midpoint"
      MP_SET_midpoint_repository_jdbcUsername: "telecom"
      MP_SET_midpoint_repository_jdbcPassword: "telecom123"
      MP_SET_midpoint_repository_database: "postgresql"
      MP_SET_midpoint_repository_missingSchemaAction: "create"
      JAVA_OPTS: "-Xmx2048m"
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - midpoint_data:/opt/midpoint/var
      - ./midpoint/resources:/opt/midpoint/var/import:ro
    networks:
      - backend-net
```

---

## 6. `db/02-load-midpoint-schema.sh` Final

```bash
#!/bin/bash
set -e
echo "Cargando esquema nativo de midPoint en la base 'midpoint'..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "midpoint" \
     -f /docker-entrypoint-initdb.d/sql-source/postgres-schema.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "midpoint" \
     -f /docker-entrypoint-initdb.d/sql-source/postgres-quartz.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "midpoint" \
     -f /docker-entrypoint-initdb.d/sql-source/postgres-audit.sql
echo "Esquema de midPoint cargado correctamente."
```

> ⚠️ Guardar siempre con saltos de línea **LF** (no CRLF) — verificar en la barra inferior de VS Code antes de cada commit. Agregar `*.sh text eol=lf` en `.gitattributes` para que Git no lo revierta a CRLF automáticamente en Windows.

---

## 7. Procedimiento de Levantamiento Limpio (Verificado)

```powershell
# 1. Asegurar que Docker Desktop está corriendo
docker info

# 2. Bajar todo y borrar volúmenes (estado limpio garantizado)
docker-compose down -v

# 3. Levantar el stack completo
docker-compose up --build -d

# 4. Verificar que los 4 contenedores están "Up" y "healthy"
docker ps

# 5. Verificar el log de Postgres (debe terminar en "ready to accept connections"
#    y mostrar "Esquema de midPoint cargado correctamente.")
docker logs postgres --tail 100

# 6. Verificar el log de midPoint (debe terminar en "Tomcat started on port 8080"
#    y "Initial object import finished (171 objects imported, 0 errors, 0 skipped)")
docker logs midpoint --tail 60

# 7. Abrir la consola web
# http://localhost:8080/midpoint
```

**Resultado verificado en este proyecto:**
```
✔ postgres    Up X minutes (healthy)
✔ midpoint    Up X minutes (healthy)
✔ provisioner Up X minutes
✔ asterisk    Up X minutes (healthy)

Initial object import finished (171 objects imported, 0 errors, 0 skipped)
Tomcat started on port 8080 (http) with context path '/midpoint'
Started MidPointSpringApplication in 68.521 seconds
```

---

## 8. Próximos Pasos (continuación de la Fase 3 / transición a Fase 4)

1. **Login en la consola midPoint** (`administrator` / contraseña impresa en el log de arranque o `5ecr3t` por defecto según versión).
2. **Importar los recursos personalizados:**
   - Menú → *Import object* → subir `midpoint/resources/resource-db-usuarios.xml`
   - Menú → *Import object* → subir `midpoint/resources/role-agente-call-center.xml`
3. **Probar la conexión del recurso** (`Resources` → "BD Usuarios" → `Test connection`).
4. **Verificar que el `provisioner`** está sincronizando correctamente:
   ```powershell
   docker logs provisioner -f
   docker exec -it postgres psql -U telecom -d telecom -c "SELECT * FROM extensiones_sip;"
   ```
5. **Prueba de extremo a extremo:** registrar un softphone con una extensión generada y realizar una llamada de prueba (extensión `9999` = eco).
6. Esto cierra el entregable central de la Fase 3 y deja el sistema listo para la **Fase 4 — Pruebas de Seguridad y Calidad** (SonarQube, TLS en SIP, análisis de vulnerabilidades Docker).

---

## 9. Pruebas Unitarias (sin cambios respecto al diseño original — 22/22 ✅)

```bash
pip install -r tests/requirements-test.txt
python -m pytest tests/test_provisioner.py -v
```

| Suite | Tests | Qué valida |
|---|---|---|
| `TestFiltradoAgentes` | 2 | Solo usuarios con rol `AgenteCallCenter` + `activo=TRUE` son procesados |
| `TestAsignacionExtension` | 5 | Rango correcto (1001-1099), sin duplicados, error si rango lleno |
| `TestGeneracionSipSecret` | 5 | Longitud ≥16, alfanumérico, determinista, único por usuario |
| `TestGeneracionSipAgentsConf` | 7 | Formato Asterisk válido, codecs, encabezado, agente sin nombre |
| `TestLogicaSincronizacion` | 3 | Nuevo agente recibe extensión, aprovisionado no se duplica, desactivado no aparece |

---

## 10. Lección Aprendida (para el informe final de la Fase 5)

La causa raíz más costosa de diagnosticar (Incidencia 4) no era un error de configuración de midPoint, sino un **conflicto de mecanismos de inicialización**: tanto Postgres como nuestro propio script intentaban "hacerse cargo" de la misma tarea sin saberlo. Esto refuerza un principio de buena arquitectura de contenedores: **un solo proceso debe ser dueño de cada responsabilidad de inicialización**, y cualquier archivo que no deba auto-ejecutarse debe colocarse explícitamente fuera del directorio de auto-arranque (`docker-entrypoint-initdb.d/`).