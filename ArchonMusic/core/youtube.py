import os
import re
import asyncio
import aiohttp
import random
from difflib import SequenceMatcher
from urllib.parse import quote
import yt_dlp
from py_yt import VideosSearch, Playlist
from ArchonMusic import logger, config
from ArchonMusic.helpers import Track, utils

RITESH_API_URL = os.environ.get("API_URL", "https://web.riteshyt.in").rstrip("/")
RITESH_API_KEY = os.environ.get("API_KEY", "")

SHRUTI_API_URL = os.environ.get("SHRUTI_API_URL", "https://shrutibots.site").rstrip("/")
SHRUTI_API_KEY = os.environ.get("SHRUTI_API_KEY", "")

DOWNLOAD_DIR = "downloads"


def _youtube_video_id(value: str) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    m = re.search(r"(?:v=|youtu\.be/|youtube\.com/(?:shorts/|embed/|live/))([A-Za-z0-9_-]{11})", value)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    return None


async def _http_download(url: str, file_path: str, timeout: int) -> str | None:
    try:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout, connect=15)) as session:
            async with session.get(url) as resp:
                if resp.status not in (200, 206):
                    logger.warning(f"[Download] HTTP {resp.status} from {url.split('?')[0]}")
                    return None
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype or "text/html" in ctype:
                    logger.warning(f"[Download] Non-media response from {url.split('?')[0]}")
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)
        return file_path if os.path.exists(file_path) and os.path.getsize(file_path) > 0 else None
    except Exception as e:
        logger.warning(f"[Download] request failed: {e}")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        return None


