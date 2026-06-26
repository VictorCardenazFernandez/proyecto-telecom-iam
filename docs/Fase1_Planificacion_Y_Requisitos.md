# Fase 1: Planificación y Requisitos
## Laboratorio de Integración de Sistemas — Infraestructura Unificada de Comunicaciones y Gestión de Identidad

**Rol responsable de esta sesión:** Product Owner
**Sesión:** 1 de 5

---

## 1. Alcance del Sistema (Resumen Ejecutivo)

El proyecto consiste en construir un **prototipo funcional dockerizado** que demuestre la modernización de la plataforma de atención al cliente de una empresa de telecomunicaciones del sector financiero. El sistema actual depende de centrales telefónicas legacy desconectadas de la gestión de usuarios, lo que genera procesos manuales lentos (~4.5 minutos por registro) y vulnerabilidades de seguridad.

La solución propuesta reemplaza ese modelo monolítico por una **arquitectura de microservicios** orquestada con Docker Compose, donde:

- **midPoint** actúa como la "fuente de la verdad" para identidades y roles (RBAC).
- **Asterisk (PBX)** gestiona el enrutamiento de llamadas VoIP, generando CDRs.
- Una **base de datos relacional** (MariaDB/PostgreSQL) persiste tanto el repositorio de configuración de midPoint como las tablas de usuarios/clientes.
- **Softphones** (Linphone, Zoiper, MicroSIP) permiten a los agentes autenticarse y realizar llamadas con credenciales sincronizadas automáticamente.

El sistema debe cumplir con controles de seguridad alineados a **ISO 27001** (cifrado TLS para SIP, autenticación centralizada, logs de auditoría trazables) y con atributos de calidad de **ISO/IEC 25010** (fiabilidad, seguridad, interoperabilidad, mantenibilidad).

**Flujo de valor central (de extremo a extremo):**

```
Alta de usuario en BD (rol "AgenteCallCenter")
        ↓
midPoint detecta el cambio (Synchronization)
        ↓
midPoint provisiona la extensión SIP vía API/script en Asterisk (pjsip.conf)
        ↓
Agente se autentica desde su Softphone con las credenciales generadas
        ↓
Se realiza una llamada entre extensiones → se genera un CDR
        ↓
El CDR se almacena en la base de datos para auditoría/reportes
```

**Fuera de alcance (para esta iteración):** integración con sistemas de facturación reales del banco, IVR avanzado con IA/reconocimiento de voz, despliegue en producción/nube (se trabajará en entorno local con Docker), grabación de llamadas persistente a largo plazo.

---

## 2. Definición de Componentes — ¿Qué hace exactamente cada uno?

### 2.1 Asterisk (Motor de Comunicación / PBX)
**Responsabilidad principal:** ser el motor VoIP del sistema.

- Actúa como **PBX (Private Branch Exchange)**: recibe registros SIP de los softphones y los autentica.
- **Enrutamiento de llamadas**: define el *dialplan* (`extensions.conf`) que decide cómo se conecta una extensión con otra (ej. extensión 1001 llama a 1002).
- **Gestión de extensiones** vía `pjsip.conf`: cada agente tiene un usuario SIP (extensión + contraseña) que es creado/actualizado dinámicamente a partir de lo que indique midPoint.
- **Generación de CDRs (Call Detail Records)**: cada llamada genera un registro (origen, destino, duración, fecha, estado) que se escribe en la base de datos.
- **Seguridad de capa de transporte**: soporta TLS/SRTP para cifrar la señalización SIP y el audio (RTP), evitando que credenciales o conversaciones viajen en texto plano.
- **No decide quién tiene permiso de qué** — esa lógica de negocio (roles, accesos) vive en midPoint; Asterisk solo ejecuta lo que midPoint le indica.

**Imagen base:** contenedor personalizado sobre `debian:bullseye` que compila Asterisk con los módulos necesarios (chan_pjsip, app_queue, cdr_*, res_srtp).
**Puertos expuestos:** `5062/udp-tcp` (SIP), `10000-10100/udp` (RTP).

