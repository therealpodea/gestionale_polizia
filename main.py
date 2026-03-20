import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import database
from auth import router as auth_router
from routers.dashboard import router as dashboard_router
from routers.cittadini import router as cittadini_router
from routers.api import router as api_router
from routers.affari_interni import router as ai_router
from routers.impostazioni import router as impostazioni_router
from routers.documentazione import router as documentazione_router
from routers.denunce import router as denunce_router
from routers.documenti_cittadini import router as documenti_cittadini_router

os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect_db()
    print("✅ Database connesso")
    yield
    await database.close_db()


app = FastAPI(
    title="Polizia d'Estovia — Gestionale",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(cittadini_router)
app.include_router(api_router)
app.include_router(ai_router)
app.include_router(impostazioni_router)
app.include_router(documentazione_router)
app.include_router(denunce_router)
app.include_router(documenti_cittadini_router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    token = request.cookies.get("session_token")
    if token:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})


async def main():
    print("🚀 Avvio Gestionale Polizia d'Estovia...")
    port = int(os.getenv("PORT", config.APP_PORT))
    server_config = uvicorn.Config(
        app=app,
        host=config.APP_HOST,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(server_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
