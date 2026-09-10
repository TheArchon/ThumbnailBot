import os
import asyncio

from pyrogram import errors, filters, types

from ArchonMusic import app, db, lang


broadcasting = False


@app.on_message(filters.command(["broadcast"]) & app.sudoers)
@lang.language()
async def _broadcast(_, message: types.Message):
    global broadcasting

    # Direct broadcast text
    broadcast_text = message.text.split(None, 1)

    if len(broadcast_text) < 2 and not message.reply_to_message:
        return await message.reply_text(
            "Usage:\n/broadcast Your message here"
        )

    if broadcasting:
        return await message.reply_text(message.lang["gcast_active"])

    msg = message.reply_to_message
    direct_text = broadcast_text[1] if len(broadcast_text) > 1 else None

    count, ucount = 0, 0
    chats, groups, users = [], [], []

    sent = await message.reply_text(message.lang["gcast_start"])

    if "-nochat" not in message.command:
        groups.extend(await db.get_chats())

    if "-user" in message.command:
        users.extend(await db.get_users())

    chats.extend(groups + users)
    broadcasting = True

    failed = ""

    for chat in chats:
        if not broadcasting:
            await sent.edit_text(
                message.lang["gcast_stopped"].format(count, ucount)
            )
            break

        try:
            if direct_text:
                await app.send_message(
                    chat_id=chat,
                    text=direct_text
                )
            else:
                if "-copy" in message.text:
                    await msg.copy(
                        chat,
                        reply_markup=msg.reply_markup
                    )
                else:
                    await msg.forward(chat)

            if chat in groups:
                count += 1
            else:
                ucount += 1

            await asyncio.sleep(0.1)

        except errors.FloodWait as fw:
            await asyncio.sleep(fw.value + 30)

        except Exception as ex:
            failed += f"{chat} - {ex}\n"
            continue

    text = message.lang["gcast_end"].format(count, ucount)

    if failed:
        with open("errors.txt", "w") as f:
            f.write(failed)

        await message.reply_document(
            document="errors.txt",
            caption=text,
        )

        os.remove("errors.txt")

    broadcasting = False
    await sent.edit_text(text)


@app.on_message(
    filters.command(["stop_gcast", "stop_broadcast"]) & app.sudoers
)
@lang.language()
async def _stop_gcast(_, message: types.Message):
    global broadcasting

    if not broadcasting:
        return await message.reply_text(
            message.lang["gcast_inactive"]
        )

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