---

### 2.2 midPoint (Gestión de Identidad / IAM)
**Responsabilidad principal:** ser el **orquestador de identidades** y la fuente de la verdad del sistema (Identity Governance & Administration).

- **Gestión de usuarios y roles (RBAC)**: define roles como `AgenteCallCenter`, `Supervisor`, `Administrador`, cada uno con permisos distintos (quién puede llamar a quién, quién accede a reportes de CDRs, etc.).
- **Conector/Recurso hacia la Base de Datos**: lee la tabla de usuarios/clientes de la BD (recurso tipo "Scripted SQL" o similar) para detectar altas, bajas y cambios.
- **Sincronización (Synchronization / Provisioning)**: cuando detecta que un usuario nuevo tiene el rol `AgenteCallCenter`, ejecuta un *mapping* que:
  - genera una extensión SIP y una contraseña,
  - provisiona esa extensión en Asterisk (vía script/API que escribe en `pjsip.conf` o usa AMI/ARI).
- **Autenticación centralizada**: actúa como punto único de gestión de credenciales, evitando que cada sistema (Asterisk, BD, futuras apps) mantenga su propio set de usuarios.
- **Auditoría (ISO 27001 – A.8.16)**: registra quién inició sesión, qué cambios de identidad ocurrieron y a qué recursos se les dio acceso, generando logs/reportes consultables.

**Imagen base:** `evolveum/midpoint`.
**Puerto expuesto:** `8080` (consola web administrativa).
**Depende de:** la base de datos (su propio repositorio de configuración).

---

### 2.3 Base de Datos (MariaDB / PostgreSQL)
**Responsabilidad principal:** ser la **capa de persistencia** compartida del ecosistema.

Almacena dos tipos de información claramente separados (en esquemas/bases de datos distintos dentro del mismo motor, o en instancias separadas si se prefiere):

1. **Repositorio de configuración de midPoint**: objetos del sistema (usuarios, roles, recursos, tareas de sincronización, logs de auditoría de midPoint).
2. **Datos de negocio del call center**:
   - Tabla `usuarios`/`clientes`: identidad base que midPoint lee como fuente para provisionar (nombre, correo, rol, estado activo/inactivo).
   - Tabla `cdr` (Call Detail Records): registros de llamadas generados por Asterisk (origen, destino, duración, timestamp, disposición de la llamada).

**Imagen base:** `mariadb:10.6` (según guía técnica del laboratorio) o `postgres` si el equipo decide usarla para CDRs.
**Puerto expuesto:** `3306` (MariaDB) / `5432` (PostgreSQL).
**Consideraciones de seguridad:** contraseñas gestionadas vía variables de entorno (`.env`), nunca hardcodeadas; volúmenes Docker para persistencia de datos entre reinicios.

---

### 2.4 Softphone (Frontend del Agente)
**Responsabilidad principal:** ser el **punto de acceso del agente de call center** a la central telefónica.

- Aplicación cliente SIP (Linphone, Zoiper, MicroSIP o un softphone WebRTC embebido en navegador).
- Se configura con los parámetros provistos automáticamente por la sincronización midPoint → Asterisk: **servidor (IP del contenedor Asterisk), puerto 5062, número de extensión y contraseña (secret)**.
- Permite **registrarse** contra el PBX (estado "Registrado"), **recibir y realizar llamadas** entre extensiones.
- No almacena lógica de negocio ni credenciales maestras: solo consume lo que el ecosistema (midPoint + Asterisk) ya configuró.

---

## 3. Actores del Sistema

