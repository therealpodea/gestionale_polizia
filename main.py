"""
╔══════════════════════════════════════════════════════════════╗
║        BACKEND GESTIONALE — POLIZIA D'ESTOVIA               ║
║        FastAPI + SQLite  |  Deploy su Railway               ║
╚══════════════════════════════════════════════════════════════╝
"""

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3, json, os, uuid
from datetime import date

# ── Chiave API dirigenza (cambiala in Railway → Variables) ──
API_KEY = os.getenv("GESTIONALE_API_KEY", "estovia_dirigenza_2026")

app = FastAPI(title="Gestionale Polizia d'Estovia")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ════════════════════════════════════════════════════════════
#  DATABASE
# ════════════════════════════════════════════════════════════

DB_PATH = os.getenv("DB_PATH", "gestionale.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            cognome TEXT NOT NULL,
            cf TEXT NOT NULL,
            discord TEXT NOT NULL,
            grado TEXT NOT NULL,
            stato TEXT NOT NULL DEFAULT 'Attivo',
            sanzione TEXT,
            note TEXT,
            dataIngresso TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id TEXT PRIMARY KEY,
            agentId TEXT NOT NULL,
            agentNome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            vecchio TEXT NOT NULL,
            nuovo TEXT NOT NULL,
            motivo TEXT NOT NULL,
            data TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS comunicati (
            id TEXT PRIMARY KEY,
            titolo TEXT NOT NULL,
            corpo TEXT NOT NULL,
            priorita TEXT NOT NULL DEFAULT 'normale',
            data TEXT NOT NULL,
            readBy TEXT NOT NULL DEFAULT '[]'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Impostazioni di default
    defaults = {
        "pwd": "estovia2026",
        "gradi": json.dumps([
            "Allievo Poliziotto","Agente","Agente Scelto","Assistente",
            "Assistente Coordinatore","Assistente Capo","Vice Sovrintendente",
            "Sovrintendente","Sovrintendente Capo","Sovrintendente Superiore",
            "Vice Ispettore","Ispettore","Ispettore Capo","Ispettore Superiore",
            "Sostituto Commissario","Vice Commissario","Commissario","Commissario Capo",
            "Primo Dirigente","Dirigente Aggiunto","Dirigente Superiore","Dirigente Generale"
        ]),
        "sanzioni": json.dumps([
            "AVVISO FORMALE 1","AVVISO FORMALE 2",
            "RICHIAMO 1","RICHIAMO 2","RICHIAMO 3","SOSPENSIONE"
        ]),
        "logo": ""
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

init_db()


# ════════════════════════════════════════════════════════════
#  AUTH — solo per le route di scrittura (dirigenza)
# ════════════════════════════════════════════════════════════

def check_auth(x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Non autorizzato")
    return True


# ════════════════════════════════════════════════════════════
#  MODELLI
# ════════════════════════════════════════════════════════════

class Agent(BaseModel):
    id: Optional[str] = None
    nome: str
    cognome: str
    cf: str
    discord: str
    grado: str
    stato: str = "Attivo"
    sanzione: Optional[str] = None
    note: Optional[str] = ""
    dataIngresso: Optional[str] = None

class HistoryEntry(BaseModel):
    id: Optional[str] = None
    agentId: str
    agentNome: str
    tipo: str
    vecchio: str
    nuovo: str
    motivo: str
    data: Optional[str] = None

class Comunicato(BaseModel):
    id: Optional[str] = None
    titolo: str
    corpo: str
    priorita: str = "normale"
    data: Optional[str] = None
    readBy: Optional[List[str]] = []

class SettingsUpdate(BaseModel):
    pwd: Optional[str] = None
    gradi: Optional[List[str]] = None
    sanzioni: Optional[List[str]] = None
    logo: Optional[str] = None

class MarkRead(BaseModel):
    agentId: str


# ════════════════════════════════════════════════════════════
#  ROUTE — LETTURA PUBBLICA
# ════════════════════════════════════════════════════════════

@app.get("/api/agents")
def get_agents():
    conn = get_db()
    rows = conn.execute("SELECT * FROM agents ORDER BY cognome").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/history")
def get_history():
    conn = get_db()
    rows = conn.execute("SELECT * FROM history ORDER BY data DESC, rowid DESC LIMIT 500").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/comunicati")
def get_comunicati():
    conn = get_db()
    rows = conn.execute("SELECT * FROM comunicati ORDER BY data DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["readBy"] = json.loads(d["readBy"])
        result.append(d)
    return result

@app.get("/api/settings")
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    s = {r["key"]: r["value"] for r in rows}
    return {
        "gradi":   json.loads(s.get("gradi", "[]")),
        "sanzioni": json.loads(s.get("sanzioni", "[]")),
        "logo":    s.get("logo", ""),
        # NON mandiamo la password al client
    }

@app.post("/api/login")
def login(body: dict):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key='pwd'").fetchone()
    conn.close()
    if not row or body.get("pwd") != row["value"]:
        raise HTTPException(status_code=401, detail="Password errata")
    return {"ok": True}

@app.post("/api/login/agente")
def login_agente(body: dict):
    nick = body.get("discord", "").strip().lower()
    if not nick:
        raise HTTPException(status_code=400, detail="Nick mancante")
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM agents WHERE lower(discord)=?", (nick,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Nick non trovato")
    if row["stato"] == "Congedato":
        raise HTTPException(status_code=403, detail="Account congedato")
    return dict(row)


# ════════════════════════════════════════════════════════════
#  ROUTE — SCRITTURA (solo dirigenza con API key)
# ════════════════════════════════════════════════════════════

@app.post("/api/agents", dependencies=[Depends(check_auth)])
def create_agent(agent: Agent):
    agent.id = agent.id or str(uuid.uuid4())[:12]
    agent.dataIngresso = agent.dataIngresso or str(date.today())
    conn = get_db()
    conn.execute("""
        INSERT INTO agents (id,nome,cognome,cf,discord,grado,stato,sanzione,note,dataIngresso)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (agent.id, agent.nome, agent.cognome, agent.cf, agent.discord,
          agent.grado, agent.stato, agent.sanzione, agent.note, agent.dataIngresso))
    # Storico ingresso
    conn.execute("""
        INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data)
        VALUES (?,?,?,?,?,?,?,?)
    """, (str(uuid.uuid4())[:12], agent.id, f"{agent.nome} {agent.cognome}",
          "Ingresso", "—", agent.grado, "Nuova assunzione", str(date.today())))
    conn.commit()
    conn.close()
    return agent

@app.put("/api/agents/{agent_id}", dependencies=[Depends(check_auth)])
def update_agent(agent_id: str, agent: Agent):
    conn = get_db()
    old = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not old:
        raise HTTPException(status_code=404, detail="Agente non trovato")
    conn.execute("""
        UPDATE agents SET nome=?,cognome=?,cf=?,discord=?,grado=?,stato=?,sanzione=?,note=?
        WHERE id=?
    """, (agent.nome, agent.cognome, agent.cf, agent.discord, agent.grado,
          agent.stato, agent.sanzione, agent.note, agent_id))
    # Se grado cambiato → storico
    if old["grado"] != agent.grado:
        conn.execute("""
            INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data)
            VALUES (?,?,?,?,?,?,?,?)
        """, (str(uuid.uuid4())[:12], agent_id, f"{agent.nome} {agent.cognome}",
              "Modifica Grado", old["grado"], agent.grado, "Modifica diretta", str(date.today())))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/agents/{agent_id}", dependencies=[Depends(check_auth)])
def delete_agent(agent_id: str):
    conn = get_db()
    conn.execute("DELETE FROM agents WHERE id=?", (agent_id,))
    conn.execute("DELETE FROM history WHERE agentId=?", (agent_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/history", dependencies=[Depends(check_auth)])
def add_history(entry: HistoryEntry):
    entry.id = entry.id or str(uuid.uuid4())[:12]
    entry.data = entry.data or str(date.today())
    conn = get_db()

    # Aggiorna anche l'agente se necessario
    ag = conn.execute("SELECT * FROM agents WHERE id=?", (entry.agentId,)).fetchone()
    if ag:
        if entry.tipo in ("Promozione", "Degrado"):
            conn.execute("UPDATE agents SET grado=? WHERE id=?", (entry.nuovo, entry.agentId))
        elif entry.tipo == "Sanzione":
            stato_nuovo = "Sospeso" if entry.nuovo == "SOSPENSIONE" else ag["stato"]
            conn.execute("UPDATE agents SET sanzione=?, stato=? WHERE id=?",
                         (entry.nuovo, stato_nuovo, entry.agentId))
        elif entry.tipo == "Rimozione Sanzione":
            conn.execute("UPDATE agents SET sanzione=NULL WHERE id=?", (entry.agentId,))
        elif entry.tipo == "Cambio Stato":
            conn.execute("UPDATE agents SET stato=? WHERE id=?", (entry.nuovo, entry.agentId))
        elif entry.tipo == "Licenziamento":
            conn.execute("UPDATE agents SET stato='Congedato' WHERE id=?", (entry.agentId,))

    conn.execute("""
        INSERT INTO history (id,agentId,agentNome,tipo,vecchio,nuovo,motivo,data)
        VALUES (?,?,?,?,?,?,?,?)
    """, (entry.id, entry.agentId, entry.agentNome, entry.tipo,
          entry.vecchio, entry.nuovo, entry.motivo, entry.data))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/history/{entry_id}", dependencies=[Depends(check_auth)])
def delete_history_entry(entry_id: str):
    conn = get_db()
    conn.execute("DELETE FROM history WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/comunicati", dependencies=[Depends(check_auth)])
def create_comunicato(com: Comunicato):
    com.id = com.id or str(uuid.uuid4())[:12]
    com.data = com.data or str(date.today())
    conn = get_db()
    conn.execute("""
        INSERT INTO comunicati (id,titolo,corpo,priorita,data,readBy)
        VALUES (?,?,?,?,?,?)
    """, (com.id, com.titolo, com.corpo, com.priorita, com.data, json.dumps(com.readBy)))
    conn.commit()
    conn.close()
    return com

@app.put("/api/comunicati/{com_id}", dependencies=[Depends(check_auth)])
def update_comunicato(com_id: str, com: Comunicato):
    conn = get_db()
    conn.execute("""
        UPDATE comunicati SET titolo=?,corpo=?,priorita=? WHERE id=?
    """, (com.titolo, com.corpo, com.priorita, com_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/comunicati/{com_id}", dependencies=[Depends(check_auth)])
def delete_comunicato(com_id: str):
    conn = get_db()
    conn.execute("DELETE FROM comunicati WHERE id=?", (com_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/comunicati/{com_id}/read")
def mark_read(com_id: str, body: MarkRead):
    conn = get_db()
    row = conn.execute("SELECT readBy FROM comunicati WHERE id=?", (com_id,)).fetchone()
    if row:
        readBy = json.loads(row["readBy"])
        if body.agentId not in readBy:
            readBy.append(body.agentId)
            conn.execute("UPDATE comunicati SET readBy=? WHERE id=?",
                         (json.dumps(readBy), com_id))
            conn.commit()
    conn.close()
    return {"ok": True}

@app.put("/api/settings", dependencies=[Depends(check_auth)])
def update_settings(s: SettingsUpdate):
    conn = get_db()
    if s.pwd:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('pwd',?)", (s.pwd,))
    if s.gradi is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('gradi',?)",
                     (json.dumps(s.gradi),))
    if s.sanzioni is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('sanzioni',?)",
                     (json.dumps(s.sanzioni),))
    if s.logo is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('logo',?)", (s.logo,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
#  SERVE IL FRONTEND
# ════════════════════════════════════════════════════════════

@app.get("/")
def serve_frontend():
    return FileResponse("gestionale.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
