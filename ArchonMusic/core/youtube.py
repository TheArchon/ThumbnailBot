# ArchonMusic - Fast YouTube engine with 2 API fallback
import asyncio
import os
import random
import re
import time
import urllib.parse
from difflib import SequenceMatcher

import aiohttp
from py_yt import Playlist, VideosSearch

from ArchonMusic import logger
from ArchonMusic.helpers import Track, utils

API1_URL = os.getenv("API_URL", "https://web.riteshyt.in").rstrip("/")
API1_KEY = os.getenv("API_KEY", "")

API2_URL = os.getenv("SHRUTI_API_URL", "https://shrutibots.site").rstrip("/")
API2_KEY = os.getenv("SHRUTI_API_KEY", "")

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self._client = None
        self._contexts = {}
        self._languages = {}
        self._recent_prefetches = {}

    async def get_client(self):
        if self._client is None or self._client.closed:
            self._client = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=45, connect=8)
            )
        return self._client

    def _clean_link(self, link):
        if not link:
            return ""
        link = str(link).strip()
        return link.split("&")[0].split("?si=")[0]

    def _video_id(self, value):
        if not value:
            return ""
        value = str(value)
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
            return value
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", value)
        return m.group(1) if m else value

    def valid(self, url):
        return bool(re.search(
            r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[A-Za-z0-9_-]{11}",
            str(url)
        ))

    def invalid(self, url):
        return bool(re.search(r"youtube\.com|youtu\.be", str(url)) and not self.valid(url))

    def _detect_language(self, text):
        t = (text or "").lower()
        # Script detection first
        if re.search(r"[\u0b80-\u0bff]", t): return "tamil"
        if re.search(r"[\u0c00-\u0c7f]", t): return "telugu"
        if re.search(r"[\u0c80-\u0cff]", t): return "kannada"
        if re.search(r"[\u0d00-\u0d7f]", t): return "malayalam"
        if re.search(r"[\u0980-\u09ff]", t): return "bengali"
        if re.search(r"[\u0a80-\u0aff]", t): return "gujarati"
        if re.search(r"[\u0a00-\u0a7f]", t): return "punjabi"
        if re.search(r"[\u0900-\u097f]", t): return "hindi"
        if re.search(r"[\u0b00-\u0b7f]", t): return "odia"
        words = {
            "bhojpuri": ["bhojpuri","bhojpuriya"],
            "hindi": ["hindi","bollywood","hindustani"],
            "punjabi": ["punjabi","panjabi"],
            "tamil": ["tamil","kollywood"],
            "telugu": ["telugu","tollywood"],
            "marathi": ["marathi"],
            "bengali": ["bengali","bangla"],
            "gujarati": ["gujarati"],
            "kannada": ["kannada","sandalwood"],
            "malayalam": ["malayalam","mollywood"],
            "odia": ["odia","oriya"],
            "assamese": ["assamese"],
            "rajasthani": ["rajasthani"],
            "haryanvi": ["haryanvi"],
            "english": ["english"],
        }
        for lang, vals in words.items():
            if any(re.search(r"\b"+re.escape(v)+r"\b", t) for v in vals):
                return lang
        return ""

    def set_context(self, track, query=None):
        if not track:
            return
        vid = self._video_id(getattr(track, "id", ""))
        if not vid:
            return
        q = query or getattr(track, "title", "") or ""
        self._contexts[vid] = q
        lang = self._detect_language(q) or self._detect_language(
            f"{getattr(track,'title','')} {getattr(track,'channel_name','')}"
        )
        if lang:
            self._languages[vid] = lang

    async def _api_json(self, base, key, path, params, timeout=10):
        client = await self.get_client()
        p = dict(params or {})
        if key:
            p.setdefault("api_key", key)
        try:
            async with client.get(f"{base}{path}", params=p, timeout=timeout) as r:
                if r.status != 200:
                    return None
                return await r.json(content_type=None)
        except Exception as e:
            logger.warning(f"API {base} {path} failed: {e}")
            return None

    def _track_from_data(self, data, m_id=0, video=False, user=""):
        if not isinstance(data, dict):
            return None
        vid = data.get("id") or data.get("videoId")
        if not vid:
            link = data.get("link") or data.get("url") or ""
            vid = self._video_id(link)
        if not vid:
            return None
        title = data.get("title") or data.get("name") or ""
        if not title or title.lower() in ("youtube", "video"):
            return None
        ch = data.get("channel") or {}
        if isinstance(ch, str):
            channel = ch
        else:
            channel = ch.get("name") or data.get("channel_name") or ""
        duration = data.get("duration") or data.get("length") or "00:00"
        thumbs = data.get("thumbnails") or data.get("thumbnail") or []
        thumb = ""
        if isinstance(thumbs, list) and thumbs:
            x = thumbs[-1]
            thumb = x.get("url","") if isinstance(x,dict) else str(x)
        elif isinstance(thumbs, str):
            thumb = thumbs
        link = data.get("link") or data.get("url") or (self.base + vid)
        return Track(
            id=vid, channel_name=channel, duration=duration,
            duration_sec=utils.to_seconds(duration), message_id=m_id,
            title=str(title)[:80], thumbnail=thumb.split("?")[0],
            url=link, view_count=data.get("viewCount",""),
            user=user, video=video
        )

    async def search(self, query, m_id, video=False):
        query = str(query).strip()
        # API 1
        for base,key in ((API1_URL,API1_KEY),(API2_URL,API2_KEY)):
            data = await self._api_json(base,key,"/search",{"query":query,"limit":5})
            if data:
                results = data.get("result") or data.get("results") or []
                for item in results:
                    tr=self._track_from_data(item,m_id,video)
                    if tr:
                        self.set_context(tr,query)
                        return tr
        # py_yt fallback
        try:
            s=VideosSearch(query,limit=5,with_live=False)
            data=await asyncio.wait_for(s.next(),12)
            for item in (data or {}).get("result",[]):
                tr=self._track_from_data(item,m_id,video)
                if tr:
                    self.set_context(tr,query)
                    return tr
        except Exception as e:
            logger.warning(f"YouTube search failed: {e}")
        return None

    async def playlist(self, limit, user, url, video):
        url=self._clean_link(url)
        for base,key in ((API1_URL,API1_KEY),(API2_URL,API2_KEY)):
            data=await self._api_json(base,key,"/playlist",{"link":url,"limit":limit})
            if data:
                arr=data.get("videos") or data.get("result") or []
                tracks=[self._track_from_data(x,0,video,user) for x in arr]
                tracks=[x for x in tracks if x]
                if tracks: return tracks
        try:
            p=await asyncio.wait_for(Playlist.get(url),20)
            out=[]
            for x in (p.get("videos") or [])[:limit]:
                tr=self._track_from_data(x,0,video,user)
                if tr: out.append(tr)
            return out
        except Exception as e:
            logger.warning(f"Playlist failed: {e}")
            return []

    async def _search_many(self, query, video=False):
        out=[]
        for base,key in ((API1_URL,API1_KEY),(API2_URL,API2_KEY)):
            data=await self._api_json(base,key,"/search",{"query":query,"limit":8},8)
            if data:
                for x in data.get("result") or data.get("results") or []:
                    tr=self._track_from_data(x,0,video,"Autoplay")
                    if tr: out.append(tr)
        if out: return out
        try:
            s=VideosSearch(query,limit=8,with_live=False)
            data=await asyncio.wait_for(s.next(),10)
            for x in (data or {}).get("result",[]):
                tr=self._track_from_data(x,0,video,"Autoplay")
                if tr: out.append(tr)
        except Exception:
            pass
        return out

    def _same(self,a,b):
        aa=re.sub(r"[^a-z0-9]+","", (a or "").lower())
        bb=re.sub(r"[^a-z0-9]+","", (b or "").lower())
        return bool(aa and bb and (aa==bb or SequenceMatcher(None,aa,bb).ratio()>.90))

    def _language_ok(self,tr,lang):
        if not lang: return True
        detected=self._detect_language(
            f"{getattr(tr,'title','')} {getattr(tr,'channel_name','')}"
        )
        # Only reject an explicit conflicting language. Neutral metadata is accepted.
        return not detected or detected==lang

    async def get_related(self, video_id, video=False, max_duration=0):
        vid=self._video_id(video_id)
        context=self._contexts.get(vid,"")
        lang=self._languages.get(vid) or self._detect_language(context)
        if not context:
            context=""
        # Build language-preserving searches. Do not depend on Recommendations/RD.
        seed_title=context
        queries=[]
        if lang:
            queries += [
                f"{lang} {seed_title} song",
                f"{seed_title} {lang} song",
                f"{lang} latest song",
                f"{lang} new songs",
                f"{lang} songs"
            ]
        else:
            queries += [f"{seed_title} similar song", f"{seed_title} songs", "latest songs"]
        seen=set()
        for q in queries:
            candidates=await self._search_many(q,video)
            random.shuffle(candidates)
            for tr in candidates:
                if tr.id in seen: continue
                seen.add(tr.id)
                if tr.id==vid: continue
                if max_duration and tr.duration_sec and tr.duration_sec>max_duration: continue
                if not self._language_ok(tr,lang): continue
                if self._same(tr.title, context): continue
                tr.user="Autoplay"
                self.set_context(tr, f"{lang+' ' if lang else ''}{tr.title}")
                return tr
        return None

    async def prefetch(self, link, video=False):
        link=self._clean_link(link)
        dl_type="video" if video else "audio"
        vid=self._video_id(link)
        key=f"{vid}_{dl_type}"
        now=time.time()
        if now-self._recent_prefetches.get(key,0)<20:
            return True
        self._recent_prefetches[key]=now
        # Hit both APIs, first one that accepts the request wins.
        for base,api_key in ((API1_URL,API1_KEY),(API2_URL,API2_KEY)):
            data=await self._api_json(
                base,api_key,"/download",
                {"url":link,"query":link,"type":dl_type,"dl_type":dl_type,"prefetch":"true"},8
            )
            if data is not None:
                return True
        return False

    async def _api_download(self, base, key, vid, video):
        typ="video" if video else "audio"
        url=self.base+vid
        # Try the flexible endpoint first.
        data=await self._api_json(
            base,key,"/download",
            {"url":url,"query":url,"type":typ,"dl_type":typ},12
        )
        if isinstance(data,dict):
            for k in ("url","download_url","stream_url","file","link","result"):
                v=data.get(k)
                if isinstance(v,str) and v.startswith(("http://","https://")):
                    return v
                if isinstance(v,dict):
                    for kk in ("url","download_url","stream_url"):
                        vv=v.get(kk)
                        if isinstance(vv,str) and vv.startswith(("http://","https://")):
                            return vv
        # Optimized direct route used by API 1.
        if key:
            ext="mp4" if video else "mp3"
            return f"{base}/downloads/{key}/youtube.com/{vid}.{ext}"
        return None

    async def download(self, video_id, video=False):
        vid=self._video_id(video_id)
        if not vid: return None
        # Give API 1 priority, then API 2, then yt-dlp/local.
        for base,key in ((API1_URL,API1_KEY),(API2_URL,API2_KEY)):
            u=await self._api_download(base,key,vid,video)
            if not u: continue
            try:
                c=await self.get_client()
                async with c.get(u,timeout=18) as r:
                    if r.status in (200,206):
                        await r.content.read(512)
                        return u
            except Exception as e:
                logger.warning(f"API stream check failed {base}: {e}")
        # Last fallback: yt-dlp. It is deliberately not the primary path.
        try:
            import yt_dlp
            out=os.path.join(DOWNLOAD_DIR, f"{vid}.{'mp4' if video else 'mp3'}")
            if os.path.exists(out) and os.path.getsize(out)>1024:
                return out
            opts={
                "quiet":True,"no_warnings":True,"noplaylist":True,
                "outtmpl":out,
                "format":"bestvideo+bestaudio/best" if video else "bestaudio/best",
                "merge_output_format":"mp4" if video else "mp3",
            }
            loop=asyncio.get_running_loop()
            def run():
                with yt_dlp.YoutubeDL(opts) as y:
                    y.download([self.base+vid])
            await asyncio.wait_for(loop.run_in_executor(None,run),35)
            if os.path.exists(out): return out
        except Exception as e:
            logger.warning(f"yt-dlp fallback failed for {vid}: {e}")
        return None

    async def stream_url(self, video_id, video=False):
        return await self.download(video_id,video)

    async def close(self):
        if self._client and not self._client.closed:
            await self._client.close()
