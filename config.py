from os import getenv
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        # Telegram
        self.API_ID = int(getenv("API_ID", "0"))
        self.API_HASH = getenv("API_HASH")
        self.BOT_TOKEN = getenv("BOT_TOKEN")

        # Database
        self.MONGO_URL = getenv("MONGO_URL")

        # IDs
        self.LOGGER_ID = int(getenv("LOGGER_ID", "0"))
        self.OWNER_ID = int(getenv("OWNER_ID", "0"))

        # Limits
        self.DURATION_LIMIT = int(getenv("DURATION_LIMIT", "99999"))
        self.QUEUE_LIMIT = int(getenv("QUEUE_LIMIT", "20"))
        self.PLAYLIST_LIMIT = int(getenv("PLAYLIST_LIMIT", "20"))

        # Assistant Sessions
        self.SESSION1 = getenv("SESSION", None)
        self.SESSION2 = getenv("SESSION2", None)
        self.SESSION3 = getenv("SESSION3", None)

        # Support
        self.SUPPORT_CHANNEL = getenv(
            "SUPPORT_CHANNEL",
            "https://t.me/ll_ROYAL_ABOUT_ll"
        )
        self.SUPPORT_CHAT = getenv(
            "SUPPORT_CHAT",
            "https://t.me/hot_dpz_stor"
        )

        # API
        self.API_URL = getenv(
            "SHRUTI_API_URL",
            "https://api.shrutibots.site"
        )
        self.API_KEY = getenv("SHRUTI_API_KEY", "")

        # Playback settings
        self.AUTO_LEAVE = (
            getenv("AUTO_LEAVE", "False").lower() == "true"
        )

        self.AUTO_END = (
            getenv("AUTO_END", "False").lower() == "true"
        )

        self.THUMB_GEN = (
            getenv("THUMB_GEN", "True").lower() == "true"
        )

        self.VIDEO_PLAY = (
            getenv("VIDEO_PLAY", "True").lower() == "true"
        )

        # Language
        self.LANG_CODE = getenv("LANG_CODE", "en")

        # Cookies
        self.COOKIES_URL = [
            url
            for url in getenv("COOKIES_URL", "").split()
            if url and "batbin.me" in url
        ]

        # Images
        self.DEFAULT_THUMB = getenv(
            "DEFAULT_THUMB",
            "https://files.catbox.moe/dno7wv.jpg"
        )

        self.PING_IMG = getenv(
            "PING_IMG",
            "https://files.catbox.moe/7hr8ah.jpg"
        )

        # /start image
        # Change this URL from Heroku Config Vars whenever you want
        # to use another JPG.
        self.START_IMAGE = getenv(
            "START_IMAGE",
            "https://files.catbox.moe/dno7wv.jpg"
        )

        # Bot information
        self.BOT_NAME = getenv(
            "BOT_NAME",
            "QUEEN MUSIC"
        )

        self.BOT_PHOTO_URL = getenv(
            "BOT_PHOTO_URL",
            self.DEFAULT_THUMB
        )

    def check(self):
        missing = [
            var
            for var in [
                "API_ID",
                "API_HASH",
                "BOT_TOKEN",
                "MONGO_URL",
                "LOGGER_ID",
                "OWNER_ID",
                "SESSION1",
            ]
            if not getattr(self, var)
        ]

        if missing:
            raise SystemExit(
                "Missing required environment variables: "
                + ", ".join(missing)
        )
