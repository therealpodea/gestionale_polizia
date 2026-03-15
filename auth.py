import os
import re
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import jwt, JWTError
from datetime import datetime, timedelta
from config import (
    DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET,
    DISCORD_REDIRECT_URI, DISCORD_API_BASE,
    DISCORD_GUILD_ID, SECRET_KEY,
    RUOLI_DIRIGENZA, RUOLI_AFFARI_INTERNI,
    RUOLI_ISPETTORATO, RUOLI_AGENTE,
)

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")

JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = 8
COOKIE_NAME      = "session_token"


# ── Pulizia nome ruolo ─────────────────────────────────────────────────────────
def _strip(name: str) -> str:
    """
    Rimuove emoji, simboli unicode e prefissi speciali dal nome del ruolo.
    '👑≫Responsabile Reparto Affari Interni' → 'Responsabile Reparto Affari Interni'
    '🎗️≫Affari Interni In Prova'            → 'Affari Interni In Prova'
    '>>Dirigenza'                            → 'Dirigenza'
    """
    # Rimuove tutti i caratteri non-ASCII (emoji e simboli unicode)
    stripped = name.encode("ascii", errors="ignore").decode("ascii")
    # Rimuove prefissi residui tipo >>, >, spazi
    stripped = re.sub(r"^[>\s»\-_|#@!~^*]+", "", stripped).strip()
    return stripped


def _match(role_name: str, role_list: list[str]) -> bool:
    """Controlla se il nome del ruolo (stripped) è nella lista, case-insensitive."""
    clean = _strip(role_name).lower()
    return any(r.lower() in clean or clean in r.lower() for r in role_list)


# ── Calcolo permesso dai nomi dei ruoli ────────────────────────────────────────
def calculate_permission_from_names(role_names: list[str]) -> tuple[int, bool]:
    """
    Restituisce (permission_level, is_ai) in base ai nomi dei ruoli Discord.
    Non richiede nessuna variabile env per i ruoli.
    """
    permission = 0
    is_ai = False

    for name in role_names:
        if _match(name, RUOLI_DIRIGENZA):
            permission = max(permission, 100)
        elif _match(name, RUOLI_AFFARI_INTERNI):
            is_ai = True
            permission = max(permission, 75)
        elif _match(name, RUOLI_ISPETTORATO):
            permission = max(permission, 50)
        elif _match(name, RUOLI_AGENTE):
            permission = max(permission, 10)

    return permission, is_ai


def get_livello(permission: int, is_ai: bool) -> str:
    if is_ai:
        return "affari_interni"
    if permission >= 100:
        return "dirigenza"
    if permission >= 50:
        return "ispettorato"
    if permission >= 10:
        return "agente"
    return "sconosciuto"


# ── JWT ────────────────────────────────────────────────────────────────────────
def create_session_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_session_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])


