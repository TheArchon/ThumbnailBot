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
    mention = m.from_user.mention
    tracks = []

    media = (
        tg.get_media(m.reply_to_message)
        if m.reply_to_message
        else None
    )

    # Telegram media
    if media:
        setattr(sent, "lang", m.lang)

        file = await tg.download(
            m.reply_to_message,
            sent,
        )

    # M3U8
    elif m3u8:
        file = await tg.process_m3u8(
            url,
            sent.id,
            video,
        )

    # URL
    elif url:

        # Playlist
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

        # Single YouTube URL
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

    # Search query
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

    # Nothing provided
    if not file:
        return await sent.edit_text(
            m.lang["play_usage"]
        )

    # Duration check
    duration_sec = int(
        getattr(file, "duration_sec", 0) or 0
    )

    if duration_sec > config.DURATION_LIMIT:
        return await sent.edit_text(
            m.lang["play_duration_limit"].format(
                config.DURATION_LIMIT // 60
            )
        )

    # Logger
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

    # Force play
    if force:
        queue.force_add(
            m.chat.id,
            file,
        )

    # Normal queue
    else:
        position = queue.add(
            m.chat.id,
            file,
        )

        # Already playing / queued
        if position != 0 or await db.get_call(m.chat.id):

            queued_title = file.title or ""

            if len(queued_title) > 40:
                queued_title = (
                    queued_title[:40].rstrip() + "..."
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

            # Add remaining playlist tracks
            if tracks:
                added = playlist_to_queue(
                    m.chat.id,
                    tracks,
                )

                await app.send_message(
                    chat_id=m.chat.id,
                    text=m.lang["playlist_queued"].format(
                        len(tracks)
                    ) + added,
                )

            return

    # --------------------------------------------------
    # Download / stream
    # --------------------------------------------------

    if not getattr(file, "file_path", None):

        extension = "mp4" if video else "webm"
        local_path = (
            f"downloads/{file.id}.{extension}"
        )

        # Existing local file
        if Path(local_path).exists() and Path(local_path).stat().st_size > 0:

            file.file_path = local_path

        else:

            # Try stream URL first
            try:
                stream_path = await yt.stream_url(
                    file.id,
                    video=video,
                )
            except Exception as e:
                stream_path = None
                print(
                    f"[YouTube] stream_url failed: {e}"
                )

            if stream_path:
                file.file_path = stream_path

            else:
                # Download
                await sent.edit_text(
                    m.lang["play_downloading"]
                )

                try:
                    result = await yt.download(
                        file.id,
                        video=video,
                    )

                    # IMPORTANT:
                    # yt.download() returns a single path.
                    # Do NOT use:
                    # file.file_path, _ = result

                    if isinstance(result, tuple):
                        file.file_path = (
                            result[0]
                            if result
                            else None
                        )
                    else:
                        file.file_path = result

                except Exception as e:
                    print(
                        f"[YouTube] Download failed: {e}"
                    )

                    return await sent.edit_text(
                        f"❌ Download failed:\n"
                        f"<code>{str(e)[:1000]}</code>"
                    )

                if not file.file_path:
                    return await sent.edit_text(
                        m.lang["play_not_found"].format(
                            config.SUPPORT_CHAT
                        )
                    )

    # --------------------------------------------------
    # Start playback
    # --------------------------------------------------

    try:
        await ArchonMusic.play_media(
            chat_id=m.chat.id,
            message=sent,
            media=file,
        )

    except Exception as e:
        print(
            f"[Play] play_media failed: {e}"
        )

        return await sent.edit_text(
            f"❌ Playback failed:\n"
            f"<code>{str(e)[:1000]}</code>"
        )

    # --------------------------------------------------
    # Add remaining playlist songs
    # --------------------------------------------------

    if not tracks:
        return

    added = playlist_to_queue(
        m.chat.id,
        tracks,
    )

    await app.send_message(
        chat_id=m.chat.id,
        text=m.lang["playlist_queued"].format(
            len(tracks)
        ) + added,
            )
