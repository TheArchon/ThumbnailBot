import asyncio
import os
import random
import re
import time
import urllib.parse

import aiohttp
from py_yt import Playlist, VideosSearch

from ArchonMusic import logger
from ArchonMusic.helpers import Track, utils

SHRUTI_API_URL = os.getenv("SHRUTI_API_URL", "https://api01.shrutibots.site").rstrip("/")
SHRUTI_API_KEY = os.getenv("SHRUTI_API_KEY", "").strip()
RITESH_API_URL = os.getenv("API_URL", "https://web.riteshyt.in").rstrip("/")
RITESH_API_KEY = os.getenv("API_KEY", "riteshfreea6901be19d3f420aad766250").strip()

LANGUAGE_MARKERS = {
    "hindi": ["hindi", "bollywood", "हिंदी"],
    "bhojpuri": ["bhojpuri", "भोजपुरी"],
    "punjabi": ["punjabi", "ਪੰਜਾਬੀ"],
    "tamil": ["tamil", "தமிழ்"],
    "telugu": ["telugu", "తెలుగు"],
    "marathi": ["marathi", "मराठी"],
    "bengali": ["bengali", "bangla", "বাংলা"],
    "gujarati": ["gujarati", "ગુજરાતી"],
    "kannada": ["kannada", "ಕನ್ನಡ"],
    "malayalam": ["malayalam", "മലയാളം"],
    "odia": ["odia", "oriya", "ଓଡ଼ିଆ"],
    "assamese": ["assamese", "অসমীয়া"],
}
NON_SONG_WORDS = {
    "episode", "episodes", "ep.", "ep ", "serial", "web series", "web-series",
    "podcast", "interview", "news", "trailer", "teaser", "reaction", "review",
    "vlog", "live", "livestream", "documentary", "movie full", "full movie",
    "chapter", "part 1", "part 2", "part-1", "part-2", "radio", "story",
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9\u0900-\u097f\u0980-\u09ff\u0a00-\u0a7f\u0b00-\u0b7f\u0c00-\u0c7f\u0d00-\u0d7f ]+", " ", str(value or "").lower()).strip()


def _language(text: str) -> str | None:
    value = _norm(text)
    for name, markers in LANGUAGE_MARKERS.items():
        if any(m.lower() in value for m in markers):
            return name
    return None


def _same_language(text: str, language: str | None) -> bool:
    if not language:
        return True
    value = _norm(text)
    markers = LANGUAGE_MARKERS[language]
    return any(m.lower() in value for m in markers)


def _is_song(data: dict) -> bool:
    title = str(data.get("title") or "")
    channel = data.get("channel") or {}
    if isinstance(channel, dict):
        channel = channel.get("name") or ""
    text = f"{title} {channel} {data.get('description') or ''}".lower()
    if any(word in text for word in NON_SONG_WORDS):
        return False
    # Reject obvious non-music channels/results, but allow official artist/label channels.
    if not data.get("id") or not data.get("link"):
        return False
    duration = utils.to_seconds(data.get("duration") or "00:00")
    return duration > 0 and duration <= 1800


