"""
Gestionale Polizia d'Estovia — Backend
FastAPI + PostgreSQL (Railway) / SQLite (fallback)
Discord OAuth2, sessioni token
"""

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import secrets, time, json, os, httpx
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
API_KEY        = os.getenv("GESTIONALE_API_KEY", "estovia2026")
DISCORD_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_GUILD  = os.getenv("DISCORD_GUILD_ID", "")
REDIRECT_URI   = os.getenv("DISCORD_REDIRECT_URI",
                            "https://gestionalepolizia-production.up.railway.app/auth/discord/callback")
DATABASE_URL   = os.getenv("DATABASE_URL", "")
DB_PATH        = os.getenv("DB_PATH", "gestionale.db")

ROLE_DIRIGENZA = {
    "staff", "dirigenza", "ispettorato", "sovrintendenza",
    "direttore", "vice direttore", "commissario", "ispettore capo",
    "ispettore", "sovrintendente capo", "sovrintendente", "assistente capo"
}

app = FastAPI(title="Gestionale PdE")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ─── DATABASE ABSTRACTION ─────────────────────────────────────────────────────
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

def get_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = False
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

def db_execute(conn, sql, params=()):
    if USE_POSTGRES:
        sql = sql.replace("?", "%s")
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur
    else:
        return conn.execute(sql, params)

def db_fetchone(conn, sql, params=()):
    cur = db_execute(conn, sql, params)
    row = cur.fetchone()
    return dict(row) if row else None

def db_fetchall(conn, sql, params=()):
    cur = db_execute(conn, sql, params)
    return [dict(r) for r in cur.fetchall()]

