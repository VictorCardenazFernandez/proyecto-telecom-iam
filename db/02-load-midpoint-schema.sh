#!/bin/bash
set -e
echo "Cargando esquema nativo de midPoint en la base 'midpoint'..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "midpoint" -f /docker-entrypoint-initdb.d/sql-source/postgres-schema.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "midpoint" -f /docker-entrypoint-initdb.d/sql-source/postgres-quartz.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "midpoint" -f /docker-entrypoint-initdb.d/sql-source/postgres-audit.sql
echo "Esquema de midPoint cargado correctamente."