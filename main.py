"""
╔══════════════════════════════════════════════════════════════╗
║        BACKEND GESTIONALE — POLIZIA D'ESTOVIA               ║
║        FastAPI + PostgreSQL  |  Deploy su Railway           ║
║        + Discord OAuth2 Login                               ║
╚══════════════════════════════════════════════════════════════╝
"""

from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import json, os, uuid, secrets
from datetime import date, datetime, timedelta
import httpx

API_KEY = os.getenv("GESTIONALE_API_KEY", "estovia_dirigenza_2026")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── DISCORD OAUTH CONFIG ──
DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_BOT_TOKEN     = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_GUILD_ID      = os.getenv("DISCORD_GUILD_ID", "")
BASE_URL              = os.getenv("BASE_URL", "https://gestionalepolizia-production.up.railway.app")
DISCORD_REDIRECT_URI  = f"{BASE_URL}/auth/discord/callback"

# ── MAPPA RUOLI DISCORD → LIVELLO ACCESSO ──
ROLE_MAP = {
    "accademia":     ["Allievo Poliziotto"],
    "agente":        ["Agente","Agente Scelto","Assistente","Assistente Coordinatore","Assistente Capo"],
    "sovrintendenza":["Vice Sovrintendente","Sovrintendente","Sovrintendente Capo","Sovrintendente Superiore"],
    "ispettorato":   ["Vice Ispettore","Ispettore","Ispettore Capo","Ispettore Superiore"],
    "dirigenza":     ["Vice Commissario","Sostituto Commissario","Commissario","Commissario Capo",
                      "Primo Dirigente","Dirigente Aggiunto","Dirigente Superiore","Dirigente Penitenziaria","Dirigente Generale"],
}
LIVELLI_GERARCHIA = ["dirigenza","ispettorato","sovrintendenza","agente","accademia"]

def discord_roles_to_level(member_roles):
    for livello in LIVELLI_GERARCHIA:
        for ruolo in ROLE_MAP[livello]:
            if ruolo in member_roles:
                return livello
    return None

app = FastAPI(title="Gestionale Polizia d'Estovia")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GRADI_DEFAULT = ["Allievo Poliziotto","Agente","Agente Scelto","Assistente","Assistente Coordinatore","Assistente Capo","Vice Sovrintendente","Sovrintendente","Sovrintendente Capo","Sovrintendente Superiore","Vice Ispettore","Ispettore","Ispettore Capo","Ispettore Superiore","Sostituto Commissario","Vice Commissario","Commissario","Commissario Capo","Primo Dirigente","Dirigente Aggiunto","Dirigente Superiore","Dirigente Penitenziaria","Dirigente Generale"]
SANZIONI_DEFAULT = ["AVVISO FORMALE 1","AVVISO FORMALE 2","RICHIAMO 1","RICHIAMO 2","RICHIAMO 3","SOSPENSIONE"]