| Actor | Tipo | Descripción | Interactúa con |
|---|---|---|---|
| **Agente de Call Center** | Usuario final | Persona que atiende llamadas de clientes; usa un softphone para registrarse y comunicarse. | Softphone, Asterisk (vía SIP) |
| **Supervisor / Administrador de IAM** | Usuario administrativo | Da de alta/baja usuarios y asigna roles desde midPoint o directamente en la BD de usuarios. | midPoint (consola web), Base de Datos |
| **Administrador de Infraestructura (DevOps)** | Usuario técnico | Despliega y mantiene el entorno Docker; configura redes, volúmenes y variables de entorno. | Docker Compose, todos los contenedores |
| **Auditor de Seguridad (ISO 27001)** | Usuario de control | Consulta logs y reportes de auditoría (quién accedió, qué cambios de identidad ocurrieron). | midPoint (reportes), logs de Asterisk |
| **Sistema midPoint** | Actor de software | Orquestador automático de identidades; actúa sin intervención humana directa una vez configurado. | Base de Datos, Asterisk |
| **Sistema Asterisk (PBX)** | Actor de software | Motor de telefonía que ejecuta el enrutamiento y genera CDRs. | Softphones, Base de Datos (CDRs) |
| **Cliente final (del banco)** | Actor externo (implícito) | Persona que llama y es atendida por un agente. No interactúa directamente con el sistema interno, pero su llamada es el evento que dispara el flujo. | Softphone del agente (vía PBX) |

---

## 4. Historias de Usuario (Product Backlog inicial)

Formato: *Como [actor], quiero [acción], para [beneficio/objetivo]*.

### Épica A — Gestión de Identidad y Acceso (midPoint)
1. **HU-01** — Como administrador de IAM, quiero dar de alta un nuevo agente en la base de datos con el rol "AgenteCallCenter", para que el sistema lo reconozca automáticamente como personal autorizado.
2. **HU-02** — Como sistema midPoint, quiero detectar (vía sincronización periódica o por evento) los nuevos registros con rol "AgenteCallCenter" en la base de datos, para iniciar su provisión automática.
3. **HU-03** — Como sistema midPoint, quiero generar una extensión SIP y una contraseña segura para cada nuevo agente, para que pueda autenticarse en Asterisk sin intervención manual.
4. **HU-04** — Como administrador de IAM, quiero poder desactivar a un agente (baja) y que su extensión SIP quede deshabilitada automáticamente, para evitar accesos no autorizados (cumplimiento ISO 27001 – control de acceso).
5. **HU-05** — Como auditor de seguridad, quiero generar un reporte desde midPoint que muestre quién inició sesión y a qué extensión accedió, para cumplir con el requisito de trazabilidad (A.8.16).

### Épica B — Telefonía / PBX (Asterisk)
6. **HU-06** — Como agente de call center, quiero registrar mi softphone usando la extensión y contraseña generadas por midPoint, para poder recibir y realizar llamadas.
7. **HU-07** — Como agente de call center, quiero realizar una llamada a otra extensión interna, para comunicarme con un compañero o probar el sistema.
8. **HU-08** — Como sistema Asterisk, quiero generar un CDR por cada llamada realizada (origen, destino, duración, estado), para que quede registro en la base de datos.
9. **HU-09** — Como administrador de infraestructura, quiero que las comunicaciones SIP estén cifradas con TLS, para evitar que las credenciales o el audio viajen en texto plano (ISO 27001).

### Épica C — Infraestructura y Persistencia (Docker / Base de Datos)
10. **HU-10** — Como administrador de infraestructura, quiero levantar todo el ecosistema (BD, midPoint, Asterisk) con un único comando `docker-compose up --build`, para garantizar reproducibilidad del entorno.
11. **HU-11** — Como administrador de infraestructura, quiero que los datos de la base de datos persistan en volúmenes Docker, para no perder información al reiniciar los contenedores.
12. **HU-12** — Como administrador de infraestructura, quiero definir una red interna (bridge) entre los contenedores, para que se comuniquen entre sí sin exponer puertos innecesarios al exterior.

