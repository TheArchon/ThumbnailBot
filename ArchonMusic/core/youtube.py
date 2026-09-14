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
from py_yt import Playlist, VideosSearch

from ArchonMusic import logger
from ArchonMusic.helpers import Track, utils

# Use environment variables for configuration
API_URL = os.getenv("API_URL", "https://web.riteshyt.in").rstrip("/")
API_KEY = os.getenv("API_KEY", "riteshfreea6901be19d3f420aad766250")
API2_URL = os.getenv("SHRUTI_API_URL", "https://shrutibots.site").rstrip("/")
API2_KEY = os.getenv("SHRUTI_API_KEY", "ShrutiBotsfhGT4c09sFRRuQIB6yCG")


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
        self.track_context = {}

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
        client = await self.get_client()
        original_query = str(query).strip()
        params = {"query": query, "limit": 1}
        if API_KEY:
            params["api_key"] = API_KEY
        try:
            async with client.get(f"{API_URL}/search", params=params) as response:
                if response.status == 200:
                    result_data = await response.json()
                    result = result_data.get("result")
                    if result:
                        data = result[0]
                        if data.get("id"):
                            self.track_context[str(data.get("id"))] = original_query
                        return Track(
                            id=data.get("id"),
                            channel_name=data.get("channel", {}).get("name"),
                            duration=data.get("duration"),
                            duration_sec=utils.to_seconds(data.get("duration")),
                            message_id=m_id,
                            title=data.get("title")[:25],
                            thumbnail=data.get("thumbnails", [{}])[-1]
                            .get("url")
                            .split("?")[0],
                            url=data.get("link"),
                            view_count=data.get("viewCount", {}).get("short"),
                            video=video,
                        )
        except Exception as e:
            logger.error(f"Error in search from API: {e}")

        # Fallback to existing search if API fails
        try:
            _search = VideosSearch(query, limit=1, with_live=False)
            results = await _search.next()
            if results and results["result"]:
                data = results["result"][0]
                if data.get("id"):
                    self.track_context[str(data.get("id"))] = original_query
                return Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    message_id=m_id,
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    video=video,
                )
        except Exception:
            pass
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

    def _language_hint(self, text: str) -> str | None:
        t = (text or "").lower()
        markers = {
            "bhojpuri": ["bhojpuri", "भोजपुरी"], "punjabi": ["punjabi", "ਪੰਜਾਬੀ"],
            "tamil": ["tamil", "தமிழ்"], "telugu": ["telugu", "తెలుగు"],
            "marathi": ["marathi", "मराठी"], "bengali": ["bengali", "বাংলা"],
            "gujarati": ["gujarati", "ગુજરાતી"], "kannada": ["kannada", "ಕನ್ನಡ"],
            "malayalam": ["malayalam", "മലയാളം"], "odia": ["odia", "ଓଡ଼ିଆ"],
            "assamese": ["assamese", "অসমীয়া"], "hindi": ["hindi", "हिंदी"],
        }
        for lang, words in markers.items():
            if any(w in t for w in words):
                return lang
        # Devanagari without a stronger regional marker is treated as Hindi.
        if re.search(r"[\u0900-\u097F]", text or ""):
            return "hindi"
        return None

    def _same_language(self, title: str, channel: str, hint: str | None) -> bool:
        if not hint:
            return True
        detected = self._language_hint(f"{title} {channel}")
        if detected is None:
            return True  # neutral metadata is allowed; don't kill autoplay
        return detected == hint

    async def _api_search(self, base: str, key: str, query: str, limit: int = 8):
        client = await self.get_client()
        params = {"query": query, "limit": limit}
        if key:
            params["api_key"] = key
        try:
            async with client.get(f"{base}/search", params=params, timeout=12) as r:
                if r.status != 200:
                    return []
                data = await r.json(content_type=None)
                result = data.get("result") or data.get("results") or data.get("videos") or []
                return result if isinstance(result, list) else []
        except Exception as e:
            logger.warning(f"API search failed {base}: {e}")
            return []

    def _track_from_data(self, data, video=False):
        vid = data.get("id") or data.get("videoId")
        if not vid:
            return None
        title = data.get("title") or "Unknown"
        thumbs = data.get("thumbnails") or []
        thumb_url = ""
        if isinstance(thumbs, list) and thumbs:
            x = thumbs[-1]
            thumb_url = x.get("url", "") if isinstance(x, dict) else str(x)
        channel = data.get("channel") or {}
        if isinstance(channel, dict):
            channel = channel.get("name", "")
        return Track(
            id=str(vid), channel_name=channel or "", duration=data.get("duration"),
            duration_sec=utils.to_seconds(data.get("duration") or "00:00"),
            title=str(title)[:25], thumbnail=thumb_url.split("?")[0],
            url=data.get("link") or (self.base + str(vid)), user="Autoplay",
            view_count="", video=video,
        )

    async def get_related(self, video_id: str, video: bool = False, max_duration: int = 0) -> Track | None:
        """Find the next song without relying on YouTube Recommendations/RD mix.
        Search both configured APIs and py_yt, while preserving the language of
        the original request when it is known.
        """
        context = getattr(self, "track_context", {}).get(str(video_id), "")
        hint = self._language_hint(context)
        candidates = []
        queries = []
        if context:
            queries += [context + " song", context]
        queries += ["latest " + (hint or "") + " songs", (hint or "") + " songs"]
        queries = [q.strip() for q in queries if q.strip()]

        seen = {str(video_id)}
        for q in queries:
            for base, key in ((API_URL, API_KEY), (API2_URL, API2_KEY)):
                for data in await self._api_search(base, key, q, 8):
                    tr = self._track_from_data(data, video=video)
                    if not tr or tr.id in seen or not tr.duration_sec:
                        continue
                    if max_duration and tr.duration_sec > max_duration:
                        continue
                    if not self._same_language(tr.title, tr.channel_name, hint):
                        continue
                    seen.add(tr.id)
                    candidates.append(tr)
                    if len(candidates) >= 12:
                        break
                if len(candidates) >= 12:
                    break
            if len(candidates) >= 12:
                break

        if not candidates:
            for q in queries:
                try:
                    results = await VideosSearch(q, limit=8, with_live=False).next()
                    for data in (results or {}).get("result", []):
                        tr = self._track_from_data(data, video=video)
                        if not tr or tr.id in seen or not tr.duration_sec:
                            continue
                        if max_duration and tr.duration_sec > max_duration:
                            continue
                        if not self._same_language(tr.title, tr.channel_name, hint):
                            continue
                        seen.add(tr.id)
                        candidates.append(tr)
                except Exception as e:
                    logger.warning(f"py_yt autoplay search failed: {e}")
                if candidates:
                    break

        if candidates:
            # Prefer a random result so autoplay doesn't repeat the same first result.
            return random.choice(candidates)
        logger.warning(f"[Autoplay] No candidate found for {video_id} (language={hint})")
        return None

    async def _download_api(self, base: str, key: str, youtube_url: str, video: bool):
        client = await self.get_client()
        typ = "video" if video else "audio"
        params = {"url": youtube_url, "type": typ}
        if key:
            params["api_key"] = key
        try:
            async with client.get(f"{base}/download", params=params, timeout=45) as r:
                if r.status != 200:
                    logger.warning(f"API {base} /download returned HTTP {r.status}")
                    return None
                content_type = (r.headers.get("Content-Type") or "").lower()
                body = await r.read()
                # Some APIs return JSON containing a direct file URL.
                if "json" in content_type or body[:1] in (b"{", b"["):
                    try:
                        import json
                        data = json.loads(body.decode("utf-8"))
                        direct = data.get("url") or data.get("download_url") or data.get("file") or data.get("link")
                        if direct:
                            async with client.get(direct, timeout=90) as rr:
                                if rr.status == 200:
                                    body = await rr.read()
                                else:
                                    return None
                    except Exception:
                        return None
                if not body or len(body) < 1024:
                    return None
                os.makedirs("downloads", exist_ok=True)
                ext = "mp4" if video else "mp3"
                path = os.path.join("downloads", f"{youtube_url.rsplit('=',1)[-1][:11]}.{ext}")
                with open(path, "wb") as f:
                    f.write(body)
                return path
        except Exception as e:
            logger.warning(f"API {base} /download failed: {e}")
            return None

    async def download(self, video_id: str, video: bool = False) -> str | None:
        url = self.base + video_id
        # API 1 -> API 2 -> local yt-dlp fallback.
        for base, key in ((API_URL, API_KEY), (API2_URL, API2_KEY)):
            path = await self._download_api(base, key, url, video)
            if path and os.path.exists(path) and os.path.getsize(path) > 1024:
                logger.info(f"[Download] Success via {base}: {video_id}")
                return path

        # Last resort: yt-dlp. This may fail on cloud IPs, but it is kept as a fallback.
        try:
            import yt_dlp
            os.makedirs("downloads", exist_ok=True)
            ext = "mp4" if video else "mp3"
            out = os.path.abspath(os.path.join("downloads", f"{video_id}.{ext}"))
            opts = {
                "outtmpl": out, "noplaylist": True, "quiet": True,
                "no_warnings": True, "overwrites": False,
                "format": "bestvideo+bestaudio/best" if video else "bestaudio/best",
                "merge_output_format": "mp4" if video else None,
            }
            opts = {k:v for k,v in opts.items() if v is not None}
            loop = asyncio.get_running_loop()
            def _run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
            await loop.run_in_executor(None, _run)
            if os.path.exists(out) and os.path.getsize(out) > 1024:
                return out
        except Exception as e:
            logger.warning(f"yt-dlp fallback failed for {video_id}: {e}")
        return None

    async def close(self):
        if self._client and not self._client.closed:
            await self._client.close()
