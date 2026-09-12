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
    # Only these are real broadcast control flags. Any other argument beginning
    # with '-' is treated as broadcast text, so `/broadcast -user -hi` works.
    control_flags = {"-user", "-nochat", "-copy"}
    flags = {x.lower() for x in args if x.lower() in control_flags}
    msg = message.reply_to_message

    direct_text = None
    if not msg:
        text_parts = [x for x in args if x.lower() not in control_flags]
        if text_parts:
            # Allow `/broadcast -user -hi` to broadcast `hi`, not `-hi`.
            cleaned = []
            for part in text_parts:
                if part.startswith("-") and len(part) > 1:
                    part = part[1:]
                cleaned.append(part)
            direct_text = " ".join(cleaned).strip()
        if not direct_text:
            return await message.reply_text("Usage:\n/broadcast Your message here")

    # -user means users only. Otherwise broadcast to saved chats/groups.
    if "-user" in flags:
        targets = list(await db.get_users())
        target_type = "users"
    elif "-nochat" in flags:
        targets = list(await db.get_users())
        target_type = "users"
    else:
        targets = list(await db.get_chats())
        target_type = "chats"

    sent = await message.reply_text("❖ sᴛᴀʀᴛᴇᴅ ʙʀᴏᴀᴅᴄᴀsᴛɪɴɢ...")
    broadcasting = True
    count = 0

    try:
        for chat_id in targets:
            if not broadcasting:
                try:
                    await sent.edit_text(
                        message.lang["gcast_stopped"].format(count, 0)
                    )
                except Exception:
                    pass
                return

            try:
                if direct_text is not None:
                    await app.send_message(chat_id=chat_id, text=direct_text)
                elif "-copy" in flags:
                    await msg.copy(chat_id, reply_markup=msg.reply_markup)
                else:
                    await msg.forward(chat_id)

                count += 1
                await asyncio.sleep(0.1)

            except errors.FloodWait as fw:
                await asyncio.sleep(fw.value + 1)
                try:
                    if direct_text is not None:
                        await app.send_message(chat_id=chat_id, text=direct_text)
                    elif "-copy" in flags:
                        await msg.copy(chat_id, reply_markup=msg.reply_markup)
                    else:
                        await msg.forward(chat_id)
                    count += 1
                except Exception:
                    pass
            except Exception:
                # One blocked/deactivated/invalid target must not stop the
                # complete broadcast and must not create/send errors.txt.
                continue

    finally:
        broadcasting = False

    # Keep the STARTED BROADCASTING message visible.
    # Send the final result as a new reply to the original /broadcast command.
    if target_type == "users":
        final_text = f"❖ ʙʀσᴧᴅᴄᴧsᴛєᴅ ϻєssᴧɢє ᴛσ {count} υsєʀs."
    else:
        final_text = (
            f"❖ ʙʀσᴧᴅᴄᴧsᴛєᴅ ϻєssᴧɢє ᴛσ {count} "
            f"ᴄʜᴧᴛs ᴡɪᴛʜ 0 ᴘɪηs ғʀσϻ ᴛʜє ʙσᴛ."
        )

    try:
        await message.reply_text(final_text, quote=True)
    except Exception:
        try:
            await app.send_message(message.chat.id, final_text)
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
