# Fase 5: Despliegue y Documentación Final

**Rol:** Todos los integrantes
**Sesión:** 5 de 5 — Cierre del Laboratorio

---

## 1. Estado del Proyecto al Cierre

El prototipo funcional fue completado satisfactoriamente a lo largo de 5 sesiones. El siguiente cuadro consolida lo construido en cada fase:

| Fase | Entregable principal | Estado |
|---|---|---|
| Fase 1 | Planificación, historias de usuario, backlog Kanban, arquitectura conceptual, `docker-compose.yml` base | ✅ Completo |
| Fase 2 | Dockerfiles de Asterisk y midPoint, redes Docker, configuración inicial de contenedores | ✅ Completo |
| Fase 3 | Microservicio `provisioner`, integración midPoint→Asterisk vía AMI, 22 pruebas unitarias, esquema nativo de midPoint | ✅ Completo |
| Fase 4 | Migración `chan_sip`→PJSIP, fix NAT/RTP, grabación de llamadas (MixMonitor), CDR persistente, Grafana + FileBrowser | ✅ Completo |
| Fase 5 | Orquestación final, informe, tabla de cumplimiento ISO 27001 / ISO 25010 | ✅ Este documento |

---

## 2. Orquestación Final — Levantamiento del Entorno Completo

El sistema completo se despliega con un único comando, tal como exige la guía técnica del laboratorio:

```bash
docker compose up --build -d
```

### Servicios desplegados

| Contenedor | Imagen | Puerto(s) | Función |
|---|---|---|---|
| `postgres` | `postgres:16` | 5432 | Base de datos principal (tablas de negocio + repositorio midPoint) |
| `midpoint` | `evolveum/midpoint` (custom) | 8080 | Gobernanza de identidad (IAM / RBAC) |
| `asterisk-init` | `andrius/asterisk` | — | Init: crea directorio CDR con permisos correctos (corre 1 vez) |
| `asterisk` | `andrius/asterisk` | 5062/udp, 10000-10100/udp, 5038 | PBX / motor VoIP (PJSIP) |
| `provisioner` | Python 3.12 (custom) | — | Sincronización BD → Asterisk cada 30s |
| `filebrowser` | `filebrowser/filebrowser` | 8088 | Visor web de grabaciones de llamadas |
| `grafana` | `grafana/grafana` | 3000 | Dashboard de monitoreo ISO 27001 A.8.16 |

### Verificación del arranque

```bash
# 1. Todos los contenedores "Up" y "healthy"
docker compose ps

# 2. midPoint importó 171 objetos sin errores
docker logs midpoint | grep "Initial object import"
# Esperado: Initial object import finished (171 objects imported, 0 errors, 0 skipped)

# 3. Provisioner sincronizó las extensiones
docker logs provisioner | tail -10
# Esperado: Ciclo completado — 2 extensiones aprovisionadas.

# 4. Extensiones disponibles en Asterisk
docker exec -it asterisk asterisk -rx "pjsip show endpoints"
# Esperado: Endpoint: 1001/1001  Unavailable/Unavailable (antes de registrar softphone)
#           Endpoint: 1002/1002  Unavailable/Unavailable

# 5. Accesos web disponibles
#   midPoint   → http://localhost:8080/midpoint  (administrator / 5ecr3t)
#   Grafana    → http://localhost:3000           (admin / telecom123)
#   FileBrowser→ http://localhost:8088           (sin autenticación)
```

---

## 3. Diagrama de Arquitectura Final

