"""
Portale pubblico per i cittadini.
Login tramite Discord OAuth — deve essere nel server della Polizia.
"""
from __future__ import annotations
from datetime import datetime
import random
import string

from bson import ObjectId
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import httpx

import config

router    = APIRouter(tags=["cittadini"])
templates = Jinja2Templates(directory="templates")

COOKIE_CITTADINO = "cittadino_session"
DISCORD_REDIRECT_CITTADINI = config.DISCORD_REDIRECT_URI.replace("/auth/callback", "/cittadini/callback")


def uid():
    return datetime.now().strftime("%Y%m%d%H%M%S") + "".join(random.choices(string.ascii_lowercase, k=4))

def oggi():
    return datetime.now().strftime("%Y-%m-%d")

def _gen_codice():
    return "SEG-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

def _ser(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def _ser_list(docs):
    return [_ser(dict(d)) for d in docs]

async def _get_cittadino(request: Request):
    discord_id = request.cookies.get(COOKIE_CITTADINO)
    if not discord_id:
        return None
    from database import get_db
    db = get_db()
    return _ser(await db["cittadini"].find_one({"discord_id": discord_id}))


# ── Home ──────────────────────────────────────────────────────────────────────
@router.get("/cittadini", response_class=HTMLResponse)
async def cittadini_home(request: Request):
    cittadino = await _get_cittadino(request)
    return templates.TemplateResponse("cittadini/home.html", {
        "request":      request,
        "cittadino":    cittadino,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── Discord OAuth ─────────────────────────────────────────────────────────────
@router.get("/cittadini/login")
async def cittadini_login():
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={config.DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_CITTADINI}"
        f"&response_type=code"
        f"&scope=identify+guilds.members.read"
    )
    return RedirectResponse(url)


@router.get("/cittadini/callback")
async def cittadini_callback(request: Request, code: str):
    from database import get_db
    db = get_db()

    async with httpx.AsyncClient() as client:
        # 1. Code → token
        token_res = await client.post(
            f"{config.DISCORD_API_BASE}/oauth2/token",
            data={
                "client_id":     config.DISCORD_CLIENT_ID,
                "client_secret": config.DISCORD_CLIENT_SECRET,
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  DISCORD_REDIRECT_CITTADINI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_res.status_code != 200:
            return templates.TemplateResponse("cittadini/accesso_negato.html", {
                "request": request,
                "motivo": "Errore durante l'autenticazione Discord. Riprova.",
            }, status_code=403)
        access_token = token_res.json()["access_token"]

        # 2. Profilo utente
        user_res = await client.get(
            f"{config.DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_res.status_code != 200:
            return templates.TemplateResponse("cittadini/accesso_negato.html", {
                "request": request,
                "motivo": "Impossibile ottenere il profilo Discord.",
            }, status_code=403)
        user = user_res.json()

        # 3. Verifica membership nel server
        member_res = await client.get(
            f"{config.DISCORD_API_BASE}/users/@me/guilds/{config.DISCORD_GUILD_ID}/member",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if member_res.status_code != 200:
            return templates.TemplateResponse("cittadini/accesso_negato.html", {
                "request": request,
                "motivo": "Non sei membro del server Discord della Polizia d'Estovia. Per accedere al portale cittadini devi essere nel server.",
                "username": user.get("username", ""),
            }, status_code=403)

        member_data = member_res.json()
        nick = member_data.get("nick") or user.get("username")

    discord_id = user["id"]
    avatar = user.get("avatar")
    avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar}.png" if avatar else ""

    # 4. Crea o aggiorna cittadino nel DB
    existing = await db["cittadini"].find_one({"discord_id": discord_id})
    if existing:
        await db["cittadini"].update_one(
            {"discord_id": discord_id},
            {"$set": {
                "username":   user.get("username"),
                "nick":       nick,
                "avatar_url": avatar_url,
                "ultimo_accesso": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }}
        )
        # Se non ha completato il profilo, vai alla compilazione
        if not existing.get("cf"):
            resp = RedirectResponse("/cittadini/profilo", status_code=303)
            resp.set_cookie(COOKIE_CITTADINO, discord_id, httponly=True, samesite="lax", max_age=86400*7)
            return resp
    else:
        # Nuovo cittadino — crea scheda vuota
        await db["cittadini"].insert_one({
            "discord_id":   discord_id,
            "username":     user.get("username"),
            "nick":         nick,
            "avatar_url":   avatar_url,
            "cf":           "",
            "nome":         "",
            "cognome":      "",
            "data_nascita": "",
            "sesso":        "",
            "nazionalita":  "",
            "luogo_nascita":"",
            "telefono":     "",
            "professione":  "",
            "fedina":       [],
            "data_registrazione": oggi(),
            "ultimo_accesso": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        resp = RedirectResponse("/cittadini/profilo", status_code=303)
        resp.set_cookie(COOKIE_CITTADINO, discord_id, httponly=True, samesite="lax", max_age=86400*7)
        return resp

    resp = RedirectResponse("/cittadini/fedina", status_code=303)
    resp.set_cookie(COOKIE_CITTADINO, discord_id, httponly=True, samesite="lax", max_age=86400*7)
    return resp


@router.get("/cittadini/logout")
async def cittadini_logout():
    resp = RedirectResponse("/cittadini")
    resp.delete_cookie(COOKIE_CITTADINO)
    return resp


# ── Profilo (compilazione dati) ───────────────────────────────────────────────
@router.get("/cittadini/profilo", response_class=HTMLResponse)
async def profilo_form(request: Request):
    cittadino = await _get_cittadino(request)
    if not cittadino:
        return RedirectResponse("/cittadini/login")
    return templates.TemplateResponse("cittadini/profilo.html", {
        "request":   request,
        "cittadino": cittadino,
        "errore":    None,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.post("/cittadini/profilo")
async def profilo_salva(
    request:      Request,
    nome:         str = Form(...),
    cognome:      str = Form(...),
    cf:           str = Form(...),
    data_nascita: str = Form(""),
    sesso:        str = Form(""),
    nazionalita:  str = Form(""),
    luogo_nascita:str = Form(""),
    telefono:     str = Form(""),
    professione:  str = Form(""),
):
    cittadino = await _get_cittadino(request)
    if not cittadino:
        return RedirectResponse("/cittadini/login")

    from database import get_db
    db = get_db()

    cf = cf.strip().upper()
    if not nome.strip() or not cognome.strip() or not cf:
        return templates.TemplateResponse("cittadini/profilo.html", {
            "request":   request,
            "cittadino": cittadino,
            "errore":    "Nome, cognome e codice fiscale sono obbligatori.",
            "dipartimento": config.DIPARTIMENTO_NOME,
        })

    # Controlla CF duplicato (altro utente)
    existing = await db["cittadini"].find_one({"cf": cf, "discord_id": {"$ne": cittadino["discord_id"]}})
    if existing:
        return templates.TemplateResponse("cittadini/profilo.html", {
            "request":   request,
            "cittadino": cittadino,
            "errore":    "Questo Codice Fiscale è già associato a un altro account.",
            "dipartimento": config.DIPARTIMENTO_NOME,
        })

    await db["cittadini"].update_one(
        {"discord_id": cittadino["discord_id"]},
        {"$set": {
            "nome":          nome.strip(),
            "cognome":       cognome.strip(),
            "cf":            cf,
            "data_nascita":  data_nascita,
            "sesso":         sesso,
            "nazionalita":   nazionalita.strip(),
            "luogo_nascita": luogo_nascita.strip(),
            "telefono":      telefono.strip(),
            "professione":   professione.strip(),
        }}
    )
    return RedirectResponse("/cittadini/fedina", status_code=303)


# ── Fedina penale ─────────────────────────────────────────────────────────────
@router.get("/cittadini/fedina", response_class=HTMLResponse)
async def fedina(request: Request, cerca_cf: str = ""):
    cittadino = await _get_cittadino(request)
    risultato = None
    segnalazioni = []

    if cerca_cf:
        from database import get_db
        db = get_db()
        risultato = _ser(await db["cittadini"].find_one({"cf": cerca_cf.upper()}))

    if cittadino:
        from database import get_db
        db = get_db()
        segnalazioni = _ser_list(
            await db["segnalazioni_pubbliche"].find({"cf": cittadino.get("cf", "")}).sort("timestamp", -1).to_list(50)
        )

    return templates.TemplateResponse("cittadini/fedina.html", {
        "request":      request,
        "cittadino":    cittadino,
        "segnalazioni": segnalazioni,
        "cerca_cf":     cerca_cf.upper() if cerca_cf else "",
        "risultato":    risultato,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── Segnalazione pubblica ─────────────────────────────────────────────────────
@router.get("/cittadini/segnalazione", response_class=HTMLResponse)
async def segnalazione_form(request: Request):
    cittadino = await _get_cittadino(request)
    return templates.TemplateResponse("cittadini/segnalazione.html", {
        "request":      request,
        "cittadino":    cittadino,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      False,
        "errore":       None,
        "codice":       None,
    })


@router.post("/cittadini/segnalazione")
async def segnalazione_invia(
    request:       Request,
    nome:          str = Form(""),
    cf:            str = Form(""),
    titolo:        str = Form(...),
    corpo:         str = Form(...),
    tipo:          str = Form("generale"),
    data_episodio: str = Form(""),
    luogo:         str = Form(""),
    priorita:      str = Form("normale"),
):
    if not titolo.strip() or not corpo.strip():
        cittadino = await _get_cittadino(request)
        return templates.TemplateResponse("cittadini/segnalazione.html", {
            "request":      request,
            "cittadino":    cittadino,
            "dipartimento": config.DIPARTIMENTO_NOME,
            "inviata":      False,
            "errore":       "Compila tutti i campi obbligatori.",
            "codice":       None,
        })

    from database import get_db
    db = get_db()
    codice = _gen_codice()

    # Se loggato, prendi i dati dal profilo
    cittadino = await _get_cittadino(request)
    if cittadino and cittadino.get("cf"):
        nome = f"{cittadino.get('nome', '')} {cittadino.get('cognome', '')}".strip()
        cf = cittadino.get("cf", "")

    await db["segnalazioni_pubbliche"].insert_one({
        "id":            codice,
        "nome":          nome.strip(),
        "cf":            cf.strip().upper(),
        "titolo":        titolo.strip(),
        "corpo":         corpo.strip(),
        "tipo":          tipo,
        "data_episodio": data_episodio or oggi(),
        "luogo":         luogo.strip(),
        "priorita":      priorita,
        "stato":         "aperta",
        "risposta_operatore": "",
        "risposta_data": "",
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":          oggi(),
    })

    return templates.TemplateResponse("cittadini/segnalazione.html", {
        "request":      request,
        "cittadino":    cittadino,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      True,
        "errore":       None,
        "codice":       codice,
    })


# ── Affari Interni pubblico ───────────────────────────────────────────────────
@router.get("/cittadini/affari-interni", response_class=HTMLResponse)
async def ai_form(request: Request):
    cittadino = await _get_cittadino(request)
    return templates.TemplateResponse("cittadini/affari_interni.html", {
        "request":      request,
        "cittadino":    cittadino,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      False,
        "errore":       None,
    })


@router.post("/cittadini/affari-interni")
async def ai_invia(
    request:             Request,
    anonima:             str = Form("no"),
    segnalante_nome:     str = Form(""),
    segnalante_cf:       str = Form(""),
    segnalante_contatto: str = Form(""),
    agente_nome:         str = Form(...),
    agente_cf:           str = Form(""),
    data_episodio:       str = Form(""),
    luogo:               str = Form(""),
    titolo:              str = Form(...),
    descrizione:         str = Form(...),
    prove:               str = Form(""),
    priorita:            str = Form("normale"),
):
    from database import get_db
    db = get_db()

    if not agente_nome.strip() or not descrizione.strip() or not titolo.strip():
        cittadino = await _get_cittadino(request)
        return templates.TemplateResponse("cittadini/affari_interni.html", {
            "request":      request,
            "cittadino":    cittadino,
            "dipartimento": config.DIPARTIMENTO_NOME,
            "inviata":      False,
            "errore":       "Compila tutti i campi obbligatori.",
        })

    is_anonima = anonima == "si"
    codice = _gen_codice()

    # Se loggato e non anonima, usa dati profilo
    cittadino = await _get_cittadino(request)
    if cittadino and not is_anonima and not segnalante_nome:
        segnalante_nome = f"{cittadino.get('nome', '')} {cittadino.get('cognome', '')}".strip()
        segnalante_cf = cittadino.get("cf", "")

    await db["segnalazioni_ai"].insert_one({
        "id":                    codice,
        "titolo":                titolo.strip(),
        "descrizione":           descrizione.strip(),
        "prove":                 prove.strip(),
        "agente_nome":           agente_nome.strip(),
        "agente_cf":             agente_cf.strip().upper(),
        "data_episodio":         data_episodio or oggi(),
        "luogo":                 luogo.strip(),
        "priorita":              priorita,
        "anonima":               is_anonima,
        "segnalante_nome":       "" if is_anonima else segnalante_nome.strip(),
        "segnalante_cf":         "" if is_anonima else segnalante_cf.strip().upper(),
        "segnalante_contatto":   "" if is_anonima else segnalante_contatto.strip(),
        "stato":                 "aperta",
        "note_interne":          "",
        "assegnata_a":           "",
        "risposta_operatore":    "",
        "risposta_data":         "",
        "ultima_modifica":       "",
        "modificata_da":         "",
        "timestamp":             datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":                  oggi(),
        "fonte":                 "portale_pubblico",
    })

    return templates.TemplateResponse("cittadini/affari_interni.html", {
        "request":      request,
        "cittadino":    cittadino,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      True,
        "errore":       None,
        "anonima":      is_anonima,
        "codice":       codice if not is_anonima else None,
    })


# ── Stato segnalazione ────────────────────────────────────────────────────────
@router.get("/cittadini/stato-segnalazione", response_class=HTMLResponse)
async def stato_segnalazione(request: Request, codice: str = ""):
    from database import get_db
    db = get_db()
    cittadino = await _get_cittadino(request)
    segnalazione = None
    segnalazioni = []
    errore = None

    if codice:
        segnalazione = _ser(await db["segnalazioni_pubbliche"].find_one({"id": codice.upper()}))
        if not segnalazione:
            errore = f"Nessuna segnalazione trovata con codice {codice.upper()}"

    if cittadino and cittadino.get("cf"):
        segnalazioni = _ser_list(
            await db["segnalazioni_pubbliche"].find({"cf": cittadino["cf"]}).sort("timestamp", -1).to_list(50)
        )

    return templates.TemplateResponse("cittadini/stato_segnalazione.html", {
        "request":      request,
        "cittadino":    cittadino,
        "segnalazione": segnalazione,
        "segnalazioni": segnalazioni,
        "codice":       codice.upper() if codice else "",
        "errore":       errore,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── Accesso negato ────────────────────────────────────────────────────────────
@router.get("/cittadini/accesso-negato", response_class=HTMLResponse)
async def accesso_negato(request: Request, motivo: str = ""):
    return templates.TemplateResponse("cittadini/accesso_negato.html", {
        "request": request,
        "motivo":  motivo or "Accesso non autorizzato.",
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── Denuncia pubblica ─────────────────────────────────────────────────────────
@router.get("/cittadini/denuncia", response_class=HTMLResponse)
async def denuncia_form(request: Request):
    cittadino = await _get_cittadino(request)
    return templates.TemplateResponse("cittadini/denuncia.html", {
        "request":      request,
        "cittadino":    cittadino,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      False,
        "errore":       None,
        "codice":       None,
    })


@router.post("/cittadini/denuncia")
async def denuncia_invia(
    request:             Request,
    denunciante_nome:    str = Form(""),
    denunciante_cf:      str = Form(""),
    denunciante_contatto:str = Form(""),
    denunciato_nome:     str = Form(...),
    denunciato_cf:       str = Form(""),
    denunciato_desc:     str = Form(""),
    data_fatto:          str = Form(...),
    ora_fatto:           str = Form(""),
    luogo:               str = Form(...),
    capi_accusa:         str = Form(...),
    descrizione:         str = Form(...),
    testimoni:           str = Form(""),
    prove:               str = Form(""),
    danno:               str = Form(""),
    priorita:            str = Form("normale"),
):
    if not denunciato_nome.strip() or not descrizione.strip() or not capi_accusa.strip():
        cittadino = await _get_cittadino(request)
        return templates.TemplateResponse("cittadini/denuncia.html", {
            "request":      request,
            "cittadino":    cittadino,
            "dipartimento": config.DIPARTIMENTO_NOME,
            "inviata":      False,
            "errore":       "Compila tutti i campi obbligatori.",
            "codice":       None,
        })

    from database import get_db
    db = get_db()
    codice = _gen_codice()

    cittadino = await _get_cittadino(request)
    if cittadino and not denunciante_cf:
        denunciante_nome = f"{cittadino.get('nome','')} {cittadino.get('cognome','')}".strip() or cittadino.get("nick","")
        denunciante_cf   = cittadino.get("cf", "")

    await db["denunce"].insert_one({
        "id":                       codice,
        "denunciante_nome":         denunciante_nome.strip(),
        "denunciante_cf":           denunciante_cf.strip().upper(),
        "denunciante_discord_id":   cittadino["discord_id"] if cittadino else "",
        "denunciante_contatto":     denunciante_contatto.strip(),
        "denunciato_nome":     denunciato_nome.strip(),
        "denunciato_cf":       denunciato_cf.strip().upper(),
        "denunciato_desc":     denunciato_desc.strip(),
        "data_fatto":          data_fatto,
        "ora_fatto":           ora_fatto,
        "luogo":               luogo.strip(),
        "capi_accusa":         capi_accusa.strip(),
        "descrizione":         descrizione.strip(),
        "testimoni":           testimoni.strip(),
        "prove":               prove.strip(),
        "danno":               danno.strip(),
        "priorita":            priorita,
        "stato":               "aperta",
        "note_interne":        "",
        "risposta_agente":     "",
        "risposta_data":       "",
        "ultima_modifica":     "",
        "modificata_da":       "",
        "timestamp":           datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":                oggi(),
        "fonte":               "portale_pubblico",
    })

    # Se il denunciato ha un CF registrato, aggiorna la sua fedina
    if denunciato_cf:
        await db["cittadini"].update_one(
            {"cf": denunciato_cf.strip().upper()},
            {"$push": {"fedina": {
                "reato":     capi_accusa.strip(),
                "data":      data_fatto,
                "luogo":     luogo.strip(),
                "sanzione":  "",
                "note":      f"Denuncia #{codice}",
                "stato":     "in_corso",
            }}}
        )

    return templates.TemplateResponse("cittadini/denuncia.html", {
        "request":      request,
        "cittadino":    cittadino,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      True,
        "errore":       None,
        "codice":       codice,
    })


# ── Chat API ──────────────────────────────────────────────────────────────────
from fastapi import Body
from fastapi.responses import JSONResponse

@router.post("/cittadini/chat/{tipo}/{doc_id}")
async def chat_invia(
    request: Request,
    tipo:    str,
    doc_id:  str,
    payload: dict = Body(...),
):
    cittadino = await _get_cittadino(request)
    if not cittadino:
        from fastapi import HTTPException
        raise HTTPException(401)

    from database import get_db
    db = get_db()
    testo = payload.get("testo", "").strip()
    if not testo:
        raise HTTPException(400)

    from bson import ObjectId
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
    msg = {
        "da":           "cittadino",
        "discord_id":   cittadino["discord_id"],
        "nome_mittente":f"{cittadino.get('nome','')} {cittadino.get('cognome','')}".strip() or cittadino.get("nick",""),
        "testo":        testo,
        "timestamp":    timestamp,
        "letto":        False,
    }
    col = "denunce" if tipo == "denunce" else "segnalazioni_pubbliche"
    await db[col].update_one(
        {"_id": ObjectId(doc_id)},
        {"$push": {"messaggi": msg}}
    )
    return JSONResponse({"ok": True, "timestamp": timestamp})


@router.get("/cittadini/chat/{tipo}/{doc_id}/poll")
async def chat_poll(
    request: Request,
    tipo:    str,
    doc_id:  str,
):
    from database import get_db
    from bson import ObjectId
    db = get_db()
    col = "denunce" if tipo == "denunce" else "segnalazioni_pubbliche"
    doc = await db[col].find_one({"_id": ObjectId(doc_id)}, {"messaggi": 1})
    if not doc:
        return JSONResponse([])
    return JSONResponse(doc.get("messaggi", []))


@router.get("/cittadini/cerca-pratica")
async def cerca_pratica(codice: str = ""):
    from database import get_db
    db = get_db()
    codice = codice.strip().upper()

    # Cerca in denunce
    d = await db["denunce"].find_one({"id": codice})
    if d:
        return JSONResponse({"found": True, "tipo": "denuncia", "id": d["id"], "titolo": f"Denuncia contro {d.get('denunciato_nome','')}", "stato": d.get("stato",""), "data": d.get("data","")})

    # Cerca in segnalazioni
    s = await db["segnalazioni_pubbliche"].find_one({"id": codice})
    if s:
        return JSONResponse({"found": True, "tipo": "segnalazione", "id": s["id"], "titolo": s.get("titolo",""), "stato": s.get("stato",""), "data": s.get("data","")})

    return JSONResponse({"found": False})


# ── Pratiche cittadino (denunce + segnalazioni) ───────────────────────────────
@router.get("/cittadini/stato-segnalazione", response_class=HTMLResponse)
async def stato_segnalazione(request: Request, codice: str = ""):
    from database import get_db
    db = get_db()
    cittadino = await _get_cittadino(request)
    denunce = []
    segnalazioni = []

    if cittadino:
        discord_id = cittadino.get("discord_id", "")
        cf = cittadino.get("cf", "")

        # Cerca denunce per discord_id (salvato al momento della denuncia se loggato)
        # oppure per CF se disponibile
        filt_d = {"$or": []}
        if discord_id:
            filt_d["$or"].append({"denunciante_discord_id": discord_id})
        if cf:
            filt_d["$or"].append({"denunciante_cf": cf})
        if not filt_d["$or"]:
            filt_d = {}

        if filt_d:
            denunce = _ser_list(
                await db["denunce"].find(filt_d).sort("timestamp", -1).to_list(50)
            )

        # Cerca segnalazioni per CF o discord_id
        filt_s = {"$or": []}
        if discord_id:
            filt_s["$or"].append({"denunciante_discord_id": discord_id})
        if cf:
            filt_s["$or"].append({"cf": cf})
        if filt_s["$or"]:
            segnalazioni = _ser_list(
                await db["segnalazioni_pubbliche"].find(filt_s).sort("timestamp", -1).to_list(50)
            )

    return templates.TemplateResponse("cittadini/stato_segnalazione.html", {
        "request":      request,
        "cittadino":    cittadino,
        "denunce":      denunce,
        "segnalazioni": segnalazioni,
        "codice":       codice.upper() if codice else "",
        "dipartimento": config.DIPARTIMENTO_NOME,
        "cf_mancante":  cittadino and not cittadino.get("cf"),
    })
