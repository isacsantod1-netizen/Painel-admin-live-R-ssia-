# PLANO DE RECUPERAÇÃO EM CASO DE COMPROMETIMENTO

Use este plano se suspeitar que keys, o servidor ou o APK foram comprometidos.

## FASE 1 — CONTENÇÃO (minutos)

1. **Ativar modo manutenção** (para TODA validação imediatamente):
   no servidor, edite `config.json` → `"manutencao": true` e reinicie.
   *(Ou pelo bot: reinicie com o config editado — sem manutenção o painel continua respondendo.)*
2. **Revogar todas as sessões agora:**
   `curl -X POST -H "X-Painel-Token: SUA_SENHA" https://SEU_SERVIDOR/api/revogar_tokens`
   → todos os aparelhos perdem o passe e precisam entrar com a Key de novo.
3. **Banir as keys comprometidas** no painel (Botão BANIR).

## FASE 2 — DIAGNÓSTICO (horas)

4. Revisar o log do painel procurando:
   - `replay_suspeito` = alguém tentando reusar respostas antigas
   - `sessao_suspeita` = muitas ativações de aparelhos numa key
   - `tentativas_excedidas` / `validar_negado` = força bruta
   - `relato_tamper_dex` / `relato_ambiente_adulterado` = aparelhos adulterados
5. Conferir `integrity` (tokens do Play Integrity) dos aparelhos suspeitos.
6. Identificar a origem: key vazada? APK modificado? servidor invadido?

## FASE 3 — ROTAÇÃO DE SEGREDOS (se o servidor foi invadido)

7. **Gerar novo par RSA** (no servidor):
   `rm -f ~/sombra_server/private.pem ~/sombra_server/public.pem`
   → o servidor gera um novo ao subir. **Guarde o `private.pem` novo!**
8. **Rebuild do APK** (a chave pública nova entra no gate):
   `python3 gen_keygate.py` → javac → d8 → build 2 passadas → assinar com `sombra.jks`
   → rodar `bash auditoria.sh novo.apk <DEXHASH>` — só publicar se APROVADO.
9. **Forçar atualização**: `"versao_min": 2` no config → APKs antigos (com a chave
   pública velha) são recusados com "Atualize o APK para continuar!".

## FASE 4 — REABERTURA

10. `"manutencao": false` + reiniciar o servidor.
11. Publicar o APK novo (link do Drive) + atualizar `checksums.txt` no GitHub.
12. Monitorar o log por 48h (replay_suspeito / sessao_suspeita).

## REFERÊNCIA RÁPIDA — comandos

- Revogar todas as sessões: `POST /api/revogar_tokens` (header X-Painel-Token)
- Banir key: painel → BANIR (ou `POST /api/chaves/<key>/ban`)
- Limite de tentativas: automático (8 falhas/10min por key)
- Bloqueio de versão: `"versao_min"` no `config.json`
- Auditoria completa: `bash apk_work/auditoria.sh <apk> <dexhash>`
