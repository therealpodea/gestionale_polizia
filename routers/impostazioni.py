"""
Router impostazioni — solo Dirigenza (permission >= 100).
Gestisce logo, favicon, info dipartimento.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import config
from auth import get_current_user_live, require_permission

router    = APIRouter(prefix="/dashboard/impostazioni", tags=["impostazioni"])
templates = Jinja2Templates(directory="templates")


async def _get_settings():
    from routers.settings_helper import get_settings
    return await get_settings()


@router.get("", response_class=HTMLResponse)
async def impostazioni_page(
    request: Request,
    msg: str = "",
    msg_type: str = "ok",
    user: dict = Depends(require_permission(100)),
):
    settings = await _get_settings()
    return templates.TemplateResponse("impostazioni.html", {
        "request":    request,
        "user":       user,
        "settings":   settings,
        "config_nome": config.DIPARTIMENTO_NOME,
        "msg":        msg,
        "msg_type":   msg_type,
    })


@router.post("/logo")
async def salva_logo(
    logo_url:    str = Form(""),
    favicon_url: str = Form(""),
    user: dict = Depends(require_permission(100)),
):
    from database import get_db
    from routers.settings_helper import invalidate_cache
    db = get_db()
    await db["impostazioni"].update_one(
        {"_id": "global"},
        {"$set": {
            "logo_url":    logo_url.strip(),
            "favicon_url": favicon_url.strip(),
        }},
        upsert=True,
    )
    invalidate_cache()
    return RedirectResponse("/dashboard/impostazioni?msg=Logo+aggiornato+con+successo&msg_type=ok", status_code=303)


@router.post("/info")
async def salva_info(
    nome:            str = Form(""),
    motto:           str = Form(""),
    colore_primario: str = Form(""),
    discord_invite:  str = Form(""),
    user: dict = Depends(require_permission(100)),
):
    from database import get_db
    from routers.settings_helper import invalidate_cache
    db = get_db()
    await db["impostazioni"].update_one(
        {"_id": "global"},
        {"$set": {
            "nome":            nome.strip(),
            "motto":           motto.strip(),
            "colore_primario": colore_primario.strip(),
            "discord_invite":  discord_invite.strip(),
        }},
        upsert=True,
    )
    invalidate_cache()
    return RedirectResponse("/dashboard/impostazioni?msg=Informazioni+aggiornate&msg_type=ok", status_code=303)