def init_db():
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS agenti (
            id SERIAL PRIMARY KEY, nome TEXT NOT NULL, cognome TEXT NOT NULL,
            codice_fiscale TEXT UNIQUE, discord_username TEXT, grado TEXT NOT NULL,
            stato TEXT NOT NULL DEFAULT 'Attivo', note TEXT DEFAULT '',
            data_ingresso TEXT NOT NULL, sanzione_attiva TEXT DEFAULT NULL,
            sanzione_motivo TEXT DEFAULT NULL,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        );
        CREATE TABLE IF NOT EXISTS azioni (
            id SERIAL PRIMARY KEY, agente_id INTEGER NOT NULL, tipo TEXT NOT NULL,
            grado_da TEXT, grado_a TEXT, sanzione TEXT, motivazione TEXT NOT NULL,
            data TEXT NOT NULL, operatore TEXT DEFAULT 'Dirigenza',
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        );
        CREATE TABLE IF NOT EXISTS comunicati (
            id SERIAL PRIMARY KEY, titolo TEXT NOT NULL, testo TEXT NOT NULL,
            priorita TEXT NOT NULL DEFAULT 'Info', autore TEXT DEFAULT 'Dirigenza',
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        );
        CREATE TABLE IF NOT EXISTS comunicati_letti (
            comunicato_id INTEGER, discord_id TEXT, PRIMARY KEY(comunicato_id, discord_id)
        );
        CREATE TABLE IF NOT EXISTS pec (
            id SERIAL PRIMARY KEY, mittente_id TEXT NOT NULL, mittente_nome TEXT NOT NULL,
            destinatario_id TEXT NOT NULL, destinatario_nome TEXT NOT NULL,
            oggetto TEXT NOT NULL, testo TEXT NOT NULL, priorita TEXT DEFAULT 'Normale',
            stato TEXT DEFAULT 'inviata', letta INTEGER DEFAULT 0,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        );
        CREATE TABLE IF NOT EXISTS segnalazioni (
            id SERIAL PRIMARY KEY, agente_id TEXT NOT NULL, agente_nome TEXT NOT NULL,
            titolo TEXT NOT NULL, descrizione TEXT NOT NULL, priorita TEXT DEFAULT 'Normale',
            stato TEXT DEFAULT 'Aperta',
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        );
        CREATE TABLE IF NOT EXISTS documenti (
            id SERIAL PRIMARY KEY, titolo TEXT NOT NULL, descrizione TEXT DEFAULT '',
            link TEXT DEFAULT '', icona TEXT DEFAULT '📄', categoria TEXT NOT NULL,
            stato TEXT DEFAULT 'Pubblicato', autore TEXT DEFAULT 'Dirigenza',
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, discord_id TEXT, discord_username TEXT,
            discord_avatar TEXT, roles TEXT, access_level TEXT, expires_at BIGINT
        );
        """)
        defaults = {
            "gradi": json.dumps(["Agente","Agente Scelto","Assistente","Assistente Capo",
                "Sovrintendente","Sovrintendente Capo","Ispettore","Ispettore Capo",
                "Commissario","Vice Direttore","Direttore"]),
            "sanzioni": json.dumps(["Avviso Formale","Richiamo Scritto","Sospensione Temporanea","Sospensione Prolungata"]),
            "logo": ""
        }
        for k, v in defaults.items():
            cur.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING", (k, v))
        conn.commit()
        conn.close()
    else:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS agenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, cognome TEXT NOT NULL,
            codice_fiscale TEXT UNIQUE, discord_username TEXT, grado TEXT NOT NULL,
            stato TEXT NOT NULL DEFAULT 'Attivo', note TEXT DEFAULT '',
            data_ingresso TEXT NOT NULL, sanzione_attiva TEXT DEFAULT NULL,
            sanzione_motivo TEXT DEFAULT NULL, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS azioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT, agente_id INTEGER NOT NULL, tipo TEXT NOT NULL,
            grado_da TEXT, grado_a TEXT, sanzione TEXT, motivazione TEXT NOT NULL,
            data TEXT NOT NULL, operatore TEXT DEFAULT 'Dirigenza',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(agente_id) REFERENCES agenti(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS comunicati (
            id INTEGER PRIMARY KEY AUTOINCREMENT, titolo TEXT NOT NULL, testo TEXT NOT NULL,
            priorita TEXT NOT NULL DEFAULT 'Info', autore TEXT DEFAULT 'Dirigenza',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS comunicati_letti (
            comunicato_id INTEGER, discord_id TEXT, PRIMARY KEY(comunicato_id, discord_id)
        );
        CREATE TABLE IF NOT EXISTS pec (
            id INTEGER PRIMARY KEY AUTOINCREMENT, mittente_id TEXT NOT NULL, mittente_nome TEXT NOT NULL,
            destinatario_id TEXT NOT NULL, destinatario_nome TEXT NOT NULL,
            oggetto TEXT NOT NULL, testo TEXT NOT NULL, priorita TEXT DEFAULT 'Normale',
            stato TEXT DEFAULT 'inviata', letta INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS segnalazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT, agente_id TEXT NOT NULL, agente_nome TEXT NOT NULL,
            titolo TEXT NOT NULL, descrizione TEXT NOT NULL, priorita TEXT DEFAULT 'Normale',
            stato TEXT DEFAULT 'Aperta', created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS documenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT, titolo TEXT NOT NULL, descrizione TEXT DEFAULT '',
            link TEXT DEFAULT '', icona TEXT DEFAULT '📄', categoria TEXT NOT NULL,
            stato TEXT DEFAULT 'Pubblicato', autore TEXT DEFAULT 'Dirigenza',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, discord_id TEXT, discord_username TEXT,
            discord_avatar TEXT, roles TEXT, access_level TEXT, expires_at INTEGER
        );
        """)
        defaults = {
            "gradi": json.dumps(["Agente","Agente Scelto","Assistente","Assistente Capo",
                "Sovrintendente","Sovrintendente Capo","Ispettore","Ispettore Capo",
                "Commissario","Vice Direttore","Direttore"]),
            "sanzioni": json.dumps(["Avviso Formale","Richiamo Scritto","Sospensione Temporanea","Sospensione Prolungata"]),
            "logo": ""
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        conn.commit()
        conn.close()

init_db()

# ─── AUTH HELPERS ─────────────────────────────────────────────────────────────
def verify_api_key(request: Request):
    key = request.headers.get("X-API-Key") or request.query_params.get("key")
    if key != API_KEY:
        raise HTTPException(403, "API key non valida")

def get_session(token: str):
    conn = get_db()
    row = db_fetchone(conn, "SELECT * FROM sessions WHERE token=? AND expires_at>?",
                      (token, int(time.time())))
    conn.close()
    return row

def require_session(request: Request):
    token = request.headers.get("X-Session") or request.query_params.get("session")
    if not token: raise HTTPException(401, "Sessione richiesta")
    sess = get_session(token)
    if not sess: raise HTTPException(401, "Sessione scaduta")
    return sess

def require_dirigenza(request: Request):
    sess = require_session(request)
    if sess["access_level"] != "dirigenza":
        raise HTTPException(403, "Accesso riservato alla dirigenza")
    return sess

# ─── MODELS ───────────────────────────────────────────────────────────────────
class AgentePUT(BaseModel):
    nome: str; cognome: str
    codice_fiscale: Optional[str] = ""
    discord_username: Optional[str] = ""
    grado: str; stato: str = "Attivo"
    note: Optional[str] = ""; data_ingresso: Optional[str] = ""

class AzionePOST(BaseModel):
    agente_id: int; tipo: str
    grado_a: Optional[str] = None; sanzione: Optional[str] = None
    motivazione: str; data: str; operatore: Optional[str] = "Dirigenza"

class ComunicatoPOST(BaseModel):
    titolo: str; testo: str; priorita: str = "Info"; autore: Optional[str] = "Dirigenza"

class PECPOST(BaseModel):
    mittente_id: str; mittente_nome: str
    destinatario_id: str; destinatario_nome: str
    oggetto: str; testo: str; priorita: str = "Normale"; stato: str = "inviata"

class SegnalazionePOST(BaseModel):
    agente_id: str; agente_nome: str
    titolo: str; descrizione: str; priorita: str = "Normale"

class DocumentoPOST(BaseModel):
    titolo: str; descrizione: Optional[str] = ""
    link: Optional[str] = ""; icona: Optional[str] = "📄"
    categoria: str; stato: Optional[str] = "Pubblicato"; autore: Optional[str] = "Dirigenza"

class SettingsUpdate(BaseModel):
    key: str; value: str

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
           f"?client_id={DISCORD_ID}&redirect_uri={REDIRECT_URI}"
           f"&response_type=code&scope=identify+guilds.members.read")
    return RedirectResponse(url)