# ── Routes ─────────────────────────────────────────────────────────────────────
@router.get("/login")
async def login():
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify+guilds.members.read"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def callback(request: Request, code: str):
    from database import get_db
    db = get_db()

    async with httpx.AsyncClient() as client:
        # 1. Code → access_token
        token_res = await client.post(
            f"{DISCORD_API_BASE}/oauth2/token",
            data={
                "client_id":     DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_res.status_code != 200:
            raise HTTPException(400, "Errore token Discord.")
        access_token = token_res.json()["access_token"]

        # 2. Profilo utente
        user_res = await client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_res.status_code != 200:
            raise HTTPException(400, "Impossibile ottenere profilo Discord.")
        user = user_res.json()

        # 3. Membership nel server → ottieni role IDs + nick
        member_res = await client.get(
            f"{DISCORD_API_BASE}/users/@me/guilds/{DISCORD_GUILD_ID}/member",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        role_ids: list[str]   = []
        role_names: list[str] = []
        nick = user.get("username")

        if member_res.status_code == 200:
            member_data = member_res.json()
            role_ids    = member_data.get("roles", [])
            nick        = member_data.get("nick") or nick
        else:
            # Non è membro del server
            return templates.TemplateResponse("accesso_negato.html", {
                "request":  request,
                "username": user.get("username", ""),
                "motivo":   "Non sei membro del server Discord del Dipartimento.",
            }, status_code=403)

        # 4. Ottieni i nomi dei ruoli tramite Bot Token
        #    Questo è il cuore del sistema: i permessi si basano sui NOMI, non sugli ID
        bot_token = os.getenv("DISCORD_BOT_TOKEN", "")
        if bot_token and role_ids:
            try:
                guild_res = await client.get(
                    f"{DISCORD_API_BASE}/guilds/{DISCORD_GUILD_ID}/roles",
                    headers={"Authorization": f"Bot {bot_token}"},
                )
                if guild_res.status_code == 200:
                    all_roles  = guild_res.json()
                    role_map   = {r["id"]: r["name"] for r in all_roles}
                    role_names = [role_map[rid] for rid in role_ids if rid in role_map]
            except Exception:
                pass

    # ── Calcola permessi dai nomi dei ruoli ─────────────────────────────────────
    permission, is_ai = calculate_permission_from_names(role_names)

    if permission == 0 and not is_ai:
        return templates.TemplateResponse("accesso_negato.html", {
            "request":  request,
            "username": user.get("username", ""),
            "motivo":   "Il tuo account Discord non ha nessun ruolo autorizzato nel Dipartimento. Contatta la Dirigenza.",
        }, status_code=403)

    livello    = get_livello(permission, is_ai)
    discord_id = user["id"]
    avatar     = user.get("avatar")
    avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar}.png" if avatar else ""

    # ── DB: aggiorna o crea ─────────────────────────────────────────────────────
    existing = await db["agenti"].find_one({"discord_id": discord_id})

    if existing:
        if existing.get("approvato") is False:
            return templates.TemplateResponse("accesso_negato.html", {
                "request":  request,
                "username": user.get("username", ""),
                "motivo":   "Il tuo account è in attesa di approvazione dalla Dirigenza.",
            }, status_code=403)
        await db["agenti"].update_one(
            {"discord_id": discord_id},
            {"$set": {
                "role_ids":   role_ids,
                "role_names": role_names,
                "permission": permission,
                "livello":    livello,
                "is_ai":      is_ai,
                "avatar_url": avatar_url,
                "nick":       nick,
            }}
        )
    else:
        # Prima registrazione — dirigenza e AI approvati automaticamente
        approvato = permission >= 100 or is_ai
        await db["agenti"].insert_one({
            "discord_id":    discord_id,
            "username":      user.get("username"),
            "nick":          nick,
            "nome":          "",
            "cognome":       "",
            "cf":            "",
            "grado":         "Agente",
            "stato":         "Attivo",
            "sanzione":      None,
            "livello":       livello,
            "permission":    permission,
            "is_ai":         is_ai,
            "role_ids":      role_ids,
            "role_names":    role_names,
            "approvato":     approvato,
            "data_ingresso": datetime.now().strftime("%Y-%m-%d"),
            "note":          "",
            "avatar_url":    avatar_url,
            "added_by":      "Sistema",
            "timestamp":     datetime.now().strftime("%d/%m/%Y %H:%M"),
        })
        if not approvato:
            return templates.TemplateResponse("accesso_negato.html", {
                "request":  request,
                "username": user.get("username", ""),
                "motivo":   "Il tuo account è stato registrato ed è in attesa di approvazione dalla Dirigenza.",
            }, status_code=403)

    session_data = {
        "discord_id": discord_id,
        "username":   user.get("username"),
        "nick":       nick,
        "avatar_url": avatar_url,
        "role_ids":   role_ids,
        "permission": permission,
        "livello":    livello,
        "is_ai":      is_ai,
    }
    token = create_session_token(session_data)
    resp  = RedirectResponse(url="/dashboard")
    resp.set_cookie(
        key=COOKIE_NAME, value=token,
        httponly=True, samesite="lax",
        max_age=JWT_EXPIRE_HOURS * 3600,
    )
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse(url="/")
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ── Dipendenze FastAPI ─────────────────────────────────────────────────────────
def get_current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Non autenticato.")
    try:
        return decode_session_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Sessione scaduta.")


async def get_current_user_live(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Non autenticato.")
    try:
        data = decode_session_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Sessione scaduta.")

    from database import get_db
    db = get_db()
    agente = await db["agenti"].find_one({"discord_id": data.get("discord_id")})
    if agente:
        if agente.get("approvato") is False:
            raise HTTPException(status_code=403, detail="Account non approvato.")
        data["permission"] = agente.get("permission", data.get("permission", 0))
        data["is_ai"]      = agente.get("is_ai", False)
        data["livello"]    = agente.get("livello", "agente")
        data["grado"]      = agente.get("grado", "Agente")
        data["nick"]       = agente.get("nick", data.get("username"))
        data["avatar_url"] = agente.get("avatar_url", "")
    return data


def require_permission(min_level: int):
    async def checker(request: Request) -> dict:
        user = await get_current_user_live(request)
        if user.get("permission", 0) < min_level:
            raise HTTPException(status_code=403, detail=f"Accesso negato. Livello richiesto: {min_level}.")
        return user
    return checker


def require_write(action: str = "modificare"):
    async def checker(request: Request) -> dict:
        user = await get_current_user_live(request)
        if user.get("permission", 0) == 0:
            raise HTTPException(status_code=403, detail="Accesso negato.")
        return user
    return checker