### Épica D — Calidad y Cumplimiento
13. **HU-13** — Como tester/QA, quiero ejecutar análisis estático de código (SonarQube) sobre los scripts de configuración y mappings, para medir mantenibilidad y fiabilidad (ISO/IEC 25010).
14. **HU-14** — Como tester/QA, quiero ejecutar pruebas unitarias sobre las reglas de mapeo de midPoint, para validar que la lógica de asignación de extensiones funciona correctamente.
15. **HU-15** — Como Product Owner, quiero contar con un repositorio Git con commits individuales por integrante y un README claro, para asegurar trazabilidad del desarrollo y facilitar la evaluación.

---

## 5. Product Backlog — Tablero Kanban Inicial

El backlog se organiza en columnas Kanban: **To Do | In Progress | Review | Done**, y se prioriza según la dependencia técnica natural del proyecto (primero infraestructura base, luego integración, luego seguridad/calidad).

### Priorización sugerida (orden de ejecución a través de las sesiones 2-5)

| Prioridad | Historia de Usuario | Sesión objetivo | Responsable sugerido |
|---|---|---|---|
| 1 | HU-10 — Docker Compose básico (BD + midPoint + Asterisk levantan) | Sesión 2 | Arquitecto DevOps |
| 2 | HU-12 — Red interna entre contenedores | Sesión 2 | Arquitecto DevOps |
| 3 | HU-11 — Volúmenes persistentes | Sesión 2 | Arquitecto DevOps |
| 4 | HU-01 — Alta de agente en BD con rol "AgenteCallCenter" | Sesión 3 | Integrador |
| 5 | HU-02 — Recurso/sincronización midPoint ↔ BD | Sesión 3 | Integrador |
| 6 | HU-03 — Provisión automática de extensión SIP en Asterisk | Sesión 3 | Integrador |
| 7 | HU-06 — Registro de softphone con credenciales generadas | Sesión 3-4 | Todos |
| 8 | HU-07 — Llamada de prueba entre extensiones | Sesión 4 | Todos |
| 9 | HU-08 — Generación y persistencia de CDR | Sesión 4 | Integrador |
| 10 | HU-09 — TLS en SIP | Sesión 4 | Arquitecto DevOps |
| 11 | HU-04 — Baja automática de agente | Sesión 4 | Integrador |
| 12 | HU-05 — Reporte de auditoría midPoint | Sesión 4 | Tester/QA |
| 13 | HU-13 — Análisis SonarQube | Sesión 4 | Tester/QA |
| 14 | HU-14 — Pruebas unitarias de mappings | Sesión 3-4 | Integrador |
| 15 | HU-15 — Repositorio, README, commits | Sesión 1 (base) → continuo | Product Owner |

### Tablero Kanban — Estado al cierre de la Sesión 1

| **To Do** | **In Progress** | **Review** | **Done** |
|---|---|---|---|
| HU-01 a HU-14 (todas las técnicas) | Terminado | — | HU-15 — Repositorio creado, README inicial, docker-compose base definido |
| | | | Documento de Planificación y Requisitos (este documento) |
| | | | Definición de actores y arquitectura conceptual |

> **Nota:** Este tablero debe replicarse en GitHub Projects (o GitHub Issues + labels) para que cada historia de usuario sea un *issue* independiente, asignable a un integrante y movible entre columnas durante las sesiones 2-5.

---

## 6. Arquitectura Conceptual Inicial

### 6.1 Diagrama de componentes (vista lógica)

