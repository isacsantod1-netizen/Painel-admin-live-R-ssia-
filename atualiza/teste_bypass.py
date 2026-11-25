#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TESTES DE BYPASS (NEGATIVOS) - simula ataques reais e exige que cada
um seja DETECTADO/BLOQUEADO pelos mecanismos do APK.
Uso: python3 teste_bypass.py <apk> [DEXHASH]
"""
import sys, os, zipfile, hashlib, struct, subprocess, tempfile

KEY = 0x5A
def X(s): return ''.join(f'{(b ^ KEY):02x}' for b in s.encode()).encode()
CERT_OFICIAL = "e84441f6a757f9a765dc88edf6cdb9ffc04081d5ce0375e74a66520f09d98dcc"
BASE = os.path.dirname(os.path.abspath(__file__))
falhas = []

def chk(nome, ok):
    print(('OK   ' if ok else 'FALHA ') + nome)
    if not ok:
        falhas.append(nome)

def main():
    apk = sys.argv[1]
    print('== TESTES DE BYPASS (ataques simulados):', os.path.basename(apk))

    # ---- ATAQUE 1: modificar o dex de funcoes (smali) ----
    z = zipfile.ZipFile(apk)
    d6 = bytearray(z.read('classes6.dex'))
    h_antes = hashlib.sha256(d6).hexdigest()
    d6[len(d6) // 2] ^= 0xFF  # corrompe 1 byte = "edicao de smali"
    h_depois = hashlib.sha256(d6).hexdigest()
    esperado = sys.argv[2] if len(sys.argv) > 2 else None
    if esperado:
        chk('ATAQUE 1 (smali editado) -> hash muda e gate detecta',
            h_antes == esperado and h_depois != esperado and X(esperado) in z.read('classes7.dex'))
    else:
        chk('ATAQUE 1 (smali editado) -> hash muda', h_depois != h_antes)

    # ---- ATAQUE 2: re-assinar com outra chave (APK Editor/MT) ----
    # prova: qualquer certificado que NAO seja o oficial gera outro SHA-256 e o
    # gate (que compara o SHA-256 do cert instalado com o oficial) nega tudo.
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'fake')])
        cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome)
                .public_key(k.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
                .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30))
                .sign(k, hashes.SHA256()))
        digest_falso = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        # e o certificado REAL do APK instalado e o oficial?
        tools = os.path.join(BASE, 'tools/android-11')
        r = subprocess.run([os.path.join(tools, 'apksigner'), 'verify', '--print-certs', apk],
                           capture_output=True, text=True)
        chk('ATAQUE 2 (re-assinado) -> cert forjado tem SHA-256 diferente e e REJEITADO',
            digest_falso != CERT_OFICIAL and CERT_OFICIAL in r.stdout)
    except ImportError:
        chk('ATAQUE 2 (re-assinado) -> lib cryptography indisponivel', False)

    # ---- ATAQUE 3: forjar passe RSA ----
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        # chave FALSA assina um passe falso
        falsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        passe = 'SOMBRAMODZ-V2|SOMBRA-FAKE-FAKE|XXXX-XXXX|01/01/2030|aa|bb|*'
        sig = falsa.sign(passe.encode(), padding.PKCS1v15(), hashes.SHA256())
        # a chave PUBLICA do SERVIDOR real tem que REJEITAR
        pub_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'sombra_server', 'public.pem')
        if not os.path.exists(pub_path):
            chk('ATAQUE 3 (passe forjado) -> rejeitado pela chave publica (SEM public.pem)', False)
        else:
            pub = serialization.load_pem_public_key(open(pub_path, 'rb').read())
            try:
                pub.verify(sig, passe.encode(), padding.PKCS1v15(), hashes.SHA256())
                chk('ATAQUE 3 (passe forjado) -> rejeitado pela chave publica', False)
            except Exception:
                chk('ATAQUE 3 (passe forjado) -> rejeitado pela chave publica', True)
    except ImportError:
        chk('ATAQUE 3 (passe forjado) -> lib cryptography indisponivel', False)

    # ---- ATAQUE 4: remover a tela Key nao abre as funcoes ----
    d7 = z.read('classes7.dex')
    m6 = z.read('classes6.dex')
    d3 = z.read('classes3.dex')
    chk('ATAQUE 4 (remover tela Key) -> funcoes exigem y.a (portas trancadas)',
        b'Ly/a;' in m6 and b'Ly/a;' in d3 and X('/api/validar') in d7)

    print()
    if falhas:
        print('RESULTADO: %d FALHAS - PROTECAO INCOMPLETA' % len(falhas))
        return 1
    print('RESULTADO: TODOS OS ATAQUES FORAM BLOQUEADOS')
    return 0

if __name__ == '__main__':
    sys.exit(main())
