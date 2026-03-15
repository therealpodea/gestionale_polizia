"""
Portale pubblico per i cittadini.
Registrazione, fedina penale, segnalazioni, stato segnalazioni.
"""
from __future__ import annotations
from datetime import datetime
import re
import hashlib
import random
import string

from bson import ObjectId
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import config

router    = APIRouter(tags=["cittadini"])
templates = Jinja2Templates(directory="templates")

COOKIE_CITTADINO = "cittadino_session"


def uid():
    return datetime.now().strftime("%Y%m%d%H%M%S") + "".join(random.choices(string.ascii_lowercase, k=4))

def oggi():
    return datetime.now().strftime("%Y-%m-%d")

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _ser(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def _ser_list(docs):
    return [_ser(dict(d)) for d in docs]

def _gen_codice() -> str:
    """Genera codice univoco per segnalazione."""
    return "SEG-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

async def _get_cittadino(request: Request):
    """Legge il cittadino dalla sessione cookie."""
    cf = request.cookies.get(COOKIE_CITTADINO)
    if not cf:
        return None
    from database import get_db
    db = get_db()
    return _ser(await db["cittadini"].find_one({"cf": cf}))


# ── Home pubblica ─────────────────────────────────────────────────────────────
@router.get("/cittadini", response_class=HTMLResponse)
async def cittadini_home(request: Request):
    return templates.TemplateResponse("cittadini/home.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── Accedi / Registrati ───────────────────────────────────────────────────────
@router.get("/cittadini/accedi", response_class=HTMLResponse)
async def accedi_form(request: Request, tab: str = "login"):
    cittadino = await _get_cittadino(request)
    if cittadino:
        return RedirectResponse("/cittadini/fedina")
    return templates.TemplateResponse("cittadini/accedi.html", {
        "request": request,
        "tab":     tab,
        "errore":  None,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.post("/cittadini/accedi")
async def accedi_post(
    request:  Request,
    azione:   str = Form("login"),
    cf:       str = Form(""),
    password: str = Form(""),
    password2:str = Form(""),
    nome:     str = Form(""),
    cognome:  str = Form(""),
    data_nascita: str = Form(""),
    contatto: str = Form(""),
):
    from database import get_db
    db = get_db()
    cf = cf.strip().upper()

    if azione == "login":
        cittadino = await db["cittadini"].find_one({"cf": cf})
        if not cittadino or cittadino.get("password") != hash_pw(password):
            return templates.TemplateResponse("cittadini/accedi.html", {
                "request": request,
                "tab":     "login",
                "errore":  "Codice Fiscale o password errati.",
                "dipartimento": config.DIPARTIMENTO_NOME,
            })
        resp = RedirectResponse("/cittadini/fedina", status_code=303)
        resp.set_cookie(COOKIE_CITTADINO, cf, httponly=True, samesite="lax", max_age=86400*7)
        return resp

    else:  # register
        if not cf or not nome.strip() or not cognome.strip() or not password:
            return templates.TemplateResponse("cittadini/accedi.html", {
                "request": request,
                "tab":     "register",
                "errore":  "Compila tutti i campi obbligatori.",
                "dipartimento": config.DIPARTIMENTO_NOME,
            })
        if password != password2:
            return templates.TemplateResponse("cittadini/accedi.html", {
                "request": request,
                "tab":     "register",
                "errore":  "Le password non coincidono.",
                "dipartimento": config.DIPARTIMENTO_NOME,
            })
        existing = await db["cittadini"].find_one({"cf": cf})
        if existing:
            return templates.TemplateResponse("cittadini/accedi.html", {
                "request": request,
                "tab":     "register",
                "errore":  "Esiste già un account con questo Codice Fiscale.",
                "dipartimento": config.DIPARTIMENTO_NOME,
            })
        await db["cittadini"].insert_one({
            "cf":                 cf,
            "nome":               nome.strip(),
            "cognome":            cognome.strip(),
            "data_nascita":       data_nascita,
            "contatto":           contatto.strip(),
            "password":           hash_pw(password),
            "fedina":             [],
            "data_registrazione": oggi(),
            "timestamp":          datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        resp = RedirectResponse("/cittadini/fedina", status_code=303)
        resp.set_cookie(COOKIE_CITTADINO, cf, httponly=True, samesite="lax", max_age=86400*7)
        return resp


@router.get("/cittadini/logout")
async def cittadini_logout():
    resp = RedirectResponse("/cittadini")
    resp.delete_cookie(COOKIE_CITTADINO)
    return resp


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
            await db["segnalazioni_pubbliche"].find({"cf": cittadino["cf"]}).sort("timestamp", -1).to_list(50)
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
    contatto:      str = Form(""),
    titolo:        str = Form(...),
    corpo:         str = Form(...),
    tipo:          str = Form("generale"),
    data_episodio: str = Form(""),
    luogo:         str = Form(""),
    priorita:      str = Form("normale"),
):
    if not nome.strip() or not titolo.strip() or not corpo.strip():
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

    await db["segnalazioni_pubbliche"].insert_one({
        "id":            codice,
        "nome":          nome.strip(),
        "cf":            cf.strip().upper(),
        "contatto":      contatto.strip(),
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

    cittadino = await _get_cittadino(request)
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

    cittadino = await _get_cittadino(request)
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

    if cittadino:
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


# ── Cerca agente (pubblico) ───────────────────────────────────────────────────
@router.get("/cittadini/cerca", response_class=HTMLResponse)
async def cittadini_cerca(request: Request, q: str = ""):
    from database import get_db
    db = get_db()
    agenti = []
    if q:
        agenti = _ser_list(await db["agenti"].find({
            "approvato": True,
            "$or": [
                {"nome":    {"$regex": q, "$options": "i"}},
                {"cognome": {"$regex": q, "$options": "i"}},
                {"cf":      {"$regex": q, "$options": "i"}},
                {"nick":    {"$regex": q, "$options": "i"}},
            ]
        }).to_list(20))
    return templates.TemplateResponse("cittadini/cerca.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "q":            q,
        "agenti":       agenti,
    })


# ── Pagine statiche ───────────────────────────────────────────────────────────
@router.get("/cittadini/norme", response_class=HTMLResponse)
async def cittadini_norme(request: Request):
    return templates.TemplateResponse("cittadini/norme.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })
