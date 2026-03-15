from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGODB_URI, MONGODB_DB_NAME

_client: AsyncIOMotorClient | None = None


async def connect_db():
    global _client
    _client = AsyncIOMotorClient(MONGODB_URI)
    await _client.admin.command("ping")
    print(f"[DB] Connesso a MongoDB → {MONGODB_DB_NAME}")


async def close_db():
    global _client
    if _client:
        _client.close()
        print("[DB] Connessione MongoDB chiusa.")


def get_db():
    if _client is None:
        raise RuntimeError("Database non inizializzato.")
    return _client[MONGODB_DB_NAME]
