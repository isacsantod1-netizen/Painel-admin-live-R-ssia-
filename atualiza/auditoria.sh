#!/bin/bash
# AUDITORIA DE SEGURANCA - rodar ANTES de cada atualizacao do APK.
# Uso: bash auditoria.sh <caminho/do.apk> [DEXHASH]
cd "$(dirname "$0")"
APK="$1"
DEX="$2"
if [ -z "$APK" ]; then
  echo "Uso: bash auditoria.sh <apk> [dexhash]"
  exit 1
fi
REL="relatorio_auditoria.txt"
{
  echo "=== AUDITORIA DE SEGURANCA $(date '+%d/%m/%Y %H:%M') ==="
  echo "APK: $APK"
  echo
  echo "--- 1/3 SUITE DE SEGURANCAS ---"
  python3 smoke_seguranca.py "$APK" "$DEX"
  R1=$?
  echo
  echo "--- 2/3 TESTES DE BYPASS (ataques simulados) ---"
  python3 teste_bypass.py "$APK" "$DEX"
  R2=$?
  echo
  echo "--- 3/3 TESTES DA API (servidor real) ---"
  python3 teste_api_seguranca.py
  R3=$?
  echo
  if [ $R1 -eq 0 ] && [ $R2 -eq 0 ] && [ $R3 -eq 0 ]; then
    echo "=== AUDITORIA: APROVADO ==="
  else
    echo "=== AUDITORIA: REPROVADO (smoke=$R1 bypass=$R2 api=$R3) - NAO PUBLICAR ==="
    exit 1
  fi
} 2>&1 | tee "$REL"
