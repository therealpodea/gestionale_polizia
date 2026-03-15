"""API esterna + badge counts per la sidebar."""
from fastapi import APIRouter, Header, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from datetime import datetime

import config
from auth import get_current_user_live

router = APIRouter(prefix="/api", tags=["api"])


def _check_key(api_key: str):
    if not config.API_KEY or api_key != config.API_KEY:
        raise HTTPException(status_code=403, detail="API key non valida.")


def _ser_list(docs):
    out = []
    for d in docs:
        d = dict(d)
        if "_id" in d:
            d["_id"] = str(d["_id"])
        out.append(d)
    return out


@router.get("/ping")
async def ping():
    return {"status": "ok", "dipartimento": config.DIPARTIMENTO_NOME, "ts": datetime.now().isoformat()}


@router.get("/badge_counts")
async def badge_counts(user: dict = Depends(get_current_user_live)):
    from database import get_db
    db = get_db()
    discord_id = user.get("discord_id")

    # Comunicati non letti dall'utente
    comunicati = await db["comunicati"].find().to_list(200)
    unread = sum(1 for c in comunicati if discord_id not in c.get("letto_da", []))

    # Segnalazioni aperte (solo dirigenza)
    seg_aperte = 0
    if user.get("permission", 0) >= 50:
        seg_aperte = await db["segnalazioni"].count_documents({"stato": "aperta"})

    # Segnalazioni AI aperte (solo AI + dirigenza)
    ai_aperte = 0
    if user.get("permission", 0) >= 75:
        ai_aperte = await db["segnalazioni_ai"].count_documents({"stato": "aperta"})

    # PEC non lette
    pec_unread = await db["pec"].count_documents({"dest_id": discord_id, "letta": False, "stato": {"$ne": "bozza"}})

    return {"comunicati_unread": unread, "segnalazioni_aperte": seg_aperte, "ai_aperte": ai_aperte, "pec_unread": pec_unread}


@router.get("/agenti")
async def api_agenti(x_api_key: str = Header(...)):
    _check_key(x_api_key)
    from database import get_db
    db = get_db()
    agenti = _ser_list(
        await db["agenti"].find(
            {"approvato": True},
            {"nome": 1, "cognome": 1, "cf": 1, "grado": 1, "stato": 1, "nick": 1}
        ).to_list(500)
    )
    return JSONResponse(agenti)


@router.get("/segnalazioni")
async def api_segnalazioni(x_api_key: str = Header(...)):
    _check_key(x_api_key)
    from database import get_db
    db = get_db()
    seg = _ser_list(
        await db["segnalazioni_pubbliche"].find({"stato": "aperta"}).to_list(100)
    )
    return JSONResponse(seg)


@router.post("/segnalazioni")
async def api_segnalazioni_post(request: Request, x_api_key: str = Header(...)):
    _check_key(x_api_key)
    from database import get_db
    db = get_db()
    body = await request.json()
    body["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    body["stato"]     = "aperta"
    body["fonte"]     = "API esterna"
    await db["segnalazioni_pubbliche"].insert_one(body)
    return {"ok": True}


@router.get("/comunicati")
async def api_comunicati(x_api_key: str = Header(...)):
    _check_key(x_api_key)
    from database import get_db
    db = get_db()
    com = _ser_list(
        await db["comunicati"].find(
            {},
            {"titolo": 1, "corpo": 1, "priorita": 1, "data": 1, "autore": 1}
        ).sort("timestamp", -1).limit(10).to_list(10)
    )
    return JSONResponse(com)