if DATABASE_URL:
    import psycopg2, psycopg2.extras

    def get_db(): return psycopg2.connect(DATABASE_URL)
    def _q(s): return s.replace("?","%s").replace("INSERT OR IGNORE","INSERT").replace("INSERT OR REPLACE","INSERT")

    def db_fetchall(q,p=()):
        conn=get_db(); cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor); cur.execute(_q(q),p); r=cur.fetchall(); conn.close(); return [dict(x) for x in r]
    def db_fetchone(q,p=()):
        conn=get_db(); cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor); cur.execute(_q(q),p); r=cur.fetchone(); conn.close(); return dict(r) if r else None
    def db_execute(q,p=()):
        conn=get_db(); cur=conn.cursor(); cur.execute(_q(q),p); conn.commit(); conn.close()
    def db_execute_many(qps):
        conn=get_db(); cur=conn.cursor()
        for q,p in qps: cur.execute(_q(q),p)
        conn.commit(); conn.close()
    def upsert(k,v):
        conn=get_db(); cur=conn.cursor(); cur.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",(k,v)); conn.commit(); conn.close()

    def init_db():
        conn=get_db(); c=conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, nome TEXT NOT NULL, cognome TEXT NOT NULL, cf TEXT NOT NULL, discord TEXT NOT NULL, grado TEXT NOT NULL, stato TEXT NOT NULL DEFAULT \'Attivo\', sanzione TEXT, note TEXT, "dataIngresso" TEXT NOT NULL, agent_pwd TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, "agentId" TEXT NOT NULL, "agentNome" TEXT NOT NULL, tipo TEXT NOT NULL, vecchio TEXT NOT NULL, nuovo TEXT NOT NULL, motivo TEXT NOT NULL, data TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS comunicati (id TEXT PRIMARY KEY, titolo TEXT NOT NULL, corpo TEXT NOT NULL, priorita TEXT NOT NULL DEFAULT \'normale\', data TEXT NOT NULL, "readBy" TEXT NOT NULL DEFAULT \'[]\')')
        c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS pec (id TEXT PRIMARY KEY, "mittenteId" TEXT NOT NULL, "mittenteNome" TEXT NOT NULL, "destinatarioId" TEXT NOT NULL, "destinatarioNome" TEXT NOT NULL, oggetto TEXT NOT NULL, corpo TEXT NOT NULL, priorita TEXT NOT NULL DEFAULT \'normale\', stato TEXT NOT NULL DEFAULT \'inviata\', letta BOOLEAN NOT NULL DEFAULT FALSE, data TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS documenti (id TEXT PRIMARY KEY, titolo TEXT NOT NULL, descrizione TEXT, url TEXT, icona TEXT, stato TEXT, categoria TEXT NOT NULL DEFAULT \'altro\', ordine INTEGER DEFAULT 0)')
        c.execute('CREATE TABLE IF NOT EXISTS segnalazioni (id TEXT PRIMARY KEY, titolo TEXT NOT NULL, corpo TEXT NOT NULL, priorita TEXT NOT NULL DEFAULT \'normale\', "mittenteId" TEXT NOT NULL, "mittenteNome" TEXT NOT NULL, stato TEXT NOT NULL DEFAULT \'aperta\', data TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS discord_sessions (token TEXT PRIMARY KEY, discord_id TEXT NOT NULL, discord_username TEXT NOT NULL, discord_avatar TEXT, livello TEXT NOT NULL, grado TEXT, agent_id TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)')
        for k,v in [("pwd","estovia2026"),("gradi",json.dumps(GRADI_DEFAULT)),("sanzioni",json.dumps(SANZIONI_DEFAULT)),("logo","")]:
            c.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING",(k,v))
        try: c.execute("ALTER TABLE agents ADD COLUMN agent_pwd TEXT")
        except: pass
        conn.commit(); conn.close()

