from pyrogram import filters, types

from ArchonMusic import ArchonMusic, app, db, lang
from ArchonMusic.helpers import can_manage_vc


@app.on_message(filters.command(["skip", "next"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _skip(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    # Delete user's /skip or /next command
    try:
        await m.delete()
    except Exception:
        pass

    # Skip current song
    await ArchonMusic.play_next(m.chat.id)

    # Send skip message, then delete it
    try:
        msg = await app.send_message(
            m.chat.id,
            m.lang["play_skipped"].format(m.from_user.mention),
        )

        await msg.delete()
    except Exception:
        pass
