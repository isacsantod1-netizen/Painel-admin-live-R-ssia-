#!/data/data/com.termux/files/usr/bin/sh
# SOMBRAMODZ - sobe servidor + bot + tunel sozinho (Termux:Boot ou manual)
# Rode com:  bash boot.sh
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

termux-wake-lock 2>/dev/null || true

# 1) tunel publico (cloudflared) - so se ainda nao estiver rodando
if ! pgrep -f "cloudflared tunnel" >/dev/null 2>&1; then
    nohup "$DIR/termux/cloudflared" tunnel --url http://127.0.0.1:8080 > tunel.log 2>&1 &
fi

# 2) espera o endereco do tunel aparecer (ate 40s)
URL=""
i=0
while [ $i -lt 40 ]; do
    URL=$(grep -o "https://[a-z0-9-]*\.trycloudflare\.com" tunel.log 2>/dev/null | grep -v "api\.trycloudflare" | head -1)
    [ -n "$URL" ] && break
    sleep 1
    i=$((i+1))
done

if [ -n "$URL" ]; then
    echo "$URL" > SERVIDOR_URL.txt
    echo ""
    echo "=============================================="
    echo "  ENDERECO DO SEU SERVIDOR:"
    echo "  $URL"
    echo "=============================================="
    echo ""
else
    echo "[!] Tunel nao subiu ainda. Depois rode:  cat SERVIDOR_URL.txt"
fi

# 3) servidor de chaves + bot telegram
if ! pgrep -f "sombra_server.py" >/dev/null 2>&1; then
    SERVIDOR_URL="$URL" nohup python3 sombra_server.py >> servidor.log 2>&1 &
fi

sleep 2
echo "[+] Servidor rodando!"
echo "[+] Painel neste celular:  http://localhost:8080"
echo "[+] Log do bot:            tail -f servidor.log"
echo "[+] Pra deixar rodando:    feche o Termux que continua (wake-lock ativo)"

# 4) publica o endereco atual no GitHub (o APK e o painel leem de la)
sh "$DIR/atualizar_url.sh" >/dev/null 2>&1 || true
