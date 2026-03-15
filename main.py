import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import nextcord
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from nextcord.ext import commands

import config
import database
from auth import router as auth_router
from bot.cogs import setup_bot
from routers.dashboard import router as dashboard_router
from routers.cittadini import router as cittadini_router
from routers.api import router as api_router
from routers.affari_interni import router as ai_router

# ── Assicura che le cartelle necessarie esistano ───────────────────────────────
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# ── Bot Discord ────────────────────────────────────────────────────────────────
intents = nextcord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(intents=intents)

# Carica cogs
if os.path.exists("./cogs"):
    for file in os.listdir("./cogs"):
        if file.endswith(".py") and file != "__init__.py":
            try:
                bot.load_extension(f"cogs.{file[:-3]}")
                print(f"[COG] Caricato: {file}")
            except Exception as e:
                print(f"[COG] Impossibile caricare {file}: {e}")


@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    if config.CANALE_LOG_ID:
        channel = bot.get_channel(config.CANALE_LOG_ID)
        if channel:
            embed = nextcord.Embed(
                title="🚔 Gestionale Polizia d'Estovia — Online",
                description="Il sistema gestionale è ora operativo.",
                color=0x0052b4,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(
                name="⏰ Avvio",
                value=f"<t:{int(datetime.now().timestamp())}:F>",
                inline=False,
            )
            embed.set_footer(text="Polizia d'Estovia — Gestionale Interno")
            await channel.send(embed=embed)


# ── FastAPI ────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect_db()
    db = database.get_db()
    await setup_bot(bot, db)
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    token = request.cookies.get("session_token")
    if token:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})


# ── Avvio ──────────────────────────────────────────────────────────────────────
async def run_bot():
    await bot.start(config.DISCORD_BOT_TOKEN)


async def run_webserver():
    port = int(os.getenv("PORT", config.APP_PORT))
    server_config = uvicorn.Config(
        app=app,
        host=config.APP_HOST,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(server_config)
    await server.serve()


async def main():
    print("🚀 Avvio Gestionale Polizia d'Estovia...")
    await asyncio.gather(run_bot(), run_webserver())


if __name__ == "__main__":
    asyncio.run(main())
