# Fase 3: Desarrollo / Configuración de Integración

**Rol:** Integrador + Soporte  
**Sesión:** 3 de 5

---

## Qué se construyó en esta sesión

### 1. Corrección del docker-compose.yml (bug heredado)

La URL JDBC en `midpoint.environment` estaba rota en la Fase 2:

```
# ANTES (roto):
MP_SET_midpoint_repository_jdbcUrl: "jdbc:postgresql://postgres:543docker exec -it midpoint bash2/midpoint"

# DESPUÉS (corregido):
MP_SET_midpoint_repository_jdbcUrl: "jdbc:postgresql://postgres:5432/midpoint"
```

### 2. Nuevo microservicio: `provisioner`

Se agrega el servicio `provisioner` al stack Docker. Su función es ser el **puente automático** entre midPoint/BD y Asterisk.

**Flujo de aprovisionamiento:**

```
BD (tabla usuarios)
      │  SELECT WHERE rol='AgenteCallCenter' AND activo=TRUE
      ▼
provisioner.py  ──────► tabla extensiones_sip  (asigna ext 1001, 1002…)
      │
      ├─► genera /etc/asterisk/agents/sip_agents.conf
      │
      └─► AMI (puerto 5038): "sip reload"  ──► Asterisk carga las nuevas cuentas
```

### 3. Esquema de BD ampliado (`db/init.sql`)

Se agregaron las tablas:

| Tabla | Función |
|---|---|
| `usuarios` | Fuente de identidades (ya existía, se amplió con `activo`, `nombre`, `email`) |
| `extensiones_sip` | Estado del aprovisionamiento por usuario |
| `cdr` | Registros de llamadas generados por Asterisk |
| `auditoria` | Log de acciones del provisioner (ISO 27001 – A.8.16) |

### 4. Recursos midPoint

- **`resource-db-usuarios.xml`**: define el conector DatabaseTable que lee la tabla `usuarios`. Configura los mappings de atributos y las reacciones de sincronización (unmatched → crear, deleted → desactivar).
- **`role-agente-call-center.xml`**: define el rol que activa el aprovisionamiento SIP.

Para importar en midPoint: Consola web (http://localhost:8080/midpoint) → `Import Object` → subir ambos XMLs.

### 5. Configuración AMI en Asterisk (`manager.conf`)

El AMI (Asterisk Manager Interface) en el puerto `5038` permite al provisioner recargar la configuración SIP en caliente sin reiniciar el contenedor.

### 6. Pruebas unitarias (22 tests — todos pasando ✅)

```
tests/test_provisioner.py — 22 passed in 0.08s
```

| Suite | Tests | Qué valida |
|---|---|---|
| `TestFiltradoAgentes` | 2 | Solo usuarios con rol + activo=TRUE son procesados |
| `TestAsignacionExtension` | 5 | Rango correcto, sin duplicados, error si rango lleno |
| `TestGeneracionSipSecret` | 5 | Longitud ≥16, alfanumérico, determinista, único por usuario |
| `TestGeneracionSipAgentsConf` | 7 | Formato Asterisk válido, codecs, encabezado, agente sin nombre |
| `TestLogicaSincronizacion` | 3 | Nuevo agente recibe ext, aprovisionado no se duplica, desactivado no aparece |

---

## Cómo levantar el entorno completo (Fase 3)

```bash
# 1. Levantar todos los servicios
docker-compose up --build -d

# 2. Ver logs del provisioner (la sincronización ocurre cada 30s)
docker logs -f provisioner

# 3. Verificar extensiones aprovisionadas en la BD
docker exec -it postgres psql -U telecom -d telecom \
  -c "SELECT u.username, e.extension, e.estado FROM usuarios u JOIN extensiones_sip e ON u.id=e.usuario_id;"

# 4. Ver el archivo SIP generado
docker exec -it asterisk cat /etc/asterisk/agents/sip_agents.conf

# 5. Verificar en Asterisk que las extensiones están registradas
docker exec -it asterisk asterisk -rx "sip show peers"
```

## Importar recursos en midPoint

1. Ir a http://localhost:8080/midpoint (usuario: `administrator`, contraseña: `5ecr3t`)
2. Menú → `Import object` → subir `midpoint/resources/resource-db-usuarios.xml`
3. Menú → `Import object` → subir `midpoint/resources/role-agente-call-center.xml`
4. En `Resources` → seleccionar "BD Usuarios" → `Test connection` (debe dar OK)
5. En `Resources` → `Import accounts` → ejecutar tarea de reconciliación

## Ejecutar los tests

```bash
pip install -r tests/requirements-test.txt
python -m pytest tests/test_provisioner.py -v
```
