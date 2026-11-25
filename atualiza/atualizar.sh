#!/data/data/com.termux/files/usr/bin/bash
# SOMBRAMODZ - atualiza tudo (rode depois de extrair o atualiza.zip)
cd ~/sombra_server || exit 1
echo "[1/3] Conferindo servidor..."
if ! python3 -m py_compile sombra_server.py 2>/dev/null; then
  echo "[!] ERRO no codigo do servidor - nada foi alterado"
  exit 1
fi
chmod +x termux/boot.sh atualizar_url.sh 2>/dev/null || true
echo "[2/3] Subindo servidor + tunel..."
sh termux/boot.sh
echo "[3/3] Publicando endereco no GitHub (1a vez pede o token)..."
sh atualizar_url.sh
echo ""
echo "=========================================="
echo "  PRONTO! Teste o PAINEL e o APK agora."
echo "=========================================="
