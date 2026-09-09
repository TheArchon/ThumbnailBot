# ArchonMusic

Telegram Music Player Bot built with Python, Pyrogram/Kurigram and Py-TGCALLS.

## 🚀 One-Click Heroku Hosting

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/Yewsdhi/NEWQUEENBOTREPO)

### Required variables

Heroku will ask for these automatically during deployment:

- `API_ID` — Telegram API ID from https://my.telegram.org/apps
- `API_HASH` — Telegram API hash
- `BOT_TOKEN` — Bot token from @BotFather
- `MONGO_URL` — MongoDB connection URI
- `LOGGER_ID` — Telegram log group ID
- `OWNER_ID` — Owner Telegram user ID
- `SESSION` — Pyrogram string session for the assistant/userbot

### Optional variables

You can add these later in **Heroku → Settings → Config Vars**:

`SESSION2`, `SESSION3`, `DURATION_LIMIT`, `QUEUE_LIMIT`, `PLAYLIST_LIMIT`, `SUPPORT_CHANNEL`, `SUPPORT_CHAT`, `SHRUTI_API_URL`, `SHRUTI_API_KEY`, `AUTO_LEAVE`, `AUTO_END`, `THUMB_GEN`, `VIDEO_PLAY`, `LANG_CODE`, `COOKIES_URL`, `DEFAULT_THUMB`, `PING_IMG`, `START_VIDEO`.

## Manual Heroku deployment

1. Fork this repository.
2. Open the **Deploy to Heroku** button above.
3. Enter the required variables.
4. Click **Deploy app**.
5. After deployment, make sure the `worker` dyno is enabled.

> The project uses Heroku's container stack through `heroku.yml` and `Dockerfile`.