@app.get("/auth/discord/callback")
async def discord_callback(code: str):
    if not DISCORD_ID or not DISCORD_SECRET:
        raise HTTPException(400, "Discord OAuth non configurato")
    async with httpx.AsyncClient() as client:
        tok = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id": DISCORD_ID, "client_secret": DISCORD_SECRET,
            "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        tok_data = tok.json()
        access_token = tok_data.get("access_token")
        if not access_token:
            return RedirectResponse("/?discord_error=1")
        user = await client.get("https://discord.com/api/users/@me",
                                 headers={"Authorization": f"Bearer {access_token}"})
        user_data = user.json()
        discord_id = user_data.get("id")
        username = user_data.get("username", "")
        avatar = user_data.get("avatar", "")
        roles = []; access_level = "agente"
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
                        access_level = "dirigenza"; break
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + 7 * 86400
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute("""INSERT INTO sessions
            (token,discord_id,discord_username,discord_avatar,roles,access_level,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(token) DO UPDATE SET
            discord_id=EXCLUDED.discord_id, discord_username=EXCLUDED.discord_username,
            discord_avatar=EXCLUDED.discord_avatar, roles=EXCLUDED.roles,
            access_level=EXCLUDED.access_level, expires_at=EXCLUDED.expires_at""",
            (token, discord_id, username, avatar, json.dumps(roles), access_level, expires))
    else:
        conn.execute("""INSERT OR REPLACE INTO sessions
            (token,discord_id,discord_username,discord_avatar,roles,access_level,expires_at)
            VALUES(?,?,?,?,?,?,?)""",
            (token, discord_id, username, avatar, json.dumps(roles), access_level, expires))
    conn.commit(); conn.close()
    return RedirectResponse(f"/?discord_session={token}&level={access_level}&name={username}")

@app.post("/auth/logout")
def logout(request: Request):
    token = request.headers.get("X-Session")
    if token:
        conn = get_db()
        db_execute(conn, "DELETE FROM sessions WHERE token=?", (token,))
        conn.commit(); conn.close()
    return {"ok": True}

@app.get("/auth/session")
def check_session(request: Request):
    token = request.headers.get("X-Session")
    if not token: raise HTTPException(401)
    sess = get_session(token)
    if not sess: raise HTTPException(401)
    return sess

# ─── SETTINGS ─────────────────────────────────────────────────────────────────
@app.get("/api/settings")
def get_settings(_=Depends(verify_api_key)):
    conn = get_db()
    rows = db_fetchall(conn, "SELECT key,value FROM settings WHERE key IN ('gradi','sanzioni','logo')")
    conn.close()
    return {r["key"]: r["value"] for r in rows}

@app.put("/api/settings")
def update_settings(body: SettingsUpdate, _=Depends(verify_api_key)):
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                    (body.key, body.value))
    else:
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (body.key, body.value))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/sync")
def sync_discord(_=Depends(verify_api_key)):
    return {"ok": True, "message": "Sync completato"}

# ─── AGENTI ───────────────────────────────────────────────────────────────────
@app.get("/api/agenti")
def list_agenti(_=Depends(verify_api_key)):
    conn = get_db()
    rows = db_fetchall(conn, "SELECT * FROM agenti ORDER BY cognome")
    conn.close(); return rows

@app.get("/api/agenti/{aid}")
def get_agente(aid: int, _=Depends(verify_api_key)):
    conn = get_db()
    ag = db_fetchone(conn, "SELECT * FROM agenti WHERE id=?", (aid,))
    if not ag: raise HTTPException(404)
    azioni = db_fetchall(conn, "SELECT * FROM azioni WHERE agente_id=? ORDER BY created_at DESC", (aid,))
    segs   = db_fetchall(conn, "SELECT * FROM segnalazioni WHERE agente_id=? ORDER BY created_at DESC", (str(aid),))
    conn.close()
    return {"agente": ag, "azioni": azioni, "segnalazioni": segs}

