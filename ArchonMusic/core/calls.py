import asyncio
import re

from ntgcalls import (ConnectionNotFound, TelegramServerError,
                      RTMPStreamingUnsupported, ConnectionError)
from pyrogram.errors import (ChatSendMediaForbidden, ChatSendPhotosForbidden,
                             MessageIdInvalid)
from pyrogram.types import InputMediaPhoto, Message
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession

from ArchonMusic import (app, config, db, lang, logger,
                   queue, thumb, userbot, yt)
from ArchonMusic.helpers import Media, Track, buttons


async def _noop():
    return None


class TgCall(PyTgCalls):
    def __init__(self):
        self.clients = []
        self.autoplay_history: dict[int, set] = {}
        self.autoplay_title_history: dict[int, set] = {}
        self._autoplay_locks: dict[int, asyncio.Lock] = {}
        self._next_locks: dict[int, asyncio.Lock] = {}
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
        self.autoplay_title_history.pop(chat_id, None)
        self._autoplay_locks.pop(chat_id, None)
        self._next_locks.pop(chat_id, None)

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
                config=types.GroupCallConfig(auto_start=True),
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
                # Prepare the next queued/autoplay track while this one is
                # playing, so /skip and automatic transition are immediate.
                asyncio.create_task(self._prefetch_next(chat_id))
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

            text = _lang["play_media"].format(
                media.url,
                title,
                media.duration,
                media.user,
            )
            keyboard = buttons.controls(chat_id)
            try:
                if _thumb:
                    await message.edit_media(
                        media=InputMediaPhoto(
                            media=_thumb,
                            caption=text,
                        ),
                        reply_markup=keyboard,
                    )
                else:
                    await message.edit_text(text, reply_markup=keyboard)
            except (ChatSendMediaForbidden, ChatSendPhotosForbidden, MessageIdInvalid):
                if _thumb:
                    sent = await app.send_photo(
                        chat_id=chat_id,
                        photo=_thumb,
                        caption=text,
                        reply_markup=keyboard,
                    )
                else:
                    sent = await app.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                    )
                media.message_id = sent.id
        except Exception as e:
            logger.warning(f"[_send_now_playing] failed for chat {chat_id}: {e!r}")


    async def replay(self, chat_id: int) -> None:
        if not await db.get_call(chat_id):
            return

        media = queue.get_current(chat_id)
        _lang = await lang.get_lang(chat_id)
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_again"])
        media.message_id = msg.id
        await self.play_media(chat_id, msg, media)


    async def _autoplay_next(self, chat_id: int, finished) -> "Track | None":
        """Ensure one autoplay track is queued and return it.

        This is guarded because StreamEnded and a manual /skip can arrive
        close together. Re-checking the queue inside the lock prevents two
        autoplay songs from being inserted for the same finished track.
        """
        existing = queue.get_next(chat_id, check=True)
        if existing:
            return existing

        video_id = getattr(finished, "id", None)
        if not video_id:
            return None

        lock = self._autoplay_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            existing = queue.get_next(chat_id, check=True)
            if existing:
                return existing

            history = self.autoplay_history.setdefault(chat_id, set())
            title_history = self.autoplay_title_history.setdefault(chat_id, set())
            history.add(str(video_id))

            # Exclude both video IDs AND normalized song titles. YouTube often
            # returns another upload/remix of the exact same song with a new ID.
            queued = queue.get_queue(chat_id)
            queued_ids = {str(item.id) for item in queued if getattr(item, "id", None)}
            queued_titles = {
                re.sub(r"\W+", " ", str(getattr(item, "title", "") or "").lower()).strip()
                for item in queued
                if getattr(item, "title", None)
            }
            exclude = history | queued_ids
            exclude_titles = title_history | queued_titles

            track = await yt.autoplay_track(
                video_id,
                video=getattr(finished, "video", False),
                exclude=exclude,
                exclude_titles=exclude_titles,
                title=getattr(finished, "title", None),
                channel_name=getattr(finished, "channel_name", None),
            )
            if not track:
                return None

            # Never insert the currently playing/queued track again, even if
            # YouTube returns a different video ID for the same song title.
            normalized_track_title = re.sub(
                r"\W+", " ", str(getattr(track, "title", "") or "").lower()
            ).strip()
            if str(track.id) in exclude:
                return None

            # youtube.py already performs fuzzy same-song filtering. Keep a
            # second guard here so a different video ID cannot slip through
            # because of a slightly different upload title.
            try:
                if any(yt._same_song(track.title, old) for old in exclude_titles if old):
                    return None
            except Exception:
                if normalized_track_title and normalized_track_title in exclude_titles:
                    return None

            history.add(str(track.id))
            if normalized_track_title:
                title_history.add(normalized_track_title)
            if getattr(track, "title", None):
                title_history.add(track.title)
            track.user = "Autoplay"
            queue.add(chat_id, track)
            return track


    async def play_next(self, chat_id: int) -> None:
        # Always wait for an in-progress transition instead of silently
        # dropping /skip. This matters when autoplay is preparing the next
        # track at the same moment a user presses Skip.
        lock = self._next_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            await self._play_next(chat_id)

    async def _play_next(self, chat_id: int) -> None:
        if loop := await db.get_loop(chat_id):
            await db.set_loop(chat_id, loop - 1)
            return await self.replay(chat_id)

        finished = queue.get_current(chat_id)
        media = queue.get_next(chat_id)

        # If there is no queued item, generate the autoplay item before
        # accessing media.message_id.
        if not media and finished and await db.get_autoplay(chat_id):
            media = await self._autoplay_next(chat_id, finished)

        try:
            if media and media.message_id:
                await app.delete_messages(
                    chat_id=chat_id,
                    message_ids=media.message_id,
                    revoke=True,
                )
                media.message_id = 0
        except Exception:
            pass

        if not media:
            return await self.stop(chat_id)

        _lang, msg = await asyncio.gather(
            lang.get_lang(chat_id),
            app.send_message(chat_id=chat_id, text="Loading..."),
        )

        if not media.file_path:
            # Stream directly from the download API's URL — ffmpeg plays
            # off it directly, so this is near-instant vs. waiting for a
            # full download to disk. Falls back to a full download() only
            # if the API didn't return valid media for this video (rare).
            media.file_path = await yt.stream_url(media.id, video=media.video)
            if not media.file_path:
                media.file_path = await yt.download(media.id, video=media.video)
            if not media.file_path:
                # No retry, no next-track chain — just report the
                # failure once and stop, exactly one message.
                await msg.edit_text(
                    _lang["error_no_file"].format(config.SUPPORT_CHAT)
                )
                return await self.stop(chat_id)

        await msg.edit_text(_lang["play_next"])

        media.message_id = msg.id
        await self.play_media(chat_id, msg, media)
        asyncio.create_task(self._prefetch_next(chat_id))

    async def _prefetch_next(self, chat_id: int) -> None:
        """Prepare the next manual/autoplay track while current audio plays."""
        try:
            upcoming = queue.get_next(chat_id, check=True)

            # IMPORTANT: autoplay must be queued BEFORE StreamEnded fires.
            # The old prefetch only looked at the manual queue, so when the
            # queue was empty there was nothing to prepare and autoplay could
            # stop at the end of the current song.
            if not upcoming and await db.get_autoplay(chat_id):
                current = queue.get_current(chat_id)
                if current:
                    upcoming = await self._autoplay_next(chat_id, current)

            if not upcoming or upcoming.file_path:
                return

            upcoming.file_path = await yt.stream_url(
                upcoming.id, video=upcoming.video
            )
        except Exception as e:
            logger.warning(f"[_prefetch_next] failed for chat {chat_id}: {e!r}")


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
