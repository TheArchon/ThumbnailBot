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
import random
import re
import urllib.parse

import aiohttp
from py_yt import Playlist, Recommendations, VideosSearch

from ArchonMusic import logger
from ArchonMusic.helpers import Track, utils

# Use environment variables for configuration
API_URL = os.getenv("API_URL", "https://web.riteshyt.in").rstrip("/")
API_KEY = os.getenv("API_KEY", "riteshfreea6901be19d3f420aad766250")
# API priority: Shruti -> Ritesh -> py_yt
SHRUTI_API_URL = os.getenv("SHRUTI_API_URL", "https://api01.shrutibots.site").rstrip("/")
SHRUTI_API_KEY = os.getenv("SHRUTI_API_KEY", "").strip()

SONG_BLOCK_WORDS = (
    "episode", "ep ", "season", "s0", "serial", "web series", "series",
    "podcast", "interview", "news", "trailer", "teaser", "review",
    "reaction", "recap", "live", "livestream", "radio", "talk show",
    "documentary", "vlog", "shorts", "short video", "promo"
)

def _norm_title(value: str) -> str:
    value = re.sub(r"[^a-z0-9\u0900-\u097f\u0980-\u09ff\u0a80-\u0aff\u0b80-\u0bff]+", " ", str(value or "").lower())
    return re.sub(r"\\s+", " ", value).strip()

def _song_ok(title: str, channel: str = "") -> bool:
    text = f"{title or ''} {channel or ''}".lower()
    if any(word in text for word in SONG_BLOCK_WORDS):
        return False
    return bool(title and str(title).strip())


