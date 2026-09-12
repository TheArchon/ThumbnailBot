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
        if not url:
            return False
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        """Compatibility helper used by the /play URL validator."""
        return not self.valid(url)

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        try:
            _search = VideosSearch(query, limit=1)
            results = await _search.next()
            if results and results["result"]:
                data = results["result"][0]
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                    message_id=m_id,
                    title=(data.get("title") or "")[:80],
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    video=video,
                )
                if track.id and query:
                    self.track_context[str(track.id)] = str(query).strip()
                return track
        except Exception as e:
            logger.error(f"Search error: {e}")
        return None

    async def stream_url(self, video_id: str, video: bool = False) -> str | None:
        """Resolve a direct media URL for immediate playback.

        Try a few YouTube player clients because one client can fail while
        another still exposes a playable direct URL. No full download is
        performed here; ffmpeg/pytgcalls streams the returned URL directly.
        """
        if not video_id:
            return None

        raw_id = str(video_id)
        # The external download API already handles YouTube extraction on a
        # server-side IP. Returning its media endpoint first avoids the
        # YouTube anti-bot challenge seen on Heroku/cloud IPs and lets
        # ffmpeg/pytgcalls start playback without downloading the whole file.
        if not video:
            api_stream = (
                f"{API_URL}/download?url={quote(raw_id, safe='')}"
                f"&type=audio&api_key={quote(API_KEY, safe='')}"
            )
            return api_stream

        url = raw_id if raw_id.startswith("http") else f"{self.base}{raw_id}"
        cookie = self.get_cookies()

        clients = ["web", "android", "tv", "web_safari"]
        for client in clients:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "geo_bypass": True,
                "socket_timeout": 8,
                "retries": 1,
                "extractor_retries": 1,
                "format": (
                    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
                    if video else
                    "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
                ),
                "extractor_args": {
                    "youtube": {"player_client": [client]},
                },
            }
            if cookie:
                opts["cookiefile"] = cookie

            def extract():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        return None
                    direct = info.get("url")
                    if direct:
                        return direct
                    formats = info.get("formats") or []
                    if video:
                        candidates = [
                            f for f in formats
                            if f.get("url") and f.get("vcodec") not in (None, "none")
                        ]
                    else:
                        candidates = [
                            f for f in formats
                            if f.get("url") and f.get("acodec") not in (None, "none")
                        ]
                    candidates.sort(
                        key=lambda f: (
                            float(f.get("abr") or 0),
                            float(f.get("tbr") or 0),
                            int(f.get("height") or 0),
                        ),
                        reverse=True,
                    )
                    return candidates[0].get("url") if candidates else None

            try:
                direct = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(None, extract),
                    timeout=12,
                )
                if direct:
                    logger.info(f"[YouTube] Direct stream ready via {client}: {video_id}")
                    return direct
            except Exception as e:
                logger.warning(f"[YouTube] stream client {client} failed for {video_id}: {e}")

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

    @staticmethod
    def _is_compilation_or_long_mix(title: str, duration_sec: int) -> bool:
        """Reject long compilations/mixes from autoplay.

        Autoplay should pick an individual song, not a 20-60 minute
        compilation, jukebox, nonstop mix, or full album.
        """
        title_l = str(title or "").lower()
        blocked = (
            "nonstop", "non-stop", "jukebox", "full album", "album",
            "compilation", "collection", "evergreen songs", "evergreen",
            "best of", "greatest hits", "hits collection", "playlist",
            "mix", "mashup", "medley", "dj set", "dj mix", "remix mix",
            "songs", "song collection", "all songs", "top songs",
            "30 songs", "50 songs", "100 songs", "1 hour", "2 hour",
            "1 hr", "2 hr",
        )
        if any(word in title_l for word in blocked):
            return True

        # Individual autoplay songs are normally short. Keep a generous
        # 10-minute ceiling so long genuine tracks can still play, while
        # preventing large compilations from entering the autoplay queue.
        return int(duration_sec or 0) > 10 * 60

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
                if detected and detected.lower() != language_hint.lower():
                    continue

            duration = int(entry.get("duration") or 0)
            if duration <= 0 or duration > config.DURATION_LIMIT:
                continue
            if self._is_compilation_or_long_mix(title, duration):
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
        """Detect the music language/scene used for autoplay searches.

        Explicit language words in the original search have highest priority.
        Bhojpuri gets a strong dedicated hint so a Bhojpuri session keeps
        returning Bhojpuri songs instead of drifting into generic Hindi.
        """
        text = f"{context} {title} {channel}".lower()

        language_keywords = {
            "bhojpuri": [
                "bhojpuri", "भोजपुरी", "bhojpuriya", "bhojpuri song",
                "bhojpuri songs", "bhojpuri gana", "bhojpuri gaana",
                "pawan singh", "khesari lal", "khesari lal yadav",
                "ritesh pandey", "shilpi raj", "pramod premi",
                "neelkamal singh", "arvind akela kallu", "ankush raja",
                "gunjan singh", "rajesh raja", "rakesh mishra",
            ],
            "punjabi": ["punjabi", "ਪੰਜਾਬੀ", "sidhu moose wala", "karan aujla", "diljit dosanjh", "amrit maan"],
            "haryanvi": ["haryanvi", "हरियाणवी", "haryanavi", "sapna choudhary", "gulzaar chhaniwala", "masoom sharma"],
            "rajasthani": ["rajasthani", "राजस्थानी", "marwadi", "मारवाड़ी"],
            "marathi": ["marathi", "मराठी", "marathi song", "marathi songs"],
            "bengali": ["bengali", "বাংলা", "bangla song", "bengali song", "bengali songs"],
            "tamil": ["tamil", "தமிழ்", "tamil song", "tamil songs"],
            "telugu": ["telugu", "తెలుగు", "telugu song", "telugu songs"],
            "kannada": ["kannada", "ಕನ್ನಡ", "kannada song", "kannada songs"],
            "malayalam": ["malayalam", "മലയാളം", "malayalam song", "malayalam songs"],
            "odia": ["odia", "oriya", "ଓଡ଼ିଆ", "odia song", "odia songs"],
            "assamese": ["assamese", "অসমীয়া", "assamese song", "assamese songs"],
            "gujarati": ["gujarati", "ગુજરાતી", "gujarati song", "gujarati songs"],
            "hindi": ["hindi", "हिंदी", "hindi song", "hindi songs"],
        }

        # Explicit Bhojpuri markers first.
        for word in language_keywords["bhojpuri"]:
            if word in text:
                return "Bhojpuri"

        # Other regional-language markers.
        for lang, words in language_keywords.items():
            if lang == "bhojpuri":
                continue
            for word in words:
                if word in text:
                    return lang.title()

        # Devanagari is useful as a Hindi/Bhojpuri fallback, but don't call it
        # Bhojpuri without a Bhojpuri-specific marker.
        if re.search(r"[\u0900-\u097F]", text):
            return "Hindi"

        return None

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

        # Prefer candidates whose title/channel explicitly matches the
        # detected language. Unknown-language metadata is still allowed so
        # autoplay does not become too restrictive.
        if language_hint:
            def score(track):
                text = f"{track.title or ''} {track.channel_name or ''}"
                detected = self._detect_language_hint(title=track.title or "", channel=track.channel_name or "")
                return 1 if detected == language_hint else 0
            candidates.sort(key=score, reverse=True)
            best_score = score(candidates[0])
            top = [c for c in candidates if score(c) == best_score]
            random.shuffle(top)
            return top[0]

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
        
