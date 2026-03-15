from __future__ import annotations
from datetime import datetime
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import config
from routers.settings_helper import get_settings
from auth import get_current_user_live, require_permission, require_write

router    = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="templates")


# ── Helpers ────────────────────────────────────────────────────────────────────
def uid():
    import time, random, string
    return datetime.now().strftime("%Y%m%d%H%M%S") + "".join(random.choices(string.ascii_lowercase, k=4))


def oggi():
    return datetime.now().strftime("%Y-%m-%d")


def _ser(doc: dict) -> dict:
    """Converte ObjectId in stringa per i template."""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def _ser_list(docs) -> list[dict]:
    return [_ser(dict(d)) for d in docs]


# ── DASHBOARD ─────────────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(get_current_user_live)):
    from database import get_db
    db = get_db()

    agenti      = await db["agenti"].count_documents({"approvato": True})
    attivi      = await db["agenti"].count_documents({"approvato": True, "stato": "Attivo"})
    sospesi     = await db["agenti"].count_documents({"approvato": True, "stato": "Sospeso"})
    promozioni  = await db["storico"].count_documents({"tipo": "Promozione"})

    ultime_azioni = _ser_list(
        await db["storico"].find().sort("timestamp", -1).limit(7).to_list(7)
    )
    ultimi_com = _ser_list(
        await db["comunicati"].find().sort("timestamp", -1).limit(3).to_list(3)
    )

    # Distribuzione gradi
    gradi = config.GRADI_DEFAULT
    grade_count = {}
    for g in gradi:
        grade_count[g] = await db["agenti"].count_documents({"approvato": True, "grado": g})

    return templates.TemplateResponse("dashboard.html", {
        "settings":   await get_settings(),
        "request":       request,
        "user":          user,
        "agenti":        agenti,
        "attivi":        attivi,
        "sospesi":       sospesi,
        "promozioni":    promozioni,
        "ultime_azioni": ultime_azioni,
        "ultimi_com":    ultimi_com,
        "grade_count":   grade_count,
        "gradi":         gradi,
        "dipartimento":  config.DIPARTIMENTO_NOME,
    })


