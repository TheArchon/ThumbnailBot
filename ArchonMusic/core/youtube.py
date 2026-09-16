import os
import re
import asyncio
import aiohttp
import random
import yt_dlp
from py_yt import VideosSearch, Playlist
from ArchonMusic import logger, config
from ArchonMusic.helpers import Track, utils

API_URL = os.environ.get("SHRUTI_API_URL", "https://api.shrutibots.site")

API_KEY = os.environ.get("SHRUTI_API_KEY", "ShrutiBotsfhGT4c09sFRRuQIB6yCG") ## Get This API KEY FROM TELEGRAM BOT USERNAME: @SHRUTIAPIBOT

DOWNLOAD_DIR = "downloads"


async def download_song(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/download",
                params={"url": video_id, "type": "audio", "api_key": API_KEY},
                timeout=aiohttp.ClientTimeout(total=300)
            ) as resp:
                if resp.status != 200:
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path
        return None
    except Exception:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None


async def download_video(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/download",
                params={"url": video_id, "type": "video", "api_key": API_KEY},
                timeout=aiohttp.ClientTimeout(total=600)
            ) as resp:
                if resp.status != 200:
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path
        return None
    except Exception:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.cookie_dir = "AloneX/cookies"

    def get_cookies(self):
        if not os.path.exists(self.cookie_dir):
            return None
        cookies_files = [f for f in os.listdir(self.cookie_dir) if f.endswith(".txt")]
        if not cookies_files:
            return None
        return os.path.join(self.cookie_dir, random.choice(cookies_files))

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        if not os.path.exists(self.cookie_dir):
            os.makedirs(self.cookie_dir)
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
        return bool(re.match(self.regex, url))

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        try:
            _search = VideosSearch(query, limit=1)
            results = await _search.next()
            if results and results["result"]:
                data = results["result"][0]
                detected_language = self._language_key(
                    data.get("title", ""), data.get("channel", {}).get("name", "")
                )
                # If YouTube omits the language from title/channel, use the
                # original user query as a second signal. This is important
                # for autoplay after a direct /play search.
                if detected_language == "unknown":
                    detected_language = self._language_key(query, "")
                return Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                    message_id=m_id,
                    title=data.get("title"),
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    language=detected_language,
                    video=video,
                )
        except Exception as e:
            logger.error(f"Search error: {e}")
        return None

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
                    title=data.get("title"),
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    language=self._language_key(data.get("title", ""), data.get("channel", {}).get("name", "")),
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
        url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    @staticmethod
    def _is_non_music_title(title: str) -> bool:
        """Reject podcast/episode/talk content from autoplay."""
        t = (title or "").lower()
        blocked = (
            "episode", "podcast", "interview", "news", "talk show",
            "full show", "full episode", "web series", "webseries",
            "documentary", "trailer", "teaser", "reaction", "reaction video", "behind the scenes", "behind-the-scenes",
        )
        return any(word in t for word in blocked)

    @staticmethod
    def _language_key(title: str, channel: str = "") -> str:
        """Classify autoplay language from title/channel without needing cookies.
        Bhojpuri is checked before Hindi because both commonly use Devanagari.
        """
        t = f"{title or ''} {channel or ''}".lower()
        if re.search(r"[\u0a00-\u0a7f]", t) or any(k in t for k in (
            "punjabi", "panjabi", "bhangra", "gurmukhi", "punjabi song", "punjabi songs", "punjabi music",
        )):
            return "punjabi"
        if any(k in t for k in (
            "bhojpuri", "bhojpuriya", "bhojpuri song", "bhojpuri songs",
            "purvanchal", "nirahua", "dinesh lal yadav", "khesari",
            "khesari lal", "pawan singh", "rakesh mishra", "pramod premi",
            "shilpi raj", "ritesh pandey", "ankush raja", "samar singh",
            "neelkamal singh", "arvind akela kallu", "gunjan singh",
            "priyanka singh", "kalpana", "chhotu chhaliya", "vikas jha",
            "alok raj", "ashish yadav", "tuntun yadav", "raj bhai",
            "aadishakti films", "wave music", "saregama hum bhojpuri",
            "t-series hamaarbhojpuri", "hamaarbhojpuri", "enter10 music bhojpuri",
            "bhojpuri hit", "bhojpuri lokgeet", "bhojpuri lok geet",
            "bhojpuri dj", "bhojpuri status", "bhojpuri vivah", "bhojpuri vivah geet",
            "golu gold", "rajesh khushdil", "vikas bedardi", "arjun rasiya",
        )):
            return "bhojpuri"
        # Common Bhojpuri vocabulary is often present even when YouTube
        # omits the word "Bhojpuri" from the title. Keep it out of Hindi.
        bhojpuri_words = (
            "गवनवा", "सईयां", "सईयाँ", "सइयां", "सइयाँ", "बलमुआ",
            "बलमा", "पिया जी", "पियवा", "भतार", "लईका", "लइका",
            "करेजा", "रउआ", "तोहरा", "हमरा", "हमार", "तोहार",
            "बाड़े", "बानी", "बाड़ू", "बाड़ू", "निरहुआ", "खेसारी",
            "पवन सिंह", "शिल्पी राज", "रउरा", "रउआ के", "हमनी", "तोहसे",
            "तोहरा बिना", "हमरा बिना", "सईया", "सईयाँ", "बलम", "बबुआ",
            "लइकी", "लईकी", "चोली", "साड़ी", "सजनी",
        )
        if any(k in t for k in bhojpuri_words):
            return "bhojpuri"
        # Devanagari without Bhojpuri markers is treated as Hindi.
        if re.search(r"[\u0900-\u097f]", t) or any(k in t for k in (
            "hindi", "bollywood", "hindustani", "hindi song", "hindi songs", "hindi music", "bollywood songs",
            "t-series", "saregama music", "tips official", "zee music company",
            "sony music india", "speed records", "punjabi song", "punjabi songs",
        )):
            return "hindi"
        return "unknown"

    @staticmethod
    def _movie_key(title: str) -> str:
        """Get a lightweight movie/source key from common YouTube song titles."""
        t = re.sub(r"\s+", " ", (title or "").lower()).strip()
        # Common formats: Song - Movie, Song | Movie, Song (Movie).
        parts = re.split(r"\s+[|–—-]\s+|\s*\|\s*", t)
        if len(parts) > 1:
            candidate = parts[-1].strip()
        else:
            m = re.search(r"\bfrom\s+(.+)$", t)
            candidate = m.group(1).strip() if m else ""
            if not candidate:
                m = re.search(r"\(([^()]*)\)\s*$", t)
                candidate = m.group(1).strip() if m else ""
        candidate = re.sub(r"[^a-z0-9 ]+", " ", candidate)
        candidate = re.sub(r"\b(official|video|audio|song|lyrics|lyric|hd|4k)\b", " ", candidate)
        return re.sub(r"\s+", " ", candidate).strip()

    async def _related_from_mix(
        self, video_id: str, played: set[str], movie_history: set[str] | None = None,
        language: str = "unknown"
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
            if self._is_non_music_title(title):
                continue
            candidate_language = self._language_key(title, entry.get("channel") or entry.get("uploader") or "")
            if language != "unknown" and candidate_language != language:
                continue
            movie_key = self._movie_key(title)
            if movie_key and movie_history and movie_key in movie_history:
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
                title=title,
                thumbnail=thumbnail,
                url=f"https://www.youtube.com/watch?v={eid}",
                view_count=self._format_views(entry.get("view_count")),
                language=candidate_language,
                video=False,
            )

        return None

    async def _related_from_search(
        self, current: Track, played: set[str], movie_history: set[str] | None = None,
        language: str = "unknown"
    ) -> Track | None:
        """Fallback used when YouTube blocks the mix-playlist scrape (common on
        server/cloud IPs without cookies). Reuses the same search backend that
        already powers /play, so it works wherever normal search works."""
        # A direct YouTube link can arrive without a language label. In that
        # case infer it once from the current title/channel before searching.
        if language == "unknown":
            language = self._language_key(
                getattr(current, "title", ""), getattr(current, "channel_name", "")
            )
        language_hint = {
            "hindi": "Hindi Bollywood songs old new",
            "bhojpuri": "Bhojpuri songs old new",
            "punjabi": "Punjabi songs old new",
        }.get(language, "songs")
        queries = []
        if current.channel_name:
            # Keep the language locked even when YouTube search returns mixed results.
            queries.append(f"{current.channel_name} {language_hint} official song")
            queries.append(f"{current.channel_name} {language_hint}")
        if current.title:
            queries.append(f"{current.title} {language_hint}")
        # Always include a language-only pool so old/new songs are not limited
        # to the current artist/channel. Candidate language is still checked below.
        queries.append(language_hint)
        if language == "hindi":
            queries.append("Hindi songs 90s 2000s 2010s latest Bollywood")
        elif language == "bhojpuri":
            queries.append("Bhojpuri old new hit songs")
        elif language == "punjabi":
            queries.append("Punjabi old new hit songs")

        for query in queries:
            try:
                _search = VideosSearch(query, limit=8)
                results = await _search.next()
            except Exception as e:
                logger.error(f"[Autoplay] Search fallback failed for {query!r}: {e}")
                continue

            for data in (results or {}).get("result", []):
                eid = data.get("id")
                if not eid or eid in played:
                    continue

                title = data.get("title") or "Unknown"
                if self._is_non_music_title(title):
                    continue
                candidate_channel = data.get("channel", {}).get("name") or ""
                candidate_language = self._language_key(title, candidate_channel)
                if language != "unknown" and candidate_language != language:
                    continue
                movie_key = self._movie_key(title)
                if movie_key and movie_history and movie_key in movie_history:
                    continue

                duration_str = data.get("duration")
                duration_sec = utils.to_seconds(duration_str) if duration_str else 0
                if not duration_sec or duration_sec > config.DURATION_LIMIT:
                    continue

                return Track(
                    id=eid,
                    channel_name=data.get("channel", {}).get("name") or "YouTube",
                    duration=duration_str,
                    duration_sec=duration_sec,
                    title=title,
                    thumbnail=(data.get("thumbnails", [{}])[-1].get("url") or "").split("?")[0] or None,
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    language=candidate_language,
                    video=False,
                )

        return None

    async def get_related(
        self, current: Track, played: list[str] | None = None,
        movie_history: list[str] | None = None
    ) -> Track | None:
        """Fetch the next autoplay track, skipping anything already played in
        this session. Tries YouTube's related mix first, falling back to a
        text search (same backend as /play) if the mix is blocked or empty —
        this is common on server/cloud IPs without YouTube cookies set."""
        if not current or not current.id:
            return None

        played = set(played or [])
        played.add(current.id)
        movie_history = set(movie_history or [])
        current_language = getattr(current, "language", "unknown") or self._language_key(
            getattr(current, "title", ""), getattr(current, "channel_name", "")
        )
        current_movie = self._movie_key(getattr(current, "title", ""))
        if current_movie:
            movie_history.add(current_movie)

        # Run the two lightweight discovery paths in parallel. On cloud IPs,
        # YouTube's RD mix can be slow/blocked while VideosSearch is often
        # available immediately. Whichever produces a valid unused track first
        # wins, reducing the pause between songs.
        mix_task = asyncio.create_task(
            self._related_from_mix(current.id, played, movie_history, current_language)
        )
        search_task = asyncio.create_task(
            self._related_from_search(current, played, movie_history, current_language)
        )
        try:
            pending = {mix_task, search_task}
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    try:
                        related = task.result()
                    except Exception as e:
                        logger.warning(f"[Autoplay] related lookup failed: {e!r}")
                        related = None
                    if related:
                        for other in pending:
                            other.cancel()
                        return related
            logger.warning(f"[Autoplay] No related track found for {current.id}.")
            return None
        finally:
            for task in (mix_task, search_task):
                if not task.done():
                    task.cancel()
