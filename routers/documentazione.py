"""
Router documentazione — biblioteca normativa del dipartimento.
Tutti possono vedere, solo Dirigenza (permission>=100) può aggiungere/eliminare.
"""
from __future__ import annotations
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import get_current_user_live
from routers.settings_helper import get_settings

router    = APIRouter(prefix="/dashboard/documentazione", tags=["documentazione"])
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
async def documentazione(
    request:   Request,
    q:         str = "",
    categoria: str = "",
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()

    filt: dict = {}
    if categoria:
        filt["categoria"] = categoria
    if q:
        filt["$or"] = [
            {"titolo":      {"$regex": q, "$options": "i"}},
            {"descrizione": {"$regex": q, "$options": "i"}},
        ]

    documenti = _ser_list(
        await db["documenti"].find(filt).sort("categoria", 1).to_list(500)
    )

    return templates.TemplateResponse("documentazione.html", {
        "request":    request,
        "settings":   await get_settings(),
        "user":       user,
        "documenti":  documenti,
        "q":          q,
        "categoria":  categoria,
    })


@router.post("/add")
async def add_documento(
    titolo:      str = Form(...),
    categoria:   str = Form(...),
    url:         str = Form(...),
    versione:    str = Form(""),
    descrizione: str = Form(""),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 100:
        from fastapi import HTTPException
        raise HTTPException(403, "Solo la Dirigenza può aggiungere documenti.")

    from database import get_db
    db = get_db()
    await db["documenti"].insert_one({
        "titolo":      titolo.strip(),
        "categoria":   categoria,
        "url":         url.strip(),
        "versione":    versione.strip(),
        "descrizione": descrizione.strip(),
        "aggiunto_da": user.get("nick") or user.get("username"),
        "data":        oggi(),
        "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    return RedirectResponse("/dashboard/documentazione", status_code=303)


@router.post("/elimina")
async def elimina_documento(
    doc_id: str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    if user.get("permission", 0) < 100:
        from fastapi import HTTPException
        raise HTTPException(403)

    from database import get_db
    db = get_db()
    await db["documenti"].delete_one({"_id": ObjectId(doc_id)})
    return RedirectResponse("/dashboard/documentazione", status_code=303)
