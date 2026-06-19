-- ============================================================
-- Base de datos de negocio: Telecom IAM Lab
-- Fase 3: Se agrega tabla de extensiones SIP y auditoría
-- ============================================================

-- ------------------------------------------------
-- 1. Tabla de usuarios del call center
--    Esta es la "fuente de la verdad" que midPoint lee
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS usuarios (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(50)  NOT NULL UNIQUE,
    password    VARCHAR(100) NOT NULL,
    rol         VARCHAR(50)  NOT NULL,
    activo      BOOLEAN      NOT NULL DEFAULT TRUE,
    email       VARCHAR(100),
    nombre      VARCHAR(100),
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------
-- 2. Tabla de extensiones SIP aprovisionadas
--    El provisioner la mantiene sincronizada con sip_agents.conf
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS extensiones_sip (
    id           SERIAL PRIMARY KEY,
    usuario_id   INTEGER      NOT NULL REFERENCES usuarios(id),
    extension    VARCHAR(10)  NOT NULL UNIQUE,   -- e.g. "1001"
    sip_secret   VARCHAR(100) NOT NULL,           -- contraseña SIP generada
    estado       VARCHAR(20)  NOT NULL DEFAULT 'PENDIENTE',
    -- PENDIENTE | APROVISIONADO | DESACTIVADO
    aprovisionado_en TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------
-- 3. Tabla de CDR (Call Detail Records)
--    Asterisk escribe aquí vía ODBC o script posterior
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS cdr (
    id           SERIAL PRIMARY KEY,
    calldate     TIMESTAMP   NOT NULL DEFAULT NOW(),
    clid         VARCHAR(80),
    src          VARCHAR(80),
    dst          VARCHAR(80),
    dcontext     VARCHAR(80),
    channel      VARCHAR(80),
    dstchannel   VARCHAR(80),
    lastapp      VARCHAR(80),
    lastdata     VARCHAR(80),
    duration     INTEGER,
    billsec      INTEGER,
    disposition  VARCHAR(45),
    amaflags     INTEGER,
    accountcode  VARCHAR(20),
    uniqueid     VARCHAR(32)
);

-- ------------------------------------------------
-- 4. Tabla de auditoría (ISO 27001 - A.8.16)
--    El provisioner y midPoint registran aquí cada acción
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS auditoria (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMP   NOT NULL DEFAULT NOW(),
    actor       VARCHAR(50) NOT NULL,   -- 'provisioner' | 'midpoint' | 'admin'
    accion      VARCHAR(50) NOT NULL,   -- 'CREAR_EXTENSION' | 'DESACTIVAR' | 'SYNC'
    usuario_id  INTEGER REFERENCES usuarios(id),
    detalle     TEXT,
    resultado   VARCHAR(20) NOT NULL    -- 'OK' | 'ERROR'
);

-- ------------------------------------------------
-- 5. Datos de prueba iniciales
-- ------------------------------------------------
INSERT INTO usuarios (username, password, rol, nombre, email) VALUES
  ('agente1', 'hashed_pass_1', 'AgenteCallCenter', 'Ana Pérez',   'ana.perez@telecom.com'),
  ('agente2', 'hashed_pass_2', 'AgenteCallCenter', 'Carlos Ruiz', 'carlos.ruiz@telecom.com'),
  ('supervisor1', 'hashed_pass_3', 'Supervisor',  'María López',  'maria.lopez@telecom.com')
ON CONFLICT (username) DO NOTHING;

-- ------------------------------------------------
-- 6. Base de datos separada para midPoint
--    midPoint crea sus propias tablas al arrancar
-- ------------------------------------------------
CREATE DATABASE midpoint;

GRANT ALL PRIVILEGES ON DATABASE midpoint TO telecom;