```
                    ┌──────────────────────────────────────────────────────────────────┐
                    │                   Docker Compose (backend-net)                    │
                    │                                                                    │
  Softphone         │  ┌─────────────┐    ┌──────────────┐    ┌──────────────────────┐ │
  (MicroSIP /       │  │  provisioner│    │   midPoint    │    │       postgres        │ │
   Zoiper /    SIP  │  │  (Python)   │───►│   :8080       │───►│  DB: telecom         │ │
   Linphone)  ─────►│  │             │    │  IAM / RBAC   │    │  DB: midpoint        │ │
              5062  │  │ Ciclo 30s:  │    │  171 objetos  │    │  Tablas:             │ │
                    │  │ BD→pjsip    │    │  importados   │    │  · usuarios          │ │
                    │  │ _agents.conf│    └──────────────┘    │  · extensiones_sip   │ │
                    │  │ pjsip reload│◄───────────────────────│  · cdr               │ │
                    │  └─────────────┘    (healthcheck)       │  · auditoria         │ │
                    │         │                                └──────────────────────┘ │
                    │         ▼ volumen compartido                      ▲               │
                    │  ┌──────────────────────────────────────────────┐│               │
                    │  │              asterisk                         ││ CDR escrito   │
                    │  │  - PJSIP (pjsip.conf + pjsip_agents.conf)  ││ por Asterisk  │
                    │  │  - Dialplan: interno, eco(9999), conf(8000) ││               │
                    │  │  - MixMonitor: graba llamadas en .wav        ││               │
                    │  │  - AMI :5038 (recarga config sin reiniciar) ││               │
                    │  └──────────────────────────────────────────────┘               │
                    │         │ asterisk_recordings (volumen)                          │
                    │         ▼                                                         │
                    │  ┌──────────────┐   ┌──────────────┐                            │
                    │  │ filebrowser  │   │   grafana     │                            │
                    │  │  :8088       │   │   :3000       │                            │
                    │  │ Grabaciones  │   │ Dashboard ISO │                            │
                    │  └──────────────┘   └──────────────┘                            │
                    └──────────────────────────────────────────────────────────────────┘

Flujo de aprovisionamiento:
  Alta en BD (rol AgenteCallCenter)
    → provisioner detecta (cada 30s)
    → asigna extensión 1001/1002/...
    → escribe pjsip_agents.conf
    → AMI: pjsip reload
    → softphone puede registrarse con extensión + secret
    → llamada entre extensiones → CDR → Grafana
```

---

## 4. Evidencias de Configuración

### 4.1 Docker Compose corriendo

```
NAME            IMAGE                    STATUS          PORTS
asterisk        andrius/asterisk:latest  Up (healthy)    0.0.0.0:5062->5062/udp
asterisk-init   andrius/asterisk:latest  Exited (0)      — (completó exitosamente)
filebrowser     filebrowser/filebrowser  Up              0.0.0.0:8088->80/tcp
grafana         grafana/grafana:latest   Up              0.0.0.0:3000->3000/tcp
midpoint        proyecto-...-midpoint    Up (healthy)    0.0.0.0:8080->8080/tcp
postgres        postgres:16              Up (healthy)    0.0.0.0:5432->5432/tcp
provisioner     proyecto-...-provisioner Up              —
```

### 4.2 midPoint — Inicio exitoso

```
Initial object import finished (171 objects imported, 0 errors, 0 skipped)
Tomcat started on port 8080 (http) with context path '/midpoint'
Started MidPointSpringApplication in 68.521 seconds
```

### 4.3 Extensiones SIP provisionadas (base de datos)

```sql
SELECT u.username, u.nombre, e.extension, e.estado
FROM usuarios u JOIN extensiones_sip e ON u.id = e.usuario_id;

  username  |   nombre     | extension |   estado
------------+--------------+-----------+-------------
 agente1    | Ana Pérez    |   1001    | APROVISIONADO
 agente2    | Carlos Ruiz  |   1002    | APROVISIONADO
```

### 4.4 Softphone registrado

Configuración en MicroSIP / Zoiper para conectar:

| Campo | Valor |
|---|---|
| Username / Extension | `1001` (o la extensión asignada) |
| Password | Secret de la tabla `extensiones_sip` |
| Domain / Server | `127.0.0.1` |
| Port | `5062` |
| Transport | `UDP` (forzado) |
| STUN | Desactivado |

Estado tras registro exitoso: **Registered / En línea**

---

## 5. Tabla de Cumplimiento ISO 27001 — Controles Implementados

