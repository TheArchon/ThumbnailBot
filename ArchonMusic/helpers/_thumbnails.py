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
import os

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from ArchonMusic import config
from ArchonMusic.helpers import Track


class Thumbnail:
    def __init__(self):
        self.rect = (914, 514)
        self.fill = (255, 255, 255)

        try:
            self.font1 = ImageFont.truetype(
                "ArchonMusic/helpers/Raleway-Bold.ttf",
                30,
            )
            self.font2 = ImageFont.truetype(
                "ArchonMusic/helpers/Inter-Light.ttf",
                30,
            )
        except Exception:
            self.font1 = ImageFont.load_default()
            self.font2 = ImageFont.load_default()

        self.session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self.session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def save_thumb(self, output_path: str, url: str) -> str:
        if not self.session:
            await self.start()

        async with self.session.get(url) as resp:
            resp.raise_for_status()

            with open(output_path, "wb") as f:
                f.write(await resp.read())

        return output_path

    def _draw_image(
        self,
        temp,
        output,
        song: Track,
        size=(1280, 720),
    ):
        """Create the now-playing artwork in the style of the reference image.

        The source thumbnail fills the whole 16:9 canvas, is softly blurred and
        darkened, and the channel/title/progress information is drawn directly
        over the lower part of the artwork. This keeps the generated photo
        looking like a single polished music-player card instead of a small
        thumbnail sitting inside another background.
        """
        source = Image.open(temp).convert("RGB")

        # Fill the complete 1280x720 canvas.
        background = ImageOps.fit(
            source,
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        # Soft blur + darkening, matching the supplied player screenshot.
        background = background.filter(ImageFilter.GaussianBlur(radius=2.2))
        background = ImageEnhance.Brightness(background).enhance(0.68)
        background = ImageEnhance.Contrast(background).enhance(0.92)
        background = background.convert("RGBA")

        # Dark transparent lower panel so white metadata remains readable.
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle((0, 505, size[0], size[1]), fill=(0, 0, 0, 92))
        background = Image.alpha_composite(background, overlay)

        draw = ImageDraw.Draw(background)

        # Small bot/channel watermark in the top-right corner.
        try:
            watermark = (config.BOT_NAME or "MUSIC").upper()[:24]
        except Exception:
            watermark = "MUSIC"
        wm_box = draw.textbbox((0, 0), watermark, font=self.font2)
        draw.text(
            (size[0] - (wm_box[2] - wm_box[0]) - 45, 30),
            watermark,
            font=self.font2,
            fill=(255, 255, 255, 235),
        )

        # Channel + views.
        channel = (song.channel_name or "Unknown")[:28]
        views = str(song.view_count or 0)
        draw.text(
            (50, 555),
            f"{channel} | {views} views",
            font=self.font2,
            fill=(255, 255, 255, 245),
        )

        # Song title.
        title = (song.title or "Unknown").replace("\n", " ").strip()[:58]
        draw.text(
            (50, 598),
            title,
            font=self.font1,
            fill=(255, 255, 255, 255),
        )

        # Progress line + knob, visually matching the reference.
        left = 48
        right = size[0] - 48
        line_y = 654
        draw.line((left, line_y, right, line_y), fill=(255, 255, 255, 235), width=5)
        # Start playback at ~88% only as a visual mock of the reference; the
        # live progress shown by the Telegram buttons is updated separately.
        knob_x = int(left + (right - left) * 0.88)
        draw.ellipse((knob_x - 11, line_y - 11, knob_x + 11, line_y + 11), fill=(255, 255, 255, 255))

        elapsed = "0:01"
        duration = song.duration or "00:00"
        draw.text((40, 672), elapsed, font=self.font2, fill=(255, 255, 255, 245))
        dur_box = draw.textbbox((0, 0), duration, font=self.font2)
        draw.text(
            (size[0] - (dur_box[2] - dur_box[0]) - 40, 672),
            duration,
            font=self.font2,
            fill=(255, 255, 255, 245),
        )

        background.convert("RGB").save(output, quality=95)
        return output

    async def generate(
        self,
        song: Track,
        size=(1280, 720),
        user_avatar=None,
    ) -> str:
        """
        Generate thumbnail.

        user_avatar is accepted for compatibility with calls.py.
        It is optional and does not affect thumbnail generation.
        """
        temp = f"cache/temp_{song.id}.jpg"
        output = f"cache/{song.id}.png"

        try:
            os.makedirs("cache", exist_ok=True)

            if os.path.exists(output):
                return output

            if not song.thumbnail:
                return config.DEFAULT_THUMB

            await self.save_thumb(
                temp,
                song.thumbnail,
            )

            await asyncio.to_thread(
                self._draw_image,
                temp,
                output,
                song,
                size,
            )

            return output

        except Exception:
            return config.DEFAULT_THUMB

        finally:
            try:
                if os.path.exists(temp):
                    os.remove(temp)
            except Exception:
                pass
