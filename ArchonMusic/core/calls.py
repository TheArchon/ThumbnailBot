#
# Copyright (C) 2025-present by TheAloneTeam@Github, < https://github.com/TheAloneTeam >.
#
# This file is part of < https://github.com/TheAloneTeam/KartikMusic > project,
# and is released under the "MIT License".
# Please see < https://github.com/TheAloneTeam/KartikMusic/blob/master/LICENSE >
#
# All rights reserved.
#

import asyncio
import time
from collections import defaultdict

from ntgcalls import (
    ConnectionError,
    ConnectionNotFound,
    RTMPStreamingUnsupported,
    TelegramServerError,
)
from pyrogram.types import InputMediaPhoto, Message
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession

from ArchonMusic import app, config, db, lang, logger, queue, thumb, userbot, yt
from ArchonMusic.helpers import Media, Track, buttons


class TgCall(PyTgCalls):
    def __init__(self):
        self.clients = []
        self.restarting = defaultdict(int)
        self.prefetch_tasks = {}

    async def pause(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=True)

        media = queue.get_current(chat_id)
        if media and media.played_at:
            media.time += int(time.time() - media.played_at)
            media.played_at = None

        return await client.pause(chat_id)

    async def resume(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=False)

        media = queue.get_current(chat_id)
        if media:
            media.played_at = time.time()

        return await client.resume(chat_id)

    async def _prepare_next(self, chat_id: int) -> None:
        """
        Keep the next autoplay item ready.

        Important:
        - Never stop the voice chat because a prefetch/download failed.
        - If autoplay is enabled and the queue becomes empty, generate another
          track from the current track.
        - Try multiple times so one bad API result does not end autoplay.
        """
        try:
            attempts = 0

            while await db.get_call(chat_id):
                if not await db.get_autoplay(chat_id):
                    await asyncio.sleep(5)
                    continue

                current = queue.get_current(chat_id)
                if not current:
                    break

                # Keep a next item available.
                next_media = queue.get_next(chat_id, check=True)

                if not next_media and isinstance(current, Track):
                    while attempts < 3 and not next_media:
                        attempts += 1
                        try:
                            max_duration = min(
                                max(int(current.duration_sec * 1.5), 300),
                                900,
                            )
                            next_media = await yt.get_related(
                                current.id,
                                video=current.video,
                                max_duration=max_duration,
                            )
                        except Exception as e:
                            logger.warning(
                                f"Autoplay generation failed for {chat_id}: {e}"
                            )
                            next_media = None

                        if next_media:
                            # Avoid accidentally re-adding the current song.
                            if (
                                getattr(next_media, "id", None)
                                == getattr(current, "id", None)
                            ):
                                next_media = None
                                continue
                            queue.add(chat_id, next_media)
                            break

                    attempts = 0

                if next_media and not next_media.file_path:
                    try:
                        next_media.file_path = await yt.download(
                            next_media.id,
                            video=next_media.video,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Autoplay prefetch failed for {chat_id}: {e}"
                        )
                        # Leave it queued. play_next() will retry instead of
                        # stopping the call.
                        next_media.file_path = None

                # Check again shortly before the current stream finishes.
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in prefetch for {chat_id}: {e}")
        finally:
            self.prefetch_tasks.pop(chat_id, None)

    async def stop(self, chat_id: int) -> None:
        if task := self.prefetch_tasks.pop(chat_id, None):
            task.cancel()

        client = await db.get_assistant(chat_id)
        media = queue.get_current(chat_id)
        if media and media.message_id:
            try:
                await app.delete_messages(chat_id, media.message_id)
            except Exception:
                pass
        queue.clear(chat_id)
        await db.remove_call(chat_id)
        await db.set_loop(chat_id, 0)

        try:
            await client.leave_call(chat_id, close=False)
        except Exception:
            pass

    async def play_media(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        seek_time: int = 0,
    ) -> None:
        if task := self.prefetch_tasks.pop(chat_id, None):
            task.cancel()

        self.restarting[chat_id] += 1
        if await db.get_call(chat_id):
            await asyncio.sleep(0.5)
        client = await db.get_assistant(chat_id)
        _lang = await lang.get_lang(chat_id)
        _thumb_mode = await db.get_thumb_mode(chat_id)
        _thumb = (
            (
                await thumb.generate(media)
                if isinstance(media, Track)
                else config.DEFAULT_THUMB
            )
            if config.THUMB_GEN and _thumb_mode
            else None
        )

        if not media.file_path:
            try:
                media.file_path = await yt.download(
                    media.id,
                    video=media.video,
                )
            except Exception as e:
                logger.warning(f"Media download failed for {chat_id}: {e}")
                media.file_path = None

            if not media.file_path:
                try:
                    await message.edit_text(
                        _lang["error_no_file"].format(config.SUPPORT_CHAT)
                    )
                except Exception:
                    pass
                return await self.play_next(chat_id)

        ffmpeg_params = (
            "-re "
            + (f"-ss {seek_time} " if seek_time > 1 else "")
            + ("-vn" if not media.video else "")
        ).strip()

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
            ffmpeg_parameters=ffmpeg_params or None,
        )

        try:
            if seek_time or await db.get_call(chat_id):
                await client.play(chat_id, stream)
            else:
                await client.play(chat_id, stream)

            media.played_at = time.time()
            if seek_time:
                media.time = seek_time
            else:
                media.time = 1
                await db.add_call(chat_id)
                text = _lang["play_media"].format(
                    media.url,
                    media.title,
                    media.duration,
                    media.user,
                )
                keyboard = buttons.controls(chat_id, lang=_lang)
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
                except Exception:
                    try:
                        await message.delete()
                    except Exception:
                        pass
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

            self.prefetch_tasks[chat_id] = asyncio.create_task(
                self._prepare_next(chat_id)
            )
        except FileNotFoundError:
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            await self.play_next(chat_id)
        except exceptions.NoActiveGroupCall:
            await self.stop(chat_id)
            await message.edit_text(_lang["error_no_call"])
        except exceptions.NoAudioSourceFound:
            await message.edit_text(_lang["error_no_audio"])
            await self.play_next(chat_id)
        except (asyncio.TimeoutError, TimeoutError):
            await message.edit_text(_lang["error_tg_server"])
            await self.play_next(chat_id)
        except (ConnectionError, ConnectionNotFound, TelegramServerError):
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
        except RTMPStreamingUnsupported:
            await self.stop(chat_id)
            await message.edit_text(_lang["error_rtmp"])
        finally:
            await asyncio.sleep(5)
            self.restarting[chat_id] -= 1

    async def replay(self, chat_id: int) -> None:
        if not await db.get_call(chat_id):
            return

        media = queue.get_current(chat_id)
        if media and media.message_id:
            try:
                await app.delete_messages(chat_id, media.message_id)
            except Exception:
                pass
        _lang = await lang.get_lang(chat_id)
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_again"])
        media.message_id = msg.id
        await self.play_media(chat_id, msg, media)

    async def play_next(self, chat_id: int, skip_user: str | None = None) -> None:
        """
        Advance the queue without allowing a temporary media/API failure to
        terminate autoplay.
        """
        _lang = await lang.get_lang(chat_id)

        # Loop protection: never recursively call play_next forever.
        for attempt in range(5):
            # Loop mode.
            if loop := await db.get_loop(chat_id):
                await db.set_loop(chat_id, loop - 1)
                return await self.replay(chat_id)

            current = queue.get_current(chat_id)

            if current and current.message_id:
                try:
                    await app.delete_messages(chat_id, current.message_id)
                except Exception:
                    pass

            # Normal queued item.
            media = queue.get_next(chat_id)

            # Queue is empty -> autoplay.
            if not media and await db.get_autoplay(chat_id):
                if current and isinstance(current, Track):
                    try:
                        if skip_user and attempt == 0:
                            msg = await app.send_message(
                                chat_id,
                                _lang["autoplay_skip"].format(skip_user),
                            )
                        elif attempt == 0:
                            msg = await app.send_message(
                                chat_id,
                                _lang["autoplay_next"],
                            )
                        else:
                            msg = None
                    except Exception:
                        msg = None

                    # Try generating a fresh autoplay track.
                    try:
                        max_duration = min(
                            max(int(current.duration_sec * 1.5), 300),
                            900,
                        )
                        media = await yt.get_related(
                            current.id,
                            video=current.video,
                            max_duration=max_duration,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Autoplay next failed for {chat_id}, "
                            f"attempt={attempt + 1}: {e}"
                        )
                        media = None

                    if media:
                        if getattr(media, "id", None) == getattr(current, "id", None):
                            media = None
                        else:
                            queue.add(chat_id, media)

                    # If generation failed, retry instead of stopping.
                    if not media:
                        await asyncio.sleep(0.8)
                        continue

                    media = queue.get_current(chat_id) or media

                    # Prefer an already-prefetched file.
                    if not media.file_path:
                        try:
                            media.file_path = await yt.download(
                                media.id,
                                video=media.video,
                            )
                        except Exception as e:
                            logger.warning(
                                f"Autoplay download failed for {chat_id}, "
                                f"attempt={attempt + 1}: {e}"
                            )
                            media.file_path = None

                    if not media.file_path:
                        # Remove/advance this bad item and generate another.
                        try:
                            queue.get_next(chat_id)
                        except Exception:
                            pass
                        await asyncio.sleep(0.5)
                        continue

                    media.message_id = msg.id if msg else None
                    return await self.play_media(chat_id, msg, media)

                # Autoplay is enabled but there is no current Track.
                await asyncio.sleep(0.5)
                continue

            # No queue and autoplay disabled.
            if not media:
                await self.stop(chat_id)
                if skip_user:
                    try:
                        return await app.send_message(
                            chat_id,
                            _lang["play_skipped"].format(skip_user),
                        )
                    except Exception:
                        return
                try:
                    return await app.send_message(
                        chat_id,
                        _lang["queue_finished"],
                    )
                except Exception:
                    return

            # We have a queued media item.
            msg = None
            if media.message_id:
                try:
                    msg = await app.get_messages(chat_id, media.message_id)
                    if not msg or not msg.id or msg.empty:
                        msg = None
                    else:
                        try:
                            text = (
                                _lang["play_skipped"].format(skip_user)
                                + "\n\n"
                                + _lang["play_next"]
                                if skip_user
                                else _lang["play_next"]
                            )
                            await msg.edit_text(text)
                        except Exception:
                            pass
                except Exception:
                    msg = None

            if not msg:
                try:
                    text = (
                        _lang["play_skipped"].format(skip_user)
                        + "\n\n"
                        + _lang["play_next"]
                        if skip_user
                        else _lang["play_next"]
                    )
                    msg = await app.send_message(chat_id, text=text)
                except Exception:
                    msg = None

            if not media.file_path:
                try:
                    media.file_path = await yt.download(
                        media.id,
                        video=media.video,
                    )
                except Exception as e:
                    logger.warning(
                        f"Queued media download failed for {chat_id}: {e}"
                    )
                    media.file_path = None

            if not media.file_path:
                # If autoplay is on, don't terminate the call. Try to get the
                # following track instead.
                if await db.get_autoplay(chat_id):
                    await asyncio.sleep(0.5)
                    continue

                if msg:
                    try:
                        await msg.edit_text(
                            _lang["error_no_file"].format(config.SUPPORT_CHAT)
                        )
                    except Exception:
                        pass
                return await self.play_next(chat_id)

            media.message_id = msg.id if msg else None
            return await self.play_media(chat_id, msg, media)

        # Only after several consecutive failures do we stop.
        if await db.get_call(chat_id):
            logger.error(
                f"Autoplay could not find a playable track after retries "
                f"for chat {chat_id}"
            )
            # Do not force-stop an active call here. The next update/prefetch
            # cycle can recover when the API becomes available again.
            return

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
                    if self.restarting.get(update.chat_id):
                        return
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