```
                         ┌─────────────────────────────┐
                         │        Docker Compose         │
                         │   (orquesta el ciclo de vida)  │
                         └───────────────┬────────────────┘
                                          │
        ┌─────────────────────┬──────────┴──────────┬─────────────────────┐
        │                      │                     │                     │
        ▼                      ▼                     ▼                     ▼
┌───────────────┐     ┌──────────────────┐  ┌──────────────────┐   ┌──────────────┐
│   Softphone     │     │     Asterisk       │  │     midPoint       │   │   Base de    │
│ (Linphone/      │◄───►│  (PBX / VoIP Core) │◄►│ (IAM / RBAC /      │◄─►│   Datos      │
│  Zoiper/Web)    │ SIP │  - dialplan        │  │  Provisioning)     │   │ (MariaDB /   │
│                 │     │  - pjsip.conf      │  │  - Recurso SQL     │   │  PostgreSQL) │
│                 │     │  - CDRs            │  │  - Synchronization │   │ - usuarios   │
└───────────────┘     └──────────────────┘  └──────────────────┘   │ - cdr        │
                                                                       │ - midpoint_db │
                                                                       └──────────────┘

Flujo de datos:
1. Alta de usuario (rol AgenteCallCenter) → tabla `usuarios` en BD
2. midPoint lee BD (Recurso Scripted SQL) → detecta cambio
3. midPoint provisiona extensión SIP → escribe/actualiza pjsip.conf en Asterisk
4. Softphone se registra contra Asterisk usando extensión + secret
5. Llamada entre extensiones → Asterisk genera CDR → se guarda en BD
6. midPoint genera reportes de auditoría (acceso, cambios de identidad)
```

### 6.2 Vista de red Docker (preliminar)

- **Red interna `backend-net` (bridge):** conecta `db`, `midpoint`, `asterisk` — comunicación privada, sin exposición innecesaria.
- **Puertos publicados al host:**
  - `8080` → midPoint (consola administrativa).
  - `5062/udp` + `10000-10100/udp` → Asterisk (SIP/RTP), necesarios para que los softphones externos al contenedor (en la máquina del agente) se conecten.
  - `3306` (o `5432`) → Base de datos, expuesto solo si se requiere acceso externo para depuración (en producción se recomendaría no publicarlo).
- **Volúmenes:**
  - `db_data` → persistencia de la base de datos.
  - `asterisk_config` → persistencia de `pjsip.conf` / `extensions.conf` (para que la provisión de midPoint sobreviva a reinicios del contenedor).
  - `midpoint_data` → persistencia del repositorio de configuración de midPoint.

### 6.3 Mapeo con atributos de calidad (ISO/IEC 25010) y seguridad (ISO 27001)

| Componente | Atributo ISO 25010 priorizado | Control ISO 27001 relacionado |
|---|---|---|
| Asterisk | Fiabilidad (continuidad del servicio de llamadas) | A.13.1 — Seguridad de redes; cifrado TLS/SRTP |
| midPoint | Seguridad, Interoperabilidad | A.9 — Control de acceso (RBAC); A.8.16 — Monitoreo |
| Base de Datos | Fiabilidad, Mantenibilidad | A.8.24 — Cifrado de credenciales en reposo |
| Docker (redes/volúmenes) | Compatibilidad/Portabilidad | A.13.1.1 — Controles de red (segmentación) |
| Conjunto del sistema | Idoneidad funcional | A.5 — Políticas de seguridad de la información |

*(Esta tabla se ampliará en la Fase 5 con evidencia concreta, según el entregable "Análisis de Cumplimiento" del laboratorio.)*

---

## 7. Próximos Pasos (transición a Fase 2)

1. Crear el repositorio en GitHub (ver sección 8) con la estructura de carpetas definida.
2. Publicar este documento, el README.md y el `docker-compose.yml` base como primer commit.
3. Configurar el tablero Kanban en GitHub Projects con las 15 historias de usuario como issues.
4. Pasar a **Fase 2 (Arquitecto DevOps)**: construcción de los `Dockerfile` de Asterisk y midPoint, y configuración de la red `backend-net`.

---

## 8. Estructura del Proyecto (Paso 1 de la guía técnica)

```
proyecto-telecom-iam/
├── docker-compose.yml
├── .env.example
├── README.md
├── docs/
│   ├── Fase1_Planificacion_y_Requisitos.md
│   └── diagrama-arquitectura.png
├── asterisk/
│   ├── Dockerfile
│   └── configs/
│       ├── pjsip.conf
│       └── extensions.conf
├── midpoint/
│   ├── Dockerfile
│   └── resources/
│       └── resource-asterisk.xml
└── db/
    └── init.sql
```