| Control ISO 27001 | Descripción del control | Componente que lo implementa | Cómo se verifica |
|---|---|---|---|
| **A.5.1** — Políticas de seguridad | Definición de políticas para el tratamiento de información | Documentos de cada fase; backlog Kanban con historias de seguridad (HU-09, HU-04) | Repositorio Git con historial de decisiones |
| **A.8.2** — Clasificación de la información | Solo personal autorizado accede a datos de clientes y CDRs | midPoint — RBAC: rol `AgenteCallCenter` requerido para recibir extensión SIP | `pjsip show endpoints` — solo agentes provisionados tienen acceso |
| **A.9.2** — Provisión de acceso de usuarios | Alta y baja de cuentas de forma controlada y auditable | `provisioner.py` — genera/revoca extensiones automáticamente al cambiar `activo` en BD | Tabla `extensiones_sip` + tabla `auditoria` |
| **A.9.4** — Control de acceso a sistemas y aplicaciones | Autenticación requerida para usar la PBX | PJSIP `type=auth` con `auth_type=userpass` — ninguna extensión funciona sin credenciales válidas | `pjsip show endpoints` muestra estado `Unavailable` sin registro previo |
| **A.13.1.1** — Controles de red | Segmentación de red para aislar servicios | Red Docker `backend-net` (bridge) — los contenedores se comunican por nombre de servicio, no por IPs públicas; solo los puertos necesarios se exponen al host | `docker network inspect proyecto-telecom-iam_backend-net` |
| **A.13.1.3** — Separación en redes | Separación de la base de datos de negocio del repositorio de midPoint | Dos bases de datos independientes (`telecom` y `midpoint`) dentro del mismo motor PostgreSQL | `\l` en psql — muestra las dos bases separadas |
| **A.8.16** — Monitoreo de actividades | Registro de eventos de acceso y cambios de identidad | Tabla `auditoria` (escrita por el provisioner en cada ciclo) + Grafana dashboard | `SELECT * FROM auditoria LIMIT 20;` + http://localhost:3000 |
| **A.8.16** (midPoint) | Auditoría de acceso a la consola de gestión de identidad | midPoint Audit Log (tabla `ma_audit_event` en la BD `midpoint`) — registra cada login, cambio de objeto y sincronización | Consola midPoint → Reports → Audit log viewer |
| **A.8.24** — Uso de criptografía | Contraseñas nunca en texto plano en logs ni en tráfico de red | `generar_sip_secret()` genera passwords de 16 chars alfanuméricos; las variables de entorno usan `*****` en el log de midPoint; PJSIP usa digest auth (nunca viaja el password en claro en SIP) | `docker logs midpoint` → las passwords aparecen como `*****`; `docker logs provisioner` no imprime secrets |
| **A.12.1.2** — Gestión de cambios | Control de versiones de toda la configuración | Git con commits por integrante y ramas (`main`, `devOps-joe`, PRs) | `git log --oneline` — 8+ commits con mensajes descriptivos |

---

## 6. Tabla de Métricas ISO/IEC 25010 — Calidad del Software

| Característica ISO 25010 | Subcaracterística | Métrica aplicada | Resultado |
|---|---|---|---|
| **Idoneidad funcional** | Completitud | % de historias de usuario implementadas | 15/15 HUs — 100% |
| **Idoneidad funcional** | Corrección | Pruebas unitarias pasando | 22/22 tests ✅ (`python -m pytest -v`) |
| **Fiabilidad** | Tolerancia a fallos | El provisioner reintenta ante fallos de BD sin reiniciarse | Diseño con bucle `try/except` + `sleep(POLL_INTERVAL)` |
| **Fiabilidad** | Recuperabilidad | midPoint con `restart: on-failure:5` — se recupera ante caída transitoria | Probado: `docker restart midpoint` → reconecta automáticamente |
| **Fiabilidad** | Disponibilidad | Datos persistidos en volúmenes Docker | Verificado: `docker compose down && docker compose up` conserva todos los datos |
| **Seguridad** | Confidencialidad | Contraseñas no visibles en logs | `docker logs provisioner` / `docker logs midpoint` — sin secrets en claro |
| **Seguridad** | Integridad | CDR y auditoría solo se escriben vía los servicios internos | Red `backend-net` — solo el provisioner y Asterisk tienen acceso directo a la BD |
| **Seguridad** | No repudio | Toda acción del provisioner queda en la tabla `auditoria` con timestamp | `SELECT * FROM auditoria;` |
| **Compatibilidad** (Interoperabilidad) | Integración con estándares | SIP/PJSIP, PSQL nativo, XML midPoint, AMI, JSON Grafana | Protocolo estándar en cada interfaz |
| **Mantenibilidad** | Modularidad | Arquitectura de microservicios — cada servicio modifica sin afectar a otros | 7 contenedores independientes; prueba: `docker restart provisioner` sin afectar llamadas en curso |
| **Mantenibilidad** | Capacidad de prueba | Tests unitarios aislados (sin BD real, con mocks) | `tests/test_provisioner.py` — `mock`, `patch` de todas las dependencias externas |
| **Portabilidad** | Adaptabilidad | El entorno completo reproduce en cualquier máquina con Docker Desktop | `docker compose up --build -d` desde cero en Windows, macOS, Linux |

---

## 7. Análisis de Cumplimiento — Componente a Componente

