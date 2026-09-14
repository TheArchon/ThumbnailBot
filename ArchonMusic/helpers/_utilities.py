import re

from pyrogram import enums, types

from ArchonMusic import app


class Utilities:
    def __init__(self):
        pass

    def format_eta(self, seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}:{seconds % 60:02d} min"
        else:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            return f"{h}:{m:02d}:{s:02d} h"

    def format_size(self, bytes: int) -> str:
        if bytes >= 1024**3:
            return f"{bytes / 1024 ** 3:.2f} GB"
        elif bytes >= 1024**2:
            return f"{bytes / 1024 ** 2:.2f} MB"
        else:
            return f"{bytes / 1024:.2f} KB"

    def to_seconds(self, time: str) -> int:
        parts = [int(p) for p in time.strip().split(":")]
        return sum(
            value * 60**i for i, value in enumerate(reversed(parts))
        )

    def format_duration(self, seconds: int) -> str:
        seconds = int(seconds or 0)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)

        if h:
            return f"{h}:{m:02d}:{s:02d}"

        return f"{m}:{s:02d}"

    def get_url(self, message_1: types.Message) -> str | None:
        link = None
        messages = [message_1]

        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)

        for message in messages:
            entities = message.entities or message.caption_entities or []

            for entity in entities:
                if entity.type == enums.MessageEntityType.TEXT_LINK:
                    link = entity.url
                    break

                elif entity.type == enums.MessageEntityType.URL:
                    text = message.text or message.caption

                    if not text:
                        continue

                    link = text[
                        entity.offset : entity.offset + entity.length
                    ]
                    break

        if link:
            return link.split("&si")[0].split("?si")[0]

        return None

    async def extract_user(
        self, msg: types.Message
    ) -> types.User | None:
        if msg.reply_to_message:
            return msg.reply_to_message.from_user

        if msg.entities:
            for e in msg.entities:
                if e.type == enums.MessageEntityType.TEXT_MENTION:
                    return e.user

        if msg.text:
            try:
                if m := re.search(r"@(\w{5,32})", msg.text):
                    return await app.get_users(m.group(0))

                if m := re.search(r"\b\d{6,15}\b", msg.text):
                    return await app.get_users(int(m.group(0)))

            except Exception:
                pass

        return None

    # ==========================================================
    # PLAY LOG
    # ==========================================================

    async def play_log(
        self,
        m: types.Message,
        link: str = None,
        title: str = None,
        duration: str = None,
        query: str = None,
        stream_type: str = "youtube",
    ) -> None:
        try:
            if not m or not m.chat:
                return

            # Do not log messages from logger chat itself
            if m.chat.id == app.logger:
                return

            chat = m.chat
            user = m.from_user

            # -----------------------------
            # Chat information
            # -----------------------------
            chat_username = (
                f"@{chat.username}"
                if chat.username
                else "N/A"
            )

            chat_name = chat.title or "Private Chat"

            # -----------------------------
            # User information
            # -----------------------------
            user_id = user.id if user else 0

            username = (
                f"@{user.username}"
                if user and user.username
                else "N/A"
            )

            if user:
                first_name = user.first_name or ""
                last_name = user.last_name or ""

                full_name = (
                    f"{first_name} {last_name}".strip()
                    or "N/A"
                )
            else:
                full_name = "Anonymous"

            # -----------------------------
            # Song information
            # -----------------------------
            song_title = title or query or "N/A"
            song_duration = duration or "N/A"
            song_link = link or "N/A"
            stream = stream_type or "youtube"

            # -----------------------------
            # Logger message
            # -----------------------------
            text = (
                "● Pʟᴀʏ Lᴏɢ\n\n"
                f"● Cʜᴀᴛ Iᴅ: {chat.id}\n"
                f"● Cʜᴀᴛ Nᴀᴍᴇ: {chat_name}\n"
                f"● Cʜᴀᴛ Usᴇʀɴᴀᴍᴇ: {chat_username}\n\n"
                f"● Iᴅ: {user_id}\n"
                f"● Nᴀᴍᴇ: {username} | {full_name}\n\n"
                f"● Sᴏɴɢ: {song_title}\n"
                f"● Dᴜʀᴀᴛɪᴏɴ: {song_duration}\n"
                f"● Sᴛʀᴇᴀᴍ: {stream}\n"
                f"● Lɪɴᴋ: {song_link}"
            )

            await app.send_message(
                chat_id=app.logger,
                text=text,
            )

        except Exception as e:
            print(f"PLAY LOG ERROR: {e}")

    # ==========================================================
    # NEW USER / NEW CHAT LOG
    # ==========================================================

    async def send_log(
        self,
        m: types.Message,
        chat: bool = False,
    ) -> None:
        try:
            if not m:
                return

            # -----------------------------
            # NEW CHAT LOG
            # -----------------------------
            if chat:
                user = m.from_user

                user_id = user.id if user else 0

                username = (
                    f"@{user.username}"
                    if user and user.username
                    else "N/A"
                )

                if user:
                    first_name = user.first_name or ""
                    last_name = user.last_name or ""

                    full_name = (
                        f"{first_name} {last_name}".strip()
                        or "N/A"
                    )
                else:
                    full_name = "Anonymous"

                chat_name = m.chat.title or "N/A"

                text = (
                    "● Nᴇᴡ Cʜᴀᴛ Lᴏɢ\n\n"
                    f"● Cʜᴀᴛ Iᴅ: {m.chat.id}\n"
                    f"● Cʜᴀᴛ Nᴀᴍᴇ: {chat_name}\n\n"
                    f"● Iᴅ: {user_id}\n"
                    f"● Nᴀᴍᴇ: {username} | {full_name}"
                )

                return await app.send_message(
                    chat_id=app.logger,
                    text=text,
                )

            # -----------------------------
            # NEW USER LOG
            # -----------------------------
            user = m.from_user

            if not user:
                return

            user_id = user.id

            username = (
                f"@{user.username}"
                if user.username
                else "N/A"
            )

            first_name = user.first_name or ""
            last_name = user.last_name or ""

            full_name = (
                f"{first_name} {last_name}".strip()
                or "N/A"
            )

            text = (
                "● Nᴇᴡ Usᴇʀ Lᴏɢ\n\n"
                f"● Iᴅ: {user_id}\n"
                f"● Nᴀᴍᴇ: {username} | {full_name}"
            )

            await app.send_message(
                chat_id=app.logger,
                text=text,
            )

        except Exception as e:
            print(f"USER/CHAT LOG ERROR: {e}")

    # ==========================================================
    # BOT REMOVED LOG
    # ==========================================================

    async def send_left_log(
        self,
        chat_id: int,
        chat_title: str,
        user: types.User = None,
    ) -> None:
        try:
            user_id = user.id if user else 0

            username = (
                f"@{user.username}"
                if user and user.username
                else "N/A"
            )

            if user:
                first_name = user.first_name or ""
                last_name = user.last_name or ""

                full_name = (
                    f"{first_name} {last_name}".strip()
                    or "N/A"
                )
            else:
                full_name = "Anonymous"

            text = (
                "● Bᴏᴛ Rᴇᴍᴏᴠᴇᴅ Lᴏɢ\n\n"
                f"● Cʜᴀᴛ: {chat_id} | {chat_title}\n"
                f"● Iᴅ: {user_id}\n"
                f"● Nᴀᴍᴇ: {username} | {full_name}"
            )

            await app.send_message(
                chat_id=app.logger,
                text=text,
            )

        except Exception as e:
            print(f"LEFT LOG ERROR: {e}")
