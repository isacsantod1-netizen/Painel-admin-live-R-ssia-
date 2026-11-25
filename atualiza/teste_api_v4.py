#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TESTES E2E das protecoes v4 do servidor: Play Integrity real (estrutura/nonce/
pacote/idade + politica exigir), revogacao de sessao POR KEY e acao revogar do painel.
Sobe o servidor REAL numa pasta isolada. Saida 0 = tudo verde."""
import sys, os, json, time, hmac, hashlib, base64, shutil, sqlite3, subprocess, urllib.request, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVIDOR_SRC = os.path.join(BASE, 'sombra_server', 'sombra_server.py')
PORTA = 8098
URL = 'http://127.0.0.1:%d' % PORTA
PKG = 'com.liverussia.cr'
falhas = []

def chk(nome, ok):
    print(('OK   ' if ok else 'FALHA ') + nome)
    if not ok:
        falhas.append(nome)

def post(path, body, headers=None):
    r = urllib.request.Request(URL + path, data=json.dumps(body).encode(),
                               headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        resp = urllib.request.urlopen(r, timeout=15)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}

def token_fake(nonce, pkg=PKG, ts=None, extra=None):
    """JWT de 3 partes com payload legivel (como o do Play Integrity)."""
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b'=').decode()
    h = b64({"alg": "RS256", "typ": "JWT"})
    p = {"requestDetails": {
            "requestPackageName": pkg,
            "timestampMillis": ts if ts is not None else int(time.time() * 1000),
            "nonce": nonce}}
    if extra:
        p.update(extra)
    return h + '.' + b64(p) + '.assinatura-fake'

def main():
    print('== TESTE API v4 (Play Integrity real + revogacao por key) em %s' % URL)
    td = tempfile.mkdtemp(prefix='sombra_v4_')
    shutil.copy(SERVIDOR_SRC, td)
    cfg = {'bot_token': '', 'admins': [], 'canal': '', 'senha_painel': 'senha-v4',
           'porta': PORTA, 'validade_grant_dias': 7, 'versao_min': 0, 'banir_auto': True,
           'manutencao': False, 'max_ativacoes_dia': 3, 'integrity_modo': 'exigir'}
    with open(os.path.join(td, 'config.json'), 'w') as f:
        json.dump(cfg, f)
    proc = subprocess.Popen([sys.executable, 'sombra_server.py'], cwd=td,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok_boot = False
    for _ in range(40):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(URL + '/api/estado', timeout=3)
            ok_boot = True
            break
        except urllib.error.HTTPError:
            ok_boot = True
            break
        except Exception:
            pass
    chk('servidor sobe com integrity_modo=exigir', ok_boot)
    if not ok_boot:
        proc.terminate()
        return 1

    auth = {'X-Painel-Token': 'senha-v4'}

    def nova_key(nome):
        st, js = post('/api/chaves', {'cliente': nome, 'nota': 'v4', 'dias': 7, 'max_aparelhos': 99}, auth)
        import re
        m = re.search(r'SOMBRA-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}', json.dumps(js))
        if not m:
            chk('criar key ' + nome, False)
            return None, None
        con = sqlite3.connect(os.path.join(td, 'sombra.db'))
        kid = str(con.execute("SELECT id FROM chaves WHERE chave=?", (m.group(0),)).fetchone()[0])
        con.close()
        return m.group(0), kid

    try:
        k1, id1 = nova_key('integ-ok')
        k2, id2 = nova_key('integ-neg')
        k3, id3 = nova_key('revogar')
        k4, id4 = nova_key('revogar2')
        chk('criacao de keys de teste', all([k1, k2, k3, k4]))

        # 1. token valido (estrutura+nonce+pacote+idade) -> aceito
        nz = 'nonce-' + k1[-4:]
        st, js = post('/api/validar', {'chave': k1, 'codigo': 'AAAA-1111', 'v': 2,
                                       'inonce': nz, 'integrity': token_fake(nz)})
        chk('integrity estrutura+nonce+pacote validos -> ACEITO',
            st == 200 and js.get('ok') is True)
        jti1 = (js.get('grant', '').split('|') + [''])[5]

        # 2. SEM token -> recusado no modo exigir
        st, js = post('/api/validar', {'chave': k2, 'codigo': 'AAAA-2222', 'v': 2})
        chk('sem integrity (modo exigir) -> RECUSADO', st == 403 and 'ntegridade' in str(js.get('erro', '')))

        # 3. nonce divergente -> recusado
        st, js = post('/api/validar', {'chave': k2, 'codigo': 'AAAA-2222', 'v': 2,
                                       'inonce': 'nonce-errado', 'integrity': token_fake('nonce-certo')})
        chk('integrity nonce divergente -> RECUSADO', st == 403)

        # 4. pacote estranho -> recusado
        st, js = post('/api/validar', {'chave': k2, 'codigo': 'AAAA-2222', 'v': 2,
                                       'inonce': 'n', 'integrity': token_fake('n', pkg='com.atacante.falso')})
        chk('integrity pacote estranho -> RECUSADO', st == 403)

        # 5. token velho -> recusado
        st, js = post('/api/validar', {'chave': k2, 'codigo': 'AAAA-2222', 'v': 2,
                                       'inonce': 'n', 'integrity': token_fake('n', ts=int(time.time() * 1000) - 3600000)})
        chk('integrity token velho (>10min) -> RECUSADO', st == 403)

        # 6. token malformado -> recusado
        st, js = post('/api/validar', {'chave': k2, 'codigo': 'AAAA-2222', 'v': 2,
                                       'inonce': 'n', 'integrity': 'nao-e-um-jwt'})
        chk('integrity formato invalido -> RECUSADO', st == 403)

        # 7. heartbeat (revalida) fica isento de integrity
        st, js = post('/api/validar', {'chave': k1, 'codigo': 'AAAA-1111', 'v': 2,
                                       'revalida': 1, 'jti': jti1})
        chk('revalida (heartbeat) isento de integrity -> ACEITO', st == 200 and js.get('ok') is True)

        # 8. REVOCACAO POR KEY: mata so as sessoes da key escolhida
        st, js = post('/api/validar', {'chave': k3, 'codigo': 'CCCC-3333', 'v': 2,
                                       'inonce': 'x', 'integrity': token_fake('x')})
        g3a = js.get('grant', '')
        jti3a = (g3a.split('|') + [''])[5]
        st, js = post('/api/validar', {'chave': k4, 'codigo': 'DDDD-4444', 'v': 2,
                                       'inonce': 'y', 'integrity': token_fake('y')})
        g4 = js.get('grant', '')
        jti4 = (g4.split('|') + [''])[5]
        st, js = post('/api/revogar_tokens', {'chave': k3}, auth)
        chk('revogar_tokens por key (endpoint)', st == 200 and js.get('ok') is True)
        st, js = post('/api/validar', {'chave': k3, 'codigo': 'CCCC-3333', 'v': 2, 'revalida': 1, 'jti': jti3a})
        chk('key revogada: revalida c/ jti antigo RECUSADO', st == 403)
        st, js = post('/api/validar', {'chave': k4, 'codigo': 'DDDD-4444', 'v': 2, 'revalida': 1, 'jti': jti4})
        jti4b = (js.get('grant', '').split('|') + [''])[5]
        chk('outra key NAO foi afetada pela revogacao', st == 200 and js.get('ok') is True)

        # 9. acao 'revogar' do painel (por id) - reusa a sessao viva da k4
        st, js = post('/api/chaves/%s/revogar' % id4, {}, auth)
        chk('painel: acao revogar por id', st == 200 and js.get('ok') is True)
        st, js = post('/api/validar', {'chave': k4, 'codigo': 'DDDD-4444', 'v': 2, 'revalida': 1, 'jti': jti4b})
        chk('sessao morre apos acao revogar do painel', st == 403)

    finally:
        proc.terminate()

    print()
    if falhas:
        print('RESULTADO: %d FALHAS' % len(falhas))
        return 1
    print('RESULTADO: API v4 RESISTIU A TODOS OS ATAQUES')
    return 0

if __name__ == '__main__':
    sys.exit(main())
