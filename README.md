# Infraestructura Unificada de Comunicaciones y Gestión de Identidad

Prototipo de microservicios dockerizado que integra **Asterisk (PBX/VoIP)** con **midPoint (Identity Governance)** y una base de datos compartida, bajo estándares de calidad **ISO/IEC 25010** y seguridad **ISO 27001**.

> Proyecto académico — Laboratorio de Integración de Sistemas.

---

## 🎯 Objetivo del Proyecto

Modernizar la gestión de identidad y la central telefónica de una empresa de telecomunicaciones del sector financiero, reemplazando sistemas legacy aislados por una arquitectura de microservicios donde:

- **midPoint** es la fuente de la verdad para usuarios y roles (RBAC).
- **Asterisk** gestiona el enrutamiento de llamadas VoIP y genera CDRs.
- Una **base de datos** centraliza tanto la configuración de identidad como los datos de negocio (usuarios, CDRs).
- Los **agentes** usan softphones para autenticarse con credenciales aprovisionadas automáticamente.

## 🧩 Componentes del Sistema

| Servicio | Imagen base | Puerto(s) | Función |
|---|---|---|---|
| `db` | `mariadb:10.6` | 3306 | Persistencia de usuarios, CDRs y repositorio midPoint |
| `midpoint` | `evolveum/midpoint` | 8080 | Gestión de identidad, RBAC, provisión automática |
| `asterisk` | personalizada (`debian:bullseye`) | 5060 (SIP), 10000-10100 (RTP) | PBX, dialplan, CDRs |
| Softphone | Linphone / Zoiper / MicroSIP (cliente local) | — | Punto de acceso del agente |

## 👥 Actores

- **Agente de Call Center**: realiza/recibe llamadas vía softphone.
- **Administrador de IAM**: gestiona usuarios y roles en midPoint/BD.
- **Administrador de Infraestructura (DevOps)**: despliega y mantiene el entorno Docker.
- **Auditor de Seguridad**: revisa logs y reportes de cumplimiento ISO 27001.

## 🚀 Cómo levantar el entorno

```bash
git clone <url-del-repositorio>
cd proyecto-telecom-iam
cp .env.example .env   # completar variables (contraseñas, etc.)
docker-compose up --build
```

- Consola midPoint: http://localhost:8080/midpoint (usuario por defecto `administrator`)
- Asterisk SIP: apuntar el softphone a la IP del host, puerto 5060.

## 🗂️ Estructura del repositorio

```
proyecto-telecom-iam/
├── docker-compose.yml
├── .env.example
├── README.md
├── docs/
│   └── Fase1_Planificacion_y_Requisitos.md
├── asterisk/
│   ├── Dockerfile
│   └── configs/ (pjsip.conf, extensions.conf)
├── midpoint/
│   ├── Dockerfile
│   └── resources/ (resource-asterisk.xml)
└── db/
    └── init.sql
```

## 📋 Metodología (SDLC)

Proyecto desarrollado en 5 sesiones siguiendo Scrum/Kanban:

1. **Planificación y Requisitos** (Product Owner) — *Sesión actual*
2. **Diseño y Configuración** (Arquitecto DevOps)
3. **Desarrollo/Integración** (Integrador)
4. **Pruebas de Seguridad y Calidad** (QA)
5. **Despliegue y Documentación** (Todos)

El backlog y el tablero Kanban se gestionan en [GitHub Projects](#) (issues por historia de usuario).

## ✅ Cumplimiento

- **ISO/IEC 25010**: fiabilidad, seguridad, interoperabilidad y mantenibilidad evaluadas mediante SonarQube y pruebas unitarias.
- **ISO 27001**: TLS en SIP, control de acceso vía midPoint (RBAC), logs de auditoría (control A.8.16).

## 👤 Equipo

| Integrante | Rol |
|---|---|
| Victor Cárdenas Fernández | Product Owner |
| ??? | Arquitecto DevOps |
| ??? | Arquitecto DevOps |
| ??? | Integrador / QA |