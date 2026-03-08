"""
Gestionale Polizia d'Estovia — Backend
FastAPI + SQLite, Discord OAuth2, sessioni JWT
"""

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import sqlite3, secrets, time, json, os, httpx
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
API_KEY        = os.getenv("GESTIONALE_API_KEY", "estovia2026")
DISCORD_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_GUILD  = os.getenv("DISCORD_GUILD_ID", "")
REDIRECT_URI   = os.getenv("DISCORD_REDIRECT_URI", "https://gestionalepolizia-production.up.railway.app/auth/discord/callback")
DB_PATH        = os.getenv("DB_PATH", "gestionale.db")

# Ruoli Discord → livello accesso
ROLE_DIRIGENZA = {
    "staff", "dirigenza", "ispettorato", "sovrintendenza",
    "direttore", "vice direttore", "commissario", "ispettore capo",
    "ispettore", "sovrintendente capo", "sovrintendente", "assistente capo"
}

app = FastAPI(title="Gestionale PdE")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ─── DATABASE ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE IF NOT EXISTS agenti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        cognome TEXT NOT NULL,
        codice_fiscale TEXT UNIQUE,
        discord_username TEXT,
        grado TEXT NOT NULL,
        stato TEXT NOT NULL DEFAULT 'Attivo',
        note TEXT DEFAULT '',
        data_ingresso TEXT NOT NULL,
        sanzione_attiva TEXT DEFAULT NULL,
        sanzione_motivo TEXT DEFAULT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS azioni (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agente_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        grado_da TEXT,
        grado_a TEXT,
        sanzione TEXT,
        motivazione TEXT NOT NULL,
        data TEXT NOT NULL,
        operatore TEXT DEFAULT 'Dirigenza',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(agente_id) REFERENCES agenti(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS comunicati (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titolo TEXT NOT NULL,
        testo TEXT NOT NULL,
        priorita TEXT NOT NULL DEFAULT 'Info',
        autore TEXT DEFAULT 'Dirigenza',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS comunicati_letti (
        comunicato_id INTEGER,
        discord_id TEXT,
        PRIMARY KEY(comunicato_id, discord_id)
    );
    CREATE TABLE IF NOT EXISTS pec (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mittente_id TEXT NOT NULL,
        mittente_nome TEXT NOT NULL,
        destinatario_id TEXT NOT NULL,
        destinatario_nome TEXT NOT NULL,
        oggetto TEXT NOT NULL,
        testo TEXT NOT NULL,
        priorita TEXT DEFAULT 'Normale',
        stato TEXT DEFAULT 'inviata',
        letta INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS segnalazioni (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agente_id TEXT NOT NULL,
        agente_nome TEXT NOT NULL,
        titolo TEXT NOT NULL,
        descrizione TEXT NOT NULL,
        priorita TEXT DEFAULT 'Normale',
        stato TEXT DEFAULT 'Aperta',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS documenti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titolo TEXT NOT NULL,
        descrizione TEXT DEFAULT '',
        link TEXT DEFAULT '',
        icona TEXT DEFAULT '📄',
        categoria TEXT NOT NULL,
        stato TEXT DEFAULT 'Pubblicato',
        autore TEXT DEFAULT 'Dirigenza',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        discord_id TEXT,
        discord_username TEXT,
        discord_avatar TEXT,
        roles TEXT,
        access_level TEXT,
        expires_at INTEGER
    );
    """)
    # Settings di default
    defaults = {
        "gradi": json.dumps([
            "Agente","Agente Scelto","Assistente","Assistente Capo",
            "Sovrintendente","Sovrintendente Capo","Ispettore",
            "Ispettore Capo","Commissario","Vice Direttore","Direttore"
        ]),
        "sanzioni": json.dumps(["Avviso Formale","Richiamo Scritto","Sospensione Temporanea","Sospensione Prolungata"]),
        "logo": ""
    }
    for k, v in defaults.items():
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    db.commit()
    db.close()

init_db()

# ─── AUTH HELPERS ─────────────────────────────────────────────────────────────
def verify_api_key(request: Request):
    key = request.headers.get("X-API-Key") or request.query_params.get("key")
    if key != API_KEY:
        raise HTTPException(403, "API key non valida")

def get_session(token: str):
    db = get_db()
    row = db.execute("SELECT * FROM sessions WHERE token=? AND expires_at>?",
                     (token, int(time.time()))).fetchone()
    db.close()
    return dict(row) if row else None

def require_session(request: Request):
    token = request.headers.get("X-Session") or request.query_params.get("session")
    if not token:
        raise HTTPException(401, "Sessione richiesta")
    sess = get_session(token)
    if not sess:
        raise HTTPException(401, "Sessione scaduta")
    return sess

def require_dirigenza(request: Request):
    sess = require_session(request)
    if sess["access_level"] != "dirigenza":
        raise HTTPException(403, "Accesso riservato alla dirigenza")
    return sess

# ─── MODELS ───────────────────────────────────────────────────────────────────
class AgentePUT(BaseModel):
    nome: str
    cognome: str
    codice_fiscale: Optional[str] = ""
    discord_username: Optional[str] = ""
    grado: str
    stato: str = "Attivo"
    note: Optional[str] = ""
    data_ingresso: Optional[str] = ""

class AzionePOST(BaseModel):
    agente_id: int
    tipo: str  # Promozione|Degrado|Sanzione|RimozioneSanzione|CambioStato
    grado_a: Optional[str] = None
    sanzione: Optional[str] = None
    motivazione: str
    data: str
    operatore: Optional[str] = "Dirigenza"

class ComunicatoPOST(BaseModel):
    titolo: str
    testo: str
    priorita: str = "Info"
    autore: Optional[str] = "Dirigenza"

class PECPOST(BaseModel):
    mittente_id: str
    mittente_nome: str
    destinatario_id: str
    destinatario_nome: str
    oggetto: str
    testo: str
    priorita: str = "Normale"
    stato: str = "inviata"

class SegnalazionePOST(BaseModel):
    agente_id: str
    agente_nome: str
    titolo: str
    descrizione: str
    priorita: str = "Normale"

class DocumentoPOST(BaseModel):
    titolo: str
    descrizione: Optional[str] = ""
    link: Optional[str] = ""
    icona: Optional[str] = "📄"
    categoria: str
    stato: Optional[str] = "Pubblicato"
    autore: Optional[str] = "Dirigenza"

class SettingsUpdate(BaseModel):
    key: str
    value: str

# ─── ROOT ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse("gestionale.html")

# ─── DISCORD OAUTH ─────────────────────────────────────────────────────────────
@app.get("/auth/discord")
def discord_login():
    if not DISCORD_ID:
        raise HTTPException(400, "Discord OAuth non configurato")
    url = (f"https://discord.com/api/oauth2/authorize"
           f"?client_id={DISCORD_ID}"
           f"&redirect_uri={REDIRECT_URI}"
           f"&response_type=code"
           f"&scope=identify+guilds.members.read")
    return RedirectResponse(url)

@app.get("/auth/discord/callback")
async def discord_callback(code: str):
    if not DISCORD_ID or not DISCORD_SECRET:
        raise HTTPException(400, "Discord OAuth non configurato")
    async with httpx.AsyncClient() as client:
        # Token exchange
        tok = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id": DISCORD_ID, "client_secret": DISCORD_SECRET,
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        tok_data = tok.json()
        access_token = tok_data.get("access_token")
        if not access_token:
            return RedirectResponse("/?discord_error=1")
        # User info
        user = await client.get("https://discord.com/api/users/@me",
                                 headers={"Authorization": f"Bearer {access_token}"})
        user_data = user.json()
        discord_id = user_data.get("id")
        username = user_data.get("username", "")
        avatar = user_data.get("avatar", "")
        # Guild member roles
        roles = []
        access_level = "agente"
        if DISCORD_GUILD:
            member = await client.get(
                f"https://discord.com/api/users/@me/guilds/{DISCORD_GUILD}/member",
                headers={"Authorization": f"Bearer {access_token}"})
            if member.status_code == 200:
                member_data = member.json()
                roles = [r.lower() for r in member_data.get("roles", [])]
                nick = member_data.get("nick", username)
                username = nick or username
                for rn in ROLE_DIRIGENZA:
                    if any(rn in r for r in roles):
                        access_level = "dirigenza"
                        break
    # Create session
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + 7 * 86400
    db = get_db()
    db.execute("""INSERT OR REPLACE INTO sessions
        (token,discord_id,discord_username,discord_avatar,roles,access_level,expires_at)
        VALUES(?,?,?,?,?,?,?)""",
        (token, discord_id, username, avatar, json.dumps(roles), access_level, expires))
    db.commit()
    db.close()
    return RedirectResponse(f"/?discord_session={token}&level={access_level}&name={username}")

@app.post("/auth/logout")
def logout(request: Request):
    token = request.headers.get("X-Session")
    if token:
        db = get_db()
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        db.commit()
        db.close()
    return {"ok": True}

@app.get("/auth/session")
def check_session(request: Request):
    token = request.headers.get("X-Session")
    if not token:
        raise HTTPException(401)
    sess = get_session(token)
    if not sess:
        raise HTTPException(401)
    return sess



# ─── SETTINGS ─────────────────────────────────────────────────────────────────
@app.get("/api/settings")
def get_settings(_=Depends(verify_api_key)):
    db = get_db()
    rows = db.execute("SELECT key,value FROM settings WHERE key IN ('gradi','sanzioni','logo')").fetchall()
    db.close()
    return {r["key"]: r["value"] for r in rows}

@app.put("/api/settings")
def update_settings(body: SettingsUpdate, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (body.key, body.value))
    db.commit()
    db.close()
    return {"ok": True}


# ─── SYNC DISCORD ─────────────────────────────────────────────────────────────
@app.post("/sync")
def sync_discord(_=Depends(verify_api_key)):
    return {"ok": True, "message": "Sync completato"}

# ─── AGENTI ───────────────────────────────────────────────────────────────────
@app.get("/api/agenti")
def list_agenti(_=Depends(verify_api_key)):
    db = get_db()
    rows = db.execute("SELECT * FROM agenti ORDER BY cognome").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/agenti/{aid}")
def get_agente(aid: int, _=Depends(verify_api_key)):
    db = get_db()
    ag = db.execute("SELECT * FROM agenti WHERE id=?", (aid,)).fetchone()
    if not ag:
        raise HTTPException(404)
    azioni = db.execute("SELECT * FROM azioni WHERE agente_id=? ORDER BY created_at DESC", (aid,)).fetchall()
    segs = db.execute("SELECT * FROM segnalazioni WHERE agente_id=? ORDER BY created_at DESC", (str(aid),)).fetchall()
    db.close()
    return {"agente": dict(ag), "azioni": [dict(a) for a in azioni],
            "segnalazioni": [dict(s) for s in segs]}

@app.post("/api/agenti")
def add_agente(body: AgentePUT, _=Depends(verify_api_key)):
    db = get_db()
    if not body.data_ingresso:
        body.data_ingresso = datetime.now().strftime("%Y-%m-%d")
    try:
        cur = db.execute("""INSERT INTO agenti
            (nome,cognome,codice_fiscale,discord_username,grado,stato,note,data_ingresso)
            VALUES(?,?,?,?,?,?,?,?)""",
            (body.nome, body.cognome, body.codice_fiscale, body.discord_username,
             body.grado, body.stato, body.note, body.data_ingresso))
        db.commit()
        aid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Codice fiscale già presente")
    finally:
        db.close()
    return {"id": aid}

@app.put("/api/agenti/{aid}")
def update_agente(aid: int, body: AgentePUT, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("""UPDATE agenti SET nome=?,cognome=?,codice_fiscale=?,discord_username=?,
        grado=?,stato=?,note=? WHERE id=?""",
        (body.nome, body.cognome, body.codice_fiscale, body.discord_username,
         body.grado, body.stato, body.note, aid))
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/api/agenti/{aid}")
def delete_agente(aid: int, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("DELETE FROM agenti WHERE id=?", (aid,))
    db.commit()
    db.close()
    return {"ok": True}

# ─── AZIONI ───────────────────────────────────────────────────────────────────
@app.get("/api/azioni")
def list_azioni(_=Depends(verify_api_key)):
    db = get_db()
    rows = db.execute("""
        SELECT az.*, ag.nome, ag.cognome, ag.grado as grado_attuale
        FROM azioni az JOIN agenti ag ON az.agente_id=ag.id
        ORDER BY az.created_at DESC LIMIT 200
    """).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/azioni")
def add_azione(body: AzionePOST, _=Depends(verify_api_key)):
    db = get_db()
    ag = db.execute("SELECT * FROM agenti WHERE id=?", (body.agente_id,)).fetchone()
    if not ag:
        raise HTTPException(404, "Agente non trovato")

    grado_da = ag["grado"]
    sanzione_attiva = ag["sanzione_attiva"]

    if body.tipo == "Promozione" and body.grado_a:
        db.execute("UPDATE agenti SET grado=? WHERE id=?", (body.grado_a, body.agente_id))
        grado_a = body.grado_a
    elif body.tipo == "Degrado" and body.grado_a:
        db.execute("UPDATE agenti SET grado=? WHERE id=?", (body.grado_a, body.agente_id))
        grado_a = body.grado_a
    elif body.tipo == "Sanzione" and body.sanzione:
        db.execute("UPDATE agenti SET sanzione_attiva=?,sanzione_motivo=? WHERE id=?",
                   (body.sanzione, body.motivazione, body.agente_id))
        grado_a = None
    elif body.tipo == "RimozioneSanzione":
        db.execute("UPDATE agenti SET sanzione_attiva=NULL,sanzione_motivo=NULL WHERE id=?",
                   (body.agente_id,))
        grado_a = None
    elif body.tipo == "CambioStato" and body.grado_a:
        db.execute("UPDATE agenti SET stato=? WHERE id=?", (body.grado_a, body.agente_id))
        grado_a = body.grado_a
    else:
        grado_a = body.grado_a

    cur = db.execute("""INSERT INTO azioni
        (agente_id,tipo,grado_da,grado_a,sanzione,motivazione,data,operatore)
        VALUES(?,?,?,?,?,?,?,?)""",
        (body.agente_id, body.tipo, grado_da, grado_a, body.sanzione,
         body.motivazione, body.data, body.operatore))
    db.commit()
    db.close()
    return {"id": cur.lastrowid}

@app.delete("/api/azioni/{aid}")
def delete_azione(aid: int, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("DELETE FROM azioni WHERE id=?", (aid,))
    db.commit()
    db.close()
    return {"ok": True}

# ─── COMUNICATI ───────────────────────────────────────────────────────────────
@app.get("/api/comunicati")
def list_comunicati(_=Depends(verify_api_key)):
    db = get_db()
    rows = db.execute("SELECT * FROM comunicati ORDER BY created_at DESC").fetchall()
    letti_rows = db.execute("SELECT comunicato_id, COUNT(*) as n FROM comunicati_letti GROUP BY comunicato_id").fetchall()
    letti_map = {r["comunicato_id"]: r["n"] for r in letti_rows}
    db.close()
    result = []
    for r in rows:
        d = dict(r)
        d["lettori"] = letti_map.get(d["id"], 0)
        result.append(d)
    return result

@app.post("/api/comunicati")
def add_comunicato(body: ComunicatoPOST, _=Depends(verify_api_key)):
    db = get_db()
    cur = db.execute("INSERT INTO comunicati(titolo,testo,priorita,autore) VALUES(?,?,?,?)",
                     (body.titolo, body.testo, body.priorita, body.autore))
    db.commit()
    db.close()
    return {"id": cur.lastrowid}

@app.put("/api/comunicati/{cid}")
def update_comunicato(cid: int, body: ComunicatoPOST, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("UPDATE comunicati SET titolo=?,testo=?,priorita=? WHERE id=?",
               (body.titolo, body.testo, body.priorita, cid))
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/api/comunicati/{cid}")
def delete_comunicato(cid: int, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("DELETE FROM comunicati WHERE id=?", (cid,))
    db.execute("DELETE FROM comunicati_letti WHERE comunicato_id=?", (cid,))
    db.commit()
    db.close()
    return {"ok": True}

@app.post("/api/comunicati/{cid}/letto")
async def mark_letto(cid: int, request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    discord_id = body.get("discord_id", "")
    db = get_db()
    db.execute("INSERT OR IGNORE INTO comunicati_letti(comunicato_id,discord_id) VALUES(?,?)",
               (cid, discord_id))
    db.commit()
    db.close()
    return {"ok": True}

@app.get("/api/comunicati/letti/{discord_id}")
def get_letti(discord_id: str, _=Depends(verify_api_key)):
    db = get_db()
    rows = db.execute("SELECT comunicato_id FROM comunicati_letti WHERE discord_id=?",
                      (discord_id,)).fetchall()
    db.close()
    return [r["comunicato_id"] for r in rows]

# ─── PEC ──────────────────────────────────────────────────────────────────────
@app.get("/api/pec")
def list_pec(user_id: Optional[str] = None, _=Depends(verify_api_key)):
    db = get_db()
    if user_id:
        rows = db.execute("""SELECT * FROM pec
            WHERE (mittente_id=? OR destinatario_id=?) AND stato!='bozza'
            ORDER BY created_at DESC""", (user_id, user_id)).fetchall()
    else:
        rows = db.execute("SELECT * FROM pec ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/pec/bozze/{user_id}")
def list_bozze(user_id: str, _=Depends(verify_api_key)):
    db = get_db()
    rows = db.execute("SELECT * FROM pec WHERE mittente_id=? AND stato='bozza' ORDER BY created_at DESC",
                      (user_id,)).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/pec")
def send_pec(body: PECPOST, _=Depends(verify_api_key)):
    db = get_db()
    cur = db.execute("""INSERT INTO pec
        (mittente_id,mittente_nome,destinatario_id,destinatario_nome,oggetto,testo,priorita,stato)
        VALUES(?,?,?,?,?,?,?,?)""",
        (body.mittente_id, body.mittente_nome, body.destinatario_id, body.destinatario_nome,
         body.oggetto, body.testo, body.priorita, body.stato))
    db.commit()
    db.close()
    return {"id": cur.lastrowid}

@app.put("/api/pec/{pid}/letta")
def mark_pec_letta(pid: int, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("UPDATE pec SET letta=1 WHERE id=?", (pid,))
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/api/pec/{pid}")
def delete_pec(pid: int, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("DELETE FROM pec WHERE id=?", (pid,))
    db.commit()
    db.close()
    return {"ok": True}

# ─── SEGNALAZIONI ─────────────────────────────────────────────────────────────
@app.get("/api/segnalazioni")
def list_segnalazioni(agente_id: Optional[str] = None, _=Depends(verify_api_key)):
    db = get_db()
    if agente_id:
        rows = db.execute("SELECT * FROM segnalazioni WHERE agente_id=? ORDER BY created_at DESC",
                          (agente_id,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM segnalazioni ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/segnalazioni")
def add_segnalazione(body: SegnalazionePOST, _=Depends(verify_api_key)):
    db = get_db()
    cur = db.execute("""INSERT INTO segnalazioni
        (agente_id,agente_nome,titolo,descrizione,priorita)
        VALUES(?,?,?,?,?)""",
        (body.agente_id, body.agente_nome, body.titolo, body.descrizione, body.priorita))
    db.commit()
    db.close()
    return {"id": cur.lastrowid}

@app.put("/api/segnalazioni/{sid}/stato")
async def update_stato_segnalazione(sid: int, request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    stato = body.get("stato", "")
    db = get_db()
    db.execute("UPDATE segnalazioni SET stato=? WHERE id=?", (stato, sid))
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/api/segnalazioni/{sid}")
def delete_segnalazione(sid: int, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("DELETE FROM segnalazioni WHERE id=?", (sid,))
    db.commit()
    db.close()
    return {"ok": True}

# ─── DOCUMENTI ────────────────────────────────────────────────────────────────
@app.get("/api/documenti")
def list_documenti(categoria: Optional[str] = None, _=Depends(verify_api_key)):
    db = get_db()
    if categoria:
        rows = db.execute("SELECT * FROM documenti WHERE categoria=? ORDER BY created_at DESC",
                          (categoria,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM documenti ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/documenti")
def add_documento(body: DocumentoPOST, _=Depends(verify_api_key)):
    db = get_db()
    cur = db.execute("""INSERT INTO documenti
        (titolo,descrizione,link,icona,categoria,stato,autore)
        VALUES(?,?,?,?,?,?,?)""",
        (body.titolo, body.descrizione, body.link, body.icona,
         body.categoria, body.stato, body.autore))
    db.commit()
    db.close()
    return {"id": cur.lastrowid}

@app.put("/api/documenti/{did}")
def update_documento(did: int, body: DocumentoPOST, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("""UPDATE documenti SET titolo=?,descrizione=?,link=?,icona=?,
        categoria=?,stato=? WHERE id=?""",
        (body.titolo, body.descrizione, body.link, body.icona,
         body.categoria, body.stato, did))
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/api/documenti/{did}")
def delete_documento(did: int, _=Depends(verify_api_key)):
    db = get_db()
    db.execute("DELETE FROM documenti WHERE id=?", (did,))
    db.commit()
    db.close()
    return {"ok": True}

# ─── DASHBOARD ────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def get_dashboard(_=Depends(verify_api_key)):
    db = get_db()
    totali = db.execute("SELECT COUNT(*) as n FROM agenti").fetchone()["n"]
    attivi = db.execute("SELECT COUNT(*) as n FROM agenti WHERE stato='Attivo'").fetchone()["n"]
    sospesi = db.execute("SELECT COUNT(*) as n FROM agenti WHERE stato='Sospeso'").fetchone()["n"]
    promozioni = db.execute("SELECT COUNT(*) as n FROM azioni WHERE tipo='Promozione'").fetchone()["n"]
    sanzioni_tot = db.execute("SELECT COUNT(*) as n FROM azioni WHERE tipo='Sanzione'").fetchone()["n"]
    ultime_azioni = db.execute("""
        SELECT az.*, ag.nome, ag.cognome FROM azioni az
        JOIN agenti ag ON az.agente_id=ag.id
        ORDER BY az.created_at DESC LIMIT 7
    """).fetchall()
    gradi_dist = db.execute("""
        SELECT grado, COUNT(*) as n FROM agenti GROUP BY grado ORDER BY n DESC
    """).fetchall()
    ultimi_comunicati = db.execute(
        "SELECT * FROM comunicati ORDER BY created_at DESC LIMIT 3").fetchall()
    # Trend 12 mesi
    trend = []
    for i in range(12):
        d = datetime.now() - timedelta(days=30*i)
        m = d.strftime("%Y-%m")
        prom = db.execute("SELECT COUNT(*) as n FROM azioni WHERE tipo='Promozione' AND strftime('%Y-%m',created_at)=?", (m,)).fetchone()["n"]
        san = db.execute("SELECT COUNT(*) as n FROM azioni WHERE tipo='Sanzione' AND strftime('%Y-%m',created_at)=?", (m,)).fetchone()["n"]
        deg = db.execute("SELECT COUNT(*) as n FROM azioni WHERE tipo='Degrado' AND strftime('%Y-%m',created_at)=?", (m,)).fetchone()["n"]
        trend.append({"mese": d.strftime("%b %y"), "promozioni": prom, "sanzioni": san, "degradi": deg})
    trend.reverse()
    # Stati distribuzione
    stati = db.execute("SELECT stato, COUNT(*) as n FROM agenti GROUP BY stato").fetchall()
    # Top sanzionati
    top_san = db.execute("""
        SELECT ag.nome, ag.cognome, ag.grado, COUNT(*) as n
        FROM azioni az JOIN agenti ag ON az.agente_id=ag.id
        WHERE az.tipo='Sanzione'
        GROUP BY az.agente_id ORDER BY n DESC LIMIT 6
    """).fetchall()
    # Critici ultimi 30gg
    critici = db.execute("""
        SELECT az.*, ag.nome, ag.cognome FROM azioni az
        JOIN agenti ag ON az.agente_id=ag.id
        WHERE az.tipo IN ('Sanzione','Degrado','CambioStato')
        AND az.created_at >= datetime('now','-30 days')
        ORDER BY az.created_at DESC LIMIT 20
    """).fetchall()
    db.close()
    return {
        "kpi": {"totali": totali, "attivi": attivi, "sospesi": sospesi,
                "promozioni": promozioni, "sanzioni": sanzioni_tot},
        "ultime_azioni": [dict(r) for r in ultime_azioni],
        "gradi_dist": [dict(r) for r in gradi_dist],
        "ultimi_comunicati": [dict(r) for r in ultimi_comunicati],
        "trend": trend,
        "stati_dist": [dict(r) for r in stati],
        "top_sanzionati": [dict(r) for r in top_san],
        "critici": [dict(r) for r in critici]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
