"""
Affari Interni — segnalazioni riservate.
Portale pubblico: /ai/*           (nessun login)
Gestionale:       /dashboard/ai/* (solo ruoli AI permission>=75 + dirigenza 100)
"""
from __future__ import annotations
from datetime import datetime
import random, string

from bson import ObjectId
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import config
from auth import get_current_user_live

router    = APIRouter(tags=["affari_interni"])
templates = Jinja2Templates(directory="templates")


# ── Helpers ────────────────────────────────────────────────────────────────────
def uid() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S") + "".join(random.choices(string.ascii_lowercase, k=4))

def oggi() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def _ser(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def _ser_list(docs):
    return [_ser(dict(d)) for d in docs]

def _check_ai(user: dict):
    """Solleva 403 se l'utente non è AI né dirigenza 100."""
    if not user.get("is_ai") and user.get("permission", 0) < 100:
        raise HTTPException(403, "Accesso riservato agli Affari Interni.")


# ══════════════════════════════════════════════════════════════════════════════
# PORTALE PUBBLICO — nessun login richiesto
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/ai", response_class=HTMLResponse)
async def ai_home(request: Request):
    return templates.TemplateResponse("ai/home.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.get("/ai/segnala", response_class=HTMLResponse)
async def ai_segnala_form(request: Request):
    return templates.TemplateResponse("ai/segnala.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      False,
        "errore":       None,
    })


@router.post("/ai/segnala")
async def ai_segnala_invia(
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
    if not titolo.strip() or not descrizione.strip() or not agente_nome.strip():
        return templates.TemplateResponse("ai/segnala.html", {
            "request":      request,
            "dipartimento": config.DIPARTIMENTO_NOME,
            "inviata":      False,
            "errore":       "Compila tutti i campi obbligatori: titolo, agente segnalato, descrizione.",
        })

    from database import get_db
    db = get_db()

    is_anon = anonima == "si"
    await db["segnalazioni_ai"].insert_one({
        "id":                uid(),
        "titolo":            titolo.strip(),
        "descrizione":       descrizione.strip(),
        "prove":             prove.strip(),
        "agente_nome":       agente_nome.strip(),
        "agente_cf":         agente_cf.strip(),
        "data_episodio":     data_episodio,
        "luogo":             luogo.strip(),
        "priorita":          priorita,
        "anonima":           is_anon,
        "segnalante_nome":   "" if is_anon else segnalante_nome.strip(),
        "segnalante_cf":     "" if is_anon else segnalante_cf.strip(),
        "segnalante_contatto": "" if is_anon else segnalante_contatto.strip(),
        "stato":             "aperta",
        "note_interne":      "",
        "assegnata_a":       "",
        "ultima_modifica":   "",
        "modificata_da":     "",
        "timestamp":         datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":              oggi(),
        "fonte":             "portale_pubblico",
    })

    return templates.TemplateResponse("ai/segnala.html", {
        "request":      request,
        "dipartimento": config.DIPARTIMENTO_NOME,
        "inviata":      True,
        "errore":       None,
        "anonima":      is_anon,
    })


# ══════════════════════════════════════════════════════════════════════════════
# GESTIONALE INTERNO — ruoli AI (permission>=75) + dirigenza (100)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard/ai", response_class=HTMLResponse)
async def ai_dashboard(
    request: Request,
    stato:   str = "",
    q:       str = "",
    user: dict = Depends(get_current_user_live),
):
    _check_ai(user)
    from database import get_db
    db = get_db()

    filt: dict = {}
    if stato:
        filt["stato"] = stato
    if q:
        filt["$or"] = [
            {"titolo":     {"$regex": q, "$options": "i"}},
            {"agente_nome":{"$regex": q, "$options": "i"}},
            {"agente_cf":  {"$regex": q, "$options": "i"}},
        ]

    segnalazioni = _ser_list(
        await db["segnalazioni_ai"].find(filt).sort("timestamp", -1).to_list(500)
    )
    n_aperte  = await db["segnalazioni_ai"].count_documents({"stato": "aperta"})
    n_corso   = await db["segnalazioni_ai"].count_documents({"stato": "in_corso"})
    n_chiuse  = await db["segnalazioni_ai"].count_documents({"stato": "chiusa"})
    n_arch    = await db["segnalazioni_ai"].count_documents({"stato": "archiviata"})

    return templates.TemplateResponse("ai/dashboard.html", {
        "request":      request,
        "user":         user,
        "segnalazioni": segnalazioni,
        "n_aperte":     n_aperte,
        "n_corso":      n_corso,
        "n_chiuse":     n_chiuse,
        "n_archivio":   n_arch,
        "stato":        stato,
        "q":            q,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.get("/dashboard/ai/{seg_id}", response_class=HTMLResponse)
async def ai_dettaglio(
    request: Request,
    seg_id:  str,
    user: dict = Depends(get_current_user_live),
):
    _check_ai(user)
    from database import get_db
    db = get_db()
    seg = _ser(await db["segnalazioni_ai"].find_one({"_id": ObjectId(seg_id)}))
    if not seg:
        raise HTTPException(404, "Segnalazione non trovata.")
    return templates.TemplateResponse("ai/dettaglio.html", {
        "request":      request,
        "user":         user,
        "seg":          seg,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.post("/dashboard/ai/stato")
async def ai_stato(
    seg_id:       str = Form(...),
    stato:        str = Form(...),
    note_interne: str = Form(""),
    assegnata_a:  str = Form(""),
    user: dict = Depends(get_current_user_live),
):
    _check_ai(user)
    from database import get_db
    db = get_db()
    update: dict = {
        "stato":          stato,
        "ultima_modifica": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "modificata_da":  user.get("nick") or user.get("username"),
    }
    if note_interne:
        update["note_interne"] = note_interne
    if assegnata_a:
        update["assegnata_a"] = assegnata_a
    await db["segnalazioni_ai"].update_one({"_id": ObjectId(seg_id)}, {"$set": update})
    return RedirectResponse(f"/dashboard/ai/{seg_id}", status_code=303)


@router.post("/dashboard/ai/elimina")
async def ai_elimina(
    seg_id: str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    # Solo dirigenza 100 può eliminare definitivamente
    if user.get("permission", 0) < 100:
        raise HTTPException(403, "Solo la Dirigenza può eliminare segnalazioni AI.")
    from database import get_db
    db = get_db()
    await db["segnalazioni_ai"].delete_one({"_id": ObjectId(seg_id)})
    return RedirectResponse("/dashboard/ai", status_code=303)