@app.post("/api/agenti")
def add_agente(body: AgentePUT, _=Depends(verify_api_key)):
    conn = get_db()
    if not body.data_ingresso:
        body.data_ingresso = datetime.now().strftime("%Y-%m-%d")
    try:
        if USE_POSTGRES:
            cur = conn.cursor()
            cur.execute("""INSERT INTO agenti
                (nome,cognome,codice_fiscale,discord_username,grado,stato,note,data_ingresso)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (body.nome,body.cognome,body.codice_fiscale,body.discord_username,
                 body.grado,body.stato,body.note,body.data_ingresso))
            aid = cur.fetchone()["id"]
        else:
            cur = conn.execute("""INSERT INTO agenti
                (nome,cognome,codice_fiscale,discord_username,grado,stato,note,data_ingresso)
                VALUES(?,?,?,?,?,?,?,?)""",
                (body.nome,body.cognome,body.codice_fiscale,body.discord_username,
                 body.grado,body.stato,body.note,body.data_ingresso))
            aid = cur.lastrowid
        conn.commit()
    except Exception:
        conn.rollback(); raise HTTPException(400, "Codice fiscale già presente")
    finally:
        conn.close()
    return {"id": aid}

@app.put("/api/agenti/{aid}")
def update_agente(aid: int, body: AgentePUT, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, """UPDATE agenti SET nome=?,cognome=?,codice_fiscale=?,discord_username=?,
        grado=?,stato=?,note=? WHERE id=?""",
        (body.nome,body.cognome,body.codice_fiscale,body.discord_username,
         body.grado,body.stato,body.note,aid))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/agenti/{aid}")
def delete_agente(aid: int, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, "DELETE FROM agenti WHERE id=?", (aid,))
    conn.commit(); conn.close(); return {"ok": True}

# ─── AZIONI ───────────────────────────────────────────────────────────────────
@app.get("/api/azioni")
def list_azioni(_=Depends(verify_api_key)):
    conn = get_db()
    rows = db_fetchall(conn, """SELECT az.*, ag.nome, ag.cognome FROM azioni az
        JOIN agenti ag ON az.agente_id=ag.id ORDER BY az.created_at DESC""")
    conn.close(); return rows

@app.post("/api/azioni")
def add_azione(body: AzionePOST, _=Depends(verify_api_key)):
    conn = get_db()
    ag = db_fetchone(conn, "SELECT * FROM agenti WHERE id=?", (body.agente_id,))
    if not ag: raise HTTPException(404, "Agente non trovato")
    grado_da = ag["grado"]
    try:
        if USE_POSTGRES:
            cur = conn.cursor()
            cur.execute("""INSERT INTO azioni
                (agente_id,tipo,grado_da,grado_a,sanzione,motivazione,data,operatore)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (body.agente_id,body.tipo,grado_da,body.grado_a,
                 body.sanzione,body.motivazione,body.data,body.operatore))
            aid = cur.fetchone()["id"]
        else:
            cur = conn.execute("""INSERT INTO azioni
                (agente_id,tipo,grado_da,grado_a,sanzione,motivazione,data,operatore)
                VALUES(?,?,?,?,?,?,?,?)""",
                (body.agente_id,body.tipo,grado_da,body.grado_a,
                 body.sanzione,body.motivazione,body.data,body.operatore))
            aid = cur.lastrowid
        if body.tipo == "Promozione" and body.grado_a:
            db_execute(conn, "UPDATE agenti SET grado=? WHERE id=?", (body.grado_a, body.agente_id))
        elif body.tipo == "Degrado" and body.grado_a:
            db_execute(conn, "UPDATE agenti SET grado=? WHERE id=?", (body.grado_a, body.agente_id))
        elif body.tipo == "Sanzione" and body.sanzione:
            db_execute(conn, "UPDATE agenti SET sanzione_attiva=?,sanzione_motivo=? WHERE id=?",
                      (body.sanzione, body.motivazione, body.agente_id))
        elif body.tipo == "RimozioneSanzione":
            db_execute(conn, "UPDATE agenti SET sanzione_attiva=NULL,sanzione_motivo=NULL WHERE id=?",
                      (body.agente_id,))
        elif body.tipo == "CambioStato" and body.grado_a:
            db_execute(conn, "UPDATE agenti SET stato=? WHERE id=?", (body.grado_a, body.agente_id))
        conn.commit()
    except Exception as e:
        conn.rollback(); raise HTTPException(500, str(e))
    finally:
        conn.close()
    return {"id": aid}

@app.delete("/api/azioni/{aid}")
def delete_azione(aid: int, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, "DELETE FROM azioni WHERE id=?", (aid,))
    conn.commit(); conn.close(); return {"ok": True}

# ─── COMUNICATI ───────────────────────────────────────────────────────────────
@app.get("/api/comunicati")
def list_comunicati(_=Depends(verify_api_key)):
    conn = get_db()
    rows = db_fetchall(conn, "SELECT * FROM comunicati ORDER BY created_at DESC")
    conn.close(); return rows

