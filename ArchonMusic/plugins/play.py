from pathlib import Path

from pyrogram import filters, types

from ArchonMusic import ArchonMusic, app, config, db, lang, queue, tg, yt
from ArchonMusic.helpers import buttons, utils
from ArchonMusic.helpers._play import checkUB


def playlist_to_queue(chat_id: int, tracks: list) -> str:
    text = "<blockquote expandable>"

    for track in tracks:
        pos = queue.add(chat_id, track)
        text += f"<b>{pos}.</b> {track.title}\n"

    text += "</blockquote>"
    return text[:2000]


@app.on_message(
    filters.command(["play", "playforce", "vplay", "vplayforce"])
    & filters.group
    & ~app.bl_users
)
@lang.language()
@checkUB
async def play_hndlr(
    _,
    m: types.Message,
    force: bool = False,
    m3u8: bool = False,
    video: bool = False,
    url: str = None,
) -> None:

    sent = await m.reply_text(m.lang["play_searching"])

    file = None
    tracks = []

    mention = (
        m.from_user.mention
        if m.from_user
        else "User"
    )

    media = (
        tg.get_media(m.reply_to_message)
        if m.reply_to_message
        else None
    )

    # --------------------------------------------------
    # REPLIED MEDIA
    # --------------------------------------------------
    if media:
        setattr(sent, "lang", m.lang)
        file = await tg.download(
            m.reply_to_message,
            sent,
        )

    # --------------------------------------------------
    # M3U8
    # --------------------------------------------------
    elif m3u8:
        file = await tg.process_m3u8(
            url,
            sent.id,
            video,
        )

    # --------------------------------------------------
    # URL
    # --------------------------------------------------
    elif url:

        if "playlist" in url.lower():
            await sent.edit_text(
                m.lang["playlist_fetch"]
            )

            tracks = await yt.playlist(
                config.PLAYLIST_LIMIT,
                mention,
                url,
                video,
            )

            if not tracks:
                return await sent.edit_text(
                    m.lang["playlist_error"]
                )

            file = tracks.pop(0)
            file.message_id = sent.id

        else:
            file = await yt.search(
                query=url,
                m_id=sent.id,
                video=video,
            )

        if not file:
            return await sent.edit_text(
                m.lang["play_not_found"].format(
                    config.SUPPORT_CHAT
                )
            )

    # --------------------------------------------------
    # SEARCH QUERY
    # --------------------------------------------------
    elif len(m.command) >= 2:

        query = " ".join(m.command[1:]).strip()

        if not query:
            return await sent.edit_text(
                m.lang["play_usage"]
            )

        file = await yt.search(
            query=query,
            m_id=sent.id,
            video=video,
        )

        if not file:
            return await sent.edit_text(
                m.lang["play_not_found"].format(
                    config.SUPPORT_CHAT
                )
            )

    # --------------------------------------------------
    # NOTHING FOUND
    # --------------------------------------------------
    if not file:
        return await sent.edit_text(
            m.lang["play_usage"]
        )

    # --------------------------------------------------
    # DURATION LIMIT
    # --------------------------------------------------
    duration = getattr(
        file,
        "duration_sec",
        0,
    ) or 0

    if duration > config.DURATION_LIMIT:
        return await sent.edit_text(
            m.lang["play_duration_limit"].format(
                config.DURATION_LIMIT // 60
            )
        )

    # --------------------------------------------------
    # LOGGER
    # --------------------------------------------------
    if await db.is_logger():
        try:
            await utils.play_log(
                m,
                sent.link,
                file.title,
                file.duration,
            )
        except Exception:
            pass

    file.user = mention

    # --------------------------------------------------
    # FORCE PLAY
    # --------------------------------------------------
    if force:
        queue.force_add(
            m.chat.id,
            file,
        )

    # --------------------------------------------------
    # NORMAL QUEUE
    # --------------------------------------------------
    else:
        position = queue.add(
            m.chat.id,
            file,
        )

        # Already playing / queued
        if (
            position != 0
            or await db.get_call(m.chat.id)
        ):
            queued_title = (
                file.title
                or "Unknown"
            )

            if len(queued_title) > 40:
                queued_title = (
                    queued_title[:40].rstrip()
                    + "..."
                )

            await sent.edit_text(
                m.lang["play_queued"].format(
                    position,
                    file.url,
                    queued_title,
                    file.duration,
                    mention,
                ),
                reply_markup=buttons.play_queued(
                    m.chat.id,
                    file.id,
                    m.lang["play_now"],
                ),
            )

            if tracks:
                added = playlist_to_queue(
                    m.chat.id,
                    tracks,
                )

                await app.send_message(
                    chat_id=m.chat.id,
                    text=m.lang[
                        "playlist_queued"
                    ].format(len(tracks))
                    + added,
                )

            return

    # --------------------------------------------------
    # DOWNLOAD / STREAM
    # --------------------------------------------------
    if not file.file_path:

        extension = (
            "mp4"
            if video
            else "webm"
        )

        fname = (
            f"downloads/{file.id}.{extension}"
        )

        if Path(fname).exists():
            file.file_path = fname

        else:
            try:
                file.file_path = await yt.stream_url(
                    file.id,
                    video=video,
                )
            except Exception:
                file.file_path = None

            # Fallback to normal download
            if not file.file_path:
                await sent.edit_text(
                    m.lang["play_downloading"]
                )

                try:
                    file.file_path, _ = (
                        await yt.download(
                            file.id,
                            video=video,
                        )
                    )
                except Exception as e:
                    return await sent.edit_text(
                        f"❌ Download failed:\n"
                        f"<code>{e}</code>"
                    )

    # --------------------------------------------------
    # PLAY
    # --------------------------------------------------
    try:
        await ArchonMusic.play_media(
            chat_id=m.chat.id,
            message=sent,
            media=file,
        )

    except Exception as e:
        return await sent.edit_text(
            f"❌ Playback failed:\n"
            f"<code>{e}</code>"
        )

    # --------------------------------------------------
    # PLAYLIST QUEUE
    # --------------------------------------------------
    if not tracks:
        return

    added = playlist_to_queue(
        m.chat.id,
        tracks,
    )

    await app.send_message(
        chat_id=m.chat.id,
        text=m.lang[
            "playlist_queued"
        ].format(len(tracks))
        + added,
        )
