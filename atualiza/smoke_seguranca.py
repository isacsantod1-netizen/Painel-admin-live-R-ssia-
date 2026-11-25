#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUITE DE TESTES DE SEGURANCA do APK SOMBRAMODZ (requisito 18).
Uso: python3 smoke_seguranca.py <caminho/do.apk> [DEXHASH_esperado]
Sai com codigo 0 = TUDO VERDE; 1 = falha.
"""
import sys, os, zipfile, hashlib, struct, subprocess

KEY = 0x5A
def X(s):
    return ''.join(f'{(b ^ KEY):02x}' for b in s.encode()).encode()

CERT_ESPERADO = "e84441f6a757f9a765dc88edf6cdb9ffc04081d5ce0375e74a66520f09d98dcc"
BASE = os.path.dirname(os.path.abspath(__file__))

def dex_methods(d):
    n_str, off_str = struct.unpack_from('<II', d, 56)
    n_type, off_type = struct.unpack_from('<II', d, 64)
    n_meth, off_meth = struct.unpack_from('<II', d, 88)
    def uleb(pos):
        r = s = 0
        while True:
            b = d[pos]; pos += 1
            r |= (b & 0x7f) << s
            if not (b & 0x80): break
            s += 7
        return r, pos
    def string(idx):
        p = struct.unpack_from('<I', d, off_str + idx * 4)[0]
        _, p = uleb(p)
        e = d.index(b'\x00', p)
        return d[p:e].decode('utf-8', 'replace')
    out = set()
    for i in range(n_meth):
        c, proto, name = struct.unpack_from('<HHI', d, off_meth + i * 8)
        cls = string(struct.unpack_from('<I', d, off_type + c * 4)[0])
        out.add((cls, string(name)))
    return out

def main():
    apk = sys.argv[1]
    z = zipfile.ZipFile(apk)
    d7 = z.read('classes7.dex')
    d6 = z.read('classes6.dex')
    d3 = z.read('classes3.dex')
    falhas = []

    def chk(nome, ok):
        print(('OK   ' if ok else 'FALHA ') + nome)
        if not ok:
            falhas.append(nome)

    print('== SUITE DE SEGURANCA:', os.path.basename(apk))
    # 1. assinatura
    try:
        r = subprocess.run([os.path.join(BASE, 'tools/android-11/apksigner'), 'verify', '--print-certs', apk],
                           capture_output=True, text=True, timeout=120)
        chk('assinatura = cert oficial sombra.jks', CERT_ESPERADO in r.stdout)
    except Exception as e:
        chk('assinatura = cert oficial sombra.jks (%s)' % e, False)

    # 2. integridade do dex de funcoes
    h6 = hashlib.sha256(d6).hexdigest()
    if len(sys.argv) > 2:
        chk('hash classes6 == DEXHASH cozido no gate', h6 == sys.argv[2] and X(sys.argv[2]) in d7)
    else:
        chk('DEXHASH presente no gate', X(h6) in d7)

    # 3. camadas do gate
    chk('C1 validacao online /api/validar', X('/api/validar') in d7)
    chk('C1b revalidacao + jti anti-replay', X('revalida') in d7 and b'jti' in d7)
    chk('C2 assinatura digital CERTSHA', X(CERT_ESPERADO) in d7)
    chk('C3 anti-smali (hash do dex)', X('classes6.dex') in d7)
    chk('C5 Play Integrity', X('IntegrityManagerFactory') in d7)
    chk('C6 relato /api/relato + tipos', X('/api/relato') in d7 and X('revalida_negada') in d7)
    chk('C9 somente HTTPS', X('https://') in d7)
    chk('C10 Android Keystore (AES/GCM)', b'AndroidKeyStore' in d7 and b'AES/GCM/NoPadding' in d7)
    chk('C2b ambiente adulterado (Frida/Xposed)', X('re.frida.server') in d7 and X('lsposed') in d7)
    chk('C12 permissoes por funcionalidade', ('Ly/a;', 'p') in dex_methods(d7) and b'controls' in d6 and b'native' in d6)

    # 4. ganchos (parser de method_ids)
    m6 = dex_methods(d6); m3 = dex_methods(d3)
    chk('HOOK tela Key -> y.a.a', ('Ly/a;', 'a') in m6)
    chk('HOOK funcoes protegidas -> y.a.v', ('Ly/a;', 'v') in m6)
    chk('HOOK por funcionalidade -> y.a.p', ('Ly/a;', 'p') in m6)
    chk('HOOK watchdog Application -> y.a.c', ('Ly/a;', 'c') in m3)

    # 5. tela Key intacta
    chk('tela Key intacta (keyOk/keyFail/textos)', b'keyOk' in d6 and b'keyFail' in d6 and b'Validando key...' in d6)

    # 6. SEM segredos no APK
    chk('SEM senha do painel no APK', b'isacvidaloka' not in d7 and b'isacvidaloka' not in d6)
    chk('SEM token GitHub no APK', b'ghp_' not in d7 and b'ghp_' not in d6)
    chk('SEM chave privada no APK', b'PRIVATE KEY' not in d7)

    print()
    if falhas:
        print('RESULTADO: %d FALHAS - NAO PUBLICAR' % len(falhas))
        return 1
    print('RESULTADO: TUDO VERDE - apto para publicacao')
    return 0

if __name__ == '__main__':
    sys.exit(main())