def _title_key(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\u0900-\u0d7f ]", " ", str(title or "").lower())).strip()


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.cookie_dir = "ArchonMusic/cookies"
        self.warned = False
        self._client = None
        self._stream_cache = {}
        self._recent_prefetches = {}

    async def get_client(self):
        if self._client is None or self._client.closed:
            self._client = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=45, connect=8, sock_read=35)
            )
        return self._client

    def get_cookies(self):
        if not self.checked:
            try:
                for file in os.listdir(self.cookie_dir):
                    if file.endswith(".txt"):
                        self.cookies.append(f"{self.cookie_dir}/{file}")
            except OSError:
                pass
            self.checked = True
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("YouTube cookies are not configured; yt-dlp is last fallback.")
            return None
        return random.choice(self.cookies)

    async def save_cookies(self, urls: list[str]) -> None:
        os.makedirs(self.cookie_dir, exist_ok=True)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            for url in urls:
                name = url.rstrip("/").split("/")[-1]
                try:
                    async with session.get("https://batbin.me/raw/" + name) as resp:
                        resp.raise_for_status()
                        with open(f"{self.cookie_dir}/{name}.txt", "wb") as fw:
                            fw.write(await resp.read())
                except Exception as e:
                    logger.warning(f"Cookie save failed: {e}")

    def valid(self, url: str) -> bool:
        return bool(re.search(r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[A-Za-z0-9_-]{11}", url or ""))

    def invalid(self, url: str) -> bool:
        return False

    def _clean_link(self, link: str) -> str:
        if not link:
            return ""
        link = str(link)
        match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", link)
        return self.base + match.group(1) if match else link.split("&")[0]

    def _track_from(self, data: dict, m_id: int, video: bool = False, user: str | None = None) -> Track | None:
        if not isinstance(data, dict):
            return None
        vid = data.get("id") or data.get("videoId")
        link = data.get("link") or data.get("url") or (self.base + vid if vid else None)
        channel = data.get("channel") or {}
        if isinstance(channel, dict):
            channel = channel.get("name") or ""
        thumb = data.get("thumbnail") or data.get("thumbnails") or ""
        if isinstance(thumb, list):
            thumb = (thumb[-1] or {}).get("url", "") if thumb else ""
        elif isinstance(thumb, dict):
            thumb = thumb.get("url", "")
        duration = data.get("duration") or "00:00"
        try:
            duration_sec = int(data.get("duration_sec") or utils.to_seconds(duration))
        except Exception:
            duration_sec = 0
        return Track(
            id=vid,
            channel_name=channel,
            duration=duration,
            duration_sec=duration_sec,
            message_id=m_id,
            title=str(data.get("title") or "Unknown Song")[:25],
            thumbnail=str(thumb).split("?")[0] if thumb else None,
            url=link,
            view_count=(data.get("viewCount") or {}).get("short") if isinstance(data.get("viewCount"), dict) else data.get("viewCount"),
            user=user,
            video=video,
        ) if vid and link else None

    async def _api_search(self, base_url: str, key: str, query: str, limit: int = 8):
        client = await self.get_client()
        params = {"query": query, "limit": limit}
        if key:
            params["api_key"] = key
        try:
            async with client.get(f"{base_url}/search", params=params) as resp:
                if resp.status != 200:
                    return []
                payload = await resp.json(content_type=None)
                result = payload.get("result") if isinstance(payload, dict) else payload
                return result if isinstance(result, list) else []
        except Exception as e:
            logger.warning(f"Search API failed {base_url}: {e}")
            return []

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        wanted_lang = _language(query)
        queries = [query]
        if wanted_lang:
            clean = re.sub(r"\b(hindi|bhojpuri|punjabi|tamil|telugu|marathi|bengali|bangla|gujarati|kannada|malayalam|odia|oriya|assamese)\b", "", query, flags=re.I).strip()
            queries = [f"{clean} {wanted_lang} song", f"{wanted_lang} songs {clean}" if clean else f"{wanted_lang} songs"]
        for api, key in ((SHRUTI_API_URL, SHRUTI_API_KEY), (RITESH_API_URL, RITESH_API_KEY)):
            for q in queries:
                for data in await self._api_search(api, key, q, 8):
                    if not _is_song(data):
                        continue
                    text = f"{data.get('title','')} {data.get('channel',{}).get('name','') if isinstance(data.get('channel'),dict) else data.get('channel','')}"
                    if not _same_language(text, wanted_lang):
                        continue
                    track = self._track_from(data, m_id, video=video)
                    if track:
                        return track

        # Last fallback: py_yt search, still applying strict filters.
        try:
            for q in queries:
                result = await VideosSearch(q, limit=8, with_live=False).next()
                for data in (result or {}).get("result", []):
                    if not _is_song(data):
                        continue
                    text = f"{data.get('title','')} {data.get('channel',{}).get('name','')}"
                    if not _same_language(text, wanted_lang):
                        continue
                    track = self._track_from(data, m_id, video=video)
                    if track:
                        return track
        except Exception as e:
            logger.warning(f"py_yt search failed: {e}")
        return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track]:
        tracks = []
        try:
            result = await Playlist.get(self._clean_link(url))
            for data in (result or {}).get("videos", [])[:limit]:
                if not _is_song(data):
                    continue
                track = self._track_from(data, 0, video=video, user=user)
                if track:
                    track.url = self._clean_link(track.url)
                    tracks.append(track)
        except Exception as e:
            logger.warning(f"Playlist failed: {e}")
        return tracks

    async def _probe(self, url: str) -> bool:
        try:
            client = await self.get_client()
            async with client.get(url, headers={"Range": "bytes=0-1023"}, allow_redirects=True) as resp:
                if resp.status not in (200, 206):
                    return False
                await resp.content.read(1)
                return True
        except Exception:
            return False

    async def stream_url(self, video_id: str, video: bool = False) -> str | None:
        """Fast stream URL: Shruti -> Ritesh -> yt-dlp fallback."""
        if not video_id:
            return None
        if video_id.startswith("http"):
            match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", video_id)
            if not match:
                return None
            video_id = match.group(1)
        ext = "mp4" if video else "mp3"
        cache_key = f"{video_id}:{ext}"
        cached = self._stream_cache.get(cache_key)
        if cached and await self._probe(cached):
            return cached

        youtube_url = self.base + video_id
        candidates = []
        if SHRUTI_API_KEY:
            candidates.append(f"{SHRUTI_API_URL}/download?{urllib.parse.urlencode({'url': youtube_url, 'type': 'video' if video else 'audio', 'api_key': SHRUTI_API_KEY})}")
        if RITESH_API_KEY:
            candidates.append(f"{RITESH_API_URL}/downloads/{urllib.parse.quote(RITESH_API_KEY, safe='')}/youtube.com/{video_id}.{ext}")

        for url in candidates:
            if await self._probe(url):
                self._stream_cache[cache_key] = url
                return url

        # Last resort only. This keeps API playback fast whenever either API works.
        try:
            import yt_dlp
            opts = {
                "format": "bestaudio/best" if not video else "best[ext=mp4]/best",
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "skip_download": True,
                "socket_timeout": 10,
                "nocheckcertificate": True,
            }
            cookie = self.get_cookies()
            if cookie:
                opts["cookiefile"] = cookie
            loop = asyncio.get_running_loop()
            info = await asyncio.wait_for(loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(youtube_url, download=False)), 18)
            url = info.get("url") if info else None
            if url:
                self._stream_cache[cache_key] = url
                return url
        except Exception as e:
            logger.warning(f"yt-dlp stream fallback failed for {video_id}: {e}")
        return None

    async def download(self, video_id: str, video: bool = False) -> str | None:
        # For this bot, the direct API stream is the download/stream source.
        return await self.stream_url(video_id, video=video)

    async def prefetch(self, link: str, video: bool = False):
        try:
            vid = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", link or "")
            vid = vid.group(1) if vid else link
            key = f"{vid}:{video}"
            now = time.time()
            if now - self._recent_prefetches.get(key, 0) < 20:
                return
            self._recent_prefetches[key] = now
            await self.stream_url(vid, video=video)
        except Exception as e:
            logger.warning(f"Prefetch failed: {e}")

    async def get_related(self, video_id: str, video: bool = False, max_duration: int = 0, context: str = "", blocked_ids=None, blocked_titles=None) -> Track | None:
        blocked_ids = set(blocked_ids or ())
        blocked_titles = {_title_key(x) for x in (blocked_titles or ())}
        current_lang = _language(context)
        current_title = context.split("|")[1].strip() if "|" in context else context
        queries = []
        if current_lang:
            queries += [f"{current_lang} songs {current_title}", f"{current_lang} new song", f"{current_lang} hit songs"]
        else:
            queries += [f"songs similar to {current_title}", "latest popular songs"]

        for q in queries:
            for api, key in ((SHRUTI_API_URL, SHRUTI_API_KEY), (RITESH_API_URL, RITESH_API_KEY)):
                for data in await self._api_search(api, key, q, 12):
                    if not _is_song(data):
                        continue
                    text = f"{data.get('title','')} {data.get('channel',{}).get('name','') if isinstance(data.get('channel'),dict) else data.get('channel','')}"
                    if not _same_language(text, current_lang):
                        continue
                    track = self._track_from(data, 0, video=video, user="Autoplay")
                    if not track or track.id in blocked_ids or _title_key(track.title) in blocked_titles:
                        continue
                    if max_duration and track.duration_sec > max_duration:
                        continue
                    return track
        return None

    async def close(self):
        if self._client and not self._client.closed:
            await self._client.close()
