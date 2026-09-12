import asyncio

from pyrogram import errors, filters, types

from ArchonMusic import app, db, lang


broadcasting = False


@app.on_message(filters.command(["broadcast"]) & app.sudoers)
@lang.language()
async def _broadcast(_, message: types.Message):
    global broadcasting

    if broadcasting:
        return await message.reply_text(message.lang["gcast_active"])

    command = message.command or []
    args = [str(x) for x in command[1:]]
    control_flags = {"-user", "-nochat", "-copy"}
    flags = {x.lower() for x in args if x.lower() in control_flags}
    msg = message.reply_to_message

    direct_text = None
    if not msg:
        text_parts = [x for x in args if x.lower() not in control_flags]
        if text_parts:
            cleaned = []
            for part in text_parts:
                if part.startswith("-") and len(part) > 1:
                    part = part[1:]
                cleaned.append(part)
            direct_text = " ".join(cleaned).strip()
        if not direct_text:
            return await message.reply_text("Usage:\n/broadcast Your message here")

    # `-user` broadcasts to BOTH saved chats and saved users.
    # Without `-user`, it broadcasts to saved chats only.
    chats = list(await db.get_chats())
    users = list(await db.get_users()) if "-user" in flags else []

    if not chats and not users:
        return await message.reply_text("No chats or users found.")

    sent = await message.reply_text("❖ sᴛᴀʀᴛᴇᴅ ʙʀᴏᴀᴅᴄᴀsᴛɪɴɢ...")
    broadcasting = True
    chat_count = 0
    user_count = 0

    async def send_to(target_id):
        if direct_text is not None:
            await app.send_message(chat_id=target_id, text=direct_text)
        elif "-copy" in flags:
            await msg.copy(target_id, reply_markup=msg.reply_markup)
        else:
            await msg.forward(target_id)

    try:
        # Send to chats first, then users.
        for chat_id in chats + users:
            if not broadcasting:
                break

            is_user = chat_id in users and "-user" in flags
            try:
                await send_to(chat_id)
                if is_user:
                    user_count += 1
                else:
                    chat_count += 1
                await asyncio.sleep(0.1)

            except errors.FloodWait as fw:
                await asyncio.sleep(fw.value + 1)
                try:
                    await send_to(chat_id)
                    if is_user:
                        user_count += 1
                    else:
                        chat_count += 1
                except Exception:
                    pass
            except Exception:
                continue
    finally:
        broadcasting = False

    chat_text = (
        f"❖ ʙʀσᴧᴅᴄᴧsᴛєᴅ ϻєssᴧɢє ᴛσ {chat_count} "
        f"ᴄʜᴧᴛs ᴡɪᴛʜ 0 ᴘɪηs ғʀσϻ ᴛʜє ʙσᴛ."
    )
    user_text = f"❖ ʙʀσᴧᴅᴄᴧsᴛєᴅ ϻєssᴧɢє ᴛσ {user_count} υsєʀs."

    # Always keep STARTED visible. Final results are replies to the original command.
    try:
        await message.reply_text(chat_text, quote=True)
        if "-user" in flags:
            await message.reply_text(user_text, quote=True)
    except Exception:
        try:
            await app.send_message(message.chat.id, chat_text)
            if "-user" in flags:
                await app.send_message(message.chat.id, user_text)
        except Exception:
            pass


@app.on_message(
    filters.command(["stop_gcast", "stop_broadcast"]) & app.sudoers
)
@lang.language()
async def _stop_gcast(_, message: types.Message):
    global broadcasting

    if not broadcasting:
        return await message.reply_text(message.lang["gcast_inactive"])

    broadcasting = False

    await (
        await app.send_message(
            chat_id=app.logger,
            text=message.lang["gcast_stop_log"].format(
                message.from_user.id,
                message.from_user.mention
            )
        )
    ).pin(disable_notification=False)

    await message.reply_text(message.lang["gcast_stop"])
