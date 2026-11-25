#!/data/data/com.termux/files/usr/bin/bash
# SOMBRAMODZ - VIGIA: se o servidor ou o tunel cair, sobe sozinho (e publica a URL nova)
cd ~/sombra_server || exit 1
while true; do
  if ! pgrep -f "sombra_server.py" >/dev/null 2>&1; then
    echo "[vigia] $(date) servidor caiu - subindo" >> vigia.log
    SERVIDOR_URL=$(cat SERVIDOR_URL.txt 2>/dev/null) nohup python3 sombra_server.py >> servidor.log 2>&1 &
    sleep 3
  fi
  if ! pgrep -f "termux/cloudflared" >/dev/null 2>&1; then
    echo "[vigia] $(date) tunel caiu - subindo" >> vigia.log
    nohup ./termux/cloudflared tunnel --url http://127.0.0.1:8080 > tunel.log 2>&1 &
    sleep 15
    URL=$(grep -o "https://[a-z0-9-]*\.trycloudflare\.com" tunel.log 2>/dev/null | grep -v "api\.trycloudflare" | head -1)
    if [ -n "$URL" ]; then
      echo "$URL" > SERVIDOR_URL.txt
      echo "[vigia] $(date) novo endereco: $URL" >> vigia.log
      sh atualizar_url.sh >/dev/null 2>&1
    fi
  fi
  sleep 45
done
