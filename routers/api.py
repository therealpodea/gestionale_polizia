"""
API endpoints interni — badge counts e utility.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from auth import get_current_user_live

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/badge_counts")
async def badge_counts(user: dict = Depends(get_current_user_live)):
    from database import get_db
    db = get_db()
    discord_id = user.get("discord_id")

    comunicati_unread = 0
    all_com = await db["comunicati"].find().to_list(200)
    for c in all_com:
        if discord_id not in (c.get("letto_da") or []):
            comunicati_unread += 1

    segnalazioni_aperte = await db["segnalazioni"].count_documents({"stato": "aperta"})
    ai_aperte = await db["segnalazioni_ai"].count_documents({"stato": "aperta"})

    pec_unread = await db["pec"].count_documents({
        "dest_id": discord_id,
        "letta": False,
        "stato": "inviata"
    })

    return JSONResponse({
        "comunicati_unread":   comunicati_unread,
        "segnalazioni_aperte": segnalazioni_aperte,
        "ai_aperte":           ai_aperte,
        "pec_unread":          pec_unread,
    })
