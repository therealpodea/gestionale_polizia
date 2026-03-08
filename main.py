"""
Gestionale Polizia d'Estovia — Backend
FastAPI + asyncpg (PostgreSQL Railway) / SQLite (fallback)
"""

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, RedirectResponse
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

USE_POSTGRES = bool(DATABASE_URL)

ROLE_DIRIGENZA = {
    "staff","dirigenza","ispettorato","sovrintendenza","direttore","vice direttore",
    "commissario","ispettore capo","ispettore","sovrintendente capo","sovrintendente","assistente capo"
}

app = FastAPI(title="Gestionale PdE")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ─── POSTGRES (asyncpg pool) ──────────────────────────────────────────────────
_pg_pool = None

async def get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        import asyncpg
        # Railway DATABASE_URL uses postgres:// — asyncpg needs postgresql://
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        _pg_pool = await asyncpg.create_pool(url, min_size=1, max_size=10)
    return _pg_pool

@app.on_event("startup")
async def startup():
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
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
                await conn.execute(
                    "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING", k, v)
    else:
        _init_sqlite()

@app.on_event("shutdown")
async def shutdown():
    global _pg_pool
    if _pg_pool:
        await _pg_pool.close()

# ─── SQLITE INIT ──────────────────────────────────────────────────────────────
def _init_sqlite():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
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
    conn.commit(); conn.close()

# ─── DB HELPERS ───────────────────────────────────────────────────────────────
def _sqlite_conn():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _rows(rows):
    return [dict(r) for r in rows]

# ─── AUTH HELPERS ─────────────────────────────────────────────────────────────
def verify_api_key(request: Request):
    key = request.headers.get("X-API-Key") or request.query_params.get("key")
    if key != API_KEY:
        raise HTTPException(403, "API key non valida")

async def get_session(token: str):
    now = int(time.time())
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sessions WHERE token=$1 AND expires_at>$2", token, now)
            return dict(row) if row else None
    else:
        db = _sqlite_conn()
        row = db.execute("SELECT * FROM sessions WHERE token=? AND expires_at>?", (token, now)).fetchone()
        db.close()
        return dict(row) if row else None

async def require_session(request: Request):
    token = request.headers.get("X-Session") or request.query_params.get("session")
    if not token: raise HTTPException(401, "Sessione richiesta")
    sess = await get_session(token)
    if not sess: raise HTTPException(401, "Sessione scaduta")
    return sess

# ─── MODELS ───────────────────────────────────────────────────────────────────
class AgentePUT(BaseModel):
    nome: str; cognome: str
    codice_fiscale: Optional[str] = ""; discord_username: Optional[str] = ""
    grado: str; stato: str = "Attivo"; note: Optional[str] = ""; data_ingresso: Optional[str] = ""

class AzionePOST(BaseModel):
    agente_id: int; tipo: str
    grado_a: Optional[str] = None; sanzione: Optional[str] = None
    motivazione: str; data: str; operatore: Optional[str] = "Dirigenza"

class ComunicatoPOST(BaseModel):
    titolo: str; testo: str; priorita: str = "Info"; autore: Optional[str] = "Dirigenza"

class PECPOST(BaseModel):
    mittente_id: str; mittente_nome: str; destinatario_id: str; destinatario_nome: str
    oggetto: str; testo: str; priorita: str = "Normale"; stato: str = "inviata"

class SegnalazionePOST(BaseModel):
    agente_id: str; agente_nome: str; titolo: str; descrizione: str; priorita: str = "Normale"

class DocumentoPOST(BaseModel):
    titolo: str; descrizione: Optional[str] = ""; link: Optional[str] = ""
    icona: Optional[str] = "📄"; categoria: str
    stato: Optional[str] = "Pubblicato"; autore: Optional[str] = "Dirigenza"

class SettingsUpdate(BaseModel):
    key: str; value: str

# ─── ROOT ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse("gestionale.html")

