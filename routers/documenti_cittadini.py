"""
Router documenti cittadini — registro anagrafico del portale pubblico.
Visibile a tutti gli agenti, modifica fedina solo permission>=50.
"""
from __future__ import annotations
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import get_current_user_live
from routers.settings_helper import get_settings

router    = APIRouter(prefix="/dashboard/documenti-cittadini", tags=["documenti_cittadini"])
templates = Jinja2Templates(directory="templates")


def _ser(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def _ser_list(docs):
    return [_ser(dict(d)) for d in docs]

def oggi():
    return datetime.now().strftime("%Y-%m-%d")


@router.get("", response_class=HTMLResponse)
async def lista_cittadini(
    request: Request,
    q:       str = "",
    filtro:  str = "",
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()

    filt: dict = {}
    if q:
        filt["$or"] = [
            {"nome":     {"$regex": q, "$options": "i"}},
            {"cognome":  {"$regex": q, "$options": "i"}},
            {"cf":       {"$regex": q, "$options": "i"}},
            {"username": {"$regex": q, "$options": "i"}},
            {"nick":     {"$regex": q, "$options": "i"}},
        ]
    if filtro == "con_fedina":
        filt["fedina.0"] = {"$exists": True}
    elif filtro == "senza_fedina":
        filt["$or"] = filt.get("$or", []) + [{"fedina": {"$size": 0}}, {"fedina": {"$exists": False}}]
    elif filtro == "con_denunce":
        # Cittadini con almeno una denuncia a carico
        cfs_con_denunce = await db["denunce"].distinct("denunciato_cf", {"denunciato_cf": {"$ne": ""}})
        filt["cf"] = {"$in": cfs_con_denunce}

    cittadini = _ser_list(
        await db["cittadini"].find(filt).sort("data_registrazione", -1).to_list(500)
    )

    return templates.TemplateResponse("documenti_cittadini.html", {
        "request":   request,
        "settings":  await get_settings(),
        "user":      user,
        "cittadini": cittadini,
        "q":         q,
        "filtro":    filtro,
    })


@router.get("/{cit_id}", response_class=HTMLResponse)
async def scheda_cittadino(
    request: Request,
    cit_id:  str,
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    c = _ser(await db["cittadini"].find_one({"_id": ObjectId(cit_id)}))
    if not c:
        raise HTTPException(404, "Cittadino non trovato.")

    # Denunce a carico per CF
    denunce = []
    if c.get("cf"):
        denunce = _ser_list(
            await db["denunce"].find({"denunciato_cf": c["cf"]}).sort("timestamp", -1).to_list(50)
        )

    return templates.TemplateResponse("scheda_cittadino.html", {
        "request":  request,
        "settings": await get_settings(),
        "user":     user,
        "c":        c,
        "denunce":  denunce,
    })


@router.post("/{cit_id}/fedina/add")
async def fedina_add(
    cit_id:   str,
    reato:    str = Form(...),
    data:     str = Form(""),
    stato:    str = Form("definitivo"),
    sanzione: str = Form(""),
    note:     str = Form(""),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 50:
        raise HTTPException(403)
    from database import get_db
    db = get_db()
    await db["cittadini"].update_one(
        {"_id": ObjectId(cit_id)},
        {"$push": {"fedina": {
            "reato":     reato.strip(),
            "data":      data or oggi(),
            "luogo":     "",
            "sanzione":  sanzione.strip(),
            "note":      note.strip(),
            "stato":     stato,
            "aggiunto_da": user.get("nick") or user.get("username"),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }}}
    )
    return RedirectResponse(f"/dashboard/documenti-cittadini/{cit_id}", status_code=303)


@router.post("/{cit_id}/fedina/elimina")
async def fedina_elimina(
    cit_id: str,
    idx:    int = Form(...),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 50:
        raise HTTPException(403)
    from database import get_db
    db = get_db()
    c = await db["cittadini"].find_one({"_id": ObjectId(cit_id)})
    if not c:
        raise HTTPException(404)
    fedina = c.get("fedina", [])
    if 0 <= idx < len(fedina):
        fedina.pop(idx)
        await db["cittadini"].update_one({"_id": ObjectId(cit_id)}, {"$set": {"fedina": fedina}})
    return RedirectResponse(f"/dashboard/documenti-cittadini/{cit_id}", status_code=303)


@router.post("/{cit_id}/note")
async def salva_note(
    cit_id:       str,
    note_interne: str = Form(""),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 50:
        raise HTTPException(403)
    from database import get_db
    db = get_db()
    await db["cittadini"].update_one(
        {"_id": ObjectId(cit_id)},
        {"$set": {"note_interne": note_interne.strip()}}
    )
    return RedirectResponse(f"/dashboard/documenti-cittadini/{cit_id}", status_code=303)


@router.post("/{cit_id}/elimina")
async def elimina_cittadino(
    cit_id: str,
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 100:
        raise HTTPException(403)
    from database import get_db
    db = get_db()
    await db["cittadini"].delete_one({"_id": ObjectId(cit_id)})
    return RedirectResponse("/dashboard/documenti-cittadini", status_code=303)