else:
    import sqlite3
    DB_PATH = os.getenv("DB_PATH","gestionale.db")
    def get_db():
        conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row; return conn
    def db_fetchall(q,p=()):
        conn=get_db(); r=conn.execute(q,p).fetchall(); conn.close(); return [dict(x) for x in r]
    def db_fetchone(q,p=()):
        conn=get_db(); r=conn.execute(q,p).fetchone(); conn.close(); return dict(r) if r else None
    def db_execute(q,p=()):
        conn=get_db(); conn.execute(q,p); conn.commit(); conn.close()
    def db_execute_many(qps):
        conn=get_db()
        for q,p in qps: conn.execute(q,p)
        conn.commit(); conn.close()
    def upsert(k,v): db_execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(k,v))

    def init_db():
        conn=get_db(); c=conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, nome TEXT NOT NULL, cognome TEXT NOT NULL, cf TEXT NOT NULL, discord TEXT NOT NULL, grado TEXT NOT NULL, stato TEXT NOT NULL DEFAULT 'Attivo', sanzione TEXT, note TEXT, dataIngresso TEXT NOT NULL, agent_pwd TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, agentId TEXT NOT NULL, agentNome TEXT NOT NULL, tipo TEXT NOT NULL, vecchio TEXT NOT NULL, nuovo TEXT NOT NULL, motivo TEXT NOT NULL, data TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS comunicati (id TEXT PRIMARY KEY, titolo TEXT NOT NULL, corpo TEXT NOT NULL, priorita TEXT NOT NULL DEFAULT 'normale', data TEXT NOT NULL, readBy TEXT NOT NULL DEFAULT '[]')")
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS pec (id TEXT PRIMARY KEY, mittenteId TEXT NOT NULL, mittenteNome TEXT NOT NULL, destinatarioId TEXT NOT NULL, destinatarioNome TEXT NOT NULL, oggetto TEXT NOT NULL, corpo TEXT NOT NULL, priorita TEXT NOT NULL DEFAULT 'normale', stato TEXT NOT NULL DEFAULT 'inviata', letta INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS documenti (id TEXT PRIMARY KEY, titolo TEXT NOT NULL, descrizione TEXT, url TEXT, icona TEXT, stato TEXT, categoria TEXT NOT NULL DEFAULT 'altro', ordine INTEGER DEFAULT 0)")
        c.execute("CREATE TABLE IF NOT EXISTS segnalazioni (id TEXT PRIMARY KEY, titolo TEXT NOT NULL, corpo TEXT NOT NULL, priorita TEXT NOT NULL DEFAULT 'normale', mittenteId TEXT NOT NULL, mittenteNome TEXT NOT NULL, stato TEXT NOT NULL DEFAULT 'aperta', data TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS discord_sessions (token TEXT PRIMARY KEY, discord_id TEXT NOT NULL, discord_username TEXT NOT NULL, discord_avatar TEXT, livello TEXT NOT NULL, grado TEXT, agent_id TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)")
        for k,v in [("pwd","estovia2026"),("gradi",json.dumps(GRADI_DEFAULT)),("sanzioni",json.dumps(SANZIONI_DEFAULT)),("logo","")]:
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
        try: c.execute("ALTER TABLE agents ADD COLUMN agent_pwd TEXT")
        except: pass
        conn.commit(); conn.close()

init_db()

def check_auth(x_api_key: str = Header(None)):
    if x_api_key != API_KEY: raise HTTPException(status_code=401, detail="Non autorizzato")
    return True

def get_session(x_session_token: str = Header(None)):
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Sessione mancante")
    row = db_fetchone("SELECT * FROM discord_sessions WHERE token=?", (x_session_token,))
    if not row:
        raise HTTPException(status_code=401, detail="Sessione non valida")
    if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
        db_execute("DELETE FROM discord_sessions WHERE token=?", (x_session_token,))
        raise HTTPException(status_code=401, detail="Sessione scaduta")
    return row

class Agent(BaseModel):
    id: Optional[str]=None; nome: str; cognome: str; cf: str; discord: str; grado: str
    stato: str="Attivo"; sanzione: Optional[str]=None; note: Optional[str]=""; dataIngresso: Optional[str]=None

class HistoryEntry(BaseModel):
    id: Optional[str]=None; agentId: str; agentNome: str; tipo: str; vecchio: str; nuovo: str; motivo: str; data: Optional[str]=None

class Comunicato(BaseModel):
    id: Optional[str]=None; titolo: str; corpo: str; priorita: str="normale"; data: Optional[str]=None; readBy: Optional[List[str]]=[]

class SettingsUpdate(BaseModel):
    pwd: Optional[str]=None; gradi: Optional[List[str]]=None; sanzioni: Optional[List[str]]=None; logo: Optional[str]=None

class MarkRead(BaseModel):
    agentId: str

# ══════════════════════════════════════════════════════
#   DISCORD OAUTH
# ══════════════════════════════════════════════════════

_oauth_states: dict = {}

@app.get("/auth/discord/login")
def discord_login():
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = datetime.utcnow()
    old = [k for k,v in _oauth_states.items() if (datetime.utcnow()-v).seconds > 600]
    for k in old: del _oauth_states[k]
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify"
        f"&state={state}"
    )
    return RedirectResponse(url)

