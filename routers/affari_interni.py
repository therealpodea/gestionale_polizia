"""
Affari Interni — segnalazioni riservate.
Portale pubblico: /cittadini/affari-interni  (in cittadini.py)
Gestionale:       /dashboard/ai/*            (solo ruoli AI permission>=75 + dirigenza 100)
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
from routers.settings_helper import get_settings

router    = APIRouter(tags=["affari_interni"])
templates = Jinja2Templates(directory="templates")


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
    if not user.get("is_ai") and user.get("permission", 0) < 100:
        raise HTTPException(403, "Accesso riservato agli Affari Interni.")


# ══════════════════════════════════════════════════════════════════════════════
# GESTIONALE INTERNO
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard/ai", response_class=HTMLResponse)
async def ai_dashboard(
    request:  Request,
    stato:    str = "",
    priorita: str = "",
    q:        str = "",
    user: dict = Depends(get_current_user_live),
):
    _check_ai(user)
    from database import get_db
    db = get_db()

    filt: dict = {}
    if stato:
        filt["stato"] = stato
    if priorita:
        filt["priorita"] = priorita
    if q:
        filt["$or"] = [
            {"titolo":      {"$regex": q, "$options": "i"}},
            {"agente_nome": {"$regex": q, "$options": "i"}},
            {"agente_cf":   {"$regex": q, "$options": "i"}},
            {"descrizione": {"$regex": q, "$options": "i"}},
        ]

    segnalazioni = _ser_list(
        await db["segnalazioni_ai"].find(filt).sort("timestamp", -1).to_list(500)
    )
    n_aperte  = await db["segnalazioni_ai"].count_documents({"stato": "aperta"})
    n_corso   = await db["segnalazioni_ai"].count_documents({"stato": "in_corso"})
    n_chiuse  = await db["segnalazioni_ai"].count_documents({"stato": "chiusa"})
    n_arch    = await db["segnalazioni_ai"].count_documents({"stato": "archiviata"})

    return templates.TemplateResponse("ai/dashboard.html", {
        "settings":   await get_settings(),
        "request":      request,
        "user":         user,
        "segnalazioni": segnalazioni,
        "n_aperte":     n_aperte,
        "n_corso":      n_corso,
        "n_chiuse":     n_chiuse,
        "n_archivio":   n_arch,
        "stato":        stato,
        "priorita":     priorita,
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
        "settings":   await get_settings(),
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
        "stato":           stato,
        "ultima_modifica": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "modificata_da":   user.get("nick") or user.get("username"),
    }
    if note_interne:
        update["note_interne"] = note_interne
    if assegnata_a:
        update["assegnata_a"] = assegnata_a
    await db["segnalazioni_ai"].update_one({"_id": ObjectId(seg_id)}, {"$set": update})
    return RedirectResponse(f"/dashboard/ai/{seg_id}", status_code=303)


@router.post("/dashboard/ai/risposta")
async def ai_risposta(
    seg_id:   str = Form(...),
    risposta: str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    _check_ai(user)
    from database import get_db
    db = get_db()
    await db["segnalazioni_ai"].update_one(
        {"_id": ObjectId(seg_id)},
        {"$set": {
            "risposta_operatore": risposta.strip(),
            "risposta_data":      datetime.now().strftime("%Y-%m-%d %H:%M"),
            "modificata_da":      user.get("nick") or user.get("username"),
            "ultima_modifica":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        }}
    )
    return RedirectResponse(f"/dashboard/ai/{seg_id}", status_code=303)


@router.post("/dashboard/ai/elimina")
async def ai_elimina(
    seg_id: str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 100:
        raise HTTPException(403, "Solo la Dirigenza può eliminare segnalazioni AI.")
    from database import get_db
    db = get_db()
    await db["segnalazioni_ai"].delete_one({"_id": ObjectId(seg_id)})
    return RedirectResponse("/dashboard/ai", status_code=303)


# ── Vecchie route gestionale (compatibilità con segnalazioni_ai.html) ─────────
@router.get("/dashboard/affari-interni", response_class=HTMLResponse)
async def ai_dashboard_old(request: Request, user: dict = Depends(get_current_user_live)):
    return RedirectResponse("/dashboard/ai")

@router.post("/dashboard/affari-interni/stato")
async def ai_stato_old(
    segnalazione_id: str = Form(...),
    stato:           str = Form(...),
    note_interne:    str = Form(""),
    user: dict = Depends(get_current_user_live),
):
    _check_ai(user)
    from database import get_db
    db = get_db()
    update = {
        "stato":           stato,
        "ultima_modifica": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "modificata_da":   user.get("nick") or user.get("username"),
    }
    if note_interne:
        update["note_interne"] = note_interne
        update["aggiornata_da"] = user.get("nick") or user.get("username")
        update["aggiornata_il"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    await db["segnalazioni_ai"].update_one({"_id": ObjectId(segnalazione_id)}, {"$set": update})
    return RedirectResponse("/dashboard/ai", status_code=303)

@router.post("/dashboard/affari-interni/elimina")
async def ai_elimina_old(
    segnalazione_id: str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 100:
        raise HTTPException(403)
    from database import get_db
    db = get_db()
    await db["segnalazioni_ai"].delete_one({"_id": ObjectId(segnalazione_id)})
    return RedirectResponse("/dashboard/ai", status_code=303)