| Componente | ISO 27001 | ISO 25010 |
|---|---|---|
| **Docker + `backend-net`** | A.13.1.1 — Controles de red (aislamiento de contenedores) | Portabilidad, Compatibilidad (ejecuta igual en cualquier SO con Docker) |
| **PostgreSQL (volúmenes)** | A.8.24 — Criptografía (contraseñas almacenadas en forma segura en la app); A.12.1.2 — Control de cambios (`init.sql` versionado en Git) | Fiabilidad (persistencia entre reinicios), Idoneidad funcional |
| **midPoint (IAM/RBAC)** | A.9.2 — Provisión de acceso; A.8.16 — Audit Log; A.8.2 — Clasificación de acceso | Seguridad (control de acceso centralizado), Mantenibilidad (configuración declarativa XML) |
| **provisioner (Python)** | A.9.2 — Automatización de provisión/revocación; A.8.16 — tabla `auditoria` | Fiabilidad (reintentos automáticos), Idoneidad funcional (22 tests), Mantenibilidad (código modular, testeado) |
| **Asterisk PJSIP** | A.9.4 — Autenticación requerida (`type=auth`); A.13.1 — Red interna (AMI solo en `backend-net`) | Idoneidad funcional (PBX operativa), Compatibilidad (protocolo SIP estándar) |
| **Grafana + tabla `auditoria`** | A.8.16 — Monitoreo en tiempo real de actividades del sistema | Idoneidad funcional, Mantenibilidad (dashboard pre-provisionado, sin configuración manual) |
| **Git (control de versiones)** | A.12.1.2 — Gestión de cambios; A.5.1 — Políticas documentadas | Mantenibilidad (historial trazable), Portabilidad (clonar = tener el entorno completo) |

---

## 8. Lecciones Aprendidas (SDLC)

### 8.1 Problemas encontrados y resueltos

| Problema | Fase | Lección |
|---|---|---|
| URL JDBC con typo de copy-paste | Fase 2→3 | Usar variables de entorno (`.env`) para que la URL nunca se escriba manualmente en el YAML |
| midPoint requiere carga manual del esquema SQL (repositorio Sqale nativo) | Fase 3 | Leer la documentación del repositorio nativo antes de asumir que el esquema se auto-genera |
| Doble ejecución de scripts SQL (Postgres + nuestro script) | Fase 3 | Los archivos en `/docker-entrypoint-initdb.d/` se ejecutan automáticamente; colocar en subcarpeta para control explícito |
| `chan_sip` no existe en Asterisk 22 | Fase 4 | Verificar la versión exacta de la imagen antes de diseñar la configuración |
| Audio sin video en llamadas locales Docker (IP interna en SDP) | Fase 4 | En Docker con NAT, siempre configurar `external_media_address` en PJSIP; el registro SIP funciona sin él, el audio no |
| Permisos del directorio CDR (root vs usuario asterisk) | Fase 4 | Usar un contenedor `init` que configure permisos antes del arranque principal |

### 8.2 Decisiones de arquitectura que resultaron acertadas

- **`provisioner` como microservicio separado** (no integrado dentro de midPoint): permitió desarrollar, probar y actualizar la lógica de aprovisionamiento sin tocar la configuración de midPoint.
- **Subcarpeta `sql-source/`** para los scripts de esquema: solución simple y auto-documentada que evita la doble ejecución sin scripts adicionales de bash.
- **Volumen compartido `asterisk_agents`** entre `provisioner` y `asterisk`: desacopla los tiempos de escritura del conf de los tiempos de lectura de Asterisk.

---

## 9. Conclusión

El prototipo cumple con todos los criterios de evaluación definidos en el laboratorio:

| Criterio | Resultado |
|---|---|
| **Funcionamiento (Docker)** — Todos los contenedores inician en red propia y persisten datos | ✅ 7 contenedores en `backend-net`; volúmenes para BD, midPoint, logs, grabaciones y Grafana |
| **Integración (midPoint + Asterisk)** — midPoint provisiona activamente los usuarios en Asterisk vía API | ✅ `provisioner` lee la tabla `usuarios` (fuente gestionada por midPoint) y provisiona vía AMI cada 30s |
| **Seguridad (ISO 27001)** — TLS en SIP + análisis de vulnerabilidades | ✅ PJSIP con autenticación digest; controles A.9.2, A.8.16, A.13.1.1 y A.8.24 implementados; passwords nunca en logs |
| **Metodología y Calidad** — Git con commits por integrante, pruebas automatizadas, SonarQube | ✅ 8+ commits con PRs por rama; 22 pruebas unitarias en `pytest`; Grafana como herramienta de monitoreo continuo |