@app.get("/auth/discord/callback")
async def discord_callback(code: str = None, state: str = None, error: str = None):
    if error or not code:
        return RedirectResponse("/?error=oauth_cancelled")
    if state not in _oauth_states:
        return RedirectResponse("/?error=oauth_state_invalid")
    del _oauth_states[state]

    async with httpx.AsyncClient() as client:
        # Scambia code con access_token
        token_res = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if token_res.status_code != 200:
            return RedirectResponse("/?error=token_failed")
        access_token = token_res.json().get("access_token")

        # Info utente Discord
        user_res = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_res.status_code != 200:
            return RedirectResponse("/?error=user_failed")
        user = user_res.json()
        discord_id = user["id"]
        discord_username = user.get("global_name") or user["username"]
        discord_avatar = f"https://cdn.discordapp.com/avatars/{discord_id}/{user['avatar']}.png" if user.get("avatar") else None

        # Leggi ruoli nel server tramite Bot Token
        member_res = await client.get(
            f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/members/{discord_id}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
        )
        if member_res.status_code != 200:
            return RedirectResponse("/?error=not_in_server")
        member_data = member_res.json()
        member_role_ids = member_data.get("roles", [])

        # Risolvi nomi ruoli
        guild_res = await client.get(
            f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/roles",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
        )
        guild_roles = guild_res.json() if guild_res.status_code == 200 else []
        role_id_to_name = {r["id"]: r["name"] for r in guild_roles}
        member_role_names = [role_id_to_name[rid] for rid in member_role_ids if rid in role_id_to_name]

        # Determina livello accesso
        livello = discord_roles_to_level(member_role_names)
        if not livello:
            return RedirectResponse("/?error=no_role")

        # Trova agente nel DB (per username Discord)
        agent = db_fetchone("SELECT * FROM agents WHERE lower(discord)=lower(?)", (discord_username,))
        if not agent:
            agent = db_fetchone("SELECT * FROM agents WHERE lower(discord)=lower(?)", (discord_username.split('#')[0],))
        grado = agent["grado"] if agent else None
        agent_id = agent["id"] if agent else None

        # Crea sessione (8 ore)
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow()
        expires = now + timedelta(days=7)
        db_execute(
            "INSERT INTO discord_sessions (token,discord_id,discord_username,discord_avatar,livello,grado,agent_id,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (token, discord_id, discord_username, discord_avatar, livello, grado, agent_id, now.isoformat(), expires.isoformat())
        )
        return RedirectResponse(f"/?session={token}&livello={livello}")

@app.get("/auth/session")
def get_session_info(session=Depends(get_session)):
    return {
        "discord_id":       session["discord_id"],
        "discord_username": session["discord_username"],
        "discord_avatar":   session["discord_avatar"],
        "livello":          session["livello"],
        "grado":            session["grado"],
        "agent_id":         session["agent_id"],
    }

@app.post("/auth/logout")
def logout(x_session_token: str = Header(None)):
    if x_session_token:
        db_execute("DELETE FROM discord_sessions WHERE token=?", (x_session_token,))
    return {"ok": True}

# ══════════════════════════════════════════════════════
#   API ESISTENTI (invariate)
# ══════════════════════════════════════════════════════

@app.get("/api/agents")
def get_agents(): return db_fetchall("SELECT * FROM agents ORDER BY cognome")

@app.get("/api/history")
def get_history(): return db_fetchall("SELECT * FROM history ORDER BY data DESC LIMIT 500")

@app.get("/api/comunicati")
def get_comunicati():
    rows=db_fetchall("SELECT * FROM comunicati ORDER BY data DESC")
    for r in rows:
        rb=r.get("readBy") or r.get("readby") or "[]"
        r["readBy"]=json.loads(rb)
    return rows

@app.get("/api/settings")
def get_settings():
    rows=db_fetchall("SELECT key,value FROM settings")
    s={r["key"]:r["value"] for r in rows}
    return {"gradi":json.loads(s.get("gradi","[]")),"sanzioni":json.loads(s.get("sanzioni","[]")),"logo":s.get("logo","")}

@app.post("/api/login")
def login(body: dict):
    row=db_fetchone("SELECT value FROM settings WHERE key='pwd'")
    if not row or body.get("pwd")!=row["value"]: raise HTTPException(status_code=401,detail="Password errata")
    return {"ok":True}

