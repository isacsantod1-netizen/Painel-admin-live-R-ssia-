#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOMBRAMODZ - Servidor de Chaves
===============================
Painel web admin + Bot do Telegram + API de validacao, tudo com a MESMA base.

Rodar:      python3 sombra_server.py
Painel:     http://localhost:8080        (ou o IP do celular na rede local)
API:        POST /api/validar  {"chave": "...", "codigo": "..."}
Bot:        comandos no Telegram (ver LEIA-ME_PAINEL.md)

Arquivos gerados/importantes:
  config.json    configuracao (token do bot, admins, canal, senha do painel)
  sombra.db      banco SQLite das chaves
  private.pem    chave RSA PRIVADA (assina os passes) -> GUARDE BEM
  public.pem     chave RSA PUBLICA -> vai embutida no APK
"""

import base64
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import requests
from flask import Flask, jsonify, redirect, render_template, request, session

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "sombra.db")
CONFIG_PATH = os.path.join(BASE, "config.json")
PRIV_PATH = os.path.join(BASE, "private.pem")
PUB_PATH = os.path.join(BASE, "public.pem")

FMT_DATA = "%Y-%m-%d %H:%M"
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I

app = Flask(__name__)

# ----------------------------------------------------------------------------
# Banco
# ----------------------------------------------------------------------------

def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    try:
        con.execute("PRAGMA journal_mode=WAL").fetchone()
    except sqlite3.Error:
        pass
    con.execute("PRAGMA foreign_keys=ON")
    return con


def db_init():
    con = db()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS chaves(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chave TEXT UNIQUE NOT NULL,
            cliente TEXT DEFAULT '',
            nota TEXT DEFAULT '',
            criada_em TEXT NOT NULL,
            expira_em TEXT NOT NULL,
            max_aparelhos INTEGER DEFAULT 1,
            status TEXT DEFAULT 'ativa'
        );
        CREATE TABLE IF NOT EXISTS aparelhos(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chave_id INTEGER NOT NULL REFERENCES chaves(id) ON DELETE CASCADE,
            codigo TEXT NOT NULL,
            ativado_em TEXT NOT NULL,
            ultimo_ok TEXT,
            UNIQUE(chave_id, codigo)
        );
        CREATE TABLE IF NOT EXISTS log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            criada_em TEXT NOT NULL,
            evento TEXT NOT NULL,
            detalhe TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tentativas(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quando TEXT NOT NULL,
            chave TEXT DEFAULT '',
            codigo TEXT DEFAULT '',
            origem TEXT DEFAULT ''
        );
        """
    )
    con.commit()
    con.close()


def log_evento(evento, detalhe="", con=None):
    fechar = con is None
    if fechar:
        con = db()
    con.execute(
        "INSERT INTO log(criada_em,evento,detalhe) VALUES (?,?,?)",
        (agora(), evento, detalhe),
    )
    if fechar:
        con.commit()
        con.close()


def agora():
    return datetime.now().strftime(FMT_DATA)


def parse_data(s):
    return datetime.strptime(s, FMT_DATA)


# ----------------------------------------------------------------------------
# Config + RSA
# ----------------------------------------------------------------------------