async def download_assistant(query: str, dl_type: str) -> str:
    """Helper to get stream URL from the API"""
    safe_query = urllib.parse.quote(query)
    ext = "mp3" if dl_type == "audio" else "mp4"
    if API_KEY:
        # Use query_masked path to satisfy bots that look for direct file extensions
        url = f"{API_URL}/downloads/{API_KEY}/{safe_query}.{ext}"
    else:
        url = f"{API_URL}/downloads/stream?query={safe_query}&dl_type={dl_type}"
    return url


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.cookie_dir = "KartikMusic/cookies"
        self.warned = False
        self._recent_prefetches = {}  # vidid -> timestamp
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.iregex = re.compile(
            r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)"
            r"(?!/(watch\?v=[A-Za-z0-9_-]{11}|shorts/[A-Za-z0-9_-]{11}"
            r"|playlist\?list=PL[A-Za-z0-9_-]+|[A-Za-z0-9_-]{11}))\S*"
        )
        self._client = None

    async def get_client(self):
        if self._client is None or self._client.closed:
            self._client = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=600.0, connect=10.0)
            )
        return self._client

    def get_cookies(self):
        if not self.checked:
            for file in os.listdir(self.cookie_dir):
                if file.endswith(".txt"):
                    self.cookies.append(f"{self.cookie_dir}/{file}")
            self.checked = True
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("Cookies are missing; downloads might fail.")
            return None
        return random.choice(self.cookies)

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        async with aiohttp.ClientSession() as session:
            for url in urls:
                name = url.split("/")[-1]
                link = "https://batbin.me/raw/" + name
                async with session.get(link) as resp:
                    resp.raise_for_status()
                    with open(f"{self.cookie_dir}/{name}.txt", "wb") as fw:
                        fw.write(await resp.read())
        logger.info(f"Cookies saved in {self.cookie_dir}.")

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        return bool(re.match(self.iregex, url))

    def _clean_link(self, link: str):
        if not link:
            return ""
        link = str(link)
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
        return link

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        """Fast search with strict song-only filtering. Shruti is tried first, then Ritesh."""
        client = await self.get_client()

        async def make_track(data):
            title = data.get("title") or ""
            channel = (data.get("channel") or {}).get("name", "")
            if not _song_ok(title, channel):
                return None
            thumbs = data.get("thumbnails") or []
            thumb = (thumbs[-1].get("url") if thumbs else "") or ""
            duration = data.get("duration") or "00:00"
            link = data.get("link") or data.get("url")
            vid = data.get("id")
            if not vid and link:
                m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", link)
                vid = m.group(1) if m else None
            if not vid or not link:
                return None
            return Track(
                id=vid, channel_name=channel, duration=duration,
                duration_sec=utils.to_seconds(duration), message_id=m_id,
                title=str(title)[:25], thumbnail=thumb.split("?")[0],
                url=link, view_count=(data.get("viewCount") or {}).get("short", ""),
                video=video,
            )

        # 1) Shruti
        if SHRUTI_API_KEY:
            try:
                params = {"query": query, "limit": 8, "api_key": SHRUTI_API_KEY}
                async with client.get(f"{SHRUTI_API_URL}/search", params=params) as response:
                    if response.status == 200:
                        payload = await response.json()
                        for data in (payload.get("result") or payload.get("results") or []):
                            track = await make_track(data)
                            if track:
                                logger.info(f"[YouTube] Shruti selected: {track.title}")
                                return track
            except Exception as e:
                logger.warning(f"[YouTube] Shruti search failed: {e}")

        # 2) Ritesh
        if API_KEY:
            try:
                params = {"query": query, "limit": 8, "api_key": API_KEY}
                async with client.get(f"{API_URL}/search", params=params) as response:
                    if response.status == 200:
                        payload = await response.json()
                        for data in (payload.get("result") or payload.get("results") or []):
                            track = await make_track(data)
                            if track:
                                logger.info(f"[YouTube] Ritesh selected: {track.title}")
                                return track
            except Exception as e:
                logger.warning(f"[YouTube] Ritesh search failed: {e}")

        # 3) py_yt fallback
        try:
            _search = VideosSearch(query, limit=8, with_live=False)
            results = await _search.next()
            for data in (results.get("result") if results else []) or []:
                track = await make_track(data)
                if track:
                    return track
        except Exception as e:
            logger.warning(f"[YouTube] py_yt search failed: {e}")
        return None

    async def playlist(
        self, limit: int, user: str, url: str, video: bool
    ) -> list[Track | None]:
        url = self._clean_link(url)
        client = await self.get_client()
        params = {"link": url, "limit": limit}
        if API_KEY:
            params["api_key"] = API_KEY
        try:
            async with client.get(f"{API_URL}/playlist", params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    videos = data.get("videos")
                    if videos:
                        tracks = []
                        for data in videos:
                            track = Track(
                                id=data.get("id"),
                                channel_name=data.get("channel", {}).get("name", ""),
                                duration=data.get("duration"),
                                duration_sec=utils.to_seconds(data.get("duration")),
                                title=data.get("title")[:25],
                                thumbnail=data.get("thumbnails")[-1]
                                .get("url")
                                .split("?")[0],
                                url=data.get("link").split("&list=")[0],
                                user=user,
                                view_count="",
                                video=video,
                            )
                            tracks.append(track)
                        return tracks
        except Exception as e:
            logger.error(f"Error fetching playlist from API: {e}")

        # Fallback
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist["videos"][:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails")[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception:
            pass
        return tracks

    async def prefetch(self, link: str, video: bool = False):
        """Triggers background pre-fetching on the API"""
        dl_type = "video" if video else "audio"
        link = self._clean_link(link)

        # Avoid redundant prefetches within 30 seconds
        import time

        now = time.time()
        regex = r"(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^\"&?\/\s]{11})"
        match = re.search(regex, link)
        vidid = match.group(1) if match else link

        cache_key = f"{vidid}_{dl_type}"
        if cache_key in self._recent_prefetches:
            if now - self._recent_prefetches[cache_key] < 30:
                return True

        self._recent_prefetches[cache_key] = now

        # Cleanup old prefetches (keep cache small)
        if len(self._recent_prefetches) > 100:
            self._recent_prefetches = {
                k: v for k, v in self._recent_prefetches.items() if now - v < 300
            }

        client = await self.get_client()
        params = {"query": link, "dl_type": dl_type, "prefetch": "true"}
        if API_KEY:
            params["api_key"] = API_KEY
        try:
            # Fire and forget request to the API
            async with client.get(f"{API_URL}/download", params=params):
                return True
        except Exception as e:
            logger.error(f"Prefetch failed for {link}: {e}")
        return False

    async def get_related(
        self, video_id: str, video: bool = False, max_duration: int = 0,
        blocked_ids=None, blocked_titles=None
    ) -> Track | None:
        """Return a DIFFERENT music song for autoplay, never episodes/podcasts/etc."""
        blocked_ids = {str(x) for x in (blocked_ids or set()) if x}
        blocked_titles = {_norm_title(x) for x in (blocked_titles or set()) if x}
        blocked_ids.add(str(video_id))

        def allowed(data):
            vid = str(data.get("id") or "")
            title = str(data.get("title") or "")
            channel = (data.get("channel") or {}).get("name", "")
            if not vid or vid in blocked_ids or not _song_ok(title, channel):
                return False
            if max_duration and utils.to_seconds(data.get("duration") or "00:00") > max_duration:
                return False
            nt = _norm_title(title)
            if nt and any(nt == old or nt in old or old in nt for old in blocked_titles):
                return False
            return True

        def build(data):
            thumbs = data.get("thumbnails") or []
            link = data.get("link") or f"{self.base}{data.get('id')}"
            return Track(
                id=data.get("id"),
                channel_name=(data.get("channel") or {}).get("name", ""),
                duration=data.get("duration") or "00:00",
                duration_sec=utils.to_seconds(data.get("duration") or "00:00"),
                title=str(data.get("title") or "")[:25],
                thumbnail=((thumbs[-1].get("url") if thumbs else "") or "").split("?")[0],
                url=link, user="Autoplay", video=video,
            )

        # Recommendations first, but filter aggressively.
        try:
            result = await Recommendations.getRelated(video_id)
            items = result.get("result", []) if isinstance(result, dict) else []
            candidates = [x for x in items if x.get("type") == "video" and allowed(x)]
            if candidates:
                data = random.choice(candidates[:12])
                return build(data)
        except Exception as e:
            logger.warning(f"[YouTube] related recommendations failed: {e}")

        # Search fallback. Search by the video itself; do not remove song filters.
        for q in (f"{video_id} song", f"music {video_id}"):
            try:
                _search = VideosSearch(q, limit=10, with_live=False)
                result = await _search.next()
                items = result.get("result", []) if result else []
                candidates = [x for x in items if allowed(x)]
                if candidates:
                    return build(candidates[0])
            except Exception:
                continue
        return None

    async def download(self, video_id: str, video: bool = False) -> str | None:
        url = self.base + video_id
        dl_type = "video" if video else "audio"

        # Immediate prefetch
        asyncio.create_task(self.prefetch(url, video=video))

        if API_KEY:
            # Using the optimized stream URL from the API
            stream_url = f"{API_URL}/downloads/{API_KEY}/youtube.com/{video_id}.{'mp4' if video else 'mp3'}"
        else:
            # If no API_KEY or custom logic fails, use download_assistant or fallback
            stream_url = await download_assistant(url, dl_type)

        # Wait for the stream to be ready and buffering by reading the first 1024 bytes
        try:
            client = await self.get_client()
            async with client.get(stream_url, timeout=30) as resp:
                if resp.status in [200, 206]:
                    await resp.content.read(1024)
                else:
                    logger.warning(
                        f"Download stream URL returned status {resp.status} for {video_id}"
                    )
        except Exception as e:
            logger.warning(
                f"Error checking download stream readiness for {video_id}: {e}"
            )

        return stream_url

    async def close(self):
        if self._client and not self._client.closed:
            await self._client.close()