# ─── DISCORD OAUTH ─────────────────────────────────────────────────────────────
@app.get("/auth/discord")
def discord_login():
    if not DISCORD_ID: raise HTTPException(400, "Discord OAuth non configurato")
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
        if not access_token: return RedirectResponse("/?discord_error=1")
        user_data = (await client.get("https://discord.com/api/users/@me",
                     headers={"Authorization": f"Bearer {access_token}"})).json()
        discord_id = user_data.get("id")
        username = user_data.get("username", "")
        avatar = user_data.get("avatar", "")
        roles = []; access_level = "agente"
        if DISCORD_GUILD:
            member = await client.get(
                f"https://discord.com/api/users/@me/guilds/{DISCORD_GUILD}/member",
                headers={"Authorization": f"Bearer {access_token}"})
            if member.status_code == 200:
                md = member.json()
                roles = [r.lower() for r in md.get("roles", [])]
                username = md.get("nick", username) or username
                for rn in ROLE_DIRIGENZA:
                    if any(rn in r for r in roles):
                        access_level = "dirigenza"; break
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + 7 * 86400
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("""INSERT INTO sessions
                (token,discord_id,discord_username,discord_avatar,roles,access_level,expires_at)
                VALUES($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT(token) DO UPDATE SET discord_id=$2,discord_username=$3,
                discord_avatar=$4,roles=$5,access_level=$6,expires_at=$7""",
                token, discord_id, username, avatar, json.dumps(roles), access_level, expires)
    else:
        db = _sqlite_conn()
        db.execute("""INSERT OR REPLACE INTO sessions
            (token,discord_id,discord_username,discord_avatar,roles,access_level,expires_at)
            VALUES(?,?,?,?,?,?,?)""",
            (token, discord_id, username, avatar, json.dumps(roles), access_level, expires))
        db.commit(); db.close()
    return RedirectResponse(f"/?discord_session={token}&level={access_level}&name={username}")

@app.post("/auth/logout")
async def logout(request: Request):
    token = request.headers.get("X-Session")
    if token:
        if USE_POSTGRES:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM sessions WHERE token=$1", token)
        else:
            db = _sqlite_conn(); db.execute("DELETE FROM sessions WHERE token=?", (token,))
            db.commit(); db.close()
    return {"ok": True}

@app.get("/auth/session")
async def check_session(request: Request):
    token = request.headers.get("X-Session")
    if not token: raise HTTPException(401)
    sess = await get_session(token)
    if not sess: raise HTTPException(401)
    return sess

# ─── SETTINGS ─────────────────────────────────────────────────────────────────
@app.get("/api/settings")
async def get_settings(_=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT key,value FROM settings WHERE key IN ('gradi','sanzioni','logo')")
            return {r["key"]: r["value"] for r in rows}
    else:
        db = _sqlite_conn()
        rows = db.execute("SELECT key,value FROM settings WHERE key IN ('gradi','sanzioni','logo')").fetchall()
        db.close(); return {r["key"]: r["value"] for r in rows}

@app.put("/api/settings")
async def update_settings(body: SettingsUpdate, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=$2",
                body.key, body.value)
    else:
        db = _sqlite_conn()
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (body.key, body.value))
        db.commit(); db.close()
    return {"ok": True}

@app.post("/sync")
def sync(_=Depends(verify_api_key)):
    return {"ok": True}

