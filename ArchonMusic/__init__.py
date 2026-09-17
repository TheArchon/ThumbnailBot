import time
import asyncio
import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    format="[%(asctime)s - %(levelname)s] - %(name)s: %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        RotatingFileHandler("log.txt", maxBytes=10485760, backupCount=5),
        logging.StreamHandler(),
    ],
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("ntgcalls").setLevel(logging.CRITICAL)
logging.getLogger("pymongo").setLevel(logging.ERROR)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pytgcalls").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# Define this package attribute early so submodules importing it during
# package initialization do not trigger a partially-initialized import error.
ArchonMusic = None


__version__ = "3.0.2"

from config import Config

config = Config()
config.check()
tasks = []
boot = time.time()

from ArchonMusic.core.bot import Bot
app = Bot()

from ArchonMusic.core.dir import ensure_dirs
ensure_dirs()

from ArchonMusic.core.userbot import Userbot
userbot = Userbot()

from ArchonMusic.core.mongo import MongoDB
db = MongoDB()

from ArchonMusic.core.lang import Language
lang = Language()

from ArchonMusic.core.telegram import Telegram
from ArchonMusic.core.youtube import YouTube
tg = Telegram()
yt = YouTube()

from ArchonMusic.helpers import Queue, Thumbnail
queue = Queue()
thumb = Thumbnail()

# TgCall is initialized by ArchonMusic.__main__ after the package is fully loaded.
# Keeping it out of package initialization prevents circular-import crashes.


async def stop() -> None:
    logger.info("Stopping...")
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.exceptions.CancelledError:
            pass

    await app.exit()
    await userbot.exit()
    await db.close()
    await thumb.close()

    logger.info("Stopped.\n")
