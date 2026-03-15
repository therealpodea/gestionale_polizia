"""
Router denunce — gestione procedimenti penali.
Portale pubblico: /cittadini/denuncia  (in cittadini.py)
Gestionale:       /dashboard/denunce/* (tutti gli agenti vedono, dirigenza/ispettorato gestisce)
"""
from __future__ import annotations
from datetime import datetime
import random, string

from bson import ObjectId
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import get_current_user_live
from routers.settings_helper import get_settings

router    = APIRouter(prefix="/dashboard/denunce", tags=["denunce"])
templates = Jinja2Templates(directory="templates")

LOGO = "https://i.ibb.co/1GnGhNGr/logo-polizia-d-estovia-removebg-preview-1.png"


def _ser(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def _ser_list(docs):
    return [_ser(dict(d)) for d in docs]

def oggi():
    return datetime.now().strftime("%Y-%m-%d")


@router.get("", response_class=HTMLResponse)
async def denunce_list(
    request:  Request,
    stato:    str = "",
    priorita: str = "",
    q:        str = "",
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()

    filt: dict = {}
    if stato:
        filt["stato"] = stato
    if priorita:
        filt["priorita"] = priorita
    if q:
        filt["$or"] = [
            {"denunciato_nome": {"$regex": q, "$options": "i"}},
            {"denunciato_cf":   {"$regex": q, "$options": "i"}},
            {"capi_accusa":     {"$regex": q, "$options": "i"}},
            {"denunciante_nome":{"$regex": q, "$options": "i"}},
        ]

    denunce = _ser_list(await db["denunce"].find(filt).sort("timestamp", -1).to_list(500))

    counts = {
        "n_totale":    await db["denunce"].count_documents({}),
        "n_aperte":    await db["denunce"].count_documents({"stato": "aperta"}),
        "n_analisi":   await db["denunce"].count_documents({"stato": "in_analisi"}),
        "n_info":      await db["denunce"].count_documents({"stato": "info_richieste"}),
        "n_risolte":   await db["denunce"].count_documents({"stato": "risolta"}),
        "n_archiviate":await db["denunce"].count_documents({"stato": "archiviata"}),
    }

    return templates.TemplateResponse("denunce.html", {
        "request":  request,
        "settings": await get_settings(),
        "user":     user,
        "denunce":  denunce,
        "stato":    stato,
        "priorita": priorita,
        "q":        q,
        **counts,
    })


@router.get("/{denuncia_id}", response_class=HTMLResponse)
async def denuncia_dettaglio(
    request:     Request,
    denuncia_id: str,
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    d = _ser(await db["denunce"].find_one({"_id": ObjectId(denuncia_id)}))
    if not d:
        raise HTTPException(404, "Denuncia non trovata.")
    return templates.TemplateResponse("denuncia_dettaglio.html", {
        "request":  request,
        "settings": await get_settings(),
        "user":     user,
        "d":        d,
    })


@router.post("/stato")
async def aggiorna_stato(
    denuncia_id:  str = Form(...),
    stato:        str = Form(...),
    note_interne: str = Form(""),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 10:
        raise HTTPException(403)
    from database import get_db
    db = get_db()
    update = {
        "stato":           stato,
        "ultima_modifica": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "modificata_da":   user.get("nick") or user.get("username"),
    }
    if note_interne:
        update["note_interne"] = note_interne
    await db["denunce"].update_one({"_id": ObjectId(denuncia_id)}, {"$set": update})
    return RedirectResponse(f"/dashboard/denunce/{denuncia_id}", status_code=303)


@router.post("/risposta")
async def invia_risposta(
    denuncia_id: str = Form(...),
    risposta:    str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 10:
        raise HTTPException(403)
    from database import get_db
    db = get_db()
    await db["denunce"].update_one(
        {"_id": ObjectId(denuncia_id)},
        {"$set": {
            "risposta_agente": risposta.strip(),
            "risposta_data":   datetime.now().strftime("%Y-%m-%d %H:%M"),
            "modificata_da":   user.get("nick") or user.get("username"),
            "ultima_modifica": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }}
    )
    return RedirectResponse(f"/dashboard/denunce/{denuncia_id}", status_code=303)


@router.post("/elimina")
async def elimina_denuncia(
    denuncia_id: str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 100:
        raise HTTPException(403)
    from database import get_db
    db = get_db()
    await db["denunce"].delete_one({"_id": ObjectId(denuncia_id)})
    return RedirectResponse("/dashboard/denunce", status_code=303)