# ── AGENTI ────────────────────────────────────────────────────────────────────
@router.get("/agenti", response_class=HTMLResponse)
async def agenti_page(
    request: Request,
    q: str = "",
    stato: str = "",
    grado: str = "",
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()

    filt: dict = {"approvato": True}
    if q:
        filt["$or"] = [
            {"nome":    {"$regex": q, "$options": "i"}},
            {"cognome": {"$regex": q, "$options": "i"}},
            {"cf":      {"$regex": q, "$options": "i"}},
            {"nick":    {"$regex": q, "$options": "i"}},
            {"grado":   {"$regex": q, "$options": "i"}},
        ]
    if stato:
        filt["stato"] = stato
    if grado:
        filt["grado"] = grado

    agenti = _ser_list(await db["agenti"].find(filt).sort("cognome", 1).to_list(500))

    return templates.TemplateResponse("agenti.html", {
        "settings":   await get_settings(),
        "request":  request,
        "user":     user,
        "agenti":   agenti,
        "gradi":    config.GRADI_DEFAULT,
        "q":        q,
        "stato":    stato,
        "grado":    grado,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.get("/agenti/add", response_class=HTMLResponse)
async def agenti_add_page(request: Request, user: dict = Depends(require_permission(50))):
    return templates.TemplateResponse("agenti_add.html", {
        "settings":   await get_settings(),
        "request": request,
        "user":    user,
        "gradi":   config.GRADI_DEFAULT,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.post("/agenti/add")
async def agenti_add(
    request: Request,
    nome:          str = Form(...),
    cognome:       str = Form(...),
    cf:            str = Form(...),
    discord_id:    str = Form(""),
    nick:          str = Form(""),
    grado:         str = Form(...),
    stato:         str = Form("Attivo"),
    data_ingresso: str = Form(""),
    note:          str = Form(""),
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()
    doc = {
        "nome":          nome.strip(),
        "cognome":       cognome.strip(),
        "cf":            cf.strip().upper(),
        "discord_id":    discord_id.strip(),
        "nick":          nick.strip() or f"{nome} {cognome}",
        "grado":         grado,
        "stato":         stato,
        "sanzione":      None,
        "data_ingresso": data_ingresso or oggi(),
        "note":          note.strip(),
        "approvato":     True,
        "permission":    10,
        "readonly":      False,
        "role_ids":      [],
        "livello":       "agente",
        "added_by":      user.get("username"),
        "timestamp":     datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    await db["agenti"].insert_one(doc)
    await db["storico"].insert_one({
        "id":         uid(),
        "agente_id":  str(doc.get("_id", "")),
        "agente_nome": f"{nome} {cognome}",
        "tipo":       "Ingresso",
        "vecchio":    "—",
        "nuovo":      grado,
        "motivo":     "Primo ingresso in forza",
        "operatore":  user.get("username"),
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":       oggi(),
    })
    return RedirectResponse("/dashboard/agenti", status_code=303)


@router.post("/agenti/modifica")
async def agenti_modifica(
    request: Request,
    agente_id:     str = Form(...),
    nome:          str = Form(""),
    cognome:       str = Form(""),
    cf:            str = Form(""),
    nick:          str = Form(""),
    grado:         str = Form(""),
    stato:         str = Form("Attivo"),
    data_ingresso: str = Form(""),
    note:          str = Form(""),
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()
    update = {}
    if nome.strip():      update["nome"]          = nome.strip()
    if cognome.strip():   update["cognome"]        = cognome.strip()
    if cf.strip():        update["cf"]             = cf.strip().upper()
    if nick.strip():      update["nick"]           = nick.strip()
    if grado.strip():     update["grado"]          = grado
    if stato.strip():     update["stato"]          = stato
    if data_ingresso:     update["data_ingresso"]  = data_ingresso
    update["note"] = note.strip()
    if update:
        await db["agenti"].update_one(
            {"_id": ObjectId(agente_id)},
            {"$set": update}
        )
    return RedirectResponse(f"/dashboard/agenti/{agente_id}", status_code=303)


@router.post("/agenti/elimina")
async def agenti_elimina(
    agente_id: str = Form(...),
    user: dict = Depends(require_permission(100)),
):
    from database import get_db
    db = get_db()
    await db["agenti"].delete_one({"_id": ObjectId(agente_id)})
    return RedirectResponse("/dashboard/agenti", status_code=303)


@router.get("/agenti/{agente_id}", response_class=HTMLResponse)
async def agente_dettaglio(
    request: Request,
    agente_id: str,
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    agente = _ser(await db["agenti"].find_one({"_id": ObjectId(agente_id)}))
    if not agente:
        raise HTTPException(404, "Agente non trovato.")
    storico = _ser_list(
        await db["storico"].find({"agente_id": agente_id}).sort("timestamp", -1).to_list(200)
    )
    return templates.TemplateResponse("agente_dettaglio.html", {
        "settings":   await get_settings(),
        "request": request,
        "user":    user,
        "agente":  agente,
        "storico": storico,
        "gradi":   config.GRADI_DEFAULT,
        "sanzioni": config.SANZIONI_DEFAULT,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── AZIONI DISCIPLINARI ───────────────────────────────────────────────────────
@router.post("/azioni/registra")
async def azioni_registra(
    agente_id:  str = Form(...),
    tipo:       str = Form(...),
    nuovo:      str = Form(...),
    motivo:     str = Form(...),
    data:       str = Form(""),
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()

    agente = await db["agenti"].find_one({"_id": ObjectId(agente_id)})
    if not agente:
        raise HTTPException(404)

    vecchio = ""
    update  = {}

    if tipo in ("Promozione", "Degrado"):
        vecchio = agente.get("grado", "—")
        update  = {"grado": nuovo}
    elif tipo == "Sanzione":
        vecchio = agente.get("sanzione") or "Nessuna"
        update  = {"sanzione": nuovo}
    elif tipo == "Rimozione Sanzione":
        vecchio = agente.get("sanzione") or "Nessuna"
        nuovo   = "Nessuna"
        update  = {"sanzione": None}
    elif tipo == "Cambio Stato":
        vecchio = agente.get("stato", "—")
        update  = {"stato": nuovo}
    elif tipo == "Licenziamento":
        vecchio = agente.get("stato", "—")
        update  = {"stato": "Congedato"}

    if update:
        await db["agenti"].update_one({"_id": ObjectId(agente_id)}, {"$set": update})

    agente_nome = f"{agente.get('nome', '')} {agente.get('cognome', '')}".strip()
    await db["storico"].insert_one({
        "id":          uid(),
        "agente_id":   agente_id,
        "agente_nome": agente_nome,
        "tipo":        tipo,
        "vecchio":     vecchio,
        "nuovo":       nuovo,
        "motivo":      motivo,
        "operatore":   user.get("username"),
        "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":        data or oggi(),
    })
    return RedirectResponse(f"/dashboard/agenti/{agente_id}", status_code=303)


# ── STORICO ───────────────────────────────────────────────────────────────────
@router.get("/storico", response_class=HTMLResponse)
async def storico_page(
    request: Request,
    q: str = "",
    tipo: str = "",
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()

    filt: dict = {}
    if q:
        filt["$or"] = [
            {"agente_nome": {"$regex": q, "$options": "i"}},
            {"motivo":      {"$regex": q, "$options": "i"}},
        ]
    if tipo:
        filt["tipo"] = tipo

    storico = _ser_list(
        await db["storico"].find(filt).sort("timestamp", -1).limit(300).to_list(300)
    )
    return templates.TemplateResponse("storico.html", {
        "settings":   await get_settings(),
        "request": request,
        "user":    user,
        "storico": storico,
        "q":       q,
        "tipo":    tipo,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── STATISTICHE ───────────────────────────────────────────────────────────────
@router.get("/statistiche", response_class=HTMLResponse)
async def statistiche_page(
    request: Request,
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()

    attivi  = await db["agenti"].count_documents({"approvato": True, "stato": "Attivo"})
    sospesi = await db["agenti"].count_documents({"approvato": True, "stato": "Sospeso"})
    inprova = await db["agenti"].count_documents({"approvato": True, "stato": "In Prova"})
    cong    = await db["agenti"].count_documents({"approvato": True, "stato": "Congedato"})
    tot_san = await db["storico"].count_documents({"tipo": "Sanzione"})
    tot_prom= await db["storico"].count_documents({"tipo": "Promozione"})
    tot_deg = await db["storico"].count_documents({"tipo": "Degrado"})

    # Distribuzione gradi
    gradi = config.GRADI_DEFAULT
    grade_count = {}
    for g in gradi:
        grade_count[g] = await db["agenti"].count_documents({"approvato": True, "grado": g})

    # Trend ultimi 12 mesi
    mesi_labels = []
    mesi_prom   = []
    mesi_san    = []
    for i in range(11, -1, -1):
        from datetime import timedelta
        d = datetime.now().replace(day=1) - timedelta(days=i * 28)
        key   = d.strftime("%Y-%m")
        label = d.strftime("%b %y")
        mesi_labels.append(label)
        mesi_prom.append(await db["storico"].count_documents({"tipo": "Promozione", "data": {"$regex": f"^{key}"}}))
        mesi_san.append(await db["storico"].count_documents({"tipo": "Sanzione",    "data": {"$regex": f"^{key}"}}))

    # Top sanzionati
    pipeline = [
        {"$match": {"tipo": "Sanzione"}},
        {"$group": {"_id": "$agente_nome", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 6},
    ]
    top_san = await db["storico"].aggregate(pipeline).to_list(6)

    return templates.TemplateResponse("statistiche.html", {
        "settings":   await get_settings(),
        "request":    request,
        "user":       user,
        "attivi":     attivi,
        "sospesi":    sospesi,
        "inprova":    inprova,
        "congedati":  cong,
        "tot_san":    tot_san,
        "tot_prom":   tot_prom,
        "tot_deg":    tot_deg,
        "grade_count": grade_count,
        "gradi":       gradi,
        "mesi_labels": mesi_labels,
        "mesi_prom":   mesi_prom,
        "mesi_san":    mesi_san,
        "top_san":     top_san,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── COMUNICATI ────────────────────────────────────────────────────────────────
@router.get("/comunicati", response_class=HTMLResponse)
async def comunicati_page(request: Request, user: dict = Depends(get_current_user_live)):
    from database import get_db
    db = get_db()
    comunicati = _ser_list(
        await db["comunicati"].find().sort("timestamp", -1).to_list(100)
    )
    discord_id = user.get("discord_id")
    for c in comunicati:
        c["letto"] = discord_id in c.get("letto_da", [])
    return templates.TemplateResponse("comunicati.html", {
        "settings":   await get_settings(),
        "request":    request,
        "user":       user,
        "comunicati": comunicati,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.post("/comunicati/add")
async def comunicati_add(
    titolo:   str = Form(...),
    corpo:    str = Form(...),
    priorita: str = Form("normale"),
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()
    await db["comunicati"].insert_one({
        "id":        uid(),
        "titolo":    titolo.strip(),
        "corpo":     corpo.strip(),
        "priorita":  priorita,
        "autore":    user.get("username"),
        "letto_da":  [],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":      oggi(),
    })
    return RedirectResponse("/dashboard/comunicati", status_code=303)


@router.post("/comunicati/modifica")
async def comunicati_modifica(
    comunicato_id: str = Form(...),
    titolo:        str = Form(...),
    corpo:         str = Form(...),
    priorita:      str = Form("normale"),
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()
    await db["comunicati"].update_one(
        {"_id": ObjectId(comunicato_id)},
        {"$set": {"titolo": titolo.strip(), "corpo": corpo.strip(), "priorita": priorita}}
    )
    return RedirectResponse("/dashboard/comunicati", status_code=303)


@router.post("/comunicati/elimina")
async def comunicati_elimina(
    comunicato_id: str = Form(...),
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()
    await db["comunicati"].delete_one({"_id": ObjectId(comunicato_id)})
    return RedirectResponse("/dashboard/comunicati", status_code=303)


@router.post("/comunicati/visto")
async def comunicati_visto(
    comunicato_id: str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    discord_id = user.get("discord_id")
    com = await db["comunicati"].find_one({"_id": ObjectId(comunicato_id)})
    if com:
        letto_da = com.get("letto_da", [])
        if discord_id in letto_da:
            letto_da.remove(discord_id)
        else:
            letto_da.append(discord_id)
        await db["comunicati"].update_one(
            {"_id": ObjectId(comunicato_id)},
            {"$set": {"letto_da": letto_da}}
        )
    return RedirectResponse("/dashboard/comunicati", status_code=303)


# ── SEGNALAZIONI ─────────────────────────────────────────────────────────────
@router.get("/segnalazioni", response_class=HTMLResponse)
async def segnalazioni_page(request: Request, user: dict = Depends(get_current_user_live)):
    from database import get_db
    db = get_db()

    is_dir = user.get("permission", 0) >= 50
    filt   = {} if is_dir else {"mittente_id": user.get("discord_id")}
    segnalazioni = _ser_list(
        await db["segnalazioni"].find(filt).sort("timestamp", -1).to_list(200)
    )
    return templates.TemplateResponse("segnalazioni.html", {
        "settings":   await get_settings(),
        "request":      request,
        "user":         user,
        "segnalazioni": segnalazioni,
        "is_dirigenza": is_dir,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.post("/segnalazioni/add")
async def segnalazioni_add(
    titolo:   str = Form(...),
    corpo:    str = Form(...),
    priorita: str = Form("normale"),
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    await db["segnalazioni"].insert_one({
        "id":            uid(),
        "titolo":        titolo.strip(),
        "corpo":         corpo.strip(),
        "priorita":      priorita,
        "stato":         "aperta",
        "mittente_id":   user.get("discord_id"),
        "mittente_nome": user.get("nick") or user.get("username"),
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":          oggi(),
    })
    return RedirectResponse("/dashboard/segnalazioni", status_code=303)


@router.post("/segnalazioni/stato")
async def segnalazioni_stato(
    segnalazione_id: str = Form(...),
    stato:           str = Form(...),
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()
    await db["segnalazioni"].update_one(
        {"_id": ObjectId(segnalazione_id)},
        {"$set": {"stato": stato}}
    )
    return RedirectResponse("/dashboard/segnalazioni", status_code=303)


@router.post("/segnalazioni/elimina")
async def segnalazioni_elimina(
    segnalazione_id: str = Form(...),
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()
    await db["segnalazioni"].delete_one({"_id": ObjectId(segnalazione_id)})
    return RedirectResponse("/dashboard/segnalazioni", status_code=303)


# ── VERBALI ───────────────────────────────────────────────────────────────────
@router.get("/verbali", response_class=HTMLResponse)
async def verbali_page(request: Request, user: dict = Depends(get_current_user_live)):
    from database import get_db
    db = get_db()
    verbali = _ser_list(
        await db["verbali"].find().sort("timestamp", -1).to_list(200)
    )
    return templates.TemplateResponse("verbali.html", {
        "settings":   await get_settings(),
        "request":  request,
        "user":     user,
        "verbali":  verbali,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.post("/verbali/add")
async def verbali_add(
    tipo:        str = Form(...),
    luogo:       str = Form(...),
    data_ora:    str = Form(""),
    esito:       str = Form("Positivo"),
    soggetti:    str = Form(""),
    agenti_int:  str = Form(""),
    descrizione: str = Form(...),
    note:        str = Form(""),
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    autore = user.get("nick") or user.get("username")
    titolo = f"[{tipo}] {luogo} — {data_ora or oggi()}"
    await db["verbali"].insert_one({
        "id":          uid(),
        "titolo":      titolo,
        "tipo":        tipo,
        "luogo":       luogo,
        "data_ora":    data_ora or oggi(),
        "esito":       esito,
        "soggetti":    soggetti.strip(),
        "agenti_int":  agenti_int.strip(),
        "descrizione": descrizione.strip(),
        "note":        note.strip(),
        "autore":      autore,
        "autore_id":   user.get("discord_id"),
        "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":        oggi(),
    })

    # Auto-aggiorna fedina penale se il verbale contiene un CF
    import re
    # Cerca pattern CF (16 caratteri alfanumerici) nel campo soggetti
    cf_matches = re.findall(r'\b[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]\b', soggetti.upper())
    for cf in cf_matches:
        await db["cittadini"].update_one(
            {"cf": cf},
            {"$push": {"fedina": {
                "reato":    tipo,
                "data":     data_ora.split("T")[0] if data_ora else oggi(),
                "luogo":    luogo,
                "sanzione": "",
                "note":     f"Verbale: {titolo}",
                "stato":    "definitivo",
            }}}
        )
    return RedirectResponse("/dashboard/verbali", status_code=303)


@router.post("/verbali/elimina")
async def verbali_elimina(
    verbale_id: str = Form(...),
    user: dict = Depends(require_permission(50)),
):
    from database import get_db
    db = get_db()
    await db["verbali"].delete_one({"_id": ObjectId(verbale_id)})
    return RedirectResponse("/dashboard/verbali", status_code=303)


# ── GERARCHIA ────────────────────────────────────────────────────────────────
@router.get("/gerarchia", response_class=HTMLResponse)
async def gerarchia_page(request: Request, user: dict = Depends(get_current_user_live)):
    from database import get_db
    db = get_db()

    gradi = config.GRADI_DEFAULT
    agenti_raw = _ser_list(
        await db["agenti"].find({"approvato": True}).to_list(500)
    )
    # Ordina per indice grado (più alto prima)
    def grado_key(a):
        g = a.get("grado", "")
        return -gradi.index(g) if g in gradi else 999

    agenti_raw.sort(key=grado_key)

    return templates.TemplateResponse("gerarchia.html", {
        "settings":   await get_settings(),
        "request": request,
        "user":    user,
        "agenti":  agenti_raw,
        "gradi":   gradi,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


# ── UTENTI (approvazione) ─────────────────────────────────────────────────────
@router.get("/utenti", response_class=HTMLResponse)
async def utenti_page(request: Request, user: dict = Depends(require_permission(100))):
    from database import get_db
    db = get_db()
    in_attesa = _ser_list(
        await db["agenti"].find({"approvato": False}).to_list(100)
    )
    tutti = _ser_list(
        await db["agenti"].find({"approvato": True}).sort("cognome", 1).to_list(500)
    )
    return templates.TemplateResponse("utenti.html", {
        "settings":   await get_settings(),
        "request":   request,
        "user":      user,
        "in_attesa": in_attesa,
        "tutti":     tutti,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.post("/utenti/approva")
async def utenti_approva(
    agente_id: str = Form(...),
    grado:     str = Form("Agente"),
    user: dict = Depends(require_permission(100)),
):
    from database import get_db
    db = get_db()
    await db["agenti"].update_one(
        {"_id": ObjectId(agente_id)},
        {"$set": {"approvato": True, "grado": grado, "stato": "Attivo"}}
    )
    return RedirectResponse("/dashboard/utenti", status_code=303)


@router.post("/utenti/rifiuta")
async def utenti_rifiuta(
    agente_id: str = Form(...),
    user: dict = Depends(require_permission(100)),
):
    from database import get_db
    db = get_db()
    await db["agenti"].delete_one({"_id": ObjectId(agente_id)})
    return RedirectResponse("/dashboard/utenti", status_code=303)


@router.post("/utenti/aggiorna")
async def utenti_aggiorna(
    agente_id:  str = Form(...),
    permission: int = Form(10),
    user: dict = Depends(require_permission(100)),
):
    from database import get_db
    db = get_db()
    livello = "dirigenza" if permission >= 100 else "ispettorato" if permission >= 50 else "agente"
    await db["agenti"].update_one(
        {"_id": ObjectId(agente_id)},
        {"$set": {"permission": permission, "livello": livello}}
    )
    return RedirectResponse("/dashboard/utenti", status_code=303)


# ── PEC INTERNA ───────────────────────────────────────────────────────────────
@router.get("/pec", response_class=HTMLResponse)
async def pec_page(
    request: Request,
    cartella: str = "in",
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    my_id = user.get("discord_id")

    inbox  = _ser_list(await db["pec"].find({"dest_id": my_id, "stato": {"$ne": "bozza"}}).sort("timestamp", -1).to_list(200))
    outbox = _ser_list(await db["pec"].find({"mitt_id": my_id, "stato": {"$ne": "bozza"}}).sort("timestamp", -1).to_list(200))
    bozze  = _ser_list(await db["pec"].find({"mitt_id": my_id, "stato": "bozza"}).sort("timestamp", -1).to_list(50))
    unread = sum(1 for p in inbox if not p.get("letta"))

    # Lista destinatari
    agenti = _ser_list(await db["agenti"].find({"approvato": True, "stato": {"$ne": "Congedato"}}, {"nick": 1, "nome": 1, "cognome": 1, "discord_id": 1}).to_list(300))

    lista = inbox if cartella == "in" else outbox if cartella == "out" else bozze

    return templates.TemplateResponse("pec.html", {
        "settings":   await get_settings(),
        "request":  request,
        "user":     user,
        "inbox":    inbox,
        "outbox":   outbox,
        "bozze":    bozze,
        "lista":    lista,
        "cartella": cartella,
        "unread":   unread,
        "agenti":   agenti,
        "my_id":    my_id,
        "dipartimento": config.DIPARTIMENTO_NOME,
    })


@router.post("/pec/invia")
async def pec_invia(
    dest_id:   str = Form(...),
    dest_nome: str = Form(...),
    oggetto:   str = Form(...),
    corpo:     str = Form(...),
    priorita:  str = Form("normale"),
    stato:     str = Form("inviata"),
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    mitt_nome = user.get("nick") or user.get("username")
    await db["pec"].insert_one({
        "id":        uid(),
        "mitt_id":   user.get("discord_id"),
        "mitt_nome": mitt_nome,
        "dest_id":   dest_id,
        "dest_nome": dest_nome,
        "oggetto":   oggetto.strip(),
        "corpo":     corpo.strip(),
        "priorita":  priorita,
        "stato":     stato,
        "letta":     False,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data":      oggi(),
    })
    return RedirectResponse("/dashboard/pec", status_code=303)


@router.post("/pec/leggi")
async def pec_leggi(
    pec_id: str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    await db["pec"].update_one({"_id": ObjectId(pec_id)}, {"$set": {"letta": True}})
    return RedirectResponse("/dashboard/pec", status_code=303)


@router.post("/pec/elimina")
async def pec_elimina(
    pec_id: str = Form(...),
    user: dict = Depends(get_current_user_live),
):
    from database import get_db
    db = get_db()
    # Può eliminare solo il mittente o il destinatario
    pec = await db["pec"].find_one({"_id": ObjectId(pec_id)})
    if pec and (pec.get("mitt_id") == user.get("discord_id") or pec.get("dest_id") == user.get("discord_id")):
        await db["pec"].delete_one({"_id": ObjectId(pec_id)})
    return RedirectResponse("/dashboard/pec", status_code=303)
