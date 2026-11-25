#!/data/data/com.termux/files/usr/bin/sh
# SOMBRAMODZ - corrige o tunel (v7: roda direto do curl, 1 linha, com verificacao)
cd ~/sombra_server/termux || exit 1
echo "[1/6] Parando tudo..."
pkill -9 -f vigia.sh
pkill -9 -f termux/cloudflared
pkill -9 -f cloudflared
sleep 2
rm -f ~/sombra_server/tunel.log ~/sombra_server/SERVIDOR_URL.txt
echo "[2/6] proot..."
pkg install -y proot >/dev/null 2>&1
echo "[3/6] cloudflared (37 MB)..."
rm -f cloudflared.bin
curl -sL --retry 3 -o cloudflared.bin https://raw.githubusercontent.com/isacsantod1-netizen/Painel-admin-live-R-ssia-/main/atualiza/cloudflared
echo -n "      bytes: "; wc -c < cloudflared.bin
chmod +x cloudflared.bin
echo "[4/6] DNS + certificados + invoclucro..."
echo "nameserver 8.8.8.8" > /data/data/com.termux/files/usr/etc/resolv.conf
echo "nameserver 1.1.1.1" >> /data/data/com.termux/files/usr/etc/resolv.conf
mkdir -p /data/data/com.termux/files/usr/etc/tls/certs
curl -sL --retry 3 -o /data/data/com.termux/files/usr/etc/tls/certs/ca-certificates.crt https://raw.githubusercontent.com/isacsantod1-netizen/Painel-admin-live-R-ssia-/main/atualiza/ca-certificates.crt
echo -n "      cert bytes: "; wc -c < /data/data/com.termux/files/usr/etc/tls/certs/ca-certificates.crt
echo '#!/data/data/com.termux/files/usr/bin/sh' > cloudflared
echo 'export SSL_CERT_FILE=/data/data/com.termux/files/usr/etc/tls/certs/ca-certificates.crt' >> cloudflared
echo 'export SSL_CERT_DIR=/data/data/com.termux/files/usr/etc/tls/certs' >> cloudflared
echo 'exec proot -b /data/data/com.termux/files/usr/etc/resolv.conf:/etc/resolv.conf -b /data/data/com.termux/files/usr/etc/tls:/etc/ssl /data/data/com.termux/files/home/sombra_server/termux/cloudflared.bin "$@"' >> cloudflared
chmod +x cloudflared
echo -n "      wrapper: "; head -2 cloudflared | tail -1
sed -i 's/cloudflared tunnel/termux\/cloudflared/g' ~/sombra_server/termux/boot.sh
echo "[5/6] Subindo tudo..."
cd ~/sombra_server
sh termux/boot.sh
sleep 8
echo "[6/6] Estado:"
head -4 tunel.log
tail -2 tunel.log
echo "--- ENDERECO NOVO ---"
cat SERVIDOR_URL.txt 2>/dev/null || echo "(sem endereco ainda)"
