import json
import os
from typing import Any

import aiohttp


class RichMessageAPI:
    """Small Bot API client for Telegram Rich Messages (Bot API 10.3+).

    The main bot continues to use Kurigram/Pyrogram for updates and voice-chat
    control. This helper is only used for the new Rich Message now-playing card,
    because Rich Messages are exposed by the HTTP Bot API.
    """

    def __init__(self, token: str):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"

    async def _post(self, method: str, fields: dict[str, Any], files: dict[str, tuple] | None = None):
        data = aiohttp.FormData()
        for key, value in fields.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            data.add_field(key, str(value))

        if files:
            for field, (filename, fileobj, content_type) in files.items():
                data.add_field(
                    field,
                    fileobj,
                    filename=filename,
                    content_type=content_type,
                )

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{self.base}/{method}", data=data) as resp:
                payload = await resp.json(content_type=None)
                if not payload.get("ok"):
                    raise RuntimeError(
                        f"Telegram {method} failed: {payload.get('description', 'unknown error')}"
                    )
                return payload["result"]

    async def send_now_playing(
        self,
        chat_id: int,
        title: str,
        duration: str,
        requested_by: str,
        thumb_path: str | None,
        bot_name: str,
        queue_count: int,
    ) -> int:
        """Send a single white-card Rich Message with embedded controls.

        The media block and the button rows are part of the same Rich Message,
        so Telegram clients render the controls inside the card instead of as
        a separate InlineKeyboard area.
        """
        blocks: list[dict[str, Any]] = []

        if thumb_path and os.path.exists(thumb_path):
            blocks.append(
                {
                    "type": "photo",
                    "photo": {
                        "type": "photo",
                        "media": "attach://now_playing_thumb",
                    },
                }
            )

        blocks.extend(
            [
                {"type": "paragraph", "text": "<b>🎧  Mᴜsɪᴄ Iѕ Pʟᴀʏɪɴɢ</b>"},
                {"type": "paragraph", "text": f"<b>🎵  Nᴏᴡ Pʟᴀʏɪɴɢ :</b> {title}"},
                {"type": "paragraph", "text": f"<b>⏱️  Tʀᴀᴄᴋ Dᴜʀᴀᴛɪᴏɴ :</b> {duration}"} ᴍɪɴ,
                {"type": "paragraph", "text": f"<b>👤  Rᴇǫᴜᴇsᴛᴇᴅ Bʏ :</b> {requested_by}"},
                {"type": "paragraph", "text": "<b> 🎶 Yᴏᴜʀ Tʀᴀᴄᴋ ɪs Nᴏᴡ Pʟᴀʏɪɴɢ</b>"},
                {"type": "paragraph", "text": "<b>🔊 Sɪᴛ Bᴀᴄᴋ, Rᴇʟᴀx & Eɴᴊᴏʏ Tʜᴇ Mᴜsɪᴄ</b>"},
                {"type": "paragraph", "text": f"00:01   ●──────────────   {duration}"},
                {
                    "type": "buttons",
                    "buttons": [
                        {
                            "text": "↻ Replay",
                            "style": "primary",
                            "callback_data": f"controls replay {chat_id}",
                        },
                        {
                            "text": "Ⅱ Pause",
                            "style": "danger",
                            "callback_data": f"controls pause {chat_id}",
                        },
                        {
                            "text": "» Skip",
                            "style": "success",
                            "callback_data": f"controls skip {chat_id}",
                        },
                    ],
                    "align": "center",
                },
                {
                    "type": "buttons",
                    "buttons": [
                        {
                            "text": f"☰ Queue • {max(0, queue_count)}",
                            "style": "link",
                            "callback_data": f"controls queue {chat_id}",
                        }
                    ],
                    "align": "center",
                },
            ]
        )

        rich_message = {
            "blocks": blocks,
            "skip_entity_detection": True,
        }

        fields = {
            "chat_id": chat_id,
            "rich_message": rich_message,
        }

        files = None
        file_handle = None
        try:
            if thumb_path and os.path.exists(thumb_path):
                file_handle = open(thumb_path, "rb")
                files = {
                    "now_playing_thumb": (
                        os.path.basename(thumb_path),
                        file_handle,
                        "image/png",
                    )
                }
            result = await self._post("sendRichMessage", fields, files)
            return int(result["message_id"])
        finally:
            if file_handle:
                file_handle.close()
