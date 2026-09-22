import html as html_lib
import json
import os
import re
from typing import Any

import aiohttp


class RichMessageAPI:
    """Telegram Bot API Rich Message helper for the now-playing card."""

    def __init__(self, token: str):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        # message_id -> data needed when the progress row is edited.
        self._cards: dict[tuple[int, int], dict[str, Any]] = {}

    async def _post(
        self,
        method: str,
        fields: dict[str, Any],
        files: dict[str, tuple] | None = None,
    ):
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
                        f"Telegram {method} failed: "
                        f"{payload.get('description', 'unknown error')}"
                    )
                return payload["result"]

    @staticmethod
    def _clean_user(value: str | None) -> str:
        value = value or "Unknown"
        # media.user can be an HTML mention such as
        # <a href=tg://user?id=123>Name</a>. Rich blocks don't parse that
        # string as HTML, so remove the tags before displaying it.
        value = re.sub(r"<[^>]*>", "", str(value))
        return html_lib.unescape(value).strip() or "Unknown"

    @staticmethod
    def _seconds(value: str | int | float) -> int:
        if isinstance(value, (int, float)):
            return max(0, int(value))
        try:
            parts = [int(x) for x in str(value).split(":")]
            if len(parts) == 2:
                return max(0, parts[0] * 60 + parts[1])
            if len(parts) == 3:
                return max(0, parts[0] * 3600 + parts[1] * 60 + parts[2])
        except (TypeError, ValueError):
            pass
        return 0

    @staticmethod
    def _fmt(seconds: int) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    @classmethod
    def _progress_text(cls, elapsed: int, total: int) -> str:
        total = max(1, total)
        elapsed = min(max(0, elapsed), total)
        slots = 18
        pos = min(int((elapsed / total) * slots), slots - 1)
        track = "─" * pos + "●" + "─" * (slots - pos - 1)
        return f"{cls._fmt(elapsed)}  {track}  {cls._fmt(total)}"

    @classmethod
    def _blocks(
        cls,
        title: str,
        duration: str,
        requested_by: str,
        bot_name: str,
        queue_count: int,
        elapsed: int = 0,
        photo_file_id: str | None = None,
        chat_id: int = 0,
    ) -> list[dict[str, Any]]:
        total = cls._seconds(duration)
        clean_user = cls._clean_user(requested_by)
        blocks: list[dict[str, Any]] = []

        if photo_file_id:
            blocks.append(
                {
                    "type": "photo",
                    "photo": {"type": "photo", "media": photo_file_id},
                }
            )

        # RichTextBold objects are used instead of literal <b> tags because
        # paragraph blocks do not parse HTML strings.
        blocks.extend(
            [
                {
                    "type": "paragraph",
                    "text": [
                        "🎼  ",
                        {"type": "bold", "text": f"{bot_name}"},
                        "  🎵  |  [ NO ADS ]™",
                    ],
                },
                {
                    "type": "paragraph",
                    "text": ["🎧  ", {"type": "bold", "text": "MUSIC IS PLAYING"}],
                },
                {
                    "type": "paragraph",
                    "text": [
                        "🎵  ",
                        {"type": "bold", "text": "Now Playing : "},
                        title,
                    ],
                },
                {
                    "type": "paragraph",
                    "text": [
                        "⏱️  ",
                        {"type": "bold", "text": "TRACK DURATION : "},
                        duration,
                    ],
                },
                {
                    "type": "paragraph",
                    "text": [
                        "👤  ",
                        {"type": "bold", "text": "REQUESTED BY : "},
                        clean_user,
                    ],
                },
                {
                    "type": "paragraph",
                    "text": [
                        "🎶  ",
                        {"type": "bold", "text": "YOUR TRACK IS NOW PLAYING"},
                    ],
                },
                {
                    "type": "paragraph",
                    "text": [
                        "🔊  ",
                        {"type": "bold", "text": "SIT BACK, RELAX & ENJOY THE MUSIC"},
                    ],
                },
                {
                    # This is the actual live progress row. Telegram renders
                    # style=primary as the blue rounded button seen in the
                    # reference screenshot.
                    "type": "buttons",
                    "buttons": [
                        {
                            "text": cls._progress_text(elapsed, total),
                            "style": "primary",
                            "callback_data": f"controls status {chat_id}",
                        }
                    ],
                    "align": "center",
                },
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
                            "style": "danger",
                            "callback_data": f"controls queue {chat_id}",
                        }
                    ],
                    "align": "center",
                },
            ]
        )
        return blocks

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
        file_handle = None
        try:
            files = None
            photo_file_id = None
            if thumb_path and os.path.exists(thumb_path):
                file_handle = open(thumb_path, "rb")
                files = {
                    "now_playing_thumb": (
                        os.path.basename(thumb_path),
                        file_handle,
                        "image/png",
                    )
                }
                photo = {
                    "type": "photo",
                    "photo": {"type": "photo", "media": "attach://now_playing_thumb"},
                }
            else:
                photo = None

            blocks = self._blocks(
                title=title,
                duration=duration,
                requested_by=requested_by,
                bot_name=bot_name,
                queue_count=queue_count,
                elapsed=0,
                chat_id=chat_id,
            )
            if photo:
                blocks.insert(0, photo)

            result = await self._post(
                "sendRichMessage",
                {
                    "chat_id": chat_id,
                    "rich_message": {
                        "blocks": blocks,
                        "skip_entity_detection": True,
                    },
                },
                files,
            )
            message_id = int(result["message_id"])

            photo_file_id = None
            photos = result.get("photo") or []
            if photos:
                photo_file_id = photos[-1].get("file_id")

            self._cards[(chat_id, message_id)] = {
                "title": title,
                "duration": duration,
                "requested_by": requested_by,
                "bot_name": bot_name,
                "photo_file_id": photo_file_id,
            }
            return message_id
        finally:
            if file_handle:
                file_handle.close()

    async def update_now_playing(
        self,
        chat_id: int,
        message_id: int,
        elapsed: int,
        queue_count: int,
    ) -> None:
        card = self._cards.get((chat_id, message_id))
        if not card:
            return

        blocks = self._blocks(
            title=card["title"],
            duration=card["duration"],
            requested_by=card["requested_by"],
            bot_name=card["bot_name"],
            queue_count=queue_count,
            elapsed=elapsed,
            photo_file_id=card.get("photo_file_id"),
            chat_id=chat_id,
        )

        await self._post(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "rich_message": {"blocks": blocks, "skip_entity_detection": True},
            },
        )

    async def remove_card(self, chat_id: int, message_id: int) -> None:
        self._cards.pop((chat_id, message_id), None)
