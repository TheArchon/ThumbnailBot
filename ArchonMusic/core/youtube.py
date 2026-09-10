import os
import re
import asyncio
import aiohttp
import random
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
                return Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                    message_id=m_id,
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    video=video,
                )
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
        return await self.get_related(
            current,
            played=list(exclude or []),
            played_titles=set(exclude_titles or []),
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
                    title=data.get("title")[:25],
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
        self, video_id: str, played: set[str], played_titles: set[str]
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
                title=title[:25],
                thumbnail=thumbnail,
                url=f"https://www.youtube.com/watch?v={eid}",
                view_count=self._format_views(entry.get("view_count")),
                video=False,
            )

        return None

    async def _related_from_search(
        self, current: Track, played: set[str], played_titles: set[str]
    ) -> Track | None:
        """Find a genuinely different autoplay track.

        Search returns several candidates, so do not blindly take the first
        result. Exclude every ID already played/queued and prefer a different
        title from the current song. This prevents /skip and autoplay from
        repeatedly selecting the same result.
        """
        queries = []
        title = (current.title or "").strip()
        channel = (current.channel_name or "").strip()
        if title and channel:
            queries.append(f"{title} {channel} songs")
        if title:
            queries.append(f"{title} related songs")
        if channel:
            queries.append(f"{channel} songs")
        queries = list(dict.fromkeys(q for q in queries if q))

        current_id = str(current.id)
        played_ids = {str(x) for x in played}
        played_ids.add(current_id)
        current_title = re.sub(r"\W+", " ", title.lower()).strip()
        played_titles = {re.sub(r"\W+", " ", str(x).lower()).strip() for x in played_titles if x}
        if current_title:
            played_titles.add(current_title)
        candidates = []
        seen = set(played_ids)

        for query in queries:
            try:
                results = await VideosSearch(query, limit=20).next()
            except Exception as e:
                logger.error(f"[Autoplay] Search fallback failed for {query!r}: {e}")
                continue

            for data in (results or {}).get("result", []):
                eid = str(data.get("id") or "")
                if not eid or eid in seen:
                    continue

                duration_str = data.get("duration")
                duration_sec = utils.to_seconds(duration_str) if duration_str else 0
                if not duration_sec or duration_sec > config.DURATION_LIMIT:
                    continue

                result_title = (data.get("title") or "Unknown").strip()
                normalized_title = re.sub(r"\W+", " ", result_title.lower()).strip()
                if normalized_title in played_titles or normalized_title == current_title:
                    continue

                seen.add(eid)
                candidates.append(Track(
                    id=eid,
                    channel_name=data.get("channel", {}).get("name") or "YouTube",
                    duration=duration_str,
                    duration_sec=duration_sec,
                    title=result_title[:25],
                    thumbnail=(data.get("thumbnails", [{}])[-1].get("url") or "").split("?")[0] or None,
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    video=False,
                ))

        if not candidates:
            return None

        # Randomly choose among valid unique candidates so autoplay does not
        # follow the same search-result order every time.
        return random.choice(candidates[:15])

    async def get_related(
        self,
        current: Track,
        played: list[str] | None = None,
        played_titles: set[str] | None = None,
    ) -> Track | None:
        """Fetch the next autoplay track, skipping anything already played in
        this session. Tries YouTube's related mix first, falling back to a
        text search (same backend as /play) if the mix is blocked or empty —
        this is common on server/cloud IPs without YouTube cookies set."""
        if not current or not current.id:
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
        
