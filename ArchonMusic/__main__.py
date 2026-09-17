import asyncio
import signal
import importlib
from contextlib import suppress

# Import the package module itself, not individual package attributes.
# This avoids `from ArchonMusic import ArchonMusic` during module startup,
# which can trigger a circular-import failure when the package is launched
# with `python -m ArchonMusic`.
import ArchonMusic as pkg


async def idle():
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGABRT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()


async def main():
    from ArchonMusic.core.calls import TgCall

    # Create TgCall only after the ArchonMusic package has finished loading.
    pkg.ArchonMusic = TgCall()

    await pkg.db.connect()
    await pkg.app.boot()
    await pkg.userbot.boot()
    await pkg.ArchonMusic.boot()

    from ArchonMusic.plugins import all_modules
    for module in all_modules:
        importlib.import_module(f"ArchonMusic.plugins.{module}")
    pkg.logger.info(f"Loaded {len(all_modules)} modules.")

    sudoers = await pkg.db.get_sudoers()
    pkg.app.sudoers.update(sudoers)
    pkg.app.bl_users.update(await pkg.db.get_blacklisted())
    pkg.logger.info(f"Loaded {len(pkg.app.sudoers)} sudo users.")

    await idle()
    await pkg.stop()


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
