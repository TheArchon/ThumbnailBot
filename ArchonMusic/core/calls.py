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
        self.autoplay_history = defaultdict(set)
        self.autoplay_title_history = defaultdict(set)
        self.next_locks = defaultdict(asyncio.Lock)

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
        try:
            while await db.get_call(chat_id):
                if not await db.get_autoplay(chat_id):
                    await asyncio.sleep(10)
                    continue

                media = queue.get_current(chat_id)
                if not media or not media.duration_sec:
                    break

                played_sec = media.time
                if media.played_at:
                    played_sec += int(time.time() - media.played_at)

                remaining = media.duration_sec - played_sec

                if remaining <= 45:
                    next_media = queue.get_next(chat_id, check=True)
                    if not next_media and await db.get_autoplay(chat_id):
                        if isinstance(media, Track):
                            max_duration = min(int(media.duration_sec * 1.5), 900)
                            next_media = await self._get_autoplay_track(chat_id, media)
                            if next_media:
                                self.autoplay_history[chat_id].add(str(next_media.id))
                                if next_media.title:
                                    self.autoplay_title_history[chat_id].add(next_media.title)
                                queue.add(chat_id, next_media)

                    if next_media and not next_media.file_path:
                        next_media.file_path = await yt.stream_url(
                            next_media.id, video=next_media.video
                        )
                        if not next_media.file_path:
                            next_media.file_path = await yt.download(
                                next_media.id, video=next_media.video
                            )
                    break

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
        self.autoplay_history.pop(chat_id, None)
        self.autoplay_title_history.pop(chat_id, None)
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
        update_message: bool = True,
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
            if message is not None:
                await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            return await self._play_next(chat_id)

        ffmpeg_params = (
            (f"-ss {seek_time} " if seek_time > 1 else "")
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
                if update_message and message is not None:
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
            if message is not None:
                await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            await self._play_next(chat_id)
        except exceptions.NoActiveGroupCall:
            await self.stop(chat_id)
            if message is not None:
                await message.edit_text(_lang["error_no_call"])
        except exceptions.NoAudioSourceFound:
            if message is not None:
                await message.edit_text(_lang["error_no_audio"])
            await self._play_next(chat_id)
        except (asyncio.TimeoutError, TimeoutError):
            if message is not None:
                await message.edit_text(_lang["error_tg_server"])
            await self._play_next(chat_id)
        except (ConnectionError, ConnectionNotFound, TelegramServerError):
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
        except RTMPStreamingUnsupported:
            await self.stop(chat_id)
            await message.edit_text(_lang["error_rtmp"])
        finally:
            await asyncio.sleep(1)
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

    async def _get_autoplay_track(self, chat_id: int, current: Track):
        """Retry autoplay search instead of stopping the call after one failure."""
        max_duration = min(int((current.duration_sec or 600) * 1.5), 900)
        for attempt in range(4):
            try:
                media = await asyncio.wait_for(
                    yt.get_related(
                        current.id,
                        video=current.video,
                        max_duration=max_duration,
                        blocked_ids=self.autoplay_history.get(chat_id, set()),
                        blocked_titles=self.autoplay_title_history.get(chat_id, set()),
                    ),
                    timeout=18,
                )
                if media:
                    return media
            except Exception as e:
                logger.warning(f"[Autoplay] attempt {attempt + 1}/4 failed: {e}")
            if attempt < 3:
                await asyncio.sleep(0.5)
        return None

    async def play_next(self, chat_id: int, skip_user: str | None = None) -> None:
        """Advance exactly once per chat; protects skip/StreamEnded races."""
        lock = self.next_locks[chat_id]
        if lock.locked():
            logger.info(f"[Skip/Autoplay] advance already running for {chat_id}")
            return
        async with lock:
            return await self._play_next(chat_id, skip_user=skip_user)

    async def _play_next(self, chat_id: int, skip_user: str | None = None) -> None:
        """Internal queue advance; autoplay is completely silent."""
        if loop := await db.get_loop(chat_id):
            await db.set_loop(chat_id, loop - 1)
            return await self.replay(chat_id)

        _lang = await lang.get_lang(chat_id)
        current = queue.get_current(chat_id)
        if current and isinstance(current, Track):
            self.autoplay_history.setdefault(chat_id, set()).add(str(current.id))
            if current.title:
                self.autoplay_title_history.setdefault(chat_id, set()).add(current.title)
        # Keep the current player message for silent autoplay so no extra
        # Telegram reply is created. It can be edited by play_media().
        current_message = None
        if current and current.message_id:
            try:
                current_message = await app.get_messages(chat_id, current.message_id)
            except Exception:
                current_message = None

        media = queue.get_next(chat_id)
        if not media and await db.get_autoplay(chat_id) and isinstance(current, Track):
            media = await self._get_autoplay_track(chat_id, current)
            if media:
                self.autoplay_history.setdefault(chat_id, set()).add(str(media.id))
                if media.title:
                    self.autoplay_title_history.setdefault(chat_id, set()).add(media.title)
                queue.add(chat_id, media)
                media = queue.get_current(chat_id)

        if not media:
            await self.stop(chat_id)
            # Only normal queue-finished/skip messages are emitted when
            # autoplay is OFF. Autoplay itself never emits a reply.
            if await db.get_autoplay(chat_id):
                return
            if skip_user:
                await app.send_message(chat_id, _lang["play_skipped"].format(skip_user))
            return await app.send_message(chat_id, _lang["queue_finished"])

        if not media.file_path:
            media.file_path = await yt.stream_url(media.id, video=media.video)
            if not media.file_path:
                media.file_path = await yt.download(media.id, video=media.video)
            if not media.file_path:
                logger.warning(f"[Autoplay/Queue] Stream/download failed for {media.id}")
                return await self._play_next(chat_id, skip_user=skip_user)

        # Normal queued playback may reuse its player message. Autoplay also
        # reuses the existing message and never sends a new status reply.
        if await db.get_autoplay(chat_id):
            if current_message:
                media.message_id = current_message.id
                return await self.play_media(
                    chat_id, current_message, media, update_message=True
                )
            # If the old player message disappeared, start silently without
            # creating a replacement Telegram message.
            media.message_id = 0
            return await self.play_media(
                chat_id, None, media, update_message=False
            )

        msg = None
        if media.message_id:
            try:
                msg = await app.get_messages(chat_id, media.message_id)
            except Exception:
                msg = None

        if not msg:
            text = (
                _lang["play_skipped"].format(skip_user) + "\n\n" + _lang["play_next"]
                if skip_user
                else _lang["play_next"]
            )
            msg = await app.send_message(chat_id=chat_id, text=text)

        media.message_id = msg.id
        await self.play_media(chat_id, msg, media)

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