def config_load():
    if not os.path.exists(CONFIG_PATH):
        cfg = {
            "bot_token": "",
            "admins": [],
            "canal": "",
            "senha_painel": "troque-essa-senha",
            "porta": 8080,
            "validade_grant_dias": 7,
        }
        config_save(cfg)
        return cfg
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def config_save(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def rsa_init():
    if os.path.exists(PRIV_PATH):
        with open(PRIV_PATH, "rb") as f:
            priv = serialization.load_pem_private_key(f.read(), password=None)
        return priv
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with open(PRIV_PATH, "wb") as f:
        f.write(
            priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    with open(PUB_PATH, "wb") as f:
        f.write(
            priv.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
    os.chmod(PRIV_PATH, 0o600)
    print("[+] Chave RSA gerada: private.pem / public.pem (guarde o private.pem!)")
    return priv


def assinar(texto):
    sig = PRIV.sign(texto.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode("ascii")


# ----------------------------------------------------------------------------
# Logica das chaves
# ----------------------------------------------------------------------------

def parse_max(v):
    """0 = ilimitado. Aceita 0, inf, ilimitado..."""
    s = str(v).strip().lower()
    if s in ("0", "inf", "∞", "ilimitado", "unlimited", "-1"):
        return 0
    return max(1, int(s))


def gerar_chave():
    while True:
        grupos = [
            "".join(secrets.choice(ALFABETO) for _ in range(4)) for _ in range(3)
        ]
        chave = "SOMBRA-" + "-".join(grupos)
        con = db()
        existe = con.execute("SELECT 1 FROM chaves WHERE chave=?", (chave,)).fetchone()
        con.close()
        if not existe:
            return chave


def status_real(row):
    if row["status"] == "banida":
        return "banida"
    if parse_data(row["expira_em"]) < datetime.now():
        return "expirada"
    return "ativa"


def criar_chave(chave, cliente, nota, dias, max_aparelhos):
    chave = (chave or "").strip().upper()
    if not chave:
        chave = gerar_chave()
    dias = max(1, int(dias))
    max_aparelhos = parse_max(max_aparelhos)  # 0 = ilimitado
    expira = (datetime.now() + timedelta(days=dias)).strftime(FMT_DATA)
    con = db()
    try:
        con.execute(
            "INSERT INTO chaves(chave,cliente,nota,criada_em,expira_em,max_aparelhos)"
            " VALUES (?,?,?,?,?,?)",
            (chave, cliente or "", nota or "", agora(), expira, max_aparelhos),
        )
        con.commit()
    except sqlite3.IntegrityError:
        con.close()
        return None, "essa chave ja existe"
    con.close()
    log_evento("criar", f"{chave} ({cliente}) ate {expira}")
    return chave, expira


def validar_chave(chave, codigo, origem="api"):
    """Valida chave+aparelho e monta o passe assinado."""
    chave = (chave or "").strip().upper()
    codigo = (codigo or "").strip().upper()
    if not chave or not codigo:
        return {"ok": False, "erro": "Digite a key!"}
    if len(codigo) > 40:
        return {"ok": False, "erro": "Codigo do aparelho invalido!"}

    con = db()
    row = con.execute("SELECT * FROM chaves WHERE chave=?", (chave,)).fetchone()
    if row is None:
        con.close()
        log_evento("validar_falhou", f"{chave} inexistente ({origem}/{codigo})")
        return {"ok": False, "erro": "Key invalida! Crie no painel."}

    st = status_real(row)
    if st == "banida":
        con.close()
        return {"ok": False, "erro": "Key banida!"}
    if st == "expirada":
        con.execute("UPDATE chaves SET status='expirada' WHERE id=?", (row["id"],))
        con.commit()
        con.close()
        return {"ok": False, "erro": "Key expirada!"}

    dev = con.execute(
        "SELECT * FROM aparelhos WHERE chave_id=? AND codigo=?", (row["id"], codigo)
    ).fetchone()

    if dev is None:
        n = con.execute(
            "SELECT COUNT(*) FROM aparelhos WHERE chave_id=?", (row["id"],)
        ).fetchone()[0]
        if row["max_aparelhos"] > 0 and n >= row["max_aparelhos"]:
            con.close()
            log_evento("validar_falhou", f"{chave} limite de aparelhos ({codigo})")
            return {"ok": False, "erro": "Limite de aparelhos! Apague um no painel."}
        for _tent in range(3):
            try:
                con.execute(
                    "INSERT INTO aparelhos(chave_id,codigo,ativado_em,ultimo_ok) VALUES (?,?,?,?)",
                    (row["id"], codigo, agora(), agora()),
                )
                log_evento("ativar", f"{chave} -> {codigo}", con=con)
                con.commit()
                break
            except sqlite3.OperationalError:
                try:
                    con.rollback()
                except sqlite3.Error:
                    pass
                time.sleep(0.6)
        else:
            con.close()
            return {"ok": False, "erro": "Servidor ocupado! Tente de novo."}
    else:
        for _tent in range(3):
            try:
                con.execute(
                    "UPDATE aparelhos SET ultimo_ok=? WHERE id=?", (agora(), dev["id"])
                )
                log_evento("revalidar", f"{chave} -> {codigo}", con=con)
                con.commit()
                break
            except sqlite3.OperationalError:
                try:
                    con.rollback()
                except sqlite3.Error:
                    pass
                time.sleep(0.6)
        else:
            con.close()
            return {"ok": False, "erro": "Servidor ocupado! Tente de novo."}
    con.close()

    validade = CFG.get("validade_grant_dias", 7)
    grant_expira = datetime.now() + timedelta(days=validade)
    expira_chave = parse_data(row["expira_em"])
    if grant_expira > expira_chave:
        grant_expira = expira_chave
    expira_str = grant_expira.strftime(FMT_DATA)
    nonce = secrets.token_hex(8)
    payload = f"SOMBRAMODZ-V1|{chave}|{codigo}|{expira_str}|{nonce}"
    return {
        "ok": True,
        "chave": chave,
        "codigo": codigo,
        "expira": expira_str,
        "grant": payload,
        "assinatura": assinar(payload),
    }


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------

def tg_api(method, **params):
    token = CFG.get("bot_token", "")
    if not token:
        return {"ok": False, "description": "bot_token vazio"}
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            data={k: v for k, v in params.items() if v is not None},
            timeout=20,
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


def tg_enviar(chat_id, texto):
    return tg_api("sendMessage", chat_id=chat_id, text=texto)


def publicar_canal(texto):
    canal = CFG.get("canal", "")
    if canal:
        tg_api("sendMessage", chat_id=canal, text=texto)


def bot_comando(chat_id, texto, e_admin):
    t = texto.strip()
    partes = t.split()
    cmd = partes[0].split("@")[0].lower() if partes else ""
    args = partes[1:]

    if cmd == "/start":
        tg_enviar(
            chat_id,
            "SOMBRAMODZ · Bot de chaves\n\n"
            f"Seu chat_id: {chat_id}\n\n"
            "Cliente:\n"
            "/ativar CHAVE CODIGO - ativa o aparelho\n\n"
            "Admin (coloque seu chat_id em config.json > admins):\n"
            "/criar DIAS MAX [nota] - gera chave nova (MAX 0 = ilimitado)\n"
            "/criarfixa CHAVE DIAS MAX [nota] - chave custom\n"
            "/estender CHAVE DIAS - aumenta o prazo\n"
            "/limite CHAVE N - muda acessos (0 = ilimitado)\n"
            "/delaparelho CHAVE CODIGO - remove 1 aparelho\n"
            "/lista /info /ban /liberar /reset /deletar /log /status",
        )
        return

    if cmd == "/ajuda":
        tg_enviar(chat_id, "Use /start para ver os comandos.")
        return

    if cmd == "/ativar":
        if len(args) < 2:
            tg_enviar(chat_id, "Uso: /ativar CHAVE CODIGO")
            return
        res = validar_chave(args[0], args[1], origem="telegram")
        if res["ok"]:
            tg_enviar(
                chat_id,
                f"✅ ATIVADO\nChave: {res['chave']}\nAparelho: {res['codigo']}\n"
                f"Válido até: {res['expira']}\n\nPasse:\n{res['grant']}\n{res['assinatura']}",
            )
            publicar_canal(f"ATIVAR|{res['chave']}|{res['codigo']}|{res['expira']}|{res['grant'].split('|')[-1]}|{res['assinatura']}")
        else:
            tg_enviar(chat_id, f"❌ {res['erro']}")
        return

    if not e_admin:
        tg_enviar(chat_id, "⛔ Sem permissão. Fale com o administrador.")
        return

    if cmd == "/criar":
        if len(args) < 2:
            tg_enviar(chat_id, "Uso: /criar DIAS MAX [nota]\nMAX: 1, 2, 4... ou 0 = ilimitado")
            return
        try:
            dias, mx = int(args[0]), parse_max(args[1])
        except Exception:
            tg_enviar(chat_id, "Uso: /criar DIAS MAX [nota]\nMAX: 1, 2, 4... ou 0 = ilimitado")
            return
        nota = " ".join(args[2:])
        chave, info = criar_chave(None, nota, nota, dias, mx)
        if chave is None:
            tg_enviar(chat_id, f"❌ {info}")
        else:
            lim = "∞ ilimitado" if mx == 0 else f"{mx} aparelho(s)"
            tg_enviar(chat_id, f"✅ Criada: {chave}\nExpira: {info}\nAcessos: {lim}")
        return

    if cmd == "/criarfixa":
        if len(args) < 3:
            tg_enviar(chat_id, "Uso: /criarfixa CHAVE DIAS MAX [nota]")
            return
        try:
            dias, mx = int(args[1]), parse_max(args[2])
        except Exception:
            tg_enviar(chat_id, "Uso: /criarfixa CHAVE DIAS MAX [nota]")
            return
        nota = " ".join(args[3:])
        chave, info = criar_chave(args[0], nota, nota, dias, mx)
        if chave is None:
            tg_enviar(chat_id, f"❌ {info}")
        else:
            lim = "∞ ilimitado" if mx == 0 else f"{mx} aparelho(s)"
            tg_enviar(chat_id, f"✅ Criada: {chave}\nExpira: {info}\nAcessos: {lim}")
        return

    if cmd == "/estender":
        if len(args) < 2:
            tg_enviar(chat_id, "Uso: /estender CHAVE DIAS")
            return
        con = db()
        r = con.execute("SELECT * FROM chaves WHERE chave=?", (args[0].upper(),)).fetchone()
        if not r:
            con.close()
            tg_enviar(chat_id, "❌ Chave não encontrada.")
            return
        dias = int(args[1])
        base = parse_data(r["expira_em"])
        if base < datetime.now():
            base = datetime.now()
        nova = (base + timedelta(days=dias)).strftime(FMT_DATA)
        con.execute("UPDATE chaves SET expira_em=?, status='ativa' WHERE id=?", (nova, r["id"]))
        con.commit()
        con.close()
        log_evento("estender", f"{r['chave']} +{dias}d -> {nova}")
        tg_enviar(chat_id, f"📅 {r['chave']} estendida +{dias}d\nNova validade: {nova}")
        return

    if cmd == "/limite":
        if len(args) < 2:
            tg_enviar(chat_id, "Uso: /limite CHAVE N\nN: 1, 2, 4... ou 0 = ilimitado")
            return
        mx = parse_max(args[1])
        con = db()
        r = con.execute("SELECT * FROM chaves WHERE chave=?", (args[0].upper(),)).fetchone()
        if not r:
            con.close()
            tg_enviar(chat_id, "❌ Chave não encontrada.")
            return
        con.execute("UPDATE chaves SET max_aparelhos=? WHERE id=?", (mx, r["id"]))
        con.commit()
        con.close()
        log_evento("limite", f"{r['chave']} -> {'ilimitado' if mx == 0 else mx}")
        tg_enviar(chat_id, f"🔢 {r['chave']}: acessos = {'∞ ilimitado' if mx == 0 else mx}")
        return

    if cmd == "/delaparelho":
        if len(args) < 2:
            tg_enviar(chat_id, "Uso: /delaparelho CHAVE CODIGO")
            return
        con = db()
        r = con.execute("SELECT * FROM chaves WHERE chave=?", (args[0].upper(),)).fetchone()
        if not r:
            con.close()
            tg_enviar(chat_id, "❌ Chave não encontrada.")
            return
        d = con.execute(
            "SELECT * FROM aparelhos WHERE chave_id=? AND codigo=?",
            (r["id"], args[1].upper()),
        ).fetchone()
        if d:
            con.execute("DELETE FROM aparelhos WHERE id=?", (d["id"],))
        con.commit()
        con.close()
        log_evento("del_aparelho", f"{r['chave']} {args[1].upper()}")
        tg_enviar(chat_id, f"🗑️ Aparelho {args[1].upper()} removido de {r['chave']}.")
        return

    if cmd == "/lista":
        con = db()
        rows = con.execute(
            "SELECT * FROM chaves ORDER BY id DESC LIMIT 30"
        ).fetchall()
        con.close()
        if not rows:
            tg_enviar(chat_id, "Nenhuma chave cadastrada.")
            return
        linhas = []
        for r in rows:
            linhas.append(f"{r['chave']} · {status_real(r)} · até {r['expira_em']} · {r['cliente'] or '-'}")
        tg_enviar(chat_id, "📋 Chaves:\n" + "\n".join(linhas))
        return

    if cmd == "/info":
        if not args:
            tg_enviar(chat_id, "Uso: /info CHAVE")
            return
        con = db()
        r = con.execute("SELECT * FROM chaves WHERE chave=?", (args[0].upper(),)).fetchone()
        if not r:
            con.close()
            tg_enviar(chat_id, "❌ Chave não encontrada.")
            return
        devs = con.execute(
            "SELECT * FROM aparelhos WHERE chave_id=?", (r["id"],)
        ).fetchall()
        con.close()
        linhas = [f"{d['codigo']} · ativado {d['ativado_em']} · último ok {d['ultimo_ok']}" for d in devs]
        tg_enviar(
            chat_id,
            f"🔑 {r['chave']}\nStatus: {status_real(r)}\nCliente: {r['cliente'] or '-'}\n"
            f"Criada: {r['criada_em']}\nExpira: {r['expira_em']}\n"
            f"Máx aparelhos: {r['max_aparelhos']}\n\nAparelhos:\n" + ("\n".join(linhas) if linhas else "(nenhum)"),
        )
        return

    if cmd in ("/ban", "/liberar", "/deletar", "/reset"):
        if not args:
            tg_enviar(chat_id, f"Uso: {cmd} CHAVE")
            return
        con = db()
        r = con.execute("SELECT * FROM chaves WHERE chave=?", (args[0].upper(),)).fetchone()
        if not r:
            con.close()
            tg_enviar(chat_id, "❌ Chave não encontrada.")
            return
        if cmd == "/ban":
            con.execute("UPDATE chaves SET status='banida' WHERE id=?", (r["id"],))
            log_evento("ban", r["chave"])
            msg = f"🚫 {r['chave']} banida."
        elif cmd == "/liberar":
            con.execute("UPDATE chaves SET status='ativa' WHERE id=?", (r["id"],))
            log_evento("liberar", r["chave"])
            msg = f"✅ {r['chave']} liberada."
        elif cmd == "/reset":
            con.execute("DELETE FROM aparelhos WHERE chave_id=?", (r["id"],))
            log_evento("reset", r["chave"])
            msg = f"♻️ Aparelhos de {r['chave']} removidos."
        else:
            con.execute("DELETE FROM chaves WHERE id=?", (r["id"],))
            log_evento("deletar", r["chave"])
            msg = f"🗑️ {r['chave']} apagada."
        con.commit()
        con.close()
        tg_enviar(chat_id, msg)
        return

    if cmd == "/log":
        con = db()
        rows = con.execute("SELECT * FROM log ORDER BY id DESC LIMIT 15").fetchall()
        con.close()
        linhas = [f"{r['criada_em']} · {r['evento']} · {r['detalhe']}" for r in rows]
        tg_enviar(chat_id, "🧾 Log:\n" + ("\n".join(linhas) if linhas else "(vazio)"))
        return

    if cmd == "/status":
        con = db()
        total = con.execute("SELECT COUNT(*) FROM chaves").fetchone()[0]
        devs = con.execute("SELECT COUNT(*) FROM aparelhos").fetchone()[0]
        con.close()
        tg_enviar(chat_id, f"🟢 Online\nChaves: {total}\nAparelhos: {devs}\nUptime: {uptime()}")
        return

    tg_enviar(chat_id, "Comando desconhecido. Use /start.")


def bot_loop():
    global CFG
    print("[+] Bot do Telegram ativo" if CFG.get("bot_token") else "[-] Bot do Telegram DESATIVADO (bot_token vazio)")
    offset = None
    while True:
        token = CFG.get("bot_token", "")
        if not token:
            time.sleep(10)
            continue
        try:
            CFG = config_load()  # recarrega config a cada ciclo (admins/token novos)
        except Exception:
            pass
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": 25, "offset": offset, "allowed_updates": ["message"]},
                timeout=35,
            )
            data = r.json()
            if not data.get("ok"):
                time.sleep(4)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                texto = msg.get("text", "")
                if not chat_id or not texto:
                    continue
                e_admin = chat_id in [str(a) for a in CFG.get("admins", [])]
                try:
                    bot_comando(chat_id, texto, e_admin)
                except Exception as e:
                    tg_enviar(chat_id, f"⚠️ erro: {e}")
        except Exception:
            time.sleep(6)


# ----------------------------------------------------------------------------
# Painel web
# ----------------------------------------------------------------------------

INICIO = time.time()


def uptime():
    s = int(time.time() - INICIO)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}d {h}h {m}m"


def auth_ok():
    return session.get("auth") is True


@app.after_request
def _cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Painel-Token"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return r


@app.before_request
def _antes():
    if request.method == "OPTIONS":
        return ("", 204)
    if request.headers.get("X-Painel-Token", "") == CFG.get("senha_painel", ""):
        return None
    if request.path.startswith("/api/validar") or request.path == "/login" or request.path.startswith("/static"):
        return None
    if request.path.startswith("/api/") or request.path == "/":
        if not auth_ok():
            return jsonify({"ok": False, "erro": "nao autenticado"}), 401
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("index.html", modo="login")
    ip = request.remote_addr or "?"
    bloqueio = limite(ip, maximo=6, chave="login:")
    if bloqueio is not None:
        return bloqueio
    senha = (request.json or {}).get("senha", "") if request.is_json else request.form.get("senha", "")
    import hashlib
    if hashlib.sha256(senha.encode()).hexdigest() == hashlib.sha256(CFG["senha_painel"].encode()).hexdigest():
        session["auth"] = True
        return jsonify({"ok": True})
    log_evento("login_falhou", request.remote_addr)
    return jsonify({"ok": False, "erro": "senha errada"}), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/")
def index():
    return render_template("index.html", modo="painel")


@app.route("/api/estado")
def api_estado():
    con = db()
    chaves = con.execute("SELECT * FROM chaves ORDER BY id DESC").fetchall()
    devs = con.execute("SELECT COUNT(*) FROM aparelhos").fetchone()[0]
    logs = con.execute("SELECT * FROM log ORDER BY id DESC LIMIT 20").fetchall()
    con.close()
    ativas = expiradas = banidas = 0
    lista = []
    for r in chaves:
        st = status_real(r)
        if st == "ativa":
            ativas += 1
        elif st == "expirada":
            expiradas += 1
        else:
            banidas += 1
        usados = con.execute("SELECT COUNT(*) FROM aparelhos WHERE chave_id=?", (r["id"],)).fetchone()[0]
        lista.append(dict(r, status=st, usados=usados))
    return jsonify(
        {
            "ok": True,
            "resumo": {"ativas": ativas, "expiradas": expiradas, "banidas": banidas, "aparelhos": devs},
            "chaves": lista,
            "log": [dict(r) for r in logs],
            "uptime": uptime(),
        }
    )


@app.route("/api/chaves", methods=["POST"])
def api_chaves():
    j = request.json or {}
    chave, info = criar_chave(
        j.get("chave"), j.get("cliente", ""), j.get("nota", ""),
        j.get("dias", 30), j.get("max_aparelhos", 1),
    )
    if chave is None:
        return jsonify({"ok": False, "erro": info}), 400
    return jsonify({"ok": True, "chave": chave, "expira": info})


@app.route("/api/chaves/<int:cid>/<acao>", methods=["POST"])
def api_acao(cid, acao):
    if acao not in ("ban", "liberar", "deletar", "reset"):
        return jsonify({"ok": False, "erro": "acao invalida"}), 400
    con = db()
    r = con.execute("SELECT * FROM chaves WHERE id=?", (cid,)).fetchone()
    if not r:
        con.close()
        return jsonify({"ok": False, "erro": "nao encontrada"}), 404
    if acao == "ban":
        con.execute("UPDATE chaves SET status='banida' WHERE id=?", (cid,))
    elif acao == "liberar":
        con.execute("UPDATE chaves SET status='ativa' WHERE id=?", (cid,))
    elif acao == "reset":
        con.execute("DELETE FROM aparelhos WHERE chave_id=?", (cid,))
    else:
        con.execute("DELETE FROM chaves WHERE id=?", (cid,))
    con.commit()
    con.close()
    log_evento(acao, r["chave"])
    return jsonify({"ok": True})


@app.route("/api/chaves/<int:cid>/aparelhos")
def api_aparelhos(cid):
    con = db()
    devs = con.execute("SELECT * FROM aparelhos WHERE chave_id=?", (cid,)).fetchall()
    con.close()
    return jsonify({"ok": True, "aparelhos": [dict(d) for d in devs]})


@app.route("/api/chaves/<int:cid>/estender", methods=["POST"])
def api_estender(cid):
    dias = int((request.json or {}).get("dias", 7))
    con = db()
    r = con.execute("SELECT * FROM chaves WHERE id=?", (cid,)).fetchone()
    if not r:
        con.close()
        return jsonify({"ok": False, "erro": "nao encontrada"}), 404
    base = parse_data(r["expira_em"])
    if base < datetime.now():
        base = datetime.now()
    nova = (base + timedelta(days=dias)).strftime(FMT_DATA)
    con.execute("UPDATE chaves SET expira_em=?, status='ativa' WHERE id=?", (nova, cid))
    con.commit()
    con.close()
    log_evento("estender", f"{r['chave']} +{dias}d -> {nova}")
    return jsonify({"ok": True, "expira": nova})


@app.route("/api/chaves/<int:cid>/limite", methods=["POST"])
def api_limite(cid):
    mx = parse_max((request.json or {}).get("max_aparelhos", 1))
    con = db()
    r = con.execute("SELECT * FROM chaves WHERE id=?", (cid,)).fetchone()
    if not r:
        con.close()
        return jsonify({"ok": False, "erro": "nao encontrada"}), 404
    con.execute("UPDATE chaves SET max_aparelhos=? WHERE id=?", (mx, cid))
    con.commit()
    con.close()
    log_evento("limite", f"{r['chave']} -> {'ilimitado' if mx == 0 else mx}")
    return jsonify({"ok": True, "max_aparelhos": mx})


@app.route("/api/aparelhos/<int:did>/deletar", methods=["POST"])
def api_del_aparelho(did):
    con = db()
    d = con.execute("SELECT * FROM aparelhos WHERE id=?", (did,)).fetchone()
    if d:
        con.execute("DELETE FROM aparelhos WHERE id=?", (did,))
    con.commit()
    con.close()
    log_evento("del_aparelho", d["codigo"] if d else str(did))
    return jsonify({"ok": True})


@app.route("/api/validar", methods=["POST"])
def api_validar():
    ip = request.remote_addr or "?"
    bloqueio = limite(ip)
    if bloqueio is not None:
        return bloqueio
    j = request.json or {}
    try:
        res = validar_chave(j.get("chave", ""), j.get("codigo", ""), origem="api")
    except sqlite3.OperationalError:
        res = {"ok": False, "erro": "Servidor ocupado! Tente de novo."}
    return jsonify(res), (200 if res["ok"] else 403)


def limite(ip, maximo=12, chave=""):
    """controle simples de tentativas por IP (por minuto)"""
    agora_ts = time.time()
    hist = _rate.setdefault(chave + ip, [])
    hist[:] = [t for t in hist if agora_ts - t < 60]
    if len(hist) >= maximo:
        return jsonify({"ok": False, "erro": "calma ai, muitas tentativas"}), 429
    hist.append(agora_ts)
    return None


_rate = {}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

CFG = config_load()
PRIV = rsa_init()
db_init()
app.secret_key = secrets.token_hex(32)


def main():
    global CFG
    CFG = config_load()
    porta = int(CFG.get("porta", 8080))
    th = threading.Thread(target=bot_loop, daemon=True)
    th.start()
    print(f"[+] Painel: http://localhost:{porta}")
    print(f"[+] API:    POST /api/validar")
    url_publica = os.environ.get("SERVIDOR_URL", "").strip()
    if url_publica:
        print(f"[+] Endereco publico: {url_publica}")
        if CFG.get("canal"):
            threading.Thread(target=publicar_canal,
                             args=(f"SERVIDOR|{url_publica}",), daemon=True).start()
    app.run(host="0.0.0.0", port=porta, threaded=True)


if __name__ == "__main__":
    main()
