"""
Portale pubblico per i cittadini — Segnalazioni Affari Interni.
Accessibile senza login.
"""
from __future__ import annotations
from datetime import datetime
import re

from bson import ObjectId
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import config

router    = APIRouter(tags=["cittadini"])
templates = Jinja2Templates(directory="templates")


def uid():
    import random, string
    return datetime.now().strftime("%Y%m%d%H%M%S") + "".join(random.choices(string.ascii_lowercase, k=4))

def oggi():
    return datetime.now().strftime("%Y-%m-%d")

def _ser(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def _ser_list(docs):
    return [_ser(dict(d)) for d in docs]


# ── Home pubblica ─────────────────────────────────────────────────────────────
@router.get("/cittadini", response_class=HTMLResponse)
async def cittadini_home(request: Request):
    return templates.TemplateResponse("cittadini/home.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── Segnalazione Affari Interni ───────────────────────────────────────────────
@router.get("/cittadini/affari-interni", response_class=HTMLResponse)
async def ai_form(request: Request):
    return templates.TemplateResponse("cittadini/affari_interni.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      False,
        "errore":       None,
    })


@router.post("/cittadini/affari-interni")
async def ai_invia(
    request:         Request,
    # Dati segnalante (opzionali se anonima)
    anonima:         str = Form("no"),
    segnalante_nome: str = Form(""),
    segnalante_cf:   str = Form(""),
    segnalante_contatto: str = Form(""),
    # Dati agente segnalato
    agente_nome:     str = Form(...),
    agente_cf:       str = Form(""),
    # Episodio
    data_episodio:   str = Form(""),
    luogo:           str = Form(...),
    descrizione:     str = Form(...),
    prove:           str = Form(""),
    priorita:        str = Form("normale"),
):
    from database import get_db
    db = get_db()

    # Validazione minima
    if not agente_nome.strip() or not luogo.strip() or not descrizione.strip():
        return templates.TemplateResponse("cittadini/affari_interni.html", {
            "request":      request,
            "dipartimento": config.DIPARTIMENTO_NOME,
            "inviata":      False,
            "errore":       "Compila i campi obbligatori: agente segnalato, luogo e descrizione.",
        })

    is_anonima = anonima == "si"

    doc = {
        "id":            uid(),
        "anonima":       is_anonima,
        # Segnalante
        "segnalante_nome":     "" if is_anonima else segnalante_nome.strip(),
        "segnalante_cf":       "" if is_anonima else segnalante_cf.strip(),
        "segnalante_contatto": "" if is_anonima else segnalante_contatto.strip(),
        # Agente segnalato
        "agente_nome":   agente_nome.strip(),
        "agente_cf":     agente_cf.strip(),
        # Episodio
        "data_episodio": data_episodio or oggi(),
        "luogo":         luogo.strip(),
        "descrizione":   descrizione.strip(),
        "prove":         prove.strip(),
        "priorita":      priorita,
        # Gestione
        "stato":         "aperta",
        "note_interne":  "",
        "aggiornata_da": "",
        "aggiornata_il": "",
        # Meta
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":          oggi(),
        "fonte":         "portale_pubblico",
    }
    await db["segnalazioni_ai"].insert_one(doc)

    return templates.TemplateResponse("cittadini/affari_interni.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      True,
        "errore":       None,
        "anonima":      is_anonima,
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


# ── Segnalazione pubblica generica ───────────────────────────────────────────
@router.get("/cittadini/segnalazione", response_class=HTMLResponse)
async def cittadini_segnalazione_form(request: Request):
    return templates.TemplateResponse("cittadini/segnalazione.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      False,
        "errore":       None,
    })


@router.post("/cittadini/segnalazione")
async def cittadini_segnalazione_invia(
    request:  Request,
    nome:     str = Form(...),
    cf:       str = Form(""),
    titolo:   str = Form(...),
    corpo:    str = Form(...),
    priorita: str = Form("normale"),
):
    if not nome.strip() or not titolo.strip() or not corpo.strip():
        return templates.TemplateResponse("cittadini/segnalazione.html", {
            "request":      request,
            "dipartimento": config.DIPARTIMENTO_NOME,
            "inviata":      False,
            "errore":       "Compila tutti i campi obbligatori.",
        })
    from database import get_db
    db = get_db()
    await db["segnalazioni_pubbliche"].insert_one({
        "id":        uid(),
        "nome":      nome.strip(),
        "cf":        cf.strip(),
        "titolo":    titolo.strip(),
        "corpo":     corpo.strip(),
        "priorita":  priorita,
        "stato":     "aperta",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":      oggi(),
    })
    return templates.TemplateResponse("cittadini/segnalazione.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      True,
        "errore":       None,
    })


# ── Pagine statiche ───────────────────────────────────────────────────────────
@router.get("/cittadini/norme", response_class=HTMLResponse)
async def cittadini_norme(request: Request):
    return templates.TemplateResponse("cittadini/norme.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.get("/cittadini/contatti", response_class=HTMLResponse)
async def cittadini_contatti(request: Request):
    return templates.TemplateResponse("cittadini/contatti.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })
