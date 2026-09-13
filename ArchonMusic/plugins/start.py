import asyncio
import os

from pyrogram import enums, filters, types
from pyrogram.enums import ButtonStyle

from ArchonMusic import app, config, db, lang, logger
from ArchonMusic.helpers import admin_check, buttons, utils

START_IMAGE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "start.jpg")


# /start is ONLY a welcome command.
# It must never enter the music/playback flow.
@app.on_message(filters.command(["start"]) & ~app.bl_users)
@lang.language()
async def start(_, message: types.Message):
    # Keep the blacklist behaviour separate from normal /start.
    if message.from_user and message.from_user.id in app.bl_users:
        if message.from_user.id in db.notified:
            return
        return await message.reply_text(message.lang["bl_user_notify"])

    # Telegram deep-link: /start help
    if len(message.command) > 1 and message.command[1].lower() == "help":
        if message.chat.type == enums.ChatType.PRIVATE:
            return await _help(_, message)

    private = message.chat.type == enums.ChatType.PRIVATE
    first_name = message.from_user.first_name if message.from_user else "User"

    text = (
        message.lang["start_pm"].format(first_name, app.name)
        if private
        else message.lang["start_gp"].format(app.name)
    )
    key = buttons.start_key(message.lang, private)

    # Use the local JPG instead of the old start video.
    try:
        await message.reply_photo(
            photo=START_IMAGE,
            caption=text,
            reply_markup=key,
            quote=not private,
        )
    except Exception as exc:
        # Last-resort fallback: still answer /start without buttons.
        logger.warning("/start reply failed: %s", exc)
        try:
            await message.reply_text(text=text, quote=not private)
        except Exception:
            return

    # Register the user/chat after the welcome message is sent.
    try:
        if private:
            if await db.is_user(message.from_user.id):
                return
            await utils.send_log(message)
            await db.add_user(message.from_user.id)
        else:
            if await db.is_chat(message.chat.id):
                return
            await utils.send_log(message, True)
            await db.add_chat(message.chat.id)
    except Exception as exc:
        # Database/logging failure must never break /start.
        logger.warning("/start registration failed: %s", exc)


@app.on_message(filters.command(["help"]) & filters.private & ~app.bl_users)
@lang.language()
async def _help(_, m: types.Message):
    await m.reply_text(
        text=m.lang["help_menu"],
        reply_markup=buttons.help_markup(m.lang),
        quote=True,
    )


@app.on_message(filters.command(["settings", "playmode"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def settings(_, message: types.Message):
    admin_only = await db.get_play_mode(message.chat.id)
    cmd_delete = await db.get_cmd_delete(message.chat.id)
    vclogger = await db.get_vclogger(message.chat.id)
    thumbnail = await db.get_thumb_mode(message.chat.id)
    autoplay = await db.get_autoplay(message.chat.id)
    _language = await db.get_lang(message.chat.id)
    await message.reply_text(
        text=message.lang["start_settings"].format(message.chat.title),
        reply_markup=buttons.settings_markup(
            message.lang,
            admin_only,
            cmd_delete,
            autoplay,
            vclogger,
            thumbnail,
            _language,
            message.chat.id,
        ),
        quote=True,
    )


@app.on_message(filters.new_chat_members, group=7)
@lang.language()
async def _new_member(_, message: types.Message):
    if message.chat.type != enums.ChatType.SUPERGROUP:
        return await message.chat.leave()

    await asyncio.sleep(3)
    for member in message.new_chat_members:
        if member.id == app.id:
            await utils.send_log(message, True)
            await db.add_chat(message.chat.id)

            adder = message.from_user.mention if message.from_user else "there"
            _text = message.lang["chat_added"].format(
                adder, app.name, message.lang["support"]
            )
            key = types.InlineKeyboardMarkup(
                [
                    [
                        types.InlineKeyboardButton(
                            text=message.lang["add_me"],
                            url=f"https://t.me/{app.username}?startgroup=true",
                            style=ButtonStyle.SUCCESS,
                        ),
                        types.InlineKeyboardButton(
                            text=message.lang["support"],
                            url=config.SUPPORT_CHAT,
                            style=ButtonStyle.PRIMARY,
                        ),
                    ]
                ]
            )
            try:
                await app.send_photo(
                    chat_id=message.chat.id,
                    photo=START_IMAGE,
                    caption=_text,
                    reply_markup=key,
                )
            except Exception:
                try:
                    await app.send_message(
                        chat_id=message.chat.id,
                        text=_text,
                        reply_markup=key,
                    )
                except Exception:
                    pass


@app.on_message(filters.left_chat_member, group=8)
async def _left_member(_, message: types.Message):
    if message.left_chat_member and message.left_chat_member.id == app.id:
        await utils.send_left_log(message.chat.id, message.chat.title, message.from_user)
        await db.rm_chat(message.chat.id)


@app.on_chat_member_updated()
async def _my_chat_member_updated(_, member: types.ChatMemberUpdated):
    if not member.old_chat_member or not member.new_chat_member:
        return

    old_status = member.old_chat_member.status
    new_status = member.new_chat_member.status

    if (
        old_status
        in [enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR]
        and new_status
        in [enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED]
    ):
        if member.new_chat_member.user and member.new_chat_member.user.id == app.id:
            await utils.send_left_log(member.chat.id, member.chat.title, member.from_user)
            await db.rm_chat(member.chat.id)