@app.post("/api/login/agente")
def login_agente(body: dict):
    cf=body.get("cf","").strip().upper()
    pwd=body.get("pwd","").strip()
    if not cf: raise HTTPException(status_code=400,detail="Codice Fiscale mancante")
    row=db_fetchone("SELECT * FROM agents WHERE upper(cf)=?",(cf,))
    if not row: raise HTTPException(status_code=404,detail="Codice Fiscale non trovato")
    if row.get("stato")=="Congedato": raise HTTPException(status_code=403,detail="Account congedato")
    agent_pwd=row.get("agent_pwd")
    if not agent_pwd:
        return {**row,"first_access":True}
    if pwd!=agent_pwd: raise HTTPException(status_code=401,detail="Password errata")
    return {**row,"first_access":False}

@app.post("/api/agente/set-password")
def set_agente_password(body: dict):
    cf=body.get("cf","").strip().upper()
    pwd=body.get("pwd","").strip()
    if not cf or not pwd: raise HTTPException(status_code=400,detail="Dati mancanti")
    db_execute("UPDATE agents SET agent_pwd=? WHERE upper(cf)=?",(pwd,cf))
    return {"ok":True}

@app.get("/api/agenti/passwords", dependencies=[Depends(check_auth)])
def get_agenti_passwords():
    rows=db_fetchall("SELECT id,nome,cognome,discord,agent_pwd FROM agents ORDER BY cognome")
    return [{"id":r["id"],"nome":r["nome"],"cognome":r["cognome"],"discord":r["discord"],"has_password":bool(r.get("agent_pwd"))} for r in rows]

@app.post("/api/agenti/{agent_id}/reset-password", dependencies=[Depends(check_auth)])
def reset_agente_password(agent_id: str):
    db_execute("UPDATE agents SET agent_pwd=NULL WHERE id=?",(agent_id,))
    return {"ok":True}

@app.post("/api/agenti/{agent_id}/set-password-dirigenza", dependencies=[Depends(check_auth)])
def set_agente_password_dirigenza(agent_id: str, body: dict):
    pwd=body.get("pwd","").strip()
    if not pwd or len(pwd)<3: raise HTTPException(status_code=400,detail="Password troppo corta")
    db_execute("UPDATE agents SET agent_pwd=? WHERE id=?",(pwd,agent_id))
    return {"ok":True}

@app.post("/api/agents", dependencies=[Depends(check_auth)])
def create_agent(agent: Agent):
    agent.id=agent.id or str(uuid.uuid4())[:12]
    agent.dataIngresso=agent.dataIngresso or str(date.today())
    db_execute_many([
        ("INSERT INTO agents (id,nome,cognome,cf,discord,grado,stato,sanzione,note,dataIngresso) VALUES (?,?,?,?,?,?,?,?,?,?)",(agent.id,agent.nome,agent.cognome,agent.cf,agent.discord,agent.grado,agent.stato,agent.sanzione,agent.note,agent.dataIngresso)),
        ("INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data) VALUES (?,?,?,?,?,?,?,?)",(str(uuid.uuid4())[:12],agent.id,f"{agent.nome} {agent.cognome}","Ingresso","—",agent.grado,"Nuova assunzione",str(date.today())))
    ])
    return agent

@app.put("/api/agents/{agent_id}", dependencies=[Depends(check_auth)])
def update_agent(agent_id: str, agent: Agent):
    old=db_fetchone("SELECT * FROM agents WHERE id=?",(agent_id,))
    if not old: raise HTTPException(status_code=404,detail="Agente non trovato")
    ops=[("UPDATE agents SET nome=?,cognome=?,cf=?,discord=?,grado=?,stato=?,sanzione=?,note=? WHERE id=?",(agent.nome,agent.cognome,agent.cf,agent.discord,agent.grado,agent.stato,agent.sanzione,agent.note,agent_id))]
    if old.get("grado")!=agent.grado:
        ops.append(("INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data) VALUES (?,?,?,?,?,?,?,?)",(str(uuid.uuid4())[:12],agent_id,f"{agent.nome} {agent.cognome}","Modifica Grado",old.get("grado",""),agent.grado,"Modifica diretta",str(date.today()))))
    db_execute_many(ops); return {"ok":True}

@app.delete("/api/agents/{agent_id}", dependencies=[Depends(check_auth)])
def delete_agent(agent_id: str):
    db_execute_many([("DELETE FROM agents WHERE id=?",(agent_id,)),("DELETE FROM history WHERE agentId=?",(agent_id,))]); return {"ok":True}

