import asyncio
import re

from ntgcalls import (ConnectionNotFound, TelegramServerError,
                      RTMPStreamingUnsupported, ConnectionError)
from pyrogram.errors import (ChatSendMediaForbidden, ChatSendPhotosForbidden,
                             MessageIdInvalid)
from pyrogram.types import Message
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession

from ArchonMusic import (app, config, db, lang, logger,
                   queue, thumb, userbot, yt, rich)
from ArchonMusic.helpers import Media, Track


async def _noop():
    return None


class TgCall(PyTgCalls):
    def __init__(self):
        self.clients = []
        self.autoplay_history: dict[int, set] = {}
        # Background autoplay/next-track preparation. This lets related-track
        # lookup and media download happen while the current song is playing.
        self._autoplay_tasks: dict[int, asyncio.Task] = {}
        self._bot_avatar_path: str | None = None
        # Caches each user's downloaded profile-photo file path after the
        # first lookup. Without this, the SAME user replaying/queuing
        # multiple tracks in a row re-did a Telegram profile-photo
        # lookup + download every single time, adding needless delay to
        # every "now playing" thumbnail after the first.
        self._user_avatar_cache: dict[int, str | None] = {}

    async def pause(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=True)
        return await client.pause(chat_id)

    async def resume(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=False)
        return await client.resume(chat_id)

    async def stop(self, chat_id: int) -> None:
        client = await db.get_assistant(chat_id)
        queue.clear(chat_id)
        await db.remove_call(chat_id)
        await db.set_loop(chat_id, 0)
        self.autoplay_history.pop(chat_id, None)

        task = self._autoplay_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

        try:
            await client.leave_call(chat_id, close=False)
        except Exception:
            pass


    async def _fetch_user_avatar(self, media: Media | Track) -> str | None:
        """Downloads the Telegram profile photo of whoever requested
        `media` so the thumbnail's small square slot can show the
        REQUESTING USER's picture instead of the track's cover art.

        `Track`'s real fields don't include a dedicated `user_id`, but
        `media.user` is already used elsewhere in this file (see the
        `text.format(...)` call below), so this resolves an id from
        whatever `media.user` actually is: a raw int id, a Pyrogram
        `User`-like object (has `.id`), or a numeric string. A few other
        common field names are tried first in case they exist. Returns
        None on any failure so thumbnail generation still falls back
        gracefully to the cover art — this must never block playback.
        """
        candidate = (
            getattr(media, "user_id", None)
            or getattr(media, "requested_by", None)
            or getattr(media, "from_user_id", None)
            or getattr(media, "uid", None)
            or getattr(media, "user", None)
        )

        user_id = None
        if isinstance(candidate, int):
            user_id = candidate
        elif hasattr(candidate, "id"):
            user_id = candidate.id
        elif isinstance(candidate, str):
            # media.user here is an HTML mention link, e.g.:
            #   '<a href=tg://user?id=7505121412>Some Name</a>'
            # pull the numeric id straight out of the tg://user?id= part.
            match = re.search(r"user\?id=(\d+)", candidate)
            if match:
                user_id = int(match.group(1))
            elif candidate.lstrip("-").isdigit():
                user_id = int(candidate)

        if not user_id:
            # "Autoplay" is a known placeholder media.user carries for
            # system-queued tracks nobody explicitly requested — this is
            # expected, not an error, so don't spam the logs for it.
            if not (isinstance(candidate, str) and candidate.strip().lower() == "autoplay"):
                logger.warning(
                    "[_fetch_user_avatar] could not resolve a usable user id; "
                    f"media.user was type={type(candidate).__name__!r} value={candidate!r}"
                )
            return None

        if user_id in self._user_avatar_cache:
            return self._user_avatar_cache[user_id]

        result = None
        try:
            async for photo in app.get_chat_photos(user_id, limit=1):
                result = await app.download_media(photo.file_id)
                break
            else:
                logger.warning(
                    f"[_fetch_user_avatar] user {user_id} has no profile photo"
                )
        except Exception as e:
            logger.warning(f"[_fetch_user_avatar] failed for user {user_id}: {e!r}")

        self._user_avatar_cache[user_id] = result
        return result


    async def _fetch_bot_avatar(self) -> str | None:
        """Downloads the BOT's own Telegram profile picture, used as the
        square-slot fallback when there's no requesting user to show
        (e.g. autoplay-queued tracks, which nobody explicitly requested).
        Cached after the first successful fetch since the bot's own
        picture doesn't change mid-run. Returns None on any failure so
        thumbnail generation still falls back to the cover art."""
        if self._bot_avatar_path:
            return self._bot_avatar_path
        try:
            me = await app.get_me()
            if me.photo:
                self._bot_avatar_path = await app.download_media(me.photo.big_file_id)
                return self._bot_avatar_path
            logger.warning("[_fetch_bot_avatar] bot has no profile photo")
        except Exception as e:
            logger.warning(f"[_fetch_bot_avatar] failed: {e!r}")
        return None


    async def play_media(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        seek_time: int = 0,
    ) -> None:
        # NOTE: Thumbnail/avatar fetching was previously done HERE, before
        # client.play(), which blocked actual playback start behind two
        # Telegram API round-trips + image generation (often adding
        # several seconds of delay before any audio was heard). It has
        # been moved to `_send_now_playing`, which now runs as a
        # fire-and-forget background task AFTER playback has started.
        client, _lang = await asyncio.gather(
            db.get_assistant(chat_id),
            lang.get_lang(chat_id),
        )

        if not media.file_path:
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            return await self.stop(chat_id)

        # Auto-reconnect if the download API's connection drops mid-stream
        # instead of failing outright. (Note: we don't shrink ffmpeg's
        # probesize/analyzeduration here — doing so previously caused
        # "Audio source not found" failures on some streams because
        # ffmpeg didn't get enough data to detect the audio codec before
        # giving up.)
        ffmpeg_extra = ""
        if str(media.file_path).startswith("http"):
            ffmpeg_extra = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 3"
        if seek_time > 1:
            ffmpeg_extra = f"-ss {seek_time} {ffmpeg_extra}".strip()

        stream = types.MediaStream(
            media_path=media.file_path,
            audio_parameters=types.AudioQuality.HIGH,
            video_parameters=types.VideoQuality.HD_720p,
            audio_flags=types.MediaStream.Flags.REQUIRED,
            video_flags=(
                types.MediaStream.Flags.AUTO_DETECT
                if media.video
                else types.MediaStream.Flags.IGNORE
            ),
            ffmpeg_parameters=ffmpeg_extra or None,
        )
        try:
            await client.play(
                chat_id=chat_id,
                stream=stream,
                config=types.GroupCallConfig(auto_start=False),
            )
            if not seek_time:
                media.time = 1
                await db.add_call(chat_id)
                # Playback has already started at this point. Sending the
                # "now playing" message/thumbnail is UI-only and must not
                # delay the next line of audio, so it runs in the
                # background instead of being awaited here.
                asyncio.create_task(
                    self._send_now_playing(chat_id, message, media, _lang)
                )
        except FileNotFoundError:
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            await self.stop(chat_id)
        except exceptions.NoActiveGroupCall:
            await self.stop(chat_id)
            await message.edit_text(_lang["error_no_call"])
        except exceptions.NoAudioSourceFound:
            await message.edit_text(_lang["error_no_audio"])
            await self.stop(chat_id)
        except (ConnectionError, ConnectionNotFound, TelegramServerError):
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
        except RTMPStreamingUnsupported:
            await self.stop(chat_id)
            await message.edit_text(_lang["error_rtmp"])


    async def _resolve_now_playing_avatar(self, media: Media | Track) -> str | None:
        """Requesting user's avatar, falling back to the bot's own —
        wrapped as one coroutine so calls.py can fire it off as a single
        background task that overlaps with the cover-art download."""
        avatar = await self._fetch_user_avatar(media)
        if not avatar:
            avatar = await self._fetch_bot_avatar()
        return avatar

    async def _send_now_playing(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        _lang: dict,
    ) -> None:
        """Builds and sends/edits the 'now playing' message with its
        thumbnail. Runs as a background task (fire-and-forget) so that
        avatar downloads + image generation never delay audio playback,
        which has already started by the time this runs. Any failure
        here is logged and swallowed — it must never crash or block
        anything else, since playback is already underway."""
        try:
            _thumb_mode = await db.get_thumb_mode(chat_id)
            _thumb = None
            if config.THUMB_GEN and _thumb_mode:
                if isinstance(media, Track):
                    _thumb = await thumb.generate(media, user_avatar=None)
                else:
                    _thumb = config.DEFAULT_THUMB

            title = media.title or ""
            title = title.split("#")[0].strip()
            if len(title) > 25:
                title = title[:25].rstrip() + "..."

            # Bot API 10.3 Rich Messages allow the photo, text and controls
            # to live inside ONE Telegram message/card. This replaces the
            # older InlineKeyboardMarkup, whose buttons are rendered below
            # the message as a separate keyboard area.
            queue_count = max(0, len(queue.get_queue(chat_id)) - 1)
            try:
                rich_id = await rich.send_now_playing(
                    chat_id=chat_id,
                    title=title,
                    duration=media.duration,
                    requested_by=media.user,
                    thumb_path=_thumb,
                    bot_name=config.BOT_NAME,
                    queue_count=queue_count,
                )
                media.message_id = rich_id

                # Delete the temporary/loading message. The Rich Message is
                # now the only player message and owns its embedded controls.
                try:
                    if message.id != rich_id:
                        await message.delete()
                except Exception:
                    pass
                return
            except Exception as rich_error:
                # Do not fall back to the old InlineKeyboard player: that
                # creates the duplicate buttons underneath the Rich Message.
                logger.exception(
                    f"[RichMessage] failed to render player for chat {chat_id}: {rich_error!r}"
                )
                return

        except Exception as e:
            logger.warning(
                f"[_send_now_playing] failed for chat {chat_id}: {e!r}"
            )

    async def ping(self) -> float:
        pings = [client.ping for client in self.clients]
        return round(sum(pings) / len(pings), 2)


    async def _delete_msg(self, message: Message, delay: int = 2):
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except Exception:
            pass

    async def decorators(self, client: PyTgCalls) -> None:
        @client.on_update()
        async def update_handler(_, update: types.Update) -> None:
            if isinstance(update, types.UpdatedGroupCallParticipant):
                if not await db.get_vclogger(update.chat_id):
                    return
                try:
                    user = await app.get_users(update.participant.user_id)
                except Exception:
                    return

                _lang = await lang.get_lang(update.chat_id)
                if update.action == types.GroupCallParticipant.Action.JOINED:
                    text = _lang["vclog_joined"].format(user.mention, user.id)
                elif update.action == types.GroupCallParticipant.Action.LEFT:
                    text = _lang["vclog_left"].format(user.mention, user.id)
                else:
                    return

                try:
                    sent = await app.send_message(update.chat_id, text)
                    asyncio.create_task(self._delete_msg(sent))
                except Exception:
                    pass
            elif isinstance(update, types.StreamEnded):
                if update.stream_type == types.StreamEnded.Type.AUDIO:
                    await self.play_next(update.chat_id)
            elif isinstance(update, types.ChatUpdate):
                if update.status in [
                    types.ChatUpdate.Status.KICKED,
                    types.ChatUpdate.Status.LEFT_GROUP,
                    types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
                ]:
                    await self.stop(update.chat_id)


    async def boot(self) -> None:
        PyTgCallsSession.notice_displayed = True
        for ub in userbot.clients:
            client = PyTgCalls(ub, cache_duration=100)
            await client.start()
            self.clients.append(client)
            await self.decorators(client)
        logger.info("PyTgCalls client(s) started.")
