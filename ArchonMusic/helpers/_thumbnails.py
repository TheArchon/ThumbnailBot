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
        source = Image.open(temp).convert("RGB")

        # Full image background
        background = ImageOps.fit(
            source,
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        # Blur background
        background = background.filter(
            ImageFilter.GaussianBlur(
                radius=max(8, int(min(size) * 0.025))
            )
        )

        background = ImageEnhance.Brightness(
            background
        ).enhance(0.40)

        # Keep complete thumbnail without cropping
        foreground = ImageOps.contain(
            source,
            self.rect,
            method=Image.Resampling.LANCZOS,
        )

        # Center thumbnail
        x = (size[0] - foreground.width) // 2
        y = (size[1] - foreground.height) // 2

        # Rounded mask
        mask = Image.new(
            "L",
            foreground.size,
            0,
        )

        ImageDraw.Draw(mask).rounded_rectangle(
            (
                0,
                0,
                foreground.width,
                foreground.height,
            ),
            radius=15,
            fill=255,
        )

        foreground = foreground.convert("RGBA")
        foreground.putalpha(mask)

        background = background.convert("RGBA")
        background.paste(
            foreground,
            (x, y),
            foreground,
        )

        draw = ImageDraw.Draw(background)

        # Channel + views
        draw.text(
            xy=(50, 560),
            text=(
                f"{(song.channel_name or 'Unknown')[:25]}"
                f" | {song.view_count or 0}"
            ),
            font=self.font2,
            fill=self.fill,
        )

        # Song title
        draw.text(
            (50, 600),
            (song.title or "Unknown")[:50],
            font=self.font1,
            fill=self.fill,
        )

        # Progress
        draw.text(
            (40, 650),
            "0:01",
            font=self.font1,
            fill=self.fill,
        )

        draw.line(
            [(140, 670), (1160, 670)],
            fill=self.fill,
            width=5,
            joint="curve",
        )

        # Duration
        draw.text(
            (1185, 650),
            song.duration or "00:00",
            font=self.font1,
            fill=self.fill,
        )

        background.convert("RGB").save(
            output,
            quality=95,
        )

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
