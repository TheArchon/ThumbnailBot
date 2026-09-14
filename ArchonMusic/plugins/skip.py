from pyrogram import filters, types

from ArchonMusic import ArchonMusic, app, db, lang
from ArchonMusic.helpers import can_manage_vc


@app.on_message(filters.command(["skip", "next"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _skip(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    # Delete user's /skip or /next command immediately.
    try:
        await m.delete()
    except Exception:
        pass

    await ArchonMusic.play_next(m.chat.id, m.from_user.mention)

