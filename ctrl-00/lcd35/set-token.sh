#!/bin/bash
# Stores the Home Assistant long-lived token used by the touch panel.
ENV=/opt/automacao/.env
read -rsp "Cole o token do Home Assistant e tecle Enter: " TOKEN; echo
[ ${#TOKEN} -lt 100 ] && { echo "Isso nao parece um token (muito curto). Nada foi salvo."; sleep 5; exit 1; }
sed -i '/^HA_TOKEN=/d' "$ENV" && echo "HA_TOKEN=$TOKEN" >> "$ENV" && chmod 600 "$ENV"
echo "Token salvo. O painel conecta em alguns segundos."; sleep 4
