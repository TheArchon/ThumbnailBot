# Copyright (C) 2025-present by TheAloneTeam@Github
# Licensed under the MIT License.

import asyncio
import os
import random
import re
import time
import urllib.parse
from typing import Any

import aiohttp
from py_yt import Playlist, VideosSearch

from ArchonMusic import logger
from ArchonMusic.helpers import Track, utils


# ---------------------------------------------------------------------------
# API CONFIG
# SHRUTI is primary, RITESH is fallback, yt-dlp is the last fallback.
#
# IMPORTANT:
# /download may return binary media, NOT JSON. Never call response.text()
# or response.json() on a media response.
# ---------------------------------------------------------------------------
SHRUTI_API_URL = os.getenv(
    "SHRUTI_API_URL",
    "https://api01.shrutibots.site",
).rstrip("/")
SHRUTI_API_KEY = os.getenv("SHRUTI_API_KEY", "ShrutiBotsfhGT4c09sFRRuQIB6yCG").strip()

RITESH_API_URL = os.getenv(
    "API_URL",
    "https://web.riteshyt.in",
).rstrip("/")
RITESH_API_KEY = os.getenv("API_KEY", "riteshfreea6901be19d3f420aad766250").strip()


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        # Prevent duplicate background prefetches.
        self._recent_prefetches = {}
        self._stream_cache = {}
        self._stream_cache_ttl = 180

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

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    async def get_client(self):
        if self._client is None or self._client.closed:
            self._client = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=60,
                    connect=8,
                    sock_connect=8,
                    sock_read=45,
                ),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Linux; Android 13) "
                        "AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36"
                    ),
                    "Accept": "*/*",
                },
            )
        return self._client

    @staticmethod
    def _api_candidates(base: str, endpoint: str):
        endpoint = endpoint.lstrip("/")
        return (
            f"{base}/{endpoint}",
            f"{base}/api/{endpoint}",
        )

    @staticmethod
    def _with_api_key(params: dict, key: str):
        result = dict(params or {})
        if key:
            # Different deployments use different names. Supplying both is
            # harmless for APIs that ignore unknown query parameters.
            result.setdefault("api_key", key)
            result.setdefault("key", key)
        return result

    async def _request_json(
        self,
        base: str,
        key: str,
        endpoint: str,
        params: dict,
    ):
        """Request an API endpoint that is EXPECTED to return JSON.

        This method deliberately handles decoding from raw bytes first. That
        avoids the old UnicodeDecodeError when an endpoint unexpectedly
        returns binary media.
        """
        if not base:
            return None

        client = await self.get_client()
        request_params = self._with_api_key(params, key)

        for url in self._api_candidates(base, endpoint):
            try:
                async with client.get(
                    url,
                    params=request_params,
                    allow_redirects=True,
                ) as response:
                    status = response.status

                    if status == 404:
                        continue

                    if status >= 400:
                        logger.warning(
                            f"API {base} {endpoint} returned HTTP {status}"
                        )
                        continue

                    raw = await response.read()

                    if not raw:
                        logger.warning(
                            f"API {base} {endpoint} returned an empty response"
                        )
                        continue

                    # Decode only after we know the endpoint returned data.
                    try:
                        import json

                        return json.loads(raw.decode("utf-8-sig"))
                    except (UnicodeDecodeError, ValueError, TypeError):
                        # This is expected when an endpoint returns audio/video.
                        preview = raw[:80].hex()
                        logger.warning(
                            f"API {base} {endpoint} returned non-JSON/binary "
                            f"response ({len(raw)} bytes, head={preview})"
                        )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    f"API request failed {url}: {type(e).__name__}: {e}"
                )

        return None

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------
    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        return bool(re.match(self.iregex, url))

    def _clean_link(self, link: str):
        if not link:
            return ""

        link = str(link).strip()

        # Keep only the YouTube video itself when possible.
        match = re.search(
            r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})",
            link,
        )
        if match:
            return self.base + match.group(1)

        if "&" in link:
            link = link.split("&", 1)[0]

        if "?si=" in link:
            link = link.split("?si=", 1)[0]

        elif "&si=" in link:
            link = link.split("&si=", 1)[0]

        return link

    @staticmethod
    def _video_id(value: str):
        if not value:
            return None

        value = str(value)

        if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
            return value

        match = re.search(
            r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})",
            value,
        )
        return match.group(1) if match else None

    # ------------------------------------------------------------------
    # API payload helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _items(payload: Any):
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            return []

        for key in (
            "result",
            "results",
            "videos",
            "data",
            "items",
        ):
            value = payload.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for subkey in (
                    "result",
                    "results",
                    "videos",
                    "items",
                ):
                    if isinstance(value.get(subkey), list):
                        return value[subkey]

        return []

    @staticmethod
    def _field(data: dict, *keys, default=None):
        for key in keys:
            value = data.get(key)

            if value is not None and value != "":
                return value

        return default

    def _track_from_data(
        self,
        data: dict,
        m_id: int,
        video: bool = False,
    ):
        if not isinstance(data, dict):
            return None

        vid = self._field(
            data,
            "id",
            "video_id",
            "videoId",
            "youtube_id",
        )

        link = self._field(
            data,
            "link",
            "url",
            "video_url",
            "webpage_url",
        )

        if not vid and link:
            vid = self._video_id(str(link))

        if not vid:
            return None

        vid = str(vid)

        if not link:
            link = self.base + vid

        title = str(
            self._field(
                data,
                "title",
                "name",
                default="YouTube",
            )
        )

        channel = self._field(
            data,
            "channel",
            "uploader",
            "author",
            default="",
        )

        if isinstance(channel, dict):
            channel = (
                channel.get("name")
                or channel.get("title")
                or ""
            )

        thumbs = self._field(
            data,
            "thumbnails",
            "thumbnail",
            "thumb",
            default=[],
        )

        thumb = ""

        if isinstance(thumbs, list) and thumbs:
            # Prefer the largest/last thumbnail returned by the API.
            last = thumbs[-1]
            thumb = (
                last.get("url", "")
                if isinstance(last, dict)
                else str(last)
            )

        elif isinstance(thumbs, dict):
            thumb = thumbs.get("url", "")

        elif thumbs:
            thumb = str(thumbs)

        duration = self._field(
            data,
            "duration",
            "length",
            default="00:00",
        )

        try:
            duration_sec = int(
                self._field(
                    data,
                    "duration_sec",
                    "duration_seconds",
                    default=0,
                )
                or 0
            )
        except (TypeError, ValueError):
            duration_sec = utils.to_seconds(str(duration))

        if not duration_sec:
            duration_sec = utils.to_seconds(str(duration))

        views = self._field(
            data,
            "viewCount",
            "views",
            "view_count",
            default="",
        )

        if isinstance(views, dict):
            views = (
                views.get("short")
                or views.get("text")
                or ""
            )

        return Track(
            id=vid,
            channel_name=str(channel or ""),
            duration=str(duration or "00:00"),
            duration_sec=duration_sec,
            message_id=m_id,
            title=title[:25],
            thumbnail=(
                thumb.split("?")[0]
                if thumb
                else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            ),
            url=str(link),
            view_count=str(views or ""),
            video=video,
        )

    async def _direct_youtube_track(self, value: str, m_id: int, video: bool = False):
        """Convert a YouTube URL to a Track immediately.

        URL playback must never go through search.  Metadata lookup is kept
        out of the critical path so a pasted link can reach the stream
        downloader immediately.
        """
        vid = self._video_id(value)
        if not vid:
            return None

        link = self.base + vid
        return Track(
            id=vid,
            channel_name="YouTube",
            duration="00:00",
            duration_sec=0,
            message_id=m_id,
            title=f"YouTube - {vid}",
            thumbnail=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            url=link,
            view_count="",
            video=video,
        )

    # ------------------------------------------------------------------
    # SEARCH
    # ------------------------------------------------------------------
    async def _search_api(
        self,
        name: str,
        base: str,
        key: str,
        query: str,
        m_id: int,
        video: bool,
    ):
        if not base:
            return None

        # Keep the critical search path to one request.  If the provider
        # rejects the canonical parameter, the local search running in
        # parallel can win without waiting for more API variants.
        variants = [
            {"query": query, "limit": 1},
        ]

        for params in variants:
            payload = await self._request_json(
                base,
                key,
                "search",
                params,
            )

            if payload is None:
                continue

            items = self._items(payload)

            if not items:
                continue

            # Find the first usable YouTube video instead of blindly taking
            # an invalid API object.
            for item in items:
                track = self._track_from_data(
                    item,
                    m_id,
                    video,
                )

                if track:
                    logger.info(
                        f"{name} search succeeded for: {query}"
                    )
                    return track

        return None

    async def search(
        self,
        query: str,
        m_id: int,
        video: bool = False,
    ) -> Track | None:
        """Find a track quickly; direct YouTube URLs bypass all searching."""
        # A pasted YouTube link is already the requested track.  Do not send
        # it through SHRUTI/RITESH/local search, which can add seconds and may
        # return a different video.
        direct = await self._direct_youtube_track(query, m_id, video)
        if direct:
            logger.info(f"Direct YouTube link detected: {direct.id}")
            return direct

        # Search providers are raced instead of being tried one after another.
        # A slow/422 API must not block a faster local YouTube result.
        async def api_search(name, base, key):
            return await self._search_api(
                name, base, key, query, m_id, video
            )

        tasks = []

        # Start both remote searches immediately.
        if SHRUTI_API_URL:
            tasks.append(asyncio.create_task(
                api_search("SHRUTI", SHRUTI_API_URL, SHRUTI_API_KEY)
            ))

        # Start local YouTube search at the same time. This prevents a 422/401
        # from either API from delaying the actual song selection.
        async def local_search():
            try:
                searcher = VideosSearch(
                    query,
                    limit=1,
                    with_live=False,
                )
                results = await searcher.next()
                if results and results.get("result"):
                    track = self._track_from_data(
                        results["result"][0], m_id, video
                    )
                    if track:
                        logger.info(
                            f"Local YouTube search succeeded for: {query}"
                        )
                        return track
            except Exception as e:
                logger.warning(
                    f"YouTube library fallback failed for {query}: {e}"
                )
            return None

        tasks.append(asyncio.create_task(local_search()))

        try:
            for finished in asyncio.as_completed(tasks):
                try:
                    track = await finished
                except asyncio.CancelledError:
                    continue
                except Exception as e:
                    logger.warning(
                        f"Parallel YouTube search failed for {query}: {e}"
                    )
                    continue

                if track:
                    return track
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.error(
            f"All YouTube search providers failed for: {query}"
        )
        return None

    # ------------------------------------------------------------------
    # PLAYLIST
    # ------------------------------------------------------------------
    async def playlist(
        self,
        limit: int,
        user: str,
        url: str,
        video: bool,
    ) -> list[Track | None]:
        url = self._clean_link(url)

        for name, base, key in (
            ("SHRUTI", SHRUTI_API_URL, SHRUTI_API_KEY),
            ("RITESH", RITESH_API_URL, RITESH_API_KEY),
        ):
            if not base:
                continue

            payload = await self._request_json(
                base,
                key,
                "playlist",
                {
                    "link": url,
                    "limit": limit,
                },
            )

            if not payload:
                continue

            tracks = []

            for data in self._items(payload)[:limit]:
                track = self._track_from_data(
                    data,
                    0,
                    video,
                )

                if track:
                    track.user = user
                    tracks.append(track)

            if tracks:
                logger.info(
                    f"{name} playlist succeeded"
                )
                return tracks

        try:
            plist = await Playlist.get(url)
            tracks = []

            for data in plist.get("videos", [])[:limit]:
                track = self._track_from_data(
                    data,
                    0,
                    video,
                )

                if track:
                    track.user = user
                    tracks.append(track)

            return tracks

        except Exception as e:
            logger.warning(
                f"Playlist fallback failed: {e}"
            )
            return []

    # ------------------------------------------------------------------
    # PREFETCH
    # ------------------------------------------------------------------
    async def _prefetch_api(
        self,
        base: str,
        key: str,
        name: str,
        link: str,
        dl_type: str,
        vidid: str,
    ) -> bool:
        """Prefetch without trying to decode media as UTF-8.

        Some /download endpoints return the actual MP3/MP4 bytes. The old
        implementation sent that response through _request_json(), which
        produced errors such as:
            'utf-8' codec can't decode byte 0x9f...
        """
        if not base:
            return False

        client = await self.get_client()

        common = {
            "url": link,
            "query": link,
            "type": dl_type,
            "dl_type": dl_type,
            "prefetch": "true",
        }

        params = self._with_api_key(common, key)

        for endpoint in ("download", "downloads"):
            for endpoint_url in self._api_candidates(
                base,
                endpoint,
            ):
                try:
                    async with client.get(
                        endpoint_url,
                        params=params,
                        allow_redirects=False,
                        headers={
                            "Accept": "application/json, text/plain, */*",
                        },
                    ) as response:
                        status = response.status

                        # 3xx means the API accepted the request and wants
                        # the media client to follow another URL.
                        if 200 <= status < 400:
                            logger.info(
                                f"{name} prefetch accepted for {vidid}"
                            )

                            # Do NOT read the whole media response.
                            return True

                        if status == 401:
                            logger.warning(
                                f"{name} prefetch returned HTTP 401 for {vidid} "
                                f"(API key rejected)"
                            )
                            continue

                        if status == 404:
                            continue

                        logger.warning(
                            f"{name} prefetch returned HTTP {status} "
                            f"for {vidid}"
                        )

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"{name} prefetch failed for {vidid}: "
                        f"{type(e).__name__}: {e}"
                    )

        return False

    async def prefetch(
        self,
        link: str,
        video: bool = False,
    ):
        dl_type = "video" if video else "audio"
        link = self._clean_link(link)

        vidid = self._video_id(link) or link

        cache_key = f"{vidid}_{dl_type}"
        now = time.time()

        old = self._recent_prefetches.get(cache_key)

        if old and now - old < 30:
            return True

        self._recent_prefetches[cache_key] = now

        for base, key, name in (
            (
                SHRUTI_API_URL,
                SHRUTI_API_KEY,
                "SHRUTI",
            ),
            (
                RITESH_API_URL,
                RITESH_API_KEY,
                "RITESH",
            ),
        ):
            accepted = await self._prefetch_api(
                base,
                key,
                name,
                link,
                dl_type,
                vidid,
            )

            if accepted:
                return True

        return False

    # ------------------------------------------------------------------
    # RELATED / AUTOPLAY
    # ------------------------------------------------------------------
    async def get_related(
        self,
        video_id: str,
        video: bool = False,
        max_duration: int = 0,
        query: str | None = None,
        language_hint: str | None = None,
    ) -> Track | None:
        """Get an autoplay candidate without depending on one py_yt API.

        Older py_yt releases exposed Recommendations.getRelated(), while
        newer releases may not.  Autoplay must not stop just because that
        optional recommendations endpoint is unavailable, so fall back to a
        normal YouTube search when possible.
        """
        try:
            from py_yt import Recommendations

            get_related = getattr(Recommendations, "getRelated", None)
            if get_related:
                results = await get_related(video_id)

                if isinstance(results, dict):
                    videos = [
                        r
                        for r in results.get("result", [])
                        if r.get("type") == "video"
                        and r.get("id") != video_id
                    ]

                    if max_duration:
                        videos = [
                            v
                            for v in videos
                            if utils.to_seconds(
                                v.get("duration") or "00:00"
                            ) <= max_duration
                        ]

                    if videos:
                        # Prefer candidates whose title matches the current
                        # track's detected language. Keep a soft fallback so
                        # autoplay does not stop when metadata is ambiguous.
                        if language_hint:
                            matching = []
                            for candidate in videos:
                                title = str(candidate.get("title") or "")
                                hint = language_hint
                                has_dev = any("\u0900" <= ch <= "\u097f" for ch in title)
                                bhoj = any(w in title.lower() for w in (
                                    "bhojpuri", "भोजपुरी", "भोजपुरिया", "का हो",
                                    "कइसे", "रउआ", "रउरा", "हमार", "तोहार", "बाड़े",
                                    "बानी", "छठ", "लइकी", "लइका", "सइयाँ", "बलम",
                                ))
                                ok = (hint == "hindi" and has_dev) or (hint == "bhojpuri" and bhoj) or (hint == "english" and not has_dev and not bhoj)
                                if ok:
                                    matching.append(candidate)
                            if matching:
                                videos = matching
                        track = self._track_from_data(random.choice(videos), 0, video)
                        if track:
                            return track
            else:
                logger.info("Recommendations.getRelated unavailable; using search fallback")

        except Exception as e:
            logger.info(f"Related video lookup unavailable; using search fallback: {type(e).__name__}")

        # Compatibility fallback for py_yt versions without Recommendations.
        # A title/query is preferred; if unavailable, search the current video
        # URL/id so autoplay still has a chance to continue.
        search_query = (query or "").strip()
        if language_hint == "bhojpuri":
            search_query = f"Bhojpuri {search_query} song" if search_query else "Bhojpuri latest songs"
        elif language_hint == "hindi":
            search_query = f"Hindi {search_query} song" if search_query else "Hindi latest songs"
        elif language_hint == "english":
            search_query = f"English {search_query} song" if search_query else "English latest songs"
        if not search_query:
            search_query = f"YouTube {video_id}"

        try:
            searcher = VideosSearch(search_query, limit=5, with_live=False)
            results = await searcher.next()
            items = results.get("result", []) if isinstance(results, dict) else []

            candidates = []
            for item in items:
                item_id = item.get("id")
                if not item_id or item_id == video_id:
                    continue
                duration = utils.to_seconds(item.get("duration") or "00:00")
                if max_duration and duration > max_duration:
                    continue
                track = self._track_from_data(item, 0, video)
                if track:
                    candidates.append(track)

            if candidates and language_hint:
                def lang_score(track):
                    title = str(track.title or "")
                    low = title.lower()
                    has_dev = any("\u0900" <= ch <= "\u097f" for ch in title)
                    bhoj = any(w in low for w in (
                        "bhojpuri", "भोजपुरी", "भोजपुरिया", "का हो", "कइसे",
                        "रउआ", "रउरा", "हमार", "तोहार", "बाड़े", "बानी", "छठ",
                        "लइकी", "लइका", "सइयाँ", "बलम",
                    ))
                    if language_hint == "hindi": return 2 if has_dev else 0
                    if language_hint == "bhojpuri": return 2 if bhoj else 0
                    return 2 if not has_dev and not bhoj else 0
                candidates.sort(key=lang_score, reverse=True)
            if candidates:
                return random.choice(candidates)
        except Exception as e:
            logger.warning(f"Autoplay search fallback failed for {video_id}: {e}")

        return None

    # ------------------------------------------------------------------
    # STREAM URL PROBE
    # ------------------------------------------------------------------
    async def _probe_stream(
        self,
        name: str,
        stream_url: str,
        video_id: str,
    ):
        """Validate a media endpoint without decoding its body.

        This is the important fix for the UTF-8 error. Media bytes are never
        passed through response.text() or response.json().
        """
        client = await self.get_client()

        try:
            async with client.get(
                stream_url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=4, connect=2, sock_connect=2, sock_read=3),
                headers={
                    "Accept": "*/*",
                    "Range": "bytes=0-1023",
                },
            ) as response:
                status = response.status
                final_url = str(response.url)

                if status in (200, 206):
                    # Only consume a tiny amount. Never decode it.
                    await response.content.read(1024)

                    logger.info(
                        f"{name} stream ready for {video_id}"
                    )

                    return final_url

                if status == 401:
                    logger.warning(
                        f"{name} stream returned HTTP 401 for {video_id}"
                    )
                    return None

                if status == 403:
                    logger.warning(
                        f"{name} stream returned HTTP 403 for {video_id}"
                    )
                    return None

                if status == 404:
                    logger.warning(
                        f"{name} stream returned HTTP 404 for {video_id}"
                    )
                    return None

                if status == 422:
                    logger.warning(
                        f"{name} stream returned HTTP 422 for {video_id}"
                    )
                    return None

                if status >= 500:
                    logger.warning(
                        f"{name} stream returned HTTP {status} "
                        f"for {video_id}"
                    )
                    return None

                logger.warning(
                    f"{name} stream returned HTTP {status} "
                    f"for {video_id}"
                )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                f"{name} stream check failed for {video_id}: "
                f"{type(e).__name__}: {e}"
            )

        return None

    # ------------------------------------------------------------------
    # yt-dlp LAST FALLBACK
    # ------------------------------------------------------------------
    async def _ytdlp_stream(
        self,
        video_id: str,
        video: bool = False,
    ):
        """Last-resort extractor.

        APIs remain preferred. This is only reached when both API providers
        fail. No cookies are invented or embedded here.
        """
        try:
            import yt_dlp

            url = self.base + video_id

            def extract():
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "noplaylist": True,
                    "extract_flat": False,
                    "nocheckcertificate": True,
                }

                if video:
                    opts["format"] = (
                        "best[ext=mp4]/best"
                    )
                else:
                    opts["format"] = (
                        "bestaudio/best"
                    )

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(
                        url,
                        download=False,
                    )

                    if not info:
                        return None

                    direct = info.get("url")

                    if direct:
                        return direct

                    formats = info.get("formats") or []

                    if video:
                        wanted = [
                            f
                            for f in formats
                            if f.get("url")
                            and (
                                f.get("vcodec")
                                not in (None, "none")
                            )
                        ]
                    else:
                        wanted = [
                            f
                            for f in formats
                            if f.get("url")
                            and (
                                f.get("acodec")
                                not in (None, "none")
                            )
                        ]

                    if not wanted:
                        return None

                    wanted.sort(
                        key=lambda f: (
                            f.get("abr")
                            or f.get("tbr")
                            or 0
                        ),
                        reverse=True,
                    )

                    return wanted[0].get("url")

            direct = await asyncio.to_thread(
                extract
            )

            if direct:
                logger.info(
                    f"yt-dlp stream ready for {video_id}"
                )
                return direct

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                f"yt-dlp fallback failed for {video_id}: "
                f"{type(e).__name__}: {e}"
            )

        return None

    # ------------------------------------------------------------------
    # DOWNLOAD
    # ------------------------------------------------------------------
    async def _download_provider(
        self,
        name: str,
        base: str,
        key: str,
        url: str,
        dl_type: str,
        video_id: str,
    ):
        """Try one provider with the minimum number of HTTP requests.

        The old downloader tried many endpoint/parameter combinations for
        every provider. That made a fast SHRUTI response wait behind several
        RITESH 404/422 probes. We now try the normal /download endpoint once.
        """
        if not base:
            return None

        client = await self.get_client()
        params = self._with_api_key(
            {
                "url": url,
                "type": dl_type,
            },
            key,
        )

        endpoint = f"{base}/download"

        try:
            async with client.get(
                endpoint,
                params=params,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(
                    total=4,
                    connect=2,
                    sock_connect=2,
                    sock_read=3,
                ),
                headers={"Accept": "*/*", "Range": "bytes=0-1023"},
            ) as response:
                status = response.status
                final_url = str(response.url)

                if status in (200, 206):
                    await response.content.read(1024)
                    logger.info(
                        f"{name} stream ready for {video_id}"
                    )
                    return final_url

                if status == 404:
                    # 404 means this provider has no stream for this video.
                    # Do not repeat the same request with several aliases.
                    logger.warning(
                        f"{name} stream returned HTTP 404 for {video_id}; "
                        "skipping provider"
                    )
                    return None

                logger.warning(
                    f"{name} stream returned HTTP {status} for {video_id}"
                )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                f"{name} stream check failed for {video_id}: "
                f"{type(e).__name__}: {e}"
            )

        return None

    async def download(
        self,
        video_id: str,
        video: bool = False,
    ) -> str | None:
        """Return a media URL with fast provider fallback.

        SHRUTI and RITESH are raced together so a 404/401 from RITESH cannot
        delay a successful SHRUTI stream. yt-dlp is used only if both APIs
        fail. No media response is decoded as UTF-8.
        """
        video_id = self._video_id(video_id) or str(video_id).strip()

        if not video_id:
            return None

        url = self.base + video_id
        dl_type = "video" if video else "audio"

        cache_key = f"{video_id}:{dl_type}"
        cached = self._stream_cache.get(cache_key)
        if cached:
            cached_url, cached_at = cached
            if time.time() - cached_at < self._stream_cache_ttl:
                return cached_url
            self._stream_cache.pop(cache_key, None)

        providers = (
            ("SHRUTI", SHRUTI_API_URL, SHRUTI_API_KEY),
            ("RITESH", RITESH_API_URL, RITESH_API_KEY),
        )

        tasks = [
            asyncio.create_task(
                self._download_provider(
                    name,
                    base,
                    key,
                    url,
                    dl_type,
                    video_id,
                )
            )
            for name, base, key in providers
            if base
        ]

        try:
            for finished in asyncio.as_completed(tasks):
                try:
                    result = await finished
                except asyncio.CancelledError:
                    continue
                except Exception as e:
                    logger.warning(
                        f"Parallel stream provider failed for {video_id}: "
                        f"{type(e).__name__}: {e}"
                    )
                    continue

                if result:
                    self._stream_cache[cache_key] = (result, time.time())
                    return result
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.warning(
            f"SHRUTI/RITESH stream unavailable for {video_id}; "
            "trying yt-dlp fallback"
        )

        direct = await self._ytdlp_stream(
            video_id,
            video=video,
        )

        if direct:
            self._stream_cache[cache_key] = (direct, time.time())
            return direct

        logger.error(
            f"All YouTube stream sources failed for: {video_id}"
        )
        return None

    # ------------------------------------------------------------------
    # CLOSE
    # ------------------------------------------------------------------
    async def close(self):
        if self._client and not self._client.closed:
            await self._client.close()
            self._client = None
