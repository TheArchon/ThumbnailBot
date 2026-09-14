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
# Provider priority:
# 1. Shruti
# 2. Ritesh
# 3. yt-dlp (last resort)
SHRUTI_API_URL = os.getenv("SHRUTI_API_URL", "https://shrutibots.site").rstrip("/")
SHRUTI_API_KEY = os.getenv("SHRUTI_API_KEY", "").strip()

RITESH_API_URL = os.getenv("API_URL", "https://web.riteshyt.in").rstrip("/")
RITESH_API_KEY = os.getenv("API_KEY", "riteshfreea6901be19d3f420aad766250").strip()

# Backward-compatible aliases used by older code in this module.
API2_URL = SHRUTI_API_URL
API2_KEY = SHRUTI_API_KEY
API_URL = RITESH_API_URL
API_KEY = RITESH_API_KEY


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
                timeout=aiohttp.ClientTimeout(total=180.0, connect=6.0)
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

    @staticmethod
    def _video_id(value: str) -> str:
        if not value:
            return ""
        value = str(value).strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
            return value
        patterns = (
            r"(?:v=)([A-Za-z0-9_-]{11})",
            r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
            r"(?:shorts/)([A-Za-z0-9_-]{11})",
            r"(?:embed/)([A-Za-z0-9_-]{11})",
        )
        for pattern in patterns:
            match = re.search(pattern, value)
            if match:
                return match.group(1)
        return ""

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
        """Search YouTube with Shruti first, then Ritesh, then py_yt."""
        if not query:
            return None

        original_query = str(query).strip()
        client = await self.get_client()

        # Shruti -> Ritesh
        for provider, base, key in (
            ("Shruti", SHRUTI_API_URL, SHRUTI_API_KEY),
            ("Ritesh", RITESH_API_URL, RITESH_API_KEY),
        ):
            if not base:
                continue
            params = {"query": original_query, "limit": 1}
            if key:
                params["api_key"] = key
            try:
                async with client.get(
                    f"{base}/search", params=params, timeout=8
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            f"[{provider}] Search HTTP {response.status}"
                        )
                        continue
                    result_data = await response.json(content_type=None)
                    result = (
                        result_data.get("result")
                        or result_data.get("results")
                        or result_data.get("videos")
                        or result_data.get("data")
                        or []
                    )
                    if isinstance(result, dict):
                        result = (
                            result.get("result")
                            or result.get("results")
                            or result.get("videos")
                            or [result]
                        )
                    if not isinstance(result, list) or not result:
                        continue

                    data = result[0] or {}
                    vid = data.get("id") or data.get("videoId")
                    if not vid:
                        continue

                    channel = data.get("channel") or {}
                    if isinstance(channel, dict):
                        channel = channel.get("name") or ""
                    thumbs = data.get("thumbnails") or []
                    thumb = ""
                    if isinstance(thumbs, list) and thumbs:
                        last = thumbs[-1]
                        thumb = (
                            last.get("url", "")
                            if isinstance(last, dict)
                            else str(last)
                        )

                    track = Track(
                        id=str(vid),
                        channel_name=channel,
                        duration=data.get("duration"),
                        duration_sec=utils.to_seconds(
                            data.get("duration") or "00:00"
                        ),
                        message_id=m_id,
                        title=str(data.get("title") or "Unknown")[:25],
                        thumbnail=thumb.split("?")[0],
                        url=data.get("link")
                        or data.get("url")
                        or f"{self.base}{vid}",
                        view_count=(
                            data.get("viewCount", {}).get("short")
                            if isinstance(data.get("viewCount"), dict)
                            else data.get("viewCount", "")
                        ),
                        video=video,
                    )
                    self.track_context[str(track.id)] = f"{original_query} | {track.title} | {track.channel_name}"
                    return track
            except Exception as e:
                logger.warning(f"[{provider}] Search failed: {e}")

        # Final metadata/search fallback.
        try:
            search = VideosSearch(original_query, limit=1, with_live=False)
            results = await search.next()
            if results and results.get("result"):
                data = results["result"][0]
                track = self._track_from_data(data, video=video)
                if track:
                    track.message_id = m_id
                    self.track_context[str(track.id)] = f"{original_query} | {track.title} | {track.channel_name}"
                    return track
        except Exception as e:
            logger.warning(f"[py_yt] Search fallback failed: {e}")

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
        for provider, base, key in (
            ("Shruti", SHRUTI_API_URL, SHRUTI_API_KEY),
            ("Ritesh", RITESH_API_URL, RITESH_API_KEY),
        ):
            if not base:
                continue
            params = {"url": link, "type": dl_type, "prefetch": "true"}
            if key:
                params["api_key"] = key
            try:
                async with client.get(
                    f"{base}/download", params=params, timeout=8
                ) as response:
                    if response.status == 200:
                        logger.info(f"[{provider}] Prefetch accepted: {vidid}")
                        return True
                    logger.warning(
                        f"[{provider}] Prefetch HTTP {response.status}"
                    )
            except Exception as e:
                logger.warning(f"[{provider}] Prefetch failed: {e}")
        return False

    def _language_hint(self, text: str) -> str | None:
        """Detect the requested Indian language from query/title/channel text."""
        t = (text or "").lower()
        markers = {
            "bhojpuri": ["bhojpuri", "भोजपुरी"],
            "punjabi": ["punjabi", "ਪੰਜਾਬੀ", "punjabi song", "punjabi songs"],
            "tamil": ["tamil", "தமிழ்"],
            "telugu": ["telugu", "తెలుగు"],
            "marathi": ["marathi", "मराठी"],
            "bengali": ["bengali", "bangla", "বাংলা"],
            "gujarati": ["gujarati", "ગુજરાતી"],
            "kannada": ["kannada", "ಕನ್ನಡ"],
            "malayalam": ["malayalam", "മലയാളം"],
            "odia": ["odia", "oriya", "ଓଡ଼ିଆ"],
            "assamese": ["assamese", "অসমীয়া"],
            "hindi": ["hindi", "हिंदी", "bollywood", "hindi movie", "hindi movies", "hindi song", "hindi songs", "hindustani"],
        }
        for lang, words in markers.items():
            if any(w in t for w in words):
                return lang

        # Script-based detection is useful when the user types the song name
        # in an Indian script instead of writing the language name.
        if re.search(r"[\u0A00-\u0A7F]", text or ""):
            return "punjabi"
        if re.search(r"[\u0B80-\u0BFF]", text or ""):
            return "tamil"
        if re.search(r"[\u0C00-\u0C7F]", text or ""):
            return "telugu"
        if re.search(r"[\u0900-\u097F]", text or ""):
            return "hindi"
        if re.search(r"[\u0B00-\u0B7F]", text or ""):
            return "bengali" if re.search(r"[\u0980-\u09FF]", text or "") else "odia"
        if re.search(r"[\u0C80-\u0CFF]", text or ""):
            return "kannada"
        if re.search(r"[\u0D00-\u0D7F]", text or ""):
            return "malayalam"
        return None

    def _language_query(self, context: str, hint: str | None) -> list[str]:
        """Build focused searches so autoplay does not fall into a global mix."""
        base = (context or "").split(" | ")[0].strip()
        if not hint:
            # No language was explicitly detected: keep the original context,
            # but do not invent a language and accidentally block a valid song.
            return [base] if base else []

        labels = {
            "hindi": ["Hindi movie songs", "Bollywood Hindi songs"],
            "bhojpuri": ["Bhojpuri songs", "Bhojpuri movie songs"],
            "punjabi": ["Punjabi songs", "Punjabi movie songs"],
            "tamil": ["Tamil songs", "Tamil movie songs"],
            "telugu": ["Telugu songs", "Telugu movie songs"],
            "marathi": ["Marathi songs", "Marathi movie songs"],
            "bengali": ["Bengali songs", "Bengali movie songs"],
            "gujarati": ["Gujarati songs", "Gujarati movie songs"],
            "kannada": ["Kannada songs", "Kannada movie songs"],
            "malayalam": ["Malayalam songs", "Malayalam movie songs"],
            "odia": ["Odia songs", "Odia movie songs"],
            "assamese": ["Assamese songs", "Assamese movie songs"],
        }
        queries = []
        if base:
            queries.append(f"{base} {hint} song")
        queries.extend(labels.get(hint, [f"{hint} songs"]))
        return list(dict.fromkeys(q.strip() for q in queries if q.strip()))

    def _same_language(self, title: str, channel: str, hint: str | None) -> bool:
        if not hint:
            return True
        detected = self._language_hint(f"{title} {channel}")
        if detected is None:
            # API metadata can be language-neutral. The query itself is already
            # language constrained, so allow it instead of losing autoplay.
            return True
        return detected == hint

    async def _api_search(self, base: str, key: str, query: str, limit: int = 8):
        client = await self.get_client()
        params = {"query": query, "limit": limit}
        if key:
            params["api_key"] = key
        try:
            async with client.get(f"{base}/search", params=params, timeout=8) as r:
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
        """Return a language-matched autoplay track.

        The language context is propagated from every selected autoplay track,
        so Hindi stays Hindi, Bhojpuri stays Bhojpuri, Punjabi stays Punjabi,
        etc., instead of falling into YouTube's mixed recommendations.
        """
        context = getattr(self, "track_context", {}).get(str(video_id), "")
        hint = self._language_hint(context)
        queries = self._language_query(context, hint)
        candidates = []
        seen = {str(video_id)}

        # Search both APIs in the same provider order as downloads: Shruti first,
        # then Ritesh. The query itself is language-scoped.
        for q in queries:
            for base, key in (
                (SHRUTI_API_URL, SHRUTI_API_KEY),
                (RITESH_API_URL, RITESH_API_KEY),
            ):
                for data in await self._api_search(base, key, q, 12):
                    tr = self._track_from_data(data, video=video)
                    if not tr or str(tr.id) in seen or not tr.duration_sec:
                        continue
                    if max_duration and tr.duration_sec > max_duration:
                        continue
                    if not self._same_language(tr.title or "", tr.channel_name or "", hint):
                        continue
                    seen.add(str(tr.id))
                    candidates.append(tr)
                    if len(candidates) >= 12:
                        break
                if len(candidates) >= 12:
                    break
            if len(candidates) >= 12:
                break

        # py_yt is only a last-resort metadata search. Keep the same language
        # query and filtering so it cannot introduce an unrelated language.
        if len(candidates) < 3:
            for q in queries:
                try:
                    results = await VideosSearch(q, limit=12, with_live=False).next()
                    for data in (results or {}).get("result", []):
                        tr = self._track_from_data(data, video=video)
                        if not tr or str(tr.id) in seen or not tr.duration_sec:
                            continue
                        if max_duration and tr.duration_sec > max_duration:
                            continue
                        if not self._same_language(tr.title or "", tr.channel_name or "", hint):
                            continue
                        seen.add(str(tr.id))
                        candidates.append(tr)
                        if len(candidates) >= 12:
                            break
                except Exception as e:
                    logger.warning(f"py_yt autoplay search failed: {e}")
                if len(candidates) >= 3:
                    break

        if candidates:
            selected = random.choice(candidates)
            # Critical: propagate the language context to the NEXT autoplay hop.
            selected_context = context or ""
            if hint:
                selected_context = f"{hint} | {selected.title} | {selected.channel_name}"
            else:
                selected_context = f"{selected.title} | {selected.channel_name}"
            self.track_context[str(selected.id)] = selected_context
            logger.info(
                f"[Autoplay] Selected {selected.title!r} language={hint or 'auto'}"
            )
            return selected

        logger.warning(
            f"[Autoplay] No language-matched candidate for {video_id} "
            f"(language={hint or 'auto'})"
        )
        return None

    async def _download_api(
        self, base: str, key: str, youtube_url: str, video: bool, provider: str
    ):
        """Download media from an API and always return a local file path.

        Handles both API styles:
        - JSON containing a direct media URL
        - raw binary audio/video response

        This avoids decoding binary media as UTF-8 (the old Shruti failure).
        """
        if not base:
            return None

        client = await self.get_client()
        typ = "video" if video else "audio"
        vid = self._video_id(youtube_url) or str(youtube_url).strip()
        if not vid:
            return None

        ext = "mp4" if video else "mp3"
        os.makedirs("downloads", exist_ok=True)
        path = os.path.abspath(os.path.join("downloads", f"{vid}.{ext}"))

        if os.path.exists(path) and os.path.getsize(path) > 1024:
            return path

        params = {"url": youtube_url, "type": typ}
        if key:
            params["api_key"] = key

        try:
            timeout = aiohttp.ClientTimeout(total=45, connect=6, sock_read=30)
            async with client.get(
                f"{base}/download", params=params, timeout=timeout
            ) as response:
                if response.status != 200:
                    logger.warning(
                        f"[{provider}] /download HTTP {response.status} for {vid}"
                    )
                    return None

                ctype = (
                    response.headers.get("Content-Type") or ""
                ).lower().split(";")[0].strip()

                # JSON response: locate a direct media URL.
                if "json" in ctype or ctype in (
                    "text/plain",
                    "text/html",
                    "application/javascript",
                ):
                    raw = await response.read()
                    try:
                        import json
                        data = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        logger.warning(
                            f"[{provider}] Non-JSON text response for {vid}"
                        )
                        return None

                    direct = None
                    if isinstance(data, str) and data.startswith("http"):
                        direct = data
                    elif isinstance(data, dict):
                        for key_name in (
                            "url",
                            "download_url",
                            "stream_url",
                            "link",
                            "file",
                        ):
                            value = data.get(key_name)
                            if isinstance(value, str) and value.startswith("http"):
                                direct = value
                                break
                        if not direct:
                            for nested_name in ("result", "data"):
                                nested = data.get(nested_name)
                                if isinstance(nested, dict):
                                    for key_name in (
                                        "url",
                                        "download_url",
                                        "stream_url",
                                        "link",
                                        "file",
                                    ):
                                        value = nested.get(key_name)
                                        if isinstance(value, str) and value.startswith("http"):
                                            direct = value
                                            break
                                if direct:
                                    break

                    if not direct:
                        logger.warning(
                            f"[{provider}] JSON response had no media URL for {vid}"
                        )
                        return None

                    async with client.get(direct, timeout=45) as media:
                        if media.status not in (200, 206):
                            logger.warning(
                                f"[{provider}] Direct media HTTP {media.status}"
                            )
                            return None
                        with open(path, "wb") as fh:
                            async for chunk in media.content.iter_chunked(131072):
                                if chunk:
                                    fh.write(chunk)
                else:
                    # Raw binary response. NEVER decode this as UTF-8.
                    with open(path, "wb") as fh:
                        async for chunk in response.content.iter_chunked(131072):
                            if chunk:
                                fh.write(chunk)

            if os.path.exists(path) and os.path.getsize(path) > 1024:
                logger.info(f"[{provider}] Download successful: {vid}")
                return path

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[{provider}] Download failed for {vid}: {e}")

        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
        return None

    async def download(self, video_id: str, video: bool = False) -> str | None:
        """Download with strict priority: Shruti -> Ritesh -> yt-dlp."""
        vid = self._video_id(video_id) or str(video_id).strip()
        if not vid:
            return None

        url = self.base + vid

        for provider, base, key in (
            ("Shruti", SHRUTI_API_URL, SHRUTI_API_KEY),
            ("Ritesh", RITESH_API_URL, RITESH_API_KEY),
        ):
            path = await self._download_api(
                base, key, url, video, provider
            )
            if path:
                return path

        # Last resort: local yt-dlp.
        try:
            import yt_dlp
            os.makedirs("downloads", exist_ok=True)
            ext = "mp4" if video else "mp3"
            out = os.path.abspath(os.path.join("downloads", f"{vid}.{ext}"))
            opts = {
                "outtmpl": out,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "overwrites": False,
                "format": (
                    "bestvideo+bestaudio/best"
                    if video
                    else "bestaudio/best"
                ),
                "merge_output_format": "mp4" if video else None,
                "socket_timeout": 10,
                "retries": 1,
            }
            opts = {k: v for k, v in opts.items() if v is not None}

            def _run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])

            await asyncio.to_thread(_run)
            if os.path.exists(out) and os.path.getsize(out) > 1024:
                return out
        except Exception as e:
            logger.warning(f"[yt-dlp] Fallback failed for {vid}: {e}")

        return None

    async def stream_url(self, video_id: str, video: bool = False) -> str | None:
        """Compatibility method required by plugins/play.py.

        `play.py` expects a stream_url() method. The API providers may return
        either a remote URL or raw media bytes, so the reliable contract here
        is a playable LOCAL file path. PyTgCalls can consume that path directly.
        """
        return await self.download(video_id, video=video)

    async def close(self):
        if self._client and not self._client.closed:
            await self._client.close()
