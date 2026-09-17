import asyncio
import signal
import importlib
from contextlib import suppress

from ArchonMusic import (app, config, db, logger,
                   stop, thumb, userbot, yt)
from ArchonMusic.core.calls import TgCall
import ArchonMusic as _pkg
from ArchonMusic.plugins import all_modules


async def idle():
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGABRT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()

async def main():
    # Initialize voice-call client only after ArchonMusic package initialization.
    _pkg.ArchonMusic = TgCall()
    await db.connect()
    await app.boot()
    await userbot.boot()
    await _pkg.ArchonMusic.boot()

    for module in all_modules:
        importlib.import_module(f"ArchonMusic.plugins.{module}")
    logger.info(f"Loaded {len(all_modules)} modules.")

    sudoers = await db.get_sudoers()
    app.sudoers.update(sudoers)
    app.bl_users.update(await db.get_blacklisted())
    logger.info(f"Loaded {len(app.sudoers)} sudo users.")

    await idle()
    await stop()


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
