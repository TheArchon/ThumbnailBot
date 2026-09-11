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
        return sum(value * 60**i for i, value in enumerate(reversed(parts)))

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
                    link = text[entity.offset: entity.offset + entity.length]
                    break

        if link:
            return link.split("&si")[0].split("?si")[0]
        return None


    async def extract_user(self, msg: types.Message) -> types.User | None:
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


    async def play_log(
        self,
        m: types.Message,
        link: str = None,
        title: str = None,
        duration: str = None,
        query: str = None,
        stream_type: str = "youtube",
    ) -> None:
        if m.chat.id == app.logger:
            return

        chat = m.chat
        user = m.from_user
        chat_username = f"@{chat.username}" if chat.username else "N/A"
        username = f"@{user.username}" if user and user.username else "N/A"
        user_name = user.first_name if user and user.first_name else "N/A"

        _text = (
            f"● ᴄʜᴀᴛ ɪᴅ ➠ {chat.id}\n"
            f"● ᴄʜᴀᴛ ɴᴀᴍᴇ ➠ {chat.title or 'N/A'}\n"
            f"● ᴄʜᴀᴛ ᴜsᴇʀɴᴀᴍᴇ ➠ {chat_username}\n\n"
            f"● ᴜsᴇʀ ɪᴅ ➠ {user.id if user else 0}\n"
            f"● ɴᴀᴍᴇ ➠ {user_name}\n"
            f"● ᴜsᴇʀɴᴀᴍᴇ ➠ {username}\n\n"
            f"● ǫᴜᴇʀʏ ➠ {query or 'N/A'}\n"
            f"● sᴛʀᴇᴀᴍᴛʏᴘᴇ ➠ {stream_type or 'youtube'}"
        )
        await app.send_message(chat_id=app.logger, text=_text)

    async def send_log(self, m: types.Message, chat: bool = False) -> None:
        if chat:
            user = m.from_user
            return await app.send_message(
                chat_id=app.logger,
                text=m.lang["log_chat"].format(
                    m.chat.id,
                    m.chat.title,
                    user.id if user else 0,
                    user.mention if user else "Anonymous",
                ),
            )

        await app.send_message(
            chat_id=app.logger,
            text=m.lang["log_user"].format(
                m.from_user.id,
                f"@{m.from_user.username}",
                m.from_user.mention,
            ),
        )

    async def send_left_log(self, chat_id: int, chat_title: str, user: types.User = None) -> None:
        try:
            user_id = user.id if user else 0
            user_mention = user.mention if user else "Anonymous"
            text = (
                f"<u><b>● ʙᴏᴛ ʀᴇᴍᴏᴠᴇᴅ ʟᴏɢ</b></u>\n\n"
                f"<b>● ᴄʜᴀᴛ:</b> <code>{chat_id}</code> | {chat_title}\n"
                f"<b>● ʙʏ:</b> <code>{user_id}</code> | {user_mention}"
            )
            await app.send_message(chat_id=app.logger, text=text)
        except Exception:
            pass
