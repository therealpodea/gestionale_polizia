_bot = None
_db  = None


async def setup_bot(bot, db):
    global _bot, _db
    _bot = bot
    _db  = db


def get_bot():
    return _bot


def get_db():
    return _db
