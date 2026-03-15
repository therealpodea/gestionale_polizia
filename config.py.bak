import os
from dotenv import load_dotenv

load_dotenv()

# ── Discord OAuth ──────────────────────────────────────────────────────────────
DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_BOT_TOKEN     = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_GUILD_ID      = int(os.getenv("DISCORD_GUILD_ID", "0"))
DISCORD_REDIRECT_URI  = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/callback")
DISCORD_API_BASE      = "https://discord.com/api/v10"

# ── Database ───────────────────────────────────────────────────────────────────
MONGODB_URI     = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "gestionale_polizia")

# ── App ────────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
APP_HOST   = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT   = int(os.getenv("APP_PORT", "8000"))

# ── Identità ───────────────────────────────────────────────────────────────────
DIPARTIMENTO_NOME = "Polizia d'Estovia"

# ── API Esterna ────────────────────────────────────────────────────────────────
API_KEY         = os.getenv("API_KEY", "")
POLIZIA_URL     = os.getenv("POLIZIA_URL", "")
POLIZIA_API_KEY = os.getenv("POLIZIA_API_KEY", "")

# ── Canali Discord ─────────────────────────────────────────────────────────────
CANALE_LOG_ID         = int(os.getenv("CANALE_LOG_ID", "0"))
CANALE_ANNUNCI_ID     = int(os.getenv("CANALE_ANNUNCI_ID", "0"))
WELCOME_CHANNEL_ID    = int(os.getenv("WELCOME_CHANNEL_ID", "0"))
CANALE_CANDIDATURE_ID = int(os.getenv("CANALE_CANDIDATURE_ID", "0"))
CITTADINO_ROLE_ID     = int(os.getenv("CITTADINO_ROLE_ID", "0"))

# ── PERMESSI BASATI SUL NOME DEL RUOLO ────────────────────────────────────────
# Nessuna variabile env per i ruoli — il sistema legge il nome direttamente
# da Discord e decide i permessi in base a queste liste.
# Aggiungi/rimuovi nomi di ruolo liberamente senza toccare le env su Railway.
# Il matching ignora emoji e prefissi (es. "👑≫Staff" → "Staff").

# permission = 100 → accesso completo al gestionale
RUOLI_DIRIGENZA = [
    "Staff",
    "Dirigenza",
]

# permission = 75 → tutto il gestionale + sezione Affari Interni
RUOLI_AFFARI_INTERNI = [
    "Responsabile Reparto Affari Interni",
    "Direttore Affari Interni",
    "Affari Interni",
    "Affari Interni In Prova",
]

# permission = 50 → gestionale esteso (no gestione utenti)
RUOLI_ISPETTORATO = [
    "Ispettorato",
    "Sovrintendenza",
]

# permission = 10 → accesso base (profilo, verbali, segnalazioni, PEC)
RUOLI_AGENTE = [
    "Agente",
    "Accademia",
]

# ── Gerarchia gradi ────────────────────────────────────────────────────────────
GRADI_DEFAULT = [
    "Agente",
    "Agente Scelto",
    "Caporale",
    "Sergente",
    "Maresciallo",
    "Ispettore",
    "Vice Commissario",
    "Commissario",
    "Vice Questore",
    "Questore",
    "Comandante",
]

SANZIONI_DEFAULT = [
    "AVVISO FORMALE 1",
    "AVVISO FORMALE 2",
    "RICHIAMO 1",
    "RICHIAMO 2",
    "RICHIAMO 3",
    "SOSPENSIONE",
]
