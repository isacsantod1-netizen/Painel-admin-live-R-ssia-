#!/data/data/com.termux/files/usr/bin/sh
# SOMBRAMODZ - corrige o tunel DE VEZ (v2: mata forcado + vigia parado)
cd ~/sombra_server/termux || exit 1
echo "[1/4] Parando tudo (forcado)..."
pkill -9 -f vigia.sh
pkill -9 -f termux/cloudflared
sleep 2
if pgrep -f termux/cloudflared >/dev/null 2>&1; then
  echo "[!] Ainda tem cloudflared vivo. Mata com:  pkill -9 -f termux/cloudflared"
  exit 1
fi
echo "      Tudo parado."
rm -f ~/sombra_server/tunel.log ~/sombra_server/SERVIDOR_URL.txt
echo "[2/4] Baixando cloudflared novo (37 MB)..."
rm -f cloudflared
curl -sL --retry 3 --retry-delay 2 -o cloudflared https://raw.githubusercontent.com/isacsantod1-netizen/Painel-admin-live-R-ssia-/main/atualiza/cloudflared
TAM=$(wc -c < cloudflared)
echo "      Baixado: $TAM bytes"
if [ "$TAM" -lt 30000000 ]; then
  echo "[!] Download falhou. Confira a internet e rode de novo: sh ~/sombra_server/corrigir_tunel.sh"
  exit 1
fi
chmod +x cloudflared
cd ~/sombra_server
echo "[3/4] Subindo servidor + tunel + vigia..."
sh termux/boot.sh
sleep 8
echo "[4/4] Estado final:"
echo "--- comeco do log (versao real) ---"
head -6 tunel.log
echo "--- fim do log ---"
tail -3 tunel.log
echo "--- ENDERECO NOVO ---"
cat SERVIDOR_URL.txt 2>/dev/null || echo "(sem endereco ainda)"
