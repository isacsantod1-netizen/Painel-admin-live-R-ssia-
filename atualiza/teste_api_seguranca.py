#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TESTE DE SEGURANCA DA API (E2E) - sobe o servidor REAL numa pasta isolada
e ataca a API: replay, revogacao, downgrade, manutencao, limite de tentativas,
multi-sessao e mascaramento de logs. Uso: python3 teste_api_seguranca.py
"""
import sys, os, json, time, shutil, sqlite3, subprocess, urllib.request, tempfile, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVIDOR_SRC = os.path.join(BASE, 'sombra_server', 'sombra_server.py')
PORTA = 8099
URL = 'http://127.0.0.1:%d' % PORTA
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

def main():
    print('== TESTE DE SEGURANCA DA API (servidor real em %s)' % URL)
    td = tempfile.mkdtemp(prefix='sombra_test_')
    shutil.copy(SERVIDOR_SRC, td)
    cfg = {'bot_token': '', 'admins': [], 'canal': '', 'senha_painel': 'senha-teste',
           'porta': PORTA, 'validade_grant_dias': 7, 'versao_min': 0, 'banir_auto': True,
           'manutencao': False, 'max_ativacoes_dia': 3}
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
            ok_boot = True  # qualquer HTTP = servidor respondendo (401 e esperado)
            break
        except Exception:
            pass
    chk('servidor sobe', ok_boot)
    if not ok_boot:
        proc.terminate()
        return 1

    auth = {'X-Painel-Token': 'senha-teste'}
    try:
        # criar key pelo painel
        st, js = post('/api/chaves', {'cliente': 'teste', 'nota': 'auditoria', 'dias': 7, 'max_aparelhos': 5}, auth)
        m = re.search(r'SOMBRA-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}', json.dumps(js))
        chk('criar key pelo painel', st in (200, 201) and m is not None)
        key = m.group(0) if m else None
        # id numerico vem do banco (o painel usa /api/estado para isso)
        con = sqlite3.connect(os.path.join(td, 'sombra.db'))
        kid = str(con.execute("SELECT id FROM chaves WHERE chave=?", (key,)).fetchone()[0])
        con.close()

        cod1 = 'AAAA-1111'
        cod2 = 'BBBB-2222'
        cod3 = 'CCCC-3333'

        # 1. validacao basica
        st, js = post('/api/validar', {'chave': key, 'codigo': cod1, 'v': 1})
        g1 = js.get('grant', '')
        s1 = js.get('assinatura', '')
        chk('validacao basica devolve passe assinado',
            st == 200 and js.get('ok') is True and g1.startswith('SOMBRAMODZ-V2') and len(s1) > 20 and cod1 in g1)

        # 2. rotacao de token: revalidar com jti devolve jti NOVO
        jti1 = g1.split('|')[5] if g1.count('|') >= 6 else ''
        st, js = post('/api/validar', {'chave': key, 'codigo': cod1, 'v': 1, 'revalida': 1, 'jti': jti1})
        g2 = js.get('grant', '')
        jti2 = g2.split('|')[5] if g2.count('|') >= 6 else ''
        chk('revalidacao com jti correto + ROTACAO de token',
            st == 200 and js.get('ok') is True and jti1 and jti2 and jti1 != jti2)

        # 3. ANTI-REPLAY: jti antigo e recusado
        st, js = post('/api/validar', {'chave': key, 'codigo': cod1, 'v': 1, 'revalida': 1, 'jti': jti1})
        chk('ATAQUE replay (jti antigo) -> RECUSADO', st == 403 and js.get('ok') is False)

        # 4. revogacao imediata (ban) - rota usa id numerico
        post('/api/chaves/%s/ban' % kid, {}, auth)
        st2, js2 = post('/api/validar', {'chave': key, 'codigo': cod1, 'v': 1, 'revalida': 1, 'jti': jti2})
        chk('revogacao (ban) -> validacao recusada', st2 == 403 and 'banida' in str(js2.get('erro', '')).lower())
        post('/api/chaves/%s/liberar' % kid, {}, auth)

        # 5. multi-sessao suspeita (max 3 ativacoes/dia)
        for c in (cod2, cod3):
            post('/api/validar', {'chave': key, 'codigo': c, 'v': 1})
        st, js = post('/api/validar', {'chave': key, 'codigo': 'EEEE-5555', 'v': 1})
        chk('multi-sessao suspeita -> recusado',
            st == 403 and 'aparelhos' in str(js.get('erro', '')).lower())

        # 6. relato de adulteracao registrado (sem auth, como o APK faz)
        st, js = post('/api/relato', {'chave': key, 'codigo': cod1, 'tipo': 'tamper_dex', 'detalhe': 'teste'})
        con = sqlite3.connect(os.path.join(td, 'sombra.db'))
        n = con.execute("SELECT COUNT(*) FROM log WHERE evento='relato_tamper_dex'").fetchone()[0]
        con.close()
        chk('relato de adulteracao registrado', st == 200 and n >= 1)

        # 7. revogacao em massa: rotaciona jti -> jti antigo MORRE
        st, js = post('/api/revogar_tokens', {}, auth)
        st2, js2 = post('/api/validar', {'chave': key, 'codigo': cod1, 'v': 1, 'revalida': 1, 'jti': jti2})
        chk('revogar_tokens (massa) -> jti antigo recusado',
            js.get('ok') is True and st2 == 403)

        # 8. logs SEM key completa (mascaramento)
        con = sqlite3.connect(os.path.join(td, 'sombra.db'))
        linhas = con.execute("SELECT detalhe FROM log").fetchall()
        con.close()
        vazou = [l[0] for l in linhas if key and key in str(l[0])]
        chk('logs mascarados (sem key completa)', len(vazou) == 0)

        # 9. operacao admin sem senha e recusada
        st, js = post('/api/chaves', {'cliente': 'x'}, {'X-Painel-Token': 'ERRADA'})
        chk('painel sem senha correta -> recusado', st in (401, 403))

        # 10. anti-downgrade: versao_min recusa v antigo (reinicia o servidor com o config novo)
        cfg['versao_min'] = 5
        with open(os.path.join(td, 'config.json'), 'w') as f:
            json.dump(cfg, f)
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
        proc = subprocess.Popen([sys.executable, 'sombra_server.py'], cwd=td,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(0.5)
            try:
                urllib.request.urlopen(URL + '/api/estado', timeout=3)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                pass
        st, js = post('/api/validar', {'chave': key, 'codigo': cod1, 'v': 1})
        chk('anti-downgrade (versao_min=5) -> v=1 recusado',
            st == 403 and 'atualize' in str(js.get('erro', '')).lower())

        # 11. limite de tentativas (forca bruta) - por ultimo (consome o rate do IP)
        codes = []
        for i in range(14):
            st, js = post('/api/validar', {'chave': 'SOMBRA-XXXX-FAKE-%04d' % i, 'codigo': 'DDDD-4444', 'v': 1})
            codes.append(st)
        chk('forca bruta -> 429 apos limite', 429 in codes)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(td, ignore_errors=True)

    print()
    if falhas:
        print('RESULTADO: %d FALHAS' % len(falhas))
        return 1
    print('RESULTADO: API RESISTIU A TODOS OS ATAQUES')
    return 0

if __name__ == '__main__':
    sys.exit(main())
