#!/data/data/com.termux/files/usr/bin/bash
# SOMBRAMODZ - atualiza o endereco do servidor no GitHub
# (o APK e o painel leem o endereco de la - tunel pode mudar a vontade)
cd "$(dirname "$0")" || exit 1

if [ ! -f ~/.gh_token ]; then
  if [ -t 0 ]; then
    echo "Cole seu token do GitHub (ghp_...) e aperte ENTER:"
    read -r TOK
    printf %s "$TOK" > ~/.gh_token
    chmod 600 ~/.gh_token
  else
    echo "[!] Sem token do GitHub salvo. Rode 1x manual: sh atualizar_url.sh"
    exit 0
  fi
fi

URL=$(tr -d '[:space:]' < SERVIDOR_URL.txt 2>/dev/null)
if echo "$URL" | grep -q "api\.trycloudflare" ; then URL="" ; fi
if [ -z "$URL" ]; then
  echo "[!] Tunel ainda nao subiu de verdade (sem endereco proprio)."
  echo "[!] Rode: sh termux/boot.sh   e veja se aparece https://NOME.trycloudflare.com"
  exit 1
fi

GH_TOKEN=$(cat ~/.gh_token) NOVA_URL="$URL" python3 - <<'PY'
import base64, json, os, urllib.request, urllib.error
tok = os.environ["GH_TOKEN"].strip()
url = os.environ["NOVA_URL"].strip()
api = "https://api.github.com/repos/isacsantod1-netizen/Painel-admin-live-R-ssia-/contents/servidor.txt"
def call(data=None):
    req = urllib.request.Request(api, data=json.dumps(data).encode() if data else None,
        headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"}, method="PUT" if data else "GET")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read() or b"{}")
        except Exception: return {}
    except Exception as e:
        return {"message": str(e)}
atual = call()
sha = atual.get("sha")
body = {"message": "url " + url,
        "content": base64.b64encode((url + "\n").encode()).decode(),
        "branch": "main"}
if sha: body["sha"] = sha
r = call(body)
if "content" in r:
    print("[+] ENDERECO PUBLICADO NO GITHUB:", url)
else:
    print("[!] Erro ao publicar:", r.get("message", "?"))
PY