@app.post("/api/comunicati")
def add_comunicato(body: ComunicatoPOST, _=Depends(verify_api_key)):
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute("INSERT INTO comunicati(titolo,testo,priorita,autore) VALUES(%s,%s,%s,%s) RETURNING id",
                    (body.titolo,body.testo,body.priorita,body.autore))
        cid = cur.fetchone()["id"]
    else:
        cur = conn.execute("INSERT INTO comunicati(titolo,testo,priorita,autore) VALUES(?,?,?,?)",
                           (body.titolo,body.testo,body.priorita,body.autore))
        cid = cur.lastrowid
    conn.commit(); conn.close(); return {"id": cid}

@app.put("/api/comunicati/{cid}")
def update_comunicato(cid: int, body: ComunicatoPOST, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, "UPDATE comunicati SET titolo=?,testo=?,priorita=? WHERE id=?",
               (body.titolo,body.testo,body.priorita,cid))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/comunicati/{cid}")
def delete_comunicato(cid: int, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, "DELETE FROM comunicati WHERE id=?", (cid,))
    conn.commit(); conn.close(); return {"ok": True}

@app.post("/api/comunicati/{cid}/letto")
async def mark_letto(cid: int, request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    discord_id = body.get("discord_id", "")
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute("INSERT INTO comunicati_letti(comunicato_id,discord_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (cid, discord_id))
    else:
        conn.execute("INSERT OR IGNORE INTO comunicati_letti(comunicato_id,discord_id) VALUES(?,?)",
                     (cid, discord_id))
    conn.commit(); conn.close(); return {"ok": True}

@app.get("/api/comunicati/letti/{discord_id}")
def get_letti(discord_id: str, _=Depends(verify_api_key)):
    conn = get_db()
    rows = db_fetchall(conn, "SELECT comunicato_id FROM comunicati_letti WHERE discord_id=?", (discord_id,))
    conn.close(); return [r["comunicato_id"] for r in rows]

# ─── PEC ──────────────────────────────────────────────────────────────────────
@app.get("/api/pec")
def list_pec(user_id: Optional[str] = None, _=Depends(verify_api_key)):
    conn = get_db()
    if user_id:
        rows = db_fetchall(conn, """SELECT * FROM pec
            WHERE (mittente_id=? OR destinatario_id=?) AND stato!='bozza'
            ORDER BY created_at DESC""", (user_id, user_id))
    else:
        rows = db_fetchall(conn, "SELECT * FROM pec ORDER BY created_at DESC")
    conn.close(); return rows

@app.get("/api/pec/bozze/{user_id}")
def list_bozze(user_id: str, _=Depends(verify_api_key)):
    conn = get_db()
    rows = db_fetchall(conn, "SELECT * FROM pec WHERE mittente_id=? AND stato='bozza' ORDER BY created_at DESC",
                       (user_id,))
    conn.close(); return rows

@app.post("/api/pec")
def send_pec(body: PECPOST, _=Depends(verify_api_key)):
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute("""INSERT INTO pec
            (mittente_id,mittente_nome,destinatario_id,destinatario_nome,oggetto,testo,priorita,stato)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (body.mittente_id,body.mittente_nome,body.destinatario_id,body.destinatario_nome,
             body.oggetto,body.testo,body.priorita,body.stato))
        pid = cur.fetchone()["id"]
    else:
        cur = conn.execute("""INSERT INTO pec
            (mittente_id,mittente_nome,destinatario_id,destinatario_nome,oggetto,testo,priorita,stato)
            VALUES(?,?,?,?,?,?,?,?)""",
            (body.mittente_id,body.mittente_nome,body.destinatario_id,body.destinatario_nome,
             body.oggetto,body.testo,body.priorita,body.stato))
        pid = cur.lastrowid
    conn.commit(); conn.close(); return {"id": pid}

@app.put("/api/pec/{pid}/letta")
def mark_pec_letta(pid: int, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, "UPDATE pec SET letta=1 WHERE id=?", (pid,))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/pec/{pid}")
def delete_pec(pid: int, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, "DELETE FROM pec WHERE id=?", (pid,))
    conn.commit(); conn.close(); return {"ok": True}

# ─── SEGNALAZIONI ─────────────────────────────────────────────────────────────
@app.get("/api/segnalazioni")
def list_segnalazioni(agente_id: Optional[str] = None, _=Depends(verify_api_key)):
    conn = get_db()
    if agente_id:
        rows = db_fetchall(conn, "SELECT * FROM segnalazioni WHERE agente_id=? ORDER BY created_at DESC", (agente_id,))
    else:
        rows = db_fetchall(conn, "SELECT * FROM segnalazioni ORDER BY created_at DESC")
    conn.close(); return rows

@app.post("/api/segnalazioni")
def add_segnalazione(body: SegnalazionePOST, _=Depends(verify_api_key)):
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute("""INSERT INTO segnalazioni(agente_id,agente_nome,titolo,descrizione,priorita)
            VALUES(%s,%s,%s,%s,%s) RETURNING id""",
            (body.agente_id,body.agente_nome,body.titolo,body.descrizione,body.priorita))
        sid = cur.fetchone()["id"]
    else:
        cur = conn.execute("""INSERT INTO segnalazioni(agente_id,agente_nome,titolo,descrizione,priorita)
            VALUES(?,?,?,?,?)""",
            (body.agente_id,body.agente_nome,body.titolo,body.descrizione,body.priorita))
        sid = cur.lastrowid
    conn.commit(); conn.close(); return {"id": sid}

@app.put("/api/segnalazioni/{sid}/stato")
async def update_stato_segnalazione(sid: int, request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    stato = body.get("stato", "")
    conn = get_db()
    db_execute(conn, "UPDATE segnalazioni SET stato=? WHERE id=?", (stato, sid))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/segnalazioni/{sid}")
def delete_segnalazione(sid: int, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, "DELETE FROM segnalazioni WHERE id=?", (sid,))
    conn.commit(); conn.close(); return {"ok": True}

# ─── DOCUMENTI ────────────────────────────────────────────────────────────────
@app.get("/api/documenti")
def list_documenti(categoria: Optional[str] = None, _=Depends(verify_api_key)):
    conn = get_db()
    if categoria:
        rows = db_fetchall(conn, "SELECT * FROM documenti WHERE categoria=? ORDER BY created_at DESC", (categoria,))
    else:
        rows = db_fetchall(conn, "SELECT * FROM documenti ORDER BY created_at DESC")
    conn.close(); return rows

@app.post("/api/documenti")
def add_documento(body: DocumentoPOST, _=Depends(verify_api_key)):
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute("""INSERT INTO documenti(titolo,descrizione,link,icona,categoria,stato,autore)
            VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (body.titolo,body.descrizione,body.link,body.icona,body.categoria,body.stato,body.autore))
        did = cur.fetchone()["id"]
    else:
        cur = conn.execute("""INSERT INTO documenti(titolo,descrizione,link,icona,categoria,stato,autore)
            VALUES(?,?,?,?,?,?,?)""",
            (body.titolo,body.descrizione,body.link,body.icona,body.categoria,body.stato,body.autore))
        did = cur.lastrowid
    conn.commit(); conn.close(); return {"id": did}

@app.put("/api/documenti/{did}")
def update_documento(did: int, body: DocumentoPOST, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, """UPDATE documenti SET titolo=?,descrizione=?,link=?,icona=?,
        categoria=?,stato=? WHERE id=?""",
        (body.titolo,body.descrizione,body.link,body.icona,body.categoria,body.stato,did))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/documenti/{did}")
def delete_documento(did: int, _=Depends(verify_api_key)):
    conn = get_db()
    db_execute(conn, "DELETE FROM documenti WHERE id=?", (did,))
    conn.commit(); conn.close(); return {"ok": True}

# ─── DASHBOARD ────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def get_dashboard(_=Depends(verify_api_key)):
    conn = get_db()
    def count(sql, p=()):
        r = db_fetchone(conn, sql, p)
        return list(r.values())[0] if r else 0

    totali     = count("SELECT COUNT(*) as n FROM agenti")
    attivi     = count("SELECT COUNT(*) as n FROM agenti WHERE stato='Attivo'")
    sospesi    = count("SELECT COUNT(*) as n FROM agenti WHERE stato='Sospeso'")
    promozioni = count("SELECT COUNT(*) as n FROM azioni WHERE tipo='Promozione'")
    sanzioni_t = count("SELECT COUNT(*) as n FROM azioni WHERE tipo='Sanzione'")

    ultime_azioni = db_fetchall(conn, """SELECT az.*, ag.nome, ag.cognome FROM azioni az
        JOIN agenti ag ON az.agente_id=ag.id ORDER BY az.created_at DESC LIMIT 7""")
    gradi_dist = db_fetchall(conn,
        "SELECT grado, COUNT(*) as n FROM agenti GROUP BY grado ORDER BY n DESC")
    ultimi_comunicati = db_fetchall(conn,
        "SELECT * FROM comunicati ORDER BY created_at DESC LIMIT 3")

    trend = []
    for i in range(12):
        d = datetime.now() - timedelta(days=30*i)
        m = d.strftime("%Y-%m")
        if USE_POSTGRES:
            prom = count("SELECT COUNT(*) as n FROM azioni WHERE tipo='Promozione' AND LEFT(created_at,7)=%s", (m,))
            san  = count("SELECT COUNT(*) as n FROM azioni WHERE tipo='Sanzione'   AND LEFT(created_at,7)=%s", (m,))
            deg  = count("SELECT COUNT(*) as n FROM azioni WHERE tipo='Degrado'    AND LEFT(created_at,7)=%s", (m,))
        else:
            prom = count("SELECT COUNT(*) as n FROM azioni WHERE tipo='Promozione' AND strftime('%Y-%m',created_at)=?", (m,))
            san  = count("SELECT COUNT(*) as n FROM azioni WHERE tipo='Sanzione'   AND strftime('%Y-%m',created_at)=?", (m,))
            deg  = count("SELECT COUNT(*) as n FROM azioni WHERE tipo='Degrado'    AND strftime('%Y-%m',created_at)=?", (m,))
        trend.append({"mese": d.strftime("%b %y"), "promozioni": prom, "sanzioni": san, "degradi": deg})
    trend.reverse()

    stati   = db_fetchall(conn, "SELECT stato, COUNT(*) as n FROM agenti GROUP BY stato")
    top_san = db_fetchall(conn, """SELECT ag.nome, ag.cognome, ag.grado, COUNT(*) as n
        FROM azioni az JOIN agenti ag ON az.agente_id=ag.id
        WHERE az.tipo='Sanzione' GROUP BY az.agente_id, ag.nome, ag.cognome, ag.grado
        ORDER BY n DESC LIMIT 6""")

    if USE_POSTGRES:
        critici = db_fetchall(conn, """SELECT az.*, ag.nome, ag.cognome FROM azioni az
            JOIN agenti ag ON az.agente_id=ag.id
            WHERE az.tipo IN ('Sanzione','Degrado','CambioStato')
            AND az.created_at >= to_char(now()-interval '30 days','YYYY-MM-DD')
            ORDER BY az.created_at DESC LIMIT 20""")
    else:
        critici = db_fetchall(conn, """SELECT az.*, ag.nome, ag.cognome FROM azioni az
            JOIN agenti ag ON az.agente_id=ag.id
            WHERE az.tipo IN ('Sanzione','Degrado','CambioStato')
            AND az.created_at >= datetime('now','-30 days')
            ORDER BY az.created_at DESC LIMIT 20""")
    conn.close()
    return {
        "kpi": {"totali": totali, "attivi": attivi, "sospesi": sospesi,
                "promozioni": promozioni, "sanzioni": sanzioni_t},
        "ultime_azioni": ultime_azioni, "gradi_dist": gradi_dist,
        "ultimi_comunicati": ultimi_comunicati, "trend": trend,
        "stati_dist": stati, "top_sanzionati": top_san, "critici": critici
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
