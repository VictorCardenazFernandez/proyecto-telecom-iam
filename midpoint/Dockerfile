FROM evolveum/midpoint:latest

# El conector DatabaseTable (com.evolveum.polygon.connector-databasetable
# v1.5.3.0) ya viene empaquetado dentro de esta imagen de midPoint —
# no requiere instalación adicional. midPoint lo descubre automáticamente
# al arrancar y lo registra en su repositorio interno.
#
# Para verificarlo en la UI:
#   Administración → Repository objects → tipo "Connector" → Buscar
#   Debe aparecer: "ConnId org.identityconnectors.databasetable.DatabaseTableConnector v1.5.3.0"

# Copiar los recursos de configuración iniciales que serán importados
# manualmente desde la UI la primera vez que se levanta el entorno:
#   Recursos → Importar definición → Editor embebido
#   1. midpoint/resources/role-agente-call-center.xml
#   2. midpoint/resources/resource-db-usuarios.xml
COPY resources/ /opt/midpoint/var/import/

EXPOSE 8080