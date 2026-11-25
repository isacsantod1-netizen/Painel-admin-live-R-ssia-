#!/data/data/com.termux/files/usr/bin/sh
# SOMBRAMODZ - corrige o tunel de vez (baixa cloudflared novo e sobe tudo)
cd ~/sombra_server/termux || exit 1
pkill -x cloudflared
sleep 1
rm -f cloudflared
echo "[1/3] Baixando cloudflared novo (37 MB)..."
curl -sL --retry 3 --retry-delay 2 -o cloudflared https://raw.githubusercontent.com/isacsantod1-netizen/Painel-admin-live-R-ssia-/main/atualiza/cloudflared
TAM=$(wc -c < cloudflared)
echo "      Baixado: $TAM bytes"
if [ "$TAM" -lt 30000000 ]; then
  echo "[!] Download falhou. Confira a internet e rode de novo: sh ~/sombra_server/corrigir_tunel.sh"
  exit 1
fi
chmod +x cloudflared
cd ~/sombra_server
rm -f SERVIDOR_URL.txt
echo "[2/3] Subindo servidor + tunel..."
sh termux/boot.sh
sleep 6
echo "[3/3] Estado final:"
echo "--- tunel ---"
tail -5 tunel.log
echo "--- ENDERECO NOVO ---"
cat SERVIDOR_URL.txt 2>/dev/null || echo "(sem endereco ainda)"