@app.post("/api/history", dependencies=[Depends(check_auth)])
def add_history(entry: HistoryEntry):
    entry.id=entry.id or str(uuid.uuid4())[:12]
    entry.data=entry.data or str(date.today())
    ag=db_fetchone("SELECT * FROM agents WHERE id=?",(entry.agentId,))
    ops=[]
    if ag:
        if entry.tipo in ("Promozione","Degrado"): ops.append(("UPDATE agents SET grado=? WHERE id=?",(entry.nuovo,entry.agentId)))
        elif entry.tipo=="Sanzione":
            sn="Sospeso" if entry.nuovo=="SOSPENSIONE" else ag.get("stato","Attivo")
            ops.append(("UPDATE agents SET sanzione=?,stato=? WHERE id=?",(entry.nuovo,sn,entry.agentId)))
        elif entry.tipo=="Rimozione Sanzione": ops.append(("UPDATE agents SET sanzione=NULL WHERE id=?",(entry.agentId,)))
        elif entry.tipo=="Cambio Stato": ops.append(("UPDATE agents SET stato=? WHERE id=?",(entry.nuovo,entry.agentId)))
        elif entry.tipo=="Licenziamento": ops.append(("UPDATE agents SET stato='Congedato' WHERE id=?",(entry.agentId,)))
    ops.append(("INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data) VALUES (?,?,?,?,?,?,?,?)",(entry.id,entry.agentId,entry.agentNome,entry.tipo,entry.vecchio,entry.nuovo,entry.motivo,entry.data)))
    db_execute_many(ops); return {"ok":True}

@app.delete("/api/history/{entry_id}", dependencies=[Depends(check_auth)])
def delete_history_entry(entry_id: str):
    db_execute("DELETE FROM history WHERE id=?",(entry_id,)); return {"ok":True}

@app.post("/api/comunicati", dependencies=[Depends(check_auth)])
def create_comunicato(com: Comunicato):
    com.id=com.id or str(uuid.uuid4())[:12]
    com.data=com.data or str(date.today())
    db_execute("INSERT INTO comunicati (id,titolo,corpo,priorita,data,readBy) VALUES (?,?,?,?,?,?)",(com.id,com.titolo,com.corpo,com.priorita,com.data,json.dumps(com.readBy))); return com

@app.put("/api/comunicati/{com_id}", dependencies=[Depends(check_auth)])
def update_comunicato(com_id: str, com: Comunicato):
    db_execute("UPDATE comunicati SET titolo=?,corpo=?,priorita=? WHERE id=?",(com.titolo,com.corpo,com.priorita,com_id)); return {"ok":True}

@app.delete("/api/comunicati/{com_id}", dependencies=[Depends(check_auth)])
def delete_comunicato(com_id: str):
    db_execute("DELETE FROM comunicati WHERE id=?",(com_id,)); return {"ok":True}

@app.post("/api/comunicati/{com_id}/read")
def mark_read(com_id: str, body: MarkRead):
    row=db_fetchone("SELECT * FROM comunicati WHERE id=?",(com_id,))
    if row:
        rb=row.get("readBy") or row.get("readby") or "[]"
        readBy=json.loads(rb)
        if body.agentId not in readBy:
            readBy.append(body.agentId)
            db_execute("UPDATE comunicati SET readBy=? WHERE id=?",(json.dumps(readBy),com_id))
    return {"ok":True}

@app.put("/api/settings", dependencies=[Depends(check_auth)])
def update_settings(s: SettingsUpdate):
    if s.pwd: upsert("pwd",s.pwd)
    if s.gradi is not None: upsert("gradi",json.dumps(s.gradi))
    if s.sanzioni is not None: upsert("sanzioni",json.dumps(s.sanzioni))
    if s.logo is not None: upsert("logo",s.logo)
    return {"ok":True}

class PecMessage(BaseModel):
    id: Optional[str]=None; mittenteId: str; mittenteNome: str
    destinatarioId: str; destinatarioNome: str
    oggetto: str; corpo: str; priorita: str="normale"
    stato: str="inviata"; letta: Optional[bool]=False; data: Optional[str]=None

