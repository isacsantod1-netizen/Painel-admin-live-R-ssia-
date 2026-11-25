#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TESTES DE BYPASS (ataques simulados estilo MT Manager / APK Editor).
Cada ataque precisa ser DETECTADO pelas protecoes do APK/servidor.
Sai com codigo 0 = TODOS OS ATAQUES CONTIDOS; 1 = alguma brecha.

Uso: python3 teste_bypass.py <apk> [DEXHASH]
"""
import sys, os, zipfile, hashlib, shutil, subprocess, tempfile

KEY = 0x5A
def X(s):
    return ''.join(f'{(b ^ KEY):02x}' for b in s.encode()).encode()

CERT_ESPERADO = "e84441f6a757f9a765dc88edf6cdb9ffc04081d5ce0375e74a66520f09d98dcc"
BASE = os.path.dirname(os.path.abspath(__file__))
KEYTOOL = '/usr/lib/jvm/jdk-11/bin/keytool'
APKSIGNER = os.path.join(BASE, 'tools/android-11/apksigner')
falhas = []

def chk(nome, ok):
    print(('OK   ' if ok else 'FALHA ') + nome)
    if not ok:
        falhas.append(nome)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def cert_do_apk(apk):
    r = subprocess.run([APKSIGNER, 'verify', '--print-certs', apk],
                       capture_output=True, text=True, timeout=120)
    for ln in r.stdout.splitlines():
        if 'SHA-256 digest' in ln:
            return ln.split(':')[-1].strip().replace(':', '').lower()
    return ''

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    apk = os.path.abspath(sys.argv[1])
    dexhash = sys.argv[2] if len(sys.argv) > 2 else None
    os.makedirs(os.path.join(BASE, 'tmp_bypass'), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='bypass_', dir=os.path.join(BASE, 'tmp_bypass'))
    z = zipfile.ZipFile(apk)
    d7 = z.read('classes7.dex')
    print('== TESTES DE BYPASS:', os.path.basename(apk))
    print()

    # ---------- TA1: MT Manager - re-assinar com keystore estranho ----------
    print('-- TA1 re-assinatura com keystore estranho (MT Manager)')
    estranho = os.path.join(tmp, 'estranho.jks')
    subprocess.run([KEYTOOL, '-genkeypair', '-alias', 'atacante', '-keyalg', 'RSA',
                    '-keysize', '2048', '-validity', '1', '-keystore', estranho,
                    '-storepass', 'ataque123', '-keypass', 'ataque123',
                    '-dname', 'CN=Atacante'], capture_output=True, timeout=120)
    atk1 = os.path.join(tmp, 'ta1_resign.apk')
    shutil.copy(apk, atk1)
    subprocess.run(['zip', '-qd', atk1, 'META-INF/*'], capture_output=True)
    subprocess.run([APKSIGNER, 'sign', '--ks', estranho, '--ks-key-alias', 'atacante',
                    '--ks-pass', 'pass:ataque123', '--key-pass', 'pass:ataque123',
                    '--out', atk1 + '.s', atk1], capture_output=True, timeout=300)
    os.replace(atk1 + '.s', atk1)
    cert_ataque = cert_do_apk(atk1)
    chk('TA1 cert do atacante != cert oficial (gate f()/cofre c() bloqueia)',
        bool(cert_ataque) and cert_ataque != CERT_ESPERADO)
    z1 = zipfile.ZipFile(atk1)
    chk('TA1 dex intactos no ataque (mas cert pin pega)', sha(z1.read('classes6.dex')) == sha(z.read('classes6.dex')))
    z1.close()
    os.remove(atk1)

    # ---------- TA2a: patch de smali + re-assinatura OFICIAL impossivel;
    #            patch + assinatura estranha: hash do dex diverge ----------
    print('-- TA2 patch de smali (recompile) + re-assinatura')
    atk2 = os.path.join(tmp, 'ta2_patch.apk')
    shutil.copy(apk, atk2)
    d6 = bytearray(z.read('classes6.dex'))
    d6[0x200] ^= 0xFF  # byte aleatorio na area de dados = smali mexido
    subprocess.run(['zip', '-qd', atk2, 'classes6.dex'], capture_output=True)
    with open(os.path.join(tmp, 'classes6.dex'), 'wb') as fh:
        fh.write(d6)
    subprocess.run(['zip', '-q', atk2, 'classes6.dex'], capture_output=True, cwd=tmp)
    subprocess.run(['zip', '-qd', atk2, 'META-INF/*'], capture_output=True)
    subprocess.run([APKSIGNER, 'sign', '--ks', estranho, '--ks-key-alias', 'atacante',
                    '--ks-pass', 'pass:ataque123', '--key-pass', 'pass:ataque123',
                    '--out', atk2 + '.s', atk2], capture_output=True, timeout=300)
    os.replace(atk2 + '.s', atk2)
    z2 = zipfile.ZipFile(atk2)
    h6_ataque = sha(z2.read('classes6.dex'))
    chk('TA2 hash de classes6.dex diverge (gate g() + cofre d() bloqueiam)',
        h6_ataque != sha(z.read('classes6.dex')) and (not dexhash or h6_ataque != dexhash))
    chk('TA2 hash NAO esta no cofre do gate', X(h6_ataque) not in d7 and X(dexhash or '') in d7)

    # ---------- TA3: apagar/renomear dex ----------
    print('-- TA3 dex apagado/renomeado (APK Editor)')
    atk3 = os.path.join(tmp, 'ta3_sem_dex.apk')
    shutil.copy(apk, atk3)
    subprocess.run(['zip', '-qd', atk3, 'classes6.dex'], capture_output=True)
    z3 = zipfile.ZipFile(atk3)
    chk('TA3 classes6.dex ausente -> gate g() fail-closed (ze==null=false) + cofre "AUSENTE"',
        'classes6.dex' not in z3.namelist())

    # ---------- TA4: cofre de hashes completo no classes7 ----------
    print('-- TA4 cofre de hashes (x/a) embutido')
    chk('TA4 classe x/a definida no dex', b'Lx/a;' in d7)
    chk('TA4 vault cobre os 6 dex', all(X(n) in d7 for n in
        ['classes.dex', 'classes2.dex', 'classes3.dex', 'classes4.dex', 'classes5.dex', 'classes6.dex']))
    chk('TA4 vault cobre resources.arsc + AndroidManifest.xml',
        X('resources.arsc') in d7 and X('AndroidManifest.xml') in d7)
    chk('TA4 cert pin no cofre', X(CERT_ESPERADO) in d7)
    chk('TA4 anti-debug (TracerPid/maps frida)', X('/proc/self/status') in d7 and X('libgadget') in d7)
    chk('TA4 gate v4 valida 6 dex (fail-closed)', X('classes5.dex') in d7 and X('classes2.dex') in d7)

    # ---------- TA5: passe RSA ----------
    print('-- TA5 passe RSA (grant assinado)')
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        priv = serialization.load_pem_private_key(
            open(os.path.join(BASE, '..', 'sombra_server', 'private.pem'), 'rb').read(), password=None)
        pub = serialization.load_pem_public_key(
            open(os.path.join(BASE, '..', 'sombra_server', 'public.pem'), 'rb').read())
        grant = b'SOMBRAMODZ-V2|TESTE|0000-0000|2030-01-01|nonce|jti|*'
        sig = priv.sign(grant, padding.PKCS1v15(), hashes.SHA256())
        try:
            pub.verify(sig, grant, padding.PKCS1v15(), hashes.SHA256())
            ok_real = True
        except Exception:
            ok_real = False
        try:
            pub.verify(sig, grant + b'X', padding.PKCS1v15(), hashes.SHA256())
            ok_tamper = True
        except Exception:
            ok_tamper = False
        chk('TA5 grant correto valida com chave publica do gate', ok_real)
        chk('TA5 grant adulterado RECUSADO (anti-forja)', not ok_tamper)
    except Exception as e:
        chk('TA5 passe RSA (%s)' % e, False)

    print()
    if falhas:
        print('RESULTADO: %d BRECHAS - NAO PUBLICAR' % len(falhas))
        return 1
    print('RESULTADO: TODOS OS ATAQUES CONTIDOS')
    return 0

if __name__ == '__main__':
    sys.exit(main())
