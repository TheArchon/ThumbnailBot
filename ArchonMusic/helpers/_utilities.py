import re

from pyrogram import enums, types

from ArchonMusic import app


class Utilities:
    def __init__(self):
        pass

    # =========================================================
    # TIME / SIZE
    # =========================================================

    def format_eta(self, seconds: int) -> str:
        seconds = int(seconds or 0)

        if seconds < 60:
            return f"{seconds}s"

        if seconds < 3600:
            return f"{seconds // 60}:{seconds % 60:02d} min"

        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60

        return f"{h}:{m:02d}:{s:02d} h"

    def format_size(self, bytes: int) -> str:
        bytes = int(bytes or 0)

        if bytes >= 1024**3:
            return f"{bytes / 1024**3:.2f} GB"

        if bytes >= 1024**2:
            return f"{bytes / 1024**2:.2f} MB"

        return f"{bytes / 1024:.2f} KB"

    def to_seconds(self, time: str) -> int:
        parts = [int(p) for p in time.strip().split(":")]

        return sum(
            value * 60**i
            for i, value in enumerate(reversed(parts))
        )

    def format_duration(self, seconds: int) -> str:
        seconds = int(seconds or 0)

        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)

        if h:
            return f"{h}:{m:02d}:{s:02d}"

        return f"{m}:{s:02d}"

    # =========================================================
    # URL EXTRACTOR
    # =========================================================

    def get_url(
        self,
        message_1: types.Message,
    ) -> str | None:

        link = None
        messages = [message_1]

        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)

        for message in messages:

            entities = (
                message.entities
                or message.caption_entities
                or []
            )

            for entity in entities:

                if (
                    entity.type
                    == enums.MessageEntityType.TEXT_LINK
                ):
                    link = entity.url
                    break

                elif (
                    entity.type
                    == enums.MessageEntityType.URL
                ):
                    text = message.text or message.caption

                    if not text:
                        continue

                    link = text[
                        entity.offset:
                        entity.offset + entity.length
                    ]

                    break

        if link:
            return (
                link
                .split("&si")[0]
                .split("?si")[0]
            )

        return None

    # =========================================================
    # EXTRACT USER
    # =========================================================

    async def extract_user(
        self,
        msg: types.Message,
    ) -> types.User | None:

        if msg.reply_to_message:
            return msg.reply_to_message.from_user

        if msg.entities:

            for entity in msg.entities:

                if (
                    entity.type
                    == enums.MessageEntityType.TEXT_MENTION
                ):
                    return entity.user

        if msg.text:

            try:

                username_match = re.search(
                    r"@(\w{5,32})",
                    msg.text,
                )

                if username_match:
                    return await app.get_users(
                        username_match.group(0)
                    )

                id_match = re.search(
                    r"\b\d{6,15}\b",
                    msg.text,
                )

                if id_match:
                    return await app.get_users(
                        int(id_match.group(0))
                    )

            except Exception:
                pass

        return None

    # =========================================================
    # PLAY LOG
    # =========================================================

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

            # Do not log messages from logger itself
            if m.chat.id == app.logger:
                return

            chat = m.chat
            user = m.from_user

            # -------------------------
            # Chat username
            # -------------------------

            chat_username = (
                f"@{chat.username}"
                if chat.username
                else "N/A"
            )

            # -------------------------
            # User username
            # -------------------------

            username = (
                f"@{user.username}"
                if user and user.username
                else "N/A"
            )

            # -------------------------
            # User name
            # -------------------------

            user_name = (
                user.first_name
                if user and user.first_name
                else "N/A"
            )

            if user and user.last_name:
                user_name = (
                    f"{user_name} "
                    f"{user.last_name}"
                )

            # -------------------------
            # Log text
            # -------------------------

            _text = (
                f"❖ {app.mention} ᴘʟᴀʏ ʟᴏɢ\n\n"

                f"● ᴄʜᴀᴛ ɪᴅ ➠ {chat.id}\n"
                f"● ᴄʜᴀᴛ ɴᴀᴍᴇ ➠ "
                f"{chat.title or 'N/A'}\n"
                f"● ᴄʜᴀᴛ ᴜsᴇʀɴᴀᴍᴇ ➠ "
                f"{chat_username}\n\n"

                f"● ᴜsᴇʀ ɪᴅ ➠ "
                f"{user.id if user else 0}\n"
                f"● ɴᴀᴍᴇ ➠ {user_name}\n"
                f"● ᴜsᴇʀɴᴀᴍᴇ ➠ {username}\n\n"

                f"● ǫᴜᴇʀʏ ➠ "
                f"{query or 'N/A'}\n"
                f"● sᴛʀᴇᴀᴍᴛʏᴘᴇ ➠ "
                f"{stream_type or 'youtube'}"
            )

            await app.send_message(
                chat_id=app.logger,
                text=_text,
            )

        except Exception as e:
            print(f"PLAY LOG ERROR: {e}")

    # =========================================================
    # NEW USER / CHAT LOG
    # =========================================================

    async def send_log(
        self,
        m: types.Message,
        chat: bool = False,
    ) -> None:

        try:

            # =================================================
            # GROUP / CHAT LOG
            # =================================================

            if chat:

                user = m.from_user

                user_id = (
                    user.id
                    if user
                    else 0
                )

                user_name = (
                    user.first_name
                    if user and user.first_name
                    else "N/A"
                )

                if user and user.last_name:
                    user_name = (
                        f"{user_name} "
                        f"{user.last_name}"
                    )

                username = (
                    f"@{user.username}"
                    if user and user.username
                    else "N/A"
                )

                text = (
                    "● Nᴇᴡ Cʜᴀᴛ Lᴏɢ\n\n"

                    f"● Cʜᴀᴛ Iᴅ: "
                    f"{m.chat.id}\n"

                    f"● Cʜᴀᴛ Nᴀᴍᴇ: "
                    f"{m.chat.title or 'N/A'}\n"

                    f"● Cʜᴀᴛ Uѕᴇʀɴᴀᴍᴇ: "
                    f"{'@' + m.chat.username if m.chat.username else 'N/A'}\n\n"

                    f"● Iᴅ: {user_id}\n"
                    f"● Nᴀᴍᴇ: "
                    f"{username} | {user_name}"
                )

                return await app.send_message(
                    chat_id=app.logger,
                    text=text,
                )

            # =================================================
            # NEW USER LOG
            # =================================================

            user = m.from_user

            if not user:
                return

            user_id = user.id

            username = (
                f"@{user.username}"
                if user.username
                else "N/A"
            )

            name = (
                user.first_name
                if user.first_name
                else "N/A"
            )

            if user.last_name:
                name = (
                    f"{name} "
                    f"{user.last_name}"
                )

            # Exact desired format
            text = (
                "● Nᴇᴡ Usᴇʀ Lᴏɢ\n\n"

                f"● Iᴅ: {user_id}\n"

                f"● Nᴀᴍᴇ: "
                f"{username} | {name}"
            )

            await app.send_message(
                chat_id=app.logger,
                text=text,
            )

        except Exception as e:
            print(f"SEND LOG ERROR: {e}")

    # =========================================================
    # START LOG
    # =========================================================

    async def start_log(
        self,
        m: types.Message,
    ) -> None:

        try:

            user = m.from_user

            if not user:
                print(
                    "START LOG: from_user is None"
                )
                return

            user_id = user.id

            username = (
                f"@{user.username}"
                if user.username
                else "N/A"
            )

            name = (
                user.first_name
                if user.first_name
                else "N/A"
            )

            if user.last_name:
                name = (
                    f"{name} "
                    f"{user.last_name}"
                )

            text = (
                "● Nᴇᴡ Usᴇʀ Lᴏɢ\n\n"

                f"● Iᴅ: {user_id}\n"

                f"● Nᴀᴍᴇ: "
                f"{username} | {name}"
            )

            await app.send_message(
                chat_id=app.logger,
                text=text,
            )

        except Exception as e:
            print(f"START LOG ERROR: {e}")

    # =========================================================
    # BOT LEFT LOG
    # =========================================================

    async def send_left_log(
        self,
        chat_id: int,
        chat_title: str,
        user: types.User = None,
    ) -> None:

        try:

            user_id = (
                user.id
                if user
                else 0
            )

            username = (
                f"@{user.username}"
                if user and user.username
                else "N/A"
            )

            name = (
                user.first_name
                if user and user.first_name
                else "N/A"
            )

            if user and user.last_name:
                name = (
                    f"{name} "
                    f"{user.last_name}"
                )

            text = (
                "<u><b>"
                "● ʙᴏᴛ ʀᴇᴍᴏᴠᴇᴅ ʟᴏɢ"
                "</b></u>\n\n"

                f"<b>● ᴄʜᴀᴛ:</b> "
                f"<code>{chat_id}</code> | "
                f"{chat_title}\n"

                f"<b>● ʙʏ:</b> "
                f"<code>{user_id}</code> | "
                f"{username} | {name}"
            )

            await app.send_message(
                chat_id=app.logger,
                text=text,
            )

        except Exception as e:
            print(f"LEFT LOG ERROR: {e}")


# =========================================================
# GLOBAL UTILITIES INSTANCE
# =========================================================

utils = Utilities()