# ─── AGENTI ───────────────────────────────────────────────────────────────────
@app.get("/api/agenti")
async def list_agenti(_=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            return _rows(await conn.fetch("SELECT * FROM agenti ORDER BY cognome"))
    else:
        db = _sqlite_conn()
        rows = db.execute("SELECT * FROM agenti ORDER BY cognome").fetchall()
        db.close(); return _rows(rows)

@app.get("/api/agenti/{aid}")
async def get_agente(aid: int, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            ag = await conn.fetchrow("SELECT * FROM agenti WHERE id=$1", aid)
            if not ag: raise HTTPException(404)
            azioni = await conn.fetch("SELECT * FROM azioni WHERE agente_id=$1 ORDER BY created_at DESC", aid)
            segs   = await conn.fetch("SELECT * FROM segnalazioni WHERE agente_id=$1 ORDER BY created_at DESC", str(aid))
            return {"agente": dict(ag), "azioni": _rows(azioni), "segnalazioni": _rows(segs)}
    else:
        db = _sqlite_conn()
        ag = db.execute("SELECT * FROM agenti WHERE id=?", (aid,)).fetchone()
        if not ag: raise HTTPException(404)
        azioni = db.execute("SELECT * FROM azioni WHERE agente_id=? ORDER BY created_at DESC", (aid,)).fetchall()
        segs   = db.execute("SELECT * FROM segnalazioni WHERE agente_id=? ORDER BY created_at DESC", (str(aid),)).fetchall()
        db.close()
        return {"agente": dict(ag), "azioni": _rows(azioni), "segnalazioni": _rows(segs)}

@app.post("/api/agenti")
async def add_agente(body: AgentePUT, _=Depends(verify_api_key)):
    if not body.data_ingresso: body.data_ingresso = datetime.now().strftime("%Y-%m-%d")
    try:
        if USE_POSTGRES:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""INSERT INTO agenti
                    (nome,cognome,codice_fiscale,discord_username,grado,stato,note,data_ingresso)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
                    body.nome,body.cognome,body.codice_fiscale,body.discord_username,
                    body.grado,body.stato,body.note,body.data_ingresso)
                return {"id": row["id"]}
        else:
            db = _sqlite_conn()
            cur = db.execute("""INSERT INTO agenti
                (nome,cognome,codice_fiscale,discord_username,grado,stato,note,data_ingresso)
                VALUES(?,?,?,?,?,?,?,?)""",
                (body.nome,body.cognome,body.codice_fiscale,body.discord_username,
                 body.grado,body.stato,body.note,body.data_ingresso))
            db.commit(); aid = cur.lastrowid; db.close(); return {"id": aid}
    except Exception:
        raise HTTPException(400, "Codice fiscale già presente")

@app.put("/api/agenti/{aid}")
async def update_agente(aid: int, body: AgentePUT, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("""UPDATE agenti SET nome=$1,cognome=$2,codice_fiscale=$3,
                discord_username=$4,grado=$5,stato=$6,note=$7 WHERE id=$8""",
                body.nome,body.cognome,body.codice_fiscale,body.discord_username,
                body.grado,body.stato,body.note,aid)
    else:
        db = _sqlite_conn()
        db.execute("""UPDATE agenti SET nome=?,cognome=?,codice_fiscale=?,discord_username=?,
            grado=?,stato=?,note=? WHERE id=?""",
            (body.nome,body.cognome,body.codice_fiscale,body.discord_username,
             body.grado,body.stato,body.note,aid))
        db.commit(); db.close()
    return {"ok": True}

@app.delete("/api/agenti/{aid}")
async def delete_agente(aid: int, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agenti WHERE id=$1", aid)
    else:
        db = _sqlite_conn(); db.execute("DELETE FROM agenti WHERE id=?", (aid,)); db.commit(); db.close()
    return {"ok": True}

# ─── AZIONI ───────────────────────────────────────────────────────────────────
@app.get("/api/azioni")
async def list_azioni(_=Depends(verify_api_key)):
    sql = "SELECT az.*,ag.nome,ag.cognome FROM azioni az JOIN agenti ag ON az.agente_id=ag.id ORDER BY az.created_at DESC"
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            return _rows(await conn.fetch(sql))
    else:
        db = _sqlite_conn(); rows = db.execute(sql).fetchall(); db.close(); return _rows(rows)

@app.post("/api/azioni")
async def add_azione(body: AzionePOST, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            ag = await conn.fetchrow("SELECT * FROM agenti WHERE id=$1", body.agente_id)
            if not ag: raise HTTPException(404, "Agente non trovato")
            row = await conn.fetchrow("""INSERT INTO azioni
                (agente_id,tipo,grado_da,grado_a,sanzione,motivazione,data,operatore)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
                body.agente_id,body.tipo,ag["grado"],body.grado_a,
                body.sanzione,body.motivazione,body.data,body.operatore)
            if body.tipo in ("Promozione","Degrado") and body.grado_a:
                await conn.execute("UPDATE agenti SET grado=$1 WHERE id=$2", body.grado_a, body.agente_id)
            elif body.tipo == "Sanzione" and body.sanzione:
                await conn.execute("UPDATE agenti SET sanzione_attiva=$1,sanzione_motivo=$2 WHERE id=$3",
                                   body.sanzione, body.motivazione, body.agente_id)
            elif body.tipo == "RimozioneSanzione":
                await conn.execute("UPDATE agenti SET sanzione_attiva=NULL,sanzione_motivo=NULL WHERE id=$1", body.agente_id)
            elif body.tipo == "CambioStato" and body.grado_a:
                await conn.execute("UPDATE agenti SET stato=$1 WHERE id=$2", body.grado_a, body.agente_id)
            return {"id": row["id"]}
    else:
        db = _sqlite_conn()
        ag = db.execute("SELECT * FROM agenti WHERE id=?", (body.agente_id,)).fetchone()
        if not ag: raise HTTPException(404, "Agente non trovato")
        cur = db.execute("""INSERT INTO azioni
            (agente_id,tipo,grado_da,grado_a,sanzione,motivazione,data,operatore)
            VALUES(?,?,?,?,?,?,?,?)""",
            (body.agente_id,body.tipo,ag["grado"],body.grado_a,
             body.sanzione,body.motivazione,body.data,body.operatore))
        aid = cur.lastrowid
        if body.tipo in ("Promozione","Degrado") and body.grado_a:
            db.execute("UPDATE agenti SET grado=? WHERE id=?", (body.grado_a, body.agente_id))
        elif body.tipo == "Sanzione" and body.sanzione:
            db.execute("UPDATE agenti SET sanzione_attiva=?,sanzione_motivo=? WHERE id=?",
                       (body.sanzione, body.motivazione, body.agente_id))
        elif body.tipo == "RimozioneSanzione":
            db.execute("UPDATE agenti SET sanzione_attiva=NULL,sanzione_motivo=NULL WHERE id=?", (body.agente_id,))
        elif body.tipo == "CambioStato" and body.grado_a:
            db.execute("UPDATE agenti SET stato=? WHERE id=?", (body.grado_a, body.agente_id))
        db.commit(); db.close(); return {"id": aid}

@app.delete("/api/azioni/{aid}")
async def delete_azione(aid: int, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM azioni WHERE id=$1", aid)
    else:
        db = _sqlite_conn()
        db.execute("DELETE FROM azioni WHERE id=?", (aid,))
        db.commit()
        db.close()
    return {"ok": True}

# ─── COMUNICATI ───────────────────────────────────────────────────────────────
@app.get("/api/comunicati")
async def list_comunicati(_=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            return _rows(await conn.fetch("SELECT * FROM comunicati ORDER BY created_at DESC"))
    else:
        db = _sqlite_conn(); rows = db.execute("SELECT * FROM comunicati ORDER BY created_at DESC").fetchall(); db.close(); return _rows(rows)

@app.post("/api/comunicati")
async def add_comunicato(body: ComunicatoPOST, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("INSERT INTO comunicati(titolo,testo,priorita,autore) VALUES($1,$2,$3,$4) RETURNING id",
                                      body.titolo,body.testo,body.priorita,body.autore)
            return {"id": row["id"]}
    else:
        db = _sqlite_conn()
        cur = db.execute("INSERT INTO comunicati(titolo,testo,priorita,autore) VALUES(?,?,?,?)",
                         (body.titolo,body.testo,body.priorita,body.autore))
        db.commit(); cid = cur.lastrowid; db.close(); return {"id": cid}

@app.put("/api/comunicati/{cid}")
async def update_comunicato(cid: int, body: ComunicatoPOST, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE comunicati SET titolo=$1,testo=$2,priorita=$3 WHERE id=$4",
                               body.titolo,body.testo,body.priorita,cid)
    else:
        db = _sqlite_conn(); db.execute("UPDATE comunicati SET titolo=?,testo=?,priorita=? WHERE id=?",
                                        (body.titolo,body.testo,body.priorita,cid)); db.commit(); db.close()
    return {"ok": True}

@app.delete("/api/comunicati/{cid}")
async def delete_comunicato(cid: int, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM comunicati WHERE id=$1", cid)
    else:
        db = _sqlite_conn()
        db.execute("DELETE FROM comunicati WHERE id=?", (cid,))
        db.commit()
        db.close()
    return {"ok": True}

@app.post("/api/comunicati/{cid}/letto")
async def mark_letto(cid: int, request: Request, _=Depends(verify_api_key)):
    body = await request.json(); discord_id = body.get("discord_id", "")
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO comunicati_letti(comunicato_id,discord_id) VALUES($1,$2) ON CONFLICT DO NOTHING", cid, discord_id)
    else:
        db = _sqlite_conn(); db.execute("INSERT OR IGNORE INTO comunicati_letti(comunicato_id,discord_id) VALUES(?,?)", (cid,discord_id)); db.commit(); db.close()
    return {"ok": True}

@app.get("/api/comunicati/letti/{discord_id}")
async def get_letti(discord_id: str, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT comunicato_id FROM comunicati_letti WHERE discord_id=$1", discord_id)
            return [r["comunicato_id"] for r in rows]
    else:
        db = _sqlite_conn(); rows = db.execute("SELECT comunicato_id FROM comunicati_letti WHERE discord_id=?", (discord_id,)).fetchall()
        db.close(); return [r["comunicato_id"] for r in rows]

# ─── PEC ──────────────────────────────────────────────────────────────────────
@app.get("/api/pec")
async def list_pec(user_id: Optional[str] = None, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            if user_id:
                rows = await conn.fetch("SELECT * FROM pec WHERE (mittente_id=$1 OR destinatario_id=$1) AND stato!='bozza' ORDER BY created_at DESC", user_id)
            else:
                rows = await conn.fetch("SELECT * FROM pec ORDER BY created_at DESC")
            return _rows(rows)
    else:
        db = _sqlite_conn()
        if user_id:
            rows = db.execute("SELECT * FROM pec WHERE (mittente_id=? OR destinatario_id=?) AND stato!='bozza' ORDER BY created_at DESC", (user_id,user_id)).fetchall()
        else:
            rows = db.execute("SELECT * FROM pec ORDER BY created_at DESC").fetchall()
        db.close(); return _rows(rows)

@app.get("/api/pec/bozze/{user_id}")
async def list_bozze(user_id: str, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            return _rows(await conn.fetch("SELECT * FROM pec WHERE mittente_id=$1 AND stato='bozza' ORDER BY created_at DESC", user_id))
    else:
        db = _sqlite_conn(); rows = db.execute("SELECT * FROM pec WHERE mittente_id=? AND stato='bozza' ORDER BY created_at DESC", (user_id,)).fetchall(); db.close(); return _rows(rows)

@app.post("/api/pec")
async def send_pec(body: PECPOST, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""INSERT INTO pec
                (mittente_id,mittente_nome,destinatario_id,destinatario_nome,oggetto,testo,priorita,stato)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
                body.mittente_id,body.mittente_nome,body.destinatario_id,body.destinatario_nome,
                body.oggetto,body.testo,body.priorita,body.stato)
            return {"id": row["id"]}
    else:
        db = _sqlite_conn()
        cur = db.execute("""INSERT INTO pec (mittente_id,mittente_nome,destinatario_id,destinatario_nome,oggetto,testo,priorita,stato)
            VALUES(?,?,?,?,?,?,?,?)""",
            (body.mittente_id,body.mittente_nome,body.destinatario_id,body.destinatario_nome,
             body.oggetto,body.testo,body.priorita,body.stato))
        db.commit(); pid = cur.lastrowid; db.close(); return {"id": pid}

@app.put("/api/pec/{pid}/letta")
async def mark_pec_letta(pid: int, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE pec SET letta=1 WHERE id=$1", pid)
    else:
        db = _sqlite_conn()
        db.execute("UPDATE pec SET letta=1 WHERE id=?", (pid,))
        db.commit()
        db.close()
    return {"ok": True}

@app.delete("/api/pec/{pid}")
async def delete_pec(pid: int, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM pec WHERE id=$1", pid)
    else:
        db = _sqlite_conn()
        db.execute("DELETE FROM pec WHERE id=?", (pid,))
        db.commit()
        db.close()
    return {"ok": True}

# ─── SEGNALAZIONI ─────────────────────────────────────────────────────────────
@app.get("/api/segnalazioni")
async def list_segnalazioni(agente_id: Optional[str] = None, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            if agente_id:
                rows = await conn.fetch("SELECT * FROM segnalazioni WHERE agente_id=$1 ORDER BY created_at DESC", agente_id)
            else:
                rows = await conn.fetch("SELECT * FROM segnalazioni ORDER BY created_at DESC")
            return _rows(rows)
    else:
        db = _sqlite_conn()
        if agente_id:
            rows = db.execute("SELECT * FROM segnalazioni WHERE agente_id=? ORDER BY created_at DESC", (agente_id,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM segnalazioni ORDER BY created_at DESC").fetchall()
        db.close(); return _rows(rows)

@app.post("/api/segnalazioni")
async def add_segnalazione(body: SegnalazionePOST, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("INSERT INTO segnalazioni(agente_id,agente_nome,titolo,descrizione,priorita) VALUES($1,$2,$3,$4,$5) RETURNING id",
                                      body.agente_id,body.agente_nome,body.titolo,body.descrizione,body.priorita)
            return {"id": row["id"]}
    else:
        db = _sqlite_conn()
        cur = db.execute("INSERT INTO segnalazioni(agente_id,agente_nome,titolo,descrizione,priorita) VALUES(?,?,?,?,?)",
                         (body.agente_id,body.agente_nome,body.titolo,body.descrizione,body.priorita))
        db.commit(); sid = cur.lastrowid; db.close(); return {"id": sid}

@app.put("/api/segnalazioni/{sid}/stato")
async def update_stato_segnalazione(sid: int, request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    stato = body.get("stato", "")
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE segnalazioni SET stato=$1 WHERE id=$2", stato, sid)
    else:
        db = _sqlite_conn()
        db.execute("UPDATE segnalazioni SET stato=? WHERE id=?", (stato, sid))
        db.commit()
        db.close()
    return {"ok": True}

@app.delete("/api/segnalazioni/{sid}")
async def delete_segnalazione(sid: int, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM segnalazioni WHERE id=$1", sid)
    else:
        db = _sqlite_conn()
        db.execute("DELETE FROM segnalazioni WHERE id=?", (sid,))
        db.commit()
        db.close()
    return {"ok": True}

# ─── DOCUMENTI ────────────────────────────────────────────────────────────────
@app.get("/api/documenti")
async def list_documenti(categoria: Optional[str] = None, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            if categoria:
                rows = await conn.fetch("SELECT * FROM documenti WHERE categoria=$1 ORDER BY created_at DESC", categoria)
            else:
                rows = await conn.fetch("SELECT * FROM documenti ORDER BY created_at DESC")
            return _rows(rows)
    else:
        db = _sqlite_conn()
        if categoria:
            rows = db.execute("SELECT * FROM documenti WHERE categoria=? ORDER BY created_at DESC", (categoria,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM documenti ORDER BY created_at DESC").fetchall()
        db.close(); return _rows(rows)

@app.post("/api/documenti")
async def add_documento(body: DocumentoPOST, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("INSERT INTO documenti(titolo,descrizione,link,icona,categoria,stato,autore) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id",
                                      body.titolo,body.descrizione,body.link,body.icona,body.categoria,body.stato,body.autore)
            return {"id": row["id"]}
    else:
        db = _sqlite_conn()
        cur = db.execute("INSERT INTO documenti(titolo,descrizione,link,icona,categoria,stato,autore) VALUES(?,?,?,?,?,?,?)",
                         (body.titolo,body.descrizione,body.link,body.icona,body.categoria,body.stato,body.autore))
        db.commit(); did = cur.lastrowid; db.close(); return {"id": did}

@app.put("/api/documenti/{did}")
async def update_documento(did: int, body: DocumentoPOST, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE documenti SET titolo=$1,descrizione=$2,link=$3,icona=$4,categoria=$5,stato=$6 WHERE id=$7",
                               body.titolo,body.descrizione,body.link,body.icona,body.categoria,body.stato,did)
    else:
        db = _sqlite_conn()
        db.execute("UPDATE documenti SET titolo=?,descrizione=?,link=?,icona=?,categoria=?,stato=? WHERE id=?",
                   (body.titolo,body.descrizione,body.link,body.icona,body.categoria,body.stato,did))
        db.commit(); db.close()
    return {"ok": True}

@app.delete("/api/documenti/{did}")
async def delete_documento(did: int, _=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM documenti WHERE id=$1", did)
    else:
        db = _sqlite_conn()
        db.execute("DELETE FROM documenti WHERE id=?", (did,))
        db.commit()
        db.close()
    return {"ok": True}

# ─── DASHBOARD ────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
async def get_dashboard(_=Depends(verify_api_key)):
    if USE_POSTGRES:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            async def count(sql, *p):
                r = await conn.fetchrow(sql, *p); return list(r.values())[0] if r else 0

            totali     = await count("SELECT COUNT(*) FROM agenti")
            attivi     = await count("SELECT COUNT(*) FROM agenti WHERE stato='Attivo'")
            sospesi    = await count("SELECT COUNT(*) FROM agenti WHERE stato='Sospeso'")
            promozioni = await count("SELECT COUNT(*) FROM azioni WHERE tipo='Promozione'")
            sanzioni_t = await count("SELECT COUNT(*) FROM azioni WHERE tipo='Sanzione'")
            ultime_azioni     = _rows(await conn.fetch("SELECT az.*,ag.nome,ag.cognome FROM azioni az JOIN agenti ag ON az.agente_id=ag.id ORDER BY az.created_at DESC LIMIT 7"))
            gradi_dist        = _rows(await conn.fetch("SELECT grado,COUNT(*) as n FROM agenti GROUP BY grado ORDER BY n DESC"))
            ultimi_comunicati = _rows(await conn.fetch("SELECT * FROM comunicati ORDER BY created_at DESC LIMIT 3"))
            stati    = _rows(await conn.fetch("SELECT stato,COUNT(*) as n FROM agenti GROUP BY stato"))
            top_san  = _rows(await conn.fetch("SELECT ag.nome,ag.cognome,ag.grado,COUNT(*) as n FROM azioni az JOIN agenti ag ON az.agente_id=ag.id WHERE az.tipo='Sanzione' GROUP BY az.agente_id,ag.nome,ag.cognome,ag.grado ORDER BY n DESC LIMIT 6"))
            critici  = _rows(await conn.fetch("SELECT az.*,ag.nome,ag.cognome FROM azioni az JOIN agenti ag ON az.agente_id=ag.id WHERE az.tipo IN ('Sanzione','Degrado','CambioStato') AND az.created_at >= to_char(now()-interval '30 days','YYYY-MM-DD') ORDER BY az.created_at DESC LIMIT 20"))
            trend = []
            for i in range(12):
                d = datetime.now() - timedelta(days=30*i); m = d.strftime("%Y-%m")
                prom = await count("SELECT COUNT(*) FROM azioni WHERE tipo='Promozione' AND LEFT(created_at,7)=$1", m)
                san  = await count("SELECT COUNT(*) FROM azioni WHERE tipo='Sanzione'   AND LEFT(created_at,7)=$1", m)
                deg  = await count("SELECT COUNT(*) FROM azioni WHERE tipo='Degrado'    AND LEFT(created_at,7)=$1", m)
                trend.append({"mese": d.strftime("%b %y"), "promozioni": prom, "sanzioni": san, "degradi": deg})
            trend.reverse()
    else:
        db = _sqlite_conn()
        def count(sql, p=()):
            r = db.execute(sql, p).fetchone(); return r[0] if r else 0
        totali     = count("SELECT COUNT(*) FROM agenti")
        attivi     = count("SELECT COUNT(*) FROM agenti WHERE stato='Attivo'")
        sospesi    = count("SELECT COUNT(*) FROM agenti WHERE stato='Sospeso'")
        promozioni = count("SELECT COUNT(*) FROM azioni WHERE tipo='Promozione'")
        sanzioni_t = count("SELECT COUNT(*) FROM azioni WHERE tipo='Sanzione'")
        ultime_azioni     = _rows(db.execute("SELECT az.*,ag.nome,ag.cognome FROM azioni az JOIN agenti ag ON az.agente_id=ag.id ORDER BY az.created_at DESC LIMIT 7").fetchall())
        gradi_dist        = _rows(db.execute("SELECT grado,COUNT(*) as n FROM agenti GROUP BY grado ORDER BY n DESC").fetchall())
        ultimi_comunicati = _rows(db.execute("SELECT * FROM comunicati ORDER BY created_at DESC LIMIT 3").fetchall())
        stati   = _rows(db.execute("SELECT stato,COUNT(*) as n FROM agenti GROUP BY stato").fetchall())
        top_san = _rows(db.execute("SELECT ag.nome,ag.cognome,ag.grado,COUNT(*) as n FROM azioni az JOIN agenti ag ON az.agente_id=ag.id WHERE az.tipo='Sanzione' GROUP BY az.agente_id ORDER BY n DESC LIMIT 6").fetchall())
        critici = _rows(db.execute("SELECT az.*,ag.nome,ag.cognome FROM azioni az JOIN agenti ag ON az.agente_id=ag.id WHERE az.tipo IN ('Sanzione','Degrado','CambioStato') AND az.created_at >= datetime('now','-30 days') ORDER BY az.created_at DESC LIMIT 20").fetchall())
        trend = []
        for i in range(12):
            d = datetime.now() - timedelta(days=30*i); m = d.strftime("%Y-%m")
            trend.append({"mese": d.strftime("%b %y"),
                "promozioni": count("SELECT COUNT(*) FROM azioni WHERE tipo='Promozione' AND strftime('%Y-%m',created_at)=?", (m,)),
                "sanzioni":   count("SELECT COUNT(*) FROM azioni WHERE tipo='Sanzione'   AND strftime('%Y-%m',created_at)=?", (m,)),
                "degradi":    count("SELECT COUNT(*) FROM azioni WHERE tipo='Degrado'    AND strftime('%Y-%m',created_at)=?", (m,))})
        trend.reverse(); db.close()
    return {"kpi": {"totali":totali,"attivi":attivi,"sospesi":sospesi,"promozioni":promozioni,"sanzioni":sanzioni_t},
            "ultime_azioni":ultime_azioni,"gradi_dist":gradi_dist,"ultimi_comunicati":ultimi_comunicati,
            "trend":trend,"stati_dist":stati,"top_sanzionati":top_san,"critici":critici}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
