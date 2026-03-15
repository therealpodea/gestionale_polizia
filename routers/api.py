"""
API endpoint — badge counts + sincronizzazione bot Discord sanzioni.
"""
from __future__ import annotations
from datetime import datetime
import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import config
from auth import get_current_user_live

router = APIRouter(prefix="/api", tags=["api"])

SYNC_KEY_DEFAULT = "estovia_2026_secret"


def oggi():
    return datetime.now().strftime("%Y-%m-%d")


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
    ai_aperte           = await db["segnalazioni_ai"].count_documents({"stato": "aperta"})
    denunce_aperte      = await db["denunce"].count_documents({"stato": "aperta"})
    pec_unread          = await db["pec"].count_documents({"dest_id": discord_id, "letta": False, "stato": "inviata"})

    return JSONResponse({
        "comunicati_unread":   comunicati_unread,
        "segnalazioni_aperte": segnalazioni_aperte,
        "ai_aperte":           ai_aperte,
        "pec_unread":          pec_unread,
        "denunce_aperte":      denunce_aperte,
    })


@router.get("/sync")
async def bot_sync(
    request: Request,
    discord: str = "",
    grado:   str = "",
    tipo:    str = "",
    motivo:  str = "",
    key:     str = "",
):
    sync_key = os.getenv("SYNC_KEY", SYNC_KEY_DEFAULT)
    if key != sync_key:
        return JSONResponse({"ok": False, "error": "Chiave non valida"}, status_code=401)
    if not discord or not tipo:
        return JSONResponse({"ok": False, "error": "Parametri mancanti"}, status_code=400)

    from database import get_db
    db = get_db()

    agente = await db["agenti"].find_one({
        "$or": [
            {"username": {"$regex": f"^{discord}$", "$options": "i"}},
            {"nick":     {"$regex": f"^{discord}$", "$options": "i"}},
        ]
    })

    if not agente:
        return JSONResponse({"ok": False, "error": f"Agente '{discord}' non trovato"}, status_code=404)

    agente_id   = agente["_id"]
    agente_nome = f"{agente.get('nome','')} {agente.get('cognome','')}".strip() or agente.get("nick", discord)
    now_str     = datetime.now().strftime("%Y-%m-%d %H:%M")

    update_fields: dict = {"ultima_sync": now_str}
    storico_entry: dict = {
        "agente_id":   str(agente_id),
        "agente_nome": agente_nome,
        "tipo":        tipo,
        "vecchio":     "",
        "nuovo":       grado,
        "motivo":      motivo,
        "data":        oggi(),
        "operatore":   "Bot Discord",
        "timestamp":   now_str,
    }

    t = tipo.lower()
    if t == "promozione":
        storico_entry["vecchio"] = agente.get("grado", "—")
        update_fields["grado"]   = grado
        update_fields["stato"]   = "Attivo"
    elif t == "degrado":
        storico_entry["vecchio"] = agente.get("grado", "—")
        update_fields["grado"]   = grado
    elif t == "sanzione":
        storico_entry["vecchio"] = agente.get("sanzione") or "Nessuna"
        update_fields["sanzione"] = grado
        if "sospens" in grado.lower():
            update_fields["stato"] = "Sospeso"
    elif t in ["rimozione sanzione", "rimozione_sanzione"]:
        storico_entry["vecchio"]  = agente.get("sanzione") or "Nessuna"
        storico_entry["nuovo"]    = "Nessuna"
        update_fields["sanzione"] = None
        if agente.get("stato") == "Sospeso":
            update_fields["stato"] = "Attivo"
    elif t == "licenziamento":
        storico_entry["vecchio"] = agente.get("grado", "—")
        storico_entry["nuovo"]   = "Congedato"
        update_fields["stato"]   = "Congedato"
        update_fields["grado"]   = "Congedato"
    elif t == "cambio stato":
        storico_entry["vecchio"] = agente.get("stato", "—")
        update_fields["stato"]   = grado

    await db["agenti"].update_one({"_id": agente_id}, {"$set": update_fields})
    await db["storico"].insert_one(storico_entry)

    print(f"[BOT SYNC] {discord} | {tipo} → {grado} | {motivo}")
    return JSONResponse({"ok": True, "agente": agente_nome, "tipo": tipo, "nuovo": grado})


@router.get("/sync/test")
async def sync_test(key: str = ""):
    sync_key = os.getenv("SYNC_KEY", SYNC_KEY_DEFAULT)
    if key != sync_key:
        return JSONResponse({"ok": False, "error": "Chiave non valida"}, status_code=401)
    return JSONResponse({"ok": True, "message": "Connessione al gestionale funzionante ✅"})
