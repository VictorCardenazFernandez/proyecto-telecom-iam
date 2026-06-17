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