class Documento(BaseModel):
    id: Optional[str]=None; titolo: str; descrizione: Optional[str]=""
    url: Optional[str]=""; icona: Optional[str]="📄"
    stato: Optional[str]=""; categoria: str="altro"; ordine: Optional[int]=0

class Segnalazione(BaseModel):
    id: Optional[str]=None; titolo: str; corpo: str
    priorita: str="normale"; mittenteId: str; mittenteNome: str
    stato: str="aperta"; data: Optional[str]=None

class StatoUpdate(BaseModel):
    stato: str

@app.get("/api/pec")
def get_pec():
    rows=db_fetchall("SELECT * FROM pec ORDER BY data DESC")
    for r in rows: r["letta"]=bool(r.get("letta",False))
    return rows

@app.post("/api/pec")
def create_pec(pec: PecMessage):
    pec.id=pec.id or str(uuid.uuid4())[:12]
    pec.data=pec.data or str(date.today())
    db_execute("INSERT INTO pec (id,mittenteId,mittenteNome,destinatarioId,destinatarioNome,oggetto,corpo,priorita,stato,letta,data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pec.id,pec.mittenteId,pec.mittenteNome,pec.destinatarioId,pec.destinatarioNome,pec.oggetto,pec.corpo,pec.priorita,pec.stato,0,pec.data))
    return pec

@app.put("/api/pec/{pec_id}")
def update_pec(pec_id: str, pec: PecMessage):
    db_execute("UPDATE pec SET oggetto=?,corpo=?,priorita=?,stato=?,destinatarioId=?,destinatarioNome=? WHERE id=?",
        (pec.oggetto,pec.corpo,pec.priorita,pec.stato,pec.destinatarioId,pec.destinatarioNome,pec_id))
    return {"ok":True}

@app.post("/api/pec/{pec_id}/leggi")
def leggi_pec(pec_id: str):
    db_execute("UPDATE pec SET letta=1 WHERE id=?",(pec_id,)); return {"ok":True}

@app.delete("/api/pec/{pec_id}")
def delete_pec(pec_id: str):
    db_execute("DELETE FROM pec WHERE id=?",(pec_id,)); return {"ok":True}

@app.get("/api/documenti")
def get_documenti():
    return db_fetchall("SELECT * FROM documenti ORDER BY categoria,ordine,titolo")

@app.post("/api/documenti")
def create_documento(doc: Documento, x_api_key: str = Header(None), x_session_token: str = Header(None)):
    # Dirigenza: richiede API key — può creare in qualsiasi categoria
    # Agenti: richiede session token valido — solo categoria 'altro' (verbali)
    if x_api_key == API_KEY:
        pass  # dirigenza autorizzata
    elif x_session_token:
        sess = db_fetchone("SELECT * FROM sessions WHERE token=? AND expires>datetime('now')", (x_session_token,))
        if not sess:
            raise HTTPException(status_code=401, detail="Sessione non valida")
        if doc.categoria != "altro":
            raise HTTPException(status_code=403, detail="Gli agenti possono creare solo Verbali")
    else:
        raise HTTPException(status_code=401, detail="Non autorizzato")
    doc.id=doc.id or str(uuid.uuid4())[:12]
    db_execute("INSERT INTO documenti (id,titolo,descrizione,url,icona,stato,categoria,ordine) VALUES (?,?,?,?,?,?,?,?)",
        (doc.id,doc.titolo,doc.descrizione,doc.url,doc.icona,doc.stato,doc.categoria,doc.ordine))
    return doc

@app.put("/api/documenti/{doc_id}", dependencies=[Depends(check_auth)])
def update_documento(doc_id: str, doc: Documento):
    db_execute("UPDATE documenti SET titolo=?,descrizione=?,url=?,icona=?,stato=?,categoria=?,ordine=? WHERE id=?",
        (doc.titolo,doc.descrizione,doc.url,doc.icona,doc.stato,doc.categoria,doc.ordine,doc_id))
    return {"ok":True}

@app.delete("/api/documenti/{doc_id}", dependencies=[Depends(check_auth)])
def delete_documento(doc_id: str):
    db_execute("DELETE FROM documenti WHERE id=?",(doc_id,)); return {"ok":True}

@app.get("/api/segnalazioni")
def get_segnalazioni():
    return db_fetchall("SELECT * FROM segnalazioni ORDER BY data DESC")

@app.post("/api/segnalazioni")
def create_segnalazione(seg: Segnalazione):
    seg.id=seg.id or str(uuid.uuid4())[:12]
    seg.data=seg.data or str(date.today())
    db_execute("INSERT INTO segnalazioni (id,titolo,corpo,priorita,mittenteId,mittenteNome,stato,data) VALUES (?,?,?,?,?,?,?,?)",
        (seg.id,seg.titolo,seg.corpo,seg.priorita,seg.mittenteId,seg.mittenteNome,seg.stato,seg.data))
    return seg

@app.put("/api/segnalazioni/{seg_id}", dependencies=[Depends(check_auth)])
def update_segnalazione(seg_id: str, body: StatoUpdate):
    db_execute("UPDATE segnalazioni SET stato=? WHERE id=?",(body.stato,seg_id)); return {"ok":True}

@app.delete("/api/segnalazioni/{seg_id}", dependencies=[Depends(check_auth)])
def delete_segnalazione(seg_id: str):
    db_execute("DELETE FROM segnalazioni WHERE id=?",(seg_id,)); return {"ok":True}

SYNC_KEY = os.getenv("SYNC_KEY", "estovia_2026_secret")

@app.get("/sync")
async def discord_sync(
    sync: str = None,
    discord: str = None,
    tipo: str = None,
    motivo: str = None,
    key: str = None,
    grado: str = None,
    sanzione: str = None,
    stato: str = None,
    rimozione_sanzione: str = None,
):
    # Verifica chiave segreta
    if key != SYNC_KEY:
        raise HTTPException(status_code=403, detail="Chiave non valida")
    if not discord or not tipo:
        raise HTTPException(status_code=400, detail="Parametri mancanti")

    # Trova agente per username Discord
    agent = db_fetchone("SELECT * FROM agents WHERE lower(discord)=lower(?)", (discord,))
    if not agent:
        agent = db_fetchone("SELECT * FROM agents WHERE lower(discord)=lower(?)", (discord.split('#')[0],))
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agente '{discord}' non trovato nel gestionale")

    agent_id = agent["id"]
    agent_nome = f"{agent['nome']} {agent['cognome']}"
    now = str(date.today())

    if tipo in ("Promozione", "Degrado") and grado:
        vecchio = agent["grado"]
        db_execute("UPDATE agents SET grado=? WHERE id=?", (grado, agent_id))
        db_execute(
            "INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4())[:12], agent_id, agent_nome, tipo, vecchio, grado, motivo or "", now)
        )

    elif tipo == "Sanzione" and sanzione:
        vecchio = agent.get("sanzione") or "Nessuna"
        db_execute("UPDATE agents SET sanzione=? WHERE id=?", (sanzione, agent_id))
        db_execute(
            "INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4())[:12], agent_id, agent_nome, "Sanzione", vecchio, sanzione, motivo or "", now)
        )

    elif tipo == "Rimozione Sanzione":
        vecchio = agent.get("sanzione") or "Nessuna"
        db_execute("UPDATE agents SET sanzione=NULL WHERE id=?", (agent_id,))
        db_execute(
            "INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4())[:12], agent_id, agent_nome, "Rimozione Sanzione", vecchio, "Nessuna", motivo or "", now)
        )

    elif tipo in ("Cambio Stato", "Licenziamento") and stato:
        vecchio = agent.get("stato") or "Attivo"
        db_execute("UPDATE agents SET stato=? WHERE id=?", (stato, agent_id))
        db_execute(
            "INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4())[:12], agent_id, agent_nome, tipo, vecchio, stato, motivo or "", now)
        )

    return {"ok": True, "agente": agent_nome, "tipo": tipo}

@app.get("/")
def serve_frontend(): return FileResponse("gestionale.html")

if __name__=="__main__":
    import uvicorn
    port=int(os.getenv("PORT",8000))
    uvicorn.run("main:app",host="0.0.0.0",port=port)