async def _shruti_download(video_id: str, video: bool = False) -> str | None:
    if not SHRUTI_API_KEY:
        logger.warning("[Shruti] SHRUTI_API_KEY is not configured")
        return None
    ext = "mp4" if video else "m4a"
    path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    endpoint = f"{SHRUTI_API_URL}/download"
    params = {
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "type": "video" if video else "audio",
        "api_key": SHRUTI_API_KEY,
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600, connect=15)) as session:
            async with session.get(endpoint, params=params) as resp:
                if resp.status not in (200, 206):
                    logger.warning(f"[Shruti] HTTP {resp.status}")
                    return None
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype or "text/" in ctype:
                    logger.warning("[Shruti] API returned an error response")
                    return None
                os.makedirs(DOWNLOAD_DIR, exist_ok=True)
                with open(path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            logger.info(f"[Shruti] Download successful: {video_id}")
            return path
    except Exception as e:
        logger.warning(f"[Shruti] Download failed: {e}")
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    return None


async def _ritesh_download(video_id: str, video: bool = False) -> str | None:
    if not RITESH_API_KEY:
        return None
    ext = "mp4" if video else "mp3"
    path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    # Ritesh optimized media route.
    url = f"{RITESH_API_URL}/downloads/{RITESH_API_KEY}/youtube.com/{video_id}.{ext}"
    result = await _http_download(url, path, 600)
    if result:
        logger.info(f"[Ritesh] Download successful: {video_id}")
    return result


async def _ytdlp_download(video_id: str, video: bool = False) -> str | None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    ext = "mp4" if video else "mp3"
    out = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "outtmpl": out, "retries": 2, "socket_timeout": 20,
        "geo_bypass": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" if video else "bestaudio/best",
        "merge_output_format": "mp4" if video else None,
        "postprocessors": [] if video else [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
    }
    opts = {k: v for k, v in opts.items() if v is not None}
    try:
        cookie = None
        cookie_dir = "AloneX/cookies"
        if os.path.exists(cookie_dir):
            files = [f for f in os.listdir(cookie_dir) if f.endswith(".txt")]
            if files:
                cookie = os.path.join(cookie_dir, random.choice(files))
        if cookie:
            opts["cookiefile"] = cookie
        def extract():
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        await asyncio.get_running_loop().run_in_executor(None, extract)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
        if not video:
            mp3 = os.path.splitext(out)[0] + ".mp3"
            if os.path.exists(mp3) and os.path.getsize(mp3) > 0:
                return mp3
    except Exception as e:
        logger.warning(f"[yt-dlp] Download failed: {e}")
    return None


async def download_song(link: str) -> str | None:
    video_id = _youtube_video_id(link)
    if not video_id:
        return None
    # Priority: Shruti -> Ritesh -> yt-dlp
    return (await _shruti_download(video_id, False)
            or await _ritesh_download(video_id, False)
            or await _ytdlp_download(video_id, False))


async def download_video(link: str) -> str | None:
    video_id = _youtube_video_id(link)
    if not video_id:
        return None
    # Priority: Shruti -> Ritesh -> yt-dlp
    return (await _shruti_download(video_id, True)
            or await _ritesh_download(video_id, True)
            or await _ytdlp_download(video_id, True))


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        # Keep the original user search outside Track so the Track dataclass
        # stays backwards-compatible. This lets autoplay preserve language
        # context across the autoplay chain.
        self.track_context: dict[str, str] = {}
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.cookie_dir = "AloneX/cookies"

    async def get_client(self):
        client = getattr(self, "_client", None)
        if client is None or client.closed:
            self._client = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=600, connect=15)
            )
        return self._client

    def get_cookies(self):
        if not os.path.exists(self.cookie_dir):
            return None
        cookies_files = [f for f in os.listdir(self.cookie_dir) if f.endswith(".txt")]
        if not cookies_files:
            return None
        return os.path.join(self.cookie_dir, random.choice(cookies_files))

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        os.makedirs(self.cookie_dir, exist_ok=True)
        async with aiohttp.ClientSession() as session:
            for i, url in enumerate(urls):
                path = f"{self.cookie_dir}/cookie_{i}.txt"
                link = "https://batbin.me/api/v2/paste/" + url.split("/")[-1]
                async with session.get(link) as resp:
                    resp.raise_for_status()
                    with open(path, "wb") as fw:
                        fw.write(await resp.read())
        logger.info(f"Cookies saved in {self.cookie_dir}.")

    def valid(self, url: str) -> bool:
        return bool(url and re.match(self.regex, str(url)))

    def invalid(self, url: str) -> bool:
        return not self.valid(url)

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        # Search priority: Ritesh API -> py_yt/yt-dlp fallback. Shruti currently
        # exposes download/stream endpoints, not a public search endpoint.
        if not query:
            return None
        try:
            client = await self.get_client()
            params = {"query": query, "limit": 1}
            if RITESH_API_KEY:
                params["api_key"] = RITESH_API_KEY
            async with client.get(f"{RITESH_API_URL}/search", params=params) as resp:
                if resp.status == 200:
                    payload = await resp.json(content_type=None)
                    items = payload.get("result") or payload.get("results") or payload.get("data") or []
                    if isinstance(items, dict):
                        items = items.get("result") or items.get("results") or [items]
                    if items:
                        data = items[0]
                        track = Track(
                            id=data.get("id"),
                            channel_name=(data.get("channel") or {}).get("name") if isinstance(data.get("channel"), dict) else data.get("channel"),
                            duration=data.get("duration"),
                            duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                            message_id=m_id, title=(data.get("title") or "")[:80],
                            thumbnail=((data.get("thumbnails") or [{}])[-1].get("url") or "").split("?")[0],
                            url=data.get("link") or data.get("url"),
                            view_count=(data.get("viewCount") or {}).get("short") if isinstance(data.get("viewCount"), dict) else data.get("viewCount"),
                            video=video,
                        )
                        if track.id:
                            self.track_context[str(track.id)] = str(query).strip()
                            return track
        except Exception as e:
            logger.warning(f"[Ritesh] Search failed: {e}")

        try:
            results = await VideosSearch(query, limit=1).next()
            if results and results.get("result"):
                data = results["result"][0]
                track = Track(
                    id=data.get("id"), channel_name=(data.get("channel") or {}).get("name"),
                    duration=data.get("duration"), duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                    message_id=m_id, title=(data.get("title") or "")[:80],
                    thumbnail=((data.get("thumbnails") or [{}])[-1].get("url") or "").split("?")[0],
                    url=data.get("link"), view_count=(data.get("viewCount") or {}).get("short") if isinstance(data.get("viewCount"), dict) else data.get("viewCount"),
                    video=video,
                )
                if track.id:
                    self.track_context[str(track.id)] = str(query).strip()
                return track
        except Exception as e:
            logger.error(f"[yt_yt] Search fallback failed: {e}")
        return None

    async def stream_url(self, video_id: str, video: bool = False) -> str | None:
        """Priority: Shruti stream -> Ritesh stream -> yt-dlp direct URL."""
        vid = _youtube_video_id(video_id) or str(video_id or "").strip()
        if not vid:
            return None
        client = await self.get_client()

        # 1) Shruti stream
        if SHRUTI_API_KEY:
            try:
                url = f"{SHRUTI_API_URL}/stream/{vid}"
                async with client.get(url, params={"api_key": SHRUTI_API_KEY}, headers={"Range": "bytes=0-1"}) as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if resp.status in (200, 206) and "json" not in ctype and "text/html" not in ctype:
                        logger.info(f"[Shruti] Stream ready: {vid}")
                        return str(resp.url)
            except Exception as e:
                logger.warning(f"[Shruti] Stream failed: {e}")

        # 2) Ritesh optimized stream
        if RITESH_API_KEY:
            ext = "mp4" if video else "mp3"
            url = f"{RITESH_API_URL}/downloads/{RITESH_API_KEY}/youtube.com/{vid}.{ext}"
            try:
                async with client.get(url, headers={"Range": "bytes=0-1"}) as resp:
                    if resp.status in (200, 206):
                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if "json" not in ctype and "text/html" not in ctype:
                            logger.info(f"[Ritesh] Stream ready: {vid}")
                            return url
            except Exception as e:
                logger.warning(f"[Ritesh] Stream failed: {e}")

        # 3) yt-dlp fallback
        url = f"https://www.youtube.com/watch?v={vid}"
        cookie = self.get_cookies()
        clients = ["web", "android", "tv", "web_safari"]
        for player in clients:
            opts = {
                "quiet": True, "no_warnings": True, "skip_download": True,
                "noplaylist": True, "geo_bypass": True, "socket_timeout": 10,
                "retries": 1, "extractor_retries": 1,
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" if video else "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                "extractor_args": {"youtube": {"player_client": [player]}},
            }
            if cookie:
                opts["cookiefile"] = cookie
            def extract():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    return (info or {}).get("url")
            try:
                direct = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, extract), timeout=15)
                if direct:
                    logger.info(f"[yt-dlp] Direct stream ready via {player}: {vid}")
                    return direct
            except Exception as e:
                logger.warning(f"[yt-dlp] stream client {player} failed for {vid}: {e}")
        return None

    async def close(self):
        client = getattr(self, "_client", None)
        if client and not client.closed:
            await client.close()

    async def track_from_url(self, url: str, m_id: int, video: bool = False) -> Track | None:
        """Build track metadata for a direct YouTube URL without py_yt extraction."""
        vid = _youtube_video_id(url)
        if not vid:
            return None
        try:
            client = await self.get_client()
            async with client.get(
                "https://www.youtube.com/oembed",
                params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    title = data.get("title") or "YouTube"
                    channel = data.get("author_name") or "YouTube"
                    track = Track(
                        id=vid, channel_name=channel, duration="", duration_sec=0,
                        message_id=m_id, title=title[:80],
                        thumbnail=data.get("thumbnail_url"),
                        url=f"https://www.youtube.com/watch?v={vid}",
                        view_count="", video=video,
                    )
                    self.track_context[str(vid)] = title
                    return track
        except Exception as e:
            logger.warning(f"[YouTube] oEmbed failed for {vid}: {e}")
        return None

    async def autoplay_track(
        self,
        video_id: str,
        video: bool = False,
        exclude=None,
        exclude_titles=None,
        title: str | None = None,
        channel_name: str | None = None,
    ) -> Track | None:
        """Return a related track for autoplay.

        The title/channel are passed from the currently playing Track so the
        search fallback can still work when YouTube's RD mix endpoint is
        blocked on Heroku/cloud IPs.
        """
        if not video_id:
            return None
        current = Track(
            id=video_id,
            video=video,
            title=title or "",
            channel_name=channel_name or "",
        )
        # The original /play query is stored outside Track, keyed by video ID.
        # This keeps the Track dataclass backward-compatible.
        context_query = self.track_context.get(str(video_id), "").strip()
        return await self.get_related(
            current,
            played=list(exclude or []),
            played_titles=set(exclude_titles or []),
            context_query=context_query or None,
        )

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist.get("videos", [])[:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                    title=(data.get("title") or "")[:80],
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception as e:
            logger.error(f"Playlist error: {e}")
        return tracks

    async def download(self, video_id: str, video: bool = False) -> str | None:
        if not video_id or len(video_id) < 3:
            return None

        if video:
            return await download_video(video_id)
        else:
            return await download_song(video_id)

    def _format_duration(self, seconds: int) -> str:
        seconds = max(int(seconds or 0), 0)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _format_views(self, count) -> str:
        if not count:
            return ""
        count = int(count)
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M views"
        if count >= 1_000:
            return f"{count / 1_000:.1f}K views"
        return f"{count} views"

    def _extract_related(self, video_id: str) -> dict | None:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "ignoreerrors": True,
            "geo_bypass": True,
            "socket_timeout": 10,
            "retries": 1,
            "extractor_retries": 1,
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        }
        cookie = self.get_cookies()
        if cookie:
            opts["cookiefile"] = cookie

        url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    async def _related_from_mix(
        self, video_id: str, played: set[str], played_titles: set[str],
        language_hint: str | None = None,
    ) -> Track | None:
        loop = asyncio.get_event_loop()
        try:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, self._extract_related, video_id),
                timeout=20,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[Autoplay] Mix fetch timed out for {video_id}.")
            return None
        except Exception as e:
            logger.error(f"[Autoplay] Mix fetch failed for {video_id}: {e}")
            return None

        entries = (info or {}).get("entries") or []
        for entry in entries:
            if not entry:
                continue

            eid = entry.get("id")
            if not eid or eid in played:
                continue

            title = entry.get("title") or "Unknown"
            if title.lower() in ("[deleted video]", "[private video]"):
                continue

            normalized_title = re.sub(r"\W+", " ", title.lower()).strip()
            if normalized_title in played_titles:
                continue

            # Keep the RD mix in the same regional language when possible.
            if language_hint:
                detected = self._detect_language_hint(
                    title=title,
                    channel=entry.get("channel") or entry.get("uploader") or "",
                )
                if not detected or detected.lower() != language_hint.lower():
                    continue

            duration = int(entry.get("duration") or 0)
            if duration <= 0 or duration > config.DURATION_LIMIT:
                continue

            thumbs = entry.get("thumbnails") or []
            thumbnail = thumbs[-1]["url"].split("?")[0] if thumbs else None

            return Track(
                id=eid,
                channel_name=entry.get("channel") or entry.get("uploader") or "YouTube",
                duration=self._format_duration(duration),
                duration_sec=duration,
                title=title[:80],
                thumbnail=thumbnail,
                url=f"https://www.youtube.com/watch?v={eid}",
                view_count=self._format_views(entry.get("view_count")),
                video=False,
            )

        return None

    @staticmethod
    def _norm_title(value: str) -> str:
        """Normalize a YouTube title for duplicate-song detection."""
        value = str(value or "").lower()
        # Remove common upload labels which make the same song look different.
        value = re.sub(
            r"\b(official\s*(music\s*)?video|official\s*audio|lyrics?|lyric\s*video|full\s*(song|video)|hd|4k|8k|audio|video|remaster(?:ed)?|reupload|original\s*song|dj\s*mix|extended|slowed(?:\s*\+\s*reverb)?|speed\s*up|sped\s*up)\b",
            " ",
            value,
        )
        value = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", value)
        return re.sub(r"[^a-z0-9]+", " ", value).strip()

    @classmethod
    def _same_song(cls, a: str, b: str) -> bool:
        """Return True when two YouTube titles are probably the same song."""
        a = cls._norm_title(a)
        b = cls._norm_title(b)
        if not a or not b:
            return False
        if a == b:
            return True
        # Catch titles such as "Song | Artist" vs "Song - Official Audio".
        if len(a) >= 12 and len(b) >= 12 and (a in b or b in a):
            return True
        at, bt = set(a.split()), set(b.split())
        if len(at) >= 3 and len(bt) >= 3:
            overlap = len(at & bt) / min(len(at), len(bt))
            if overlap >= 0.80:
                return True
        return SequenceMatcher(None, a, b).ratio() >= 0.84

    @staticmethod
    def _detect_language_hint(context: str = "", title: str = "", channel: str = "") -> str | None:
        """Detect the requested music language/scene.

        The original query has priority.  Candidate tracks are later checked
        against this same language so autoplay does not silently switch from
        Bhojpuri to Hindi, Hindi to Punjabi, etc.
        """
        text = f"{context} {title} {channel}".lower()

        language_keywords = {
            "bhojpuri": ["bhojpuri", "भोजपुरी", "bhojpuriya", "pawan singh", "khesari lal", "khesari lal yadav", "ritesh pandey", "shilpi raj", "pramod premi", "neelkamal singh", "arvind akela kallu", "ankush raja", "gunjan singh", "rajesh raja", "rakesh mishra"],
            "punjabi": ["punjabi", "ਪੰਜਾਬੀ", "sidhu moose wala", "sidhu moosewala", "karan aujla", "diljit dosanjh", "amrit maan", "ap dhillon", "shubh", "gippy grewal", "jazzy b", "babbu maan"],
            "haryanvi": ["haryanvi", "haryanavi", "हरियाणवी", "sapna choudhary", "gulzaar chhaniwala", "masoom sharma", "renuka panwar", "amit dhull"],
            "rajasthani": ["rajasthani", "राजस्थानी", "marwadi", "मारवाड़ी", "rajasthani song", "rajasthani songs"],
            "marathi": ["marathi", "मराठी", "marathi song", "marathi songs", "ajay atul", "swapnil bandodkar", "avdhoot gupte"],
            "bengali": ["bengali", "বাংলা", "bangla", "bangla song", "bengali song", "bengali songs", "arijit singh bengali", "shreya ghoshal bengali"],
            "tamil": ["tamil", "தமிழ்", "tamil song", "tamil songs", "anirudh", "ar rahman tamil", "vijay tamil", "ilaiyaraaja"],
            "telugu": ["telugu", "తెలుగు", "telugu song", "telugu songs", "thaman s", "devi sri prasad", "sid sriram telugu"],
            "kannada": ["kannada", "ಕನ್ನಡ", "kannada song", "kannada songs", "raghu dixit", "vijay prakash"],
            "malayalam": ["malayalam", "മലയാളം", "malayalam song", "malayalam songs", "vineeth sreenivasan", "shaan rahman"],
            "odia": ["odia", "oriya", "ଓଡ଼ିଆ", "odia song", "odia songs", "oriya song"],
            "assamese": ["assamese", "অসমীয়া", "assamese song", "assamese songs", "zubeen garg", "papon assamese"],
            "gujarati": ["gujarati", "ગુજરાતી", "gujarati song", "gujarati songs", "kinjal dave", "geeta rabari", "jignesh kaviraj", "devayat khavad"],
            "hindi": ["hindi", "हिंदी", "hindi song", "hindi songs", "bollywood", "bollywood song", "bollywood songs"],
            "urdu": ["urdu", "اردو", "urdu song", "urdu songs", "pakistani song", "pakistani songs", "qawwali"],
            "nepali": ["nepali", "नेपाली", "nepali song", "nepali songs", "nepali music"],
            "sindhi": ["sindhi", "سنڌي", "सिंधी", "sindhi song", "sindhi songs"],
            "konkani": ["konkani", "कोंकणी", "konkani song", "konkani songs"],
            "kashmiri": ["kashmiri", "کٲشُر", "कश्मीरी", "kashmiri song", "kashmiri songs"],
            "manipuri": ["manipuri", "meitei", "মৈতৈ", "manipuri song", "manipuri songs"],
            "santali": ["santali", "ᱥᱟᱱᱛᱟᱲᱤ", "santali song", "santali songs"],
            "english": ["english", "english song", "english songs", "american song", "british song", "pop song", "hollywood song"],
            "spanish": ["spanish", "español", "spanish song", "spanish songs", "latin song", "reggaeton"],
            "portuguese": ["portuguese", "português", "brazilian song", "brazilian songs"],
            "french": ["french", "français", "french song", "french songs"],
            "german": ["german", "deutsch", "german song", "german songs"],
            "italian": ["italian", "italiano", "italian song", "italian songs"],
            "korean": ["korean", "한국어", "k-pop", "kpop", "korean song", "korean songs"],
            "japanese": ["japanese", "日本語", "j-pop", "jpop", "japanese song", "japanese songs"],
            "arabic": ["arabic", "العربية", "arabic song", "arabic songs"],
            "turkish": ["turkish", "türkçe", "turkish song", "turkish songs"],
        }

        # Strong, script-based signals where the writing system is unique.
        script_languages = [
            ("punjabi", r"[\u0A00-\u0A7F]"),
            ("bengali", r"[\u0980-\u09FF]"),
            ("gujarati", r"[\u0A80-\u0AFF]"),
            ("odia", r"[\u0B00-\u0B7F]"),
            ("tamil", r"[\u0B80-\u0BFF]"),
            ("telugu", r"[\u0C00-\u0C7F]"),
            ("kannada", r"[\u0C80-\u0CFF]"),
            ("malayalam", r"[\u0D00-\u0D7F]"),
            ("santali", r"[\u1C50-\u1C7F]"),
            ("korean", r"[\uAC00-\uD7AF]"),
            ("japanese", r"[\u3040-\u30FF]"),
            ("arabic", r"[\u0600-\u06FF]"),
        ]

        # Explicit words/artist names beat generic script detection.
        for lang, words in language_keywords.items():
            for word in words:
                if word in text:
                    return lang.title()

        for lang, pattern in script_languages:
            if re.search(pattern, text):
                return lang.title()

        # Devanagari is shared by Hindi, Bhojpuri, Marathi, Haryanvi, Nepali,
        # etc.; without a language marker it is intentionally treated as Hindi
        # rather than guessing a regional language.
        if re.search(r"[\u0900-\u097F]", text):
            return "Hindi"

        return None

    @classmethod
    def _language_matches(cls, language_hint: str | None, title: str = "", channel: str = "") -> bool:
        """Strictly validate a candidate against the requested language."""
        if not language_hint:
            return True
        detected = cls._detect_language_hint(title=title, channel=channel)
        if not detected:
            return False
        return detected.casefold() == language_hint.casefold()

    @staticmethod
    def _is_compilation_or_long_mix(title: str, duration_sec: int) -> bool:
        title_l = str(title or "").lower()
        blocked = (
            "nonstop", "non-stop", "jukebox", "full album", "album", "compilation",
            "collection", "evergreen songs", "evergreen", "best of", "greatest hits",
            "hits collection", "playlist", "mix", "mashup", "medley", "dj set", "dj mix",
            "remix mix", "song collection", "all songs", "top songs", "30 songs", "50 songs",
            "100 songs", "1 hour", "2 hour", "1 hr", "2 hr",
        )
        if any(word in title_l for word in blocked):
            return True
        return int(duration_sec or 0) > 10 * 60

    async def _related_from_search(
        self, current: Track, played: set[str], played_titles: set[str],
        context_query: str | None = None,
    ) -> Track | None:
        """Find a genuinely different autoplay song.

        Do not rely on the first YouTube result. Search several candidates and
        reject both previously-used IDs and titles that are merely another
        upload/remix of a song already played.
        """
        title = (current.title or "").strip()
        channel = (current.channel_name or "").strip()

        # Keep autoplay in the same language/scene as the user's original
        # search. Never fall back to a hard-coded Hindi query.
        context = (context_query or "").strip()
        language_hint = self._detect_language_hint(context, title, channel)
        queries = []

        if language_hint:
            if context:
                queries.append(f"{context} {language_hint} songs")
            if title:
                queries.append(f"{title} {language_hint} song")
            if channel:
                queries.append(f"{channel} {language_hint} songs")
            queries.append(f"best {language_hint} songs")
        else:
            if context:
                queries.append(f"{context} songs")
            if channel:
                queries.append(f"{channel} songs")
                queries.append(f"{channel} best songs")
            if title:
                queries.append(f"{title} similar songs")

        # Always keep a useful title/channel fallback even if the language
        # detector did not recognize the query.
        if not queries:
            if title:
                queries.append(f"{title} similar songs")
            if channel:
                queries.append(f"{channel} songs")

        queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))

        current_id = str(current.id)
        played_ids = {str(x) for x in played}
        played_ids.add(current_id)
        blocked_titles = {
            self._norm_title(x) for x in (played_titles or set()) if x
        }
        current_norm = self._norm_title(title)
        if current_norm:
            blocked_titles.add(current_norm)

        candidates = []
        seen_ids = set(played_ids)
        seen_titles = set(blocked_titles)

        for query in queries:
            try:
                results = await VideosSearch(query, limit=20).next()
            except Exception as e:
                logger.warning(f"[Autoplay] Search failed for {query!r}: {e!r}")
                continue

            for data in (results or {}).get("result", []):
                eid = str(data.get("id") or "")
                if not eid or eid in seen_ids:
                    continue

                result_title = (data.get("title") or "Unknown").strip()
                norm = self._norm_title(result_title)
                if not norm or self._same_song(result_title, title):
                    continue

                # Compare against every played title, not just exact strings.
                if any(self._same_song(result_title, old) for old in blocked_titles):
                    continue

                duration_str = data.get("duration")
                duration_sec = utils.to_seconds(duration_str) if duration_str else 0
                if not duration_sec or duration_sec > config.DURATION_LIMIT:
                    continue
                if self._is_compilation_or_long_mix(result_title, duration_sec):
                    continue
                if language_hint and not self._language_matches(language_hint, result_title, data.get("channel", {}).get("name", "")):
                    continue

                seen_ids.add(eid)
                seen_titles.add(norm)
                thumbs = data.get("thumbnails") or []
                thumbnail = (thumbs[-1].get("url") or "").split("?")[0] if thumbs else None
                candidates.append(
                    Track(
                        id=eid,
                        channel_name=data.get("channel", {}).get("name") or "YouTube",
                        duration=duration_str,
                        duration_sec=duration_sec,
                        title=result_title[:80],
                        thumbnail=thumbnail,
                        url=data.get("link"),
                        view_count=data.get("viewCount", {}).get("short"),
                        video=False,
                    )
                )

        if not candidates:
            return None

        if language_hint:
            candidates = [
                c for c in candidates
                if self._language_matches(language_hint, c.title or "", c.channel_name or "")
            ]
            if not candidates:
                logger.warning(f"[Autoplay] No strict {language_hint} candidate found.")
                return None

        random.shuffle(candidates)
        return candidates[0]

        random.shuffle(candidates)
        return candidates[0]

    async def get_related(
        self,
        current: Track,
        played: list[str] | None = None,
        played_titles: set[str] | None = None,
        context_query: str | None = None,
    ) -> Track | None:
        """Return a new autoplay song, never a previously played song.

        Search is intentionally attempted before YouTube's RD mix because RD
        frequently returns another upload of the exact same song on cloud IPs.
        The mix remains a fallback, with the same duplicate filtering.
        """
        if not current or not current.id:
            return None

        played = {str(x) for x in (played or [])}
        played.add(str(current.id))
        played_titles = set(played_titles or set())
        if current.title:
            played_titles.add(current.title)

        related = await self._related_from_search(
            current, played, played_titles, context_query=context_query
        )
        if related:
            if related.id and context_query:
                self.track_context[str(related.id)] = context_query
            return related

        logger.info(
            f"[Autoplay] Search returned no unique track for {current.id}, trying RD mix."
        )
        language_hint = self._detect_language_hint(
            context_query or self.track_context.get(str(current.id), ""),
            current.title or "",
            current.channel_name or "",
        )
        related = await self._related_from_mix(
            current.id,
            played,
            {self._norm_title(x) for x in played_titles if x},
            language_hint=language_hint,
        )
        if related and not self._same_song(related.title, current.title):
            if related.id and context_query:
                self.track_context[str(related.id)] = context_query
            return related

        logger.warning(f"[Autoplay] No unique related track found for {current.id}.")
        return None

        played = {str(x) for x in (played or [])}
        played.add(str(current.id))
        played_titles = {
            re.sub(r"\W+", " ", str(x).lower()).strip()
            for x in (played_titles or set())
            if x
        }
        current_title = re.sub(
            r"\W+", " ", str(current.title or "").lower()
        ).strip()
        if current_title:
            played_titles.add(current_title)

        related = await self._related_from_mix(current.id, played, played_titles)
        if related:
            return related

        logger.info(
            f"[Autoplay] Mix returned nothing for {current.id}, trying search fallback."
        )
        related = await self._related_from_search(current, played, played_titles)
        if related:
            return related

        logger.warning(f"[Autoplay] No related track found for {current.id}.")
        return None
        
