#!/bin/bash

# 1. Obtener la IP actual de la interfaz de red principal
MI_IP=$(hostname -I | awk '{print $1}')
echo "============================================="
echo "Iniciando Entorno Telecom IAM..."
echo "IP detectada: $MI_IP"
echo "============================================="

# 2. Reemplazar la IP dinámicamente en el archivo pjsip.conf
sed -i -E "s/external_media_address=.*/external_media_address=$MI_IP/" ./asterisk/pjsip.conf
sed -i -E "s/external_signaling_address=.*/external_signaling_address=$MI_IP/" ./asterisk/pjsip.conf

# 3. Bajar contenedores viejos y levantar todo de nuevo
echo "Levantando contenedores de Docker..."
docker compose down
docker compose up -d

echo "¡Entorno listo y configurado para la red actual!"