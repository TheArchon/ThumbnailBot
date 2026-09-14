from pathlib import Path

from pyrogram import filters, types

from ArchonMusic import ArchonMusic, app, config, db, lang, logger, queue, tg, yt
from ArchonMusic.helpers import buttons, utils
from ArchonMusic.helpers._play import checkUB


def playlist_to_queue(chat_id: int, tracks: list) -> str:
    text = "<blockquote expandable>"
    for track in tracks:
        pos = queue.add(chat_id, track)
        text += f"<b>{pos}.</b> {track.title}\n"
    text = text[:1948] + "</blockquote>"
    return text

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
    mention = m.from_user.mention
    media = tg.get_media(m.reply_to_message) if m.reply_to_message else None
    tracks = []

    if media:
        setattr(sent, "lang", m.lang)
        file = await tg.download(m.reply_to_message, sent)

    elif m3u8:
        file = await tg.process_m3u8(url, sent.id, video)

    elif url:
        if "playlist" in url:
            await sent.edit_text(m.lang["playlist_fetch"])
            tracks = await yt.playlist(
                config.PLAYLIST_LIMIT, mention, url, video
            )

            if not tracks:
                return await sent.edit_text(m.lang["playlist_error"])

            file = tracks[0]
            tracks.remove(file)
            file.message_id = sent.id
        else:
            # A direct YouTube URL must be resolved from its video ID.
            # Sending the whole URL to the search API is unreliable and can
            # make /play <youtube-link> fail even though normal search works.
            if yt.valid(url):
                file = await yt.track_from_url(url, sent.id, video=video)
            else:
                file = await yt.search(url, sent.id, video=video)

        if not file:
            return await sent.edit_text(
                m.lang["play_not_found"].format(config.SUPPORT_CHAT)
            )

    elif len(m.command) >= 2:
        query = " ".join(m.command[1:])
        file = await yt.search(query, sent.id, video=video)
        if not file:
            return await sent.edit_text(
                m.lang["play_not_found"].format(config.SUPPORT_CHAT)
            )

    if not file:
        return await sent.edit_text(m.lang["play_usage"])

    if file.duration_sec > config.DURATION_LIMIT:
        return await sent.edit_text(
            m.lang["play_duration_limit"].format(config.DURATION_LIMIT // 60)
        )

    if await db.is_logger():
        if media:
            log_query = "Telegram media"
            log_stream_type = "telegram"
        elif m3u8:
            log_query = url or "M3U8"
            log_stream_type = "m3u8"
        elif url:
            log_query = url
            log_stream_type = "youtube"
        else:
            log_query = " ".join(m.command[1:]).strip() if len(m.command) > 1 else file.title
            log_stream_type = "youtube"

        await utils.play_log(
            m,
            sent.link,
            file.title,
            file.duration,
            query=log_query,
            stream_type=log_stream_type,
        )

    file.user = mention

    # Start the media download immediately after search resolution.
    # This overlaps API/download time with queue and message operations so
    # playback can begin as soon as possible.
    download_task = None
    if not file.file_path and getattr(file, "id", None):
        import asyncio
        download_task = asyncio.create_task(
            yt.stream_url(file.id, video=video)
        )

    if force:
        queue.force_add(m.chat.id, file)
    else:
        position = queue.add(m.chat.id, file)

        if position != 0 or await db.get_call(m.chat.id):
            queued_title = file.title or ""
            if len(queued_title) > 40:
                queued_title = queued_title[:40].rstrip() + "..."
            await sent.edit_text(
                m.lang["play_queued"].format(
                    position,
                    file.url,
                    queued_title,
                    file.duration,
                    m.from_user.mention,
                ),
                reply_markup=buttons.play_queued(
                    m.chat.id, file.id, m.lang["play_now"]
                ),
            )
            if tracks:
                added = playlist_to_queue(m.chat.id, tracks)
                await app.send_message(
                    chat_id=m.chat.id,
                    text=m.lang["playlist_queued"].format(len(tracks)) + added,
                )
            return

    if not file.file_path:
        fname = f"downloads/{file.id}.{'mp4' if video else 'webm'}"
        if Path(fname).exists() and Path(fname).stat().st_size > 1024:
            file.file_path = fname
        elif download_task:
            # The download has already been running in the background since
            # search completed, so awaiting it here avoids duplicate work.
            file.file_path = await download_task
            if not file.file_path:
                logger.error(f"[play] Media download failed for {file.id}")
                await sent.edit_text(m.lang["error_no_file"].format(config.SUPPORT_CHAT))
                return
        else:
            file.file_path = await yt.stream_url(file.id, video=video)
            if not file.file_path:
                logger.error(f"[play] No playable media available for {file.id}")
                await sent.edit_text(m.lang["error_no_file"].format(config.SUPPORT_CHAT))
                return

    await ArchonMusic.play_media(chat_id=m.chat.id, message=sent, media=file)
    if not tracks:
        return
    added = playlist_to_queue(m.chat.id, tracks)
    await app.send_message(
        chat_id=m.chat.id,
        text=m.lang["playlist_queued"].format(len(tracks)) + added,
    )
