#!/data/data/com.termux/files/usr/bin/sh
# SOMBRAMODZ - corrige o tunel DE VEZ (v3: DNS pro cloudflared via proot)
cd ~/sombra_server/termux || exit 1
echo "[1/6] Parando tudo (forcado)..."
pkill -9 -f vigia.sh
pkill -9 -f termux/cloudflared
pkill -9 -f cloudflared
sleep 2
rm -f ~/sombra_server/tunel.log ~/sombra_server/SERVIDOR_URL.txt
echo "[2/6] Garantindo proot (serve pro DNS)..."
pkg install -y proot ca-certificates >/dev/null 2>&1
echo "[3/6] Baixando cloudflared (37 MB)..."
rm -f cloudflared.bin
curl -sL --retry 3 --retry-delay 2 -o cloudflared.bin https://raw.githubusercontent.com/isacsantod1-netizen/Painel-admin-live-R-ssia-/main/atualiza/cloudflared
TAM=$(wc -c < cloudflared.bin)
echo "      Baixado: $TAM bytes"
if [ "$TAM" -lt 30000000 ]; then
  echo "[!] Download falhou. Confira a internet e rode de novo: sh ~/sombra_server/corrigir_tunel.sh"
  exit 1
fi
chmod +x cloudflared.bin
echo "[4/6] DNS de trabalho + invoclucro..."
echo "nameserver 8.8.8.8" > /data/data/com.termux/files/usr/etc/resolv.conf
echo "nameserver 1.1.1.1" >> /data/data/com.termux/files/usr/etc/resolv.conf
cat > cloudflared <<'WRAP'
#!/data/data/com.termux/files/usr/bin/sh
exec proot -b /data/data/com.termux/files/usr/etc/resolv.conf:/etc/resolv.conf -b /data/data/com.termux/files/usr/etc/tls:/etc/ssl /data/data/com.termux/files/home/sombra_server/termux/cloudflared.bin "$@"
WRAP
chmod +x cloudflared
sed -i 's/cloudflared tunnel/termux\/cloudflared/g' ~/sombra_server/termux/boot.sh
echo "[5/6] Subindo servidor + tunel + vigia..."
cd ~/sombra_server
sh termux/boot.sh
sleep 8
echo "[6/6] Estado final:"
echo "--- comeco do log ---"
head -6 tunel.log
echo "--- fim do log ---"
tail -3 tunel.log
echo "--- ENDERECO NOVO ---"
cat SERVIDOR_URL.txt 2>/dev/null || echo "(sem endereco ainda)"
