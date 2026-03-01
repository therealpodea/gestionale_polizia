"""
╔══════════════════════════════════════════════════════════════╗
║        BACKEND GESTIONALE — POLIZIA D'ESTOVIA               ║
║        FastAPI + PostgreSQL  |  Deploy su Railway           ║
╚══════════════════════════════════════════════════════════════╝
"""

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import json, os, uuid
from datetime import date

API_KEY = os.getenv("GESTIONALE_API_KEY", "estovia_dirigenza_2026")
DATABASE_URL = os.getenv("DATABASE_URL", "")

app = FastAPI(title="Gestionale Polizia d'Estovia")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GRADI_DEFAULT = ["Allievo Poliziotto","Agente","Agente Scelto","Assistente","Assistente Coordinatore","Assistente Capo","Vice Sovrintendente","Sovrintendente","Sovrintendente Capo","Sovrintendente Superiore","Vice Ispettore","Ispettore","Ispettore Capo","Ispettore Superiore","Sostituto Commissario","Vice Commissario","Commissario","Commissario Capo","Primo Dirigente","Dirigente Aggiunto","Dirigente Superiore","Dirigente Generale"]
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
        for k,v in [("pwd","estovia2026"),("gradi",json.dumps(GRADI_DEFAULT)),("sanzioni",json.dumps(SANZIONI_DEFAULT)),("logo","")]:
            c.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING",(k,v))
        # Aggiungi colonna agent_pwd se non esiste
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
        for k,v in [("pwd","estovia2026"),("gradi",json.dumps(GRADI_DEFAULT)),("sanzioni",json.dumps(SANZIONI_DEFAULT)),("logo","")]:
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
        try: c.execute("ALTER TABLE agents ADD COLUMN agent_pwd TEXT")
        except: pass
        conn.commit(); conn.close()

init_db()

def check_auth(x_api_key: str = Header(None)):
    if x_api_key != API_KEY: raise HTTPException(status_code=401, detail="Non autorizzato")
    return True

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

# ── LETTURA PUBBLICA ──

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
    nick=body.get("discord","").strip().lower()
    pwd=body.get("pwd","").strip()
    if not nick: raise HTTPException(status_code=400,detail="Nick mancante")
    row=db_fetchone("SELECT * FROM agents WHERE lower(discord)=?",(nick,))
    if not row: raise HTTPException(status_code=404,detail="Nick non trovato")
    if row.get("stato")=="Congedato": raise HTTPException(status_code=403,detail="Account congedato")
    agent_pwd=row.get("agent_pwd")
    if not agent_pwd:
        return {**row,"first_access":True}
    if pwd!=agent_pwd: raise HTTPException(status_code=401,detail="Password errata")
    return {**row,"first_access":False}

@app.post("/api/agente/set-password")
def set_agente_password(body: dict):
    nick=body.get("discord","").strip().lower()
    pwd=body.get("pwd","").strip()
    if not nick or not pwd: raise HTTPException(status_code=400,detail="Dati mancanti")
    db_execute("UPDATE agents SET agent_pwd=? WHERE lower(discord)=?",(pwd,nick))
    return {"ok":True}

@app.get("/api/agenti/passwords", dependencies=[Depends(check_auth)])
def get_agenti_passwords():
    rows=db_fetchall("SELECT id,nome,cognome,discord,agent_pwd FROM agents ORDER BY cognome")
    return [{"id":r["id"],"nome":r["nome"],"cognome":r["cognome"],"discord":r["discord"],"has_password":bool(r.get("agent_pwd"))} for r in rows]

@app.post("/api/agenti/{agent_id}/reset-password", dependencies=[Depends(check_auth)])
def reset_agente_password(agent_id: str):
    db_execute("UPDATE agents SET agent_pwd=NULL WHERE id=?",(agent_id,))
    return {"ok":True}

# ── SCRITTURA DIRIGENZA ──

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

@app.get("/")
def serve_frontend(): return FileResponse("gestionale.html")

if __name__=="__main__":
    import uvicorn
    port=int(os.getenv("PORT",8000))
    uvicorn.run("main:app",host="0.0.0.0",port=port)
