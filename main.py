import re
import os
import time
import random
import tempfile
import logging
from typing import Optional, Dict, Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

# ----------------------------------------------------------------------
# Logging setup – Render logs me dikhega
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("vidrop")

app = FastAPI(title="VidDrop – Full Fixed")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
COOKIES_DIR = os.getenv("COOKIES_DIR", "cookies")
MAX_RETRIES = 3
RETRY_DELAY = 2

SUPPORTED_PLATFORMS = {
    "instagram": r"(instagram\.com|instagr\.am)",
    "facebook":  r"(facebook\.com|fb\.watch)",
    "youtube":   r"(youtube\.com|youtu\.be)",
    "tiktok":    r"(tiktok\.com)",
    "pinterest": r"(pinterest\.com|pin\.it)",
    "twitter":   r"(twitter\.com|x\.com)",
    "reddit":    r"(reddit\.com|redd\.it)",
    "snapchat":  r"(snapchat\.com)",
    "linkedin":  r"(linkedin\.com)",
    "threads":   r"(threads\.net)",
}

UNSUPPORTED_PLATFORMS = {"sharechat", "moj"}

COOKIE_FILES = {
    "instagram": "instagram_cookies.txt",
    "facebook":  "facebook_cookies.txt",
    "youtube":   "youtube_cookies.txt",
    "tiktok":    "tiktok_cookies.txt",
    "twitter":   "twitter_cookies.txt",
    "reddit":    "reddit_cookies.txt",
    "linkedin":  "linkedin_cookies.txt",
    "threads":   "threads_cookies.txt",
}

# ----------------------------------------------------------------------
# Startup – cookie status logs (Render logs me dikhega)
# ----------------------------------------------------------------------
@app.on_event("startup")
async def startup_check():
    log.info("=" * 60)
    log.info("VidDrop starting – checking cookies...")
    log.info("=" * 60)
    for platform in SUPPORTED_PLATFORMS.keys():
        env_key = f"{platform.upper()}_COOKIES"
        raw = os.getenv(env_key)
        if raw:
            log.info(f"✅ {env_key}: SET ({len(raw)} chars)")
        else:
            log.warning(f"❌ {env_key}: NOT SET")

        fname = COOKIE_FILES.get(platform)
        if fname:
            for base in (COOKIES_DIR, "."):
                path = os.path.join(base, fname)
                if os.path.exists(path):
                    log.info(f"   📁 File found: {path} ({os.path.getsize(path)} bytes)")
    log.info("=" * 60)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def detect_platform(url: str) -> Optional[str]:
    for platform, pattern in SUPPORTED_PLATFORMS.items():
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return None


def is_explicitly_unsupported(url: str) -> bool:
    return any(bad in url.lower() for bad in UNSUPPORTED_PLATFORMS)


def get_cookie_file(platform: str) -> Optional[str]:
    """Env var (Render) → temp file, ya disk se file."""
    env_key = f"{platform.upper()}_COOKIES"
    raw = os.getenv(env_key)

    if raw:
        # Strip whitespace
        raw = raw.strip()
        # Convert literal \n to real newlines (Render env var format)
        if "\\n" in raw and "\n" not in raw:
            raw = raw.replace("\\n", "\n")

        if len(raw) > 50:
            tmp = os.path.join(tempfile.gettempdir(), f"_{platform}_cookies.txt")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(raw)
                log.info(f"🍪 {platform}: cookies loaded from env var → {tmp}")
                return tmp
            except Exception as e:
                log.error(f"Cookie file write failed for {platform}: {e}")

    # Disk fallback
    fname = COOKIE_FILES.get(platform)
    if fname:
        for base in (COOKIES_DIR, "."):
            path = os.path.join(base, fname)
            if os.path.exists(path) and os.path.getsize(path) > 50:
                log.info(f"🍪 {platform}: cookies loaded from file → {path}")
                return path

    return None


def build_ydl_opts(platform: str, use_cookies: bool = True) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "format": "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        "nocheckcertificate": True,
        "geo_bypass": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Mode": "navigate",
        },
    }

    if use_cookies:
        cookie = get_cookie_file(platform)
        if cookie:
            opts["cookiefile"] = cookie

    return opts


def extract_info(url: str, platform: str) -> Dict[str, Any]:
    strategies = ["with_cookies", "anonymous"] if get_cookie_file(platform) else ["anonymous"]
    last_error = None

    for strategy in strategies:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                opts = build_ydl_opts(platform, use_cookies=(strategy == "with_cookies"))
                log.info(f"Attempt {attempt}/{MAX_RETRIES} [{strategy}] → {url}")
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        log.info(f"✅ Success [{strategy}]")
                        return info
                    raise ExtractorError("Empty info")

            except (DownloadError, ExtractorError) as e:
                last_error = e
                msg = str(e).lower()
                log.warning(f"❌ Attempt {attempt} failed: {str(e)[:150]}")

                if any(k in msg for k in (
                    "empty media response", "rate-limit", "rate limit",
                    "too many requests", "cannot parse data", "http error 429",
                )):
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY + random.uniform(0, 2))
                        continue
                break

            except Exception as e:
                last_error = e
                log.error(f"❌ Unexpected error: {str(e)[:150]}")
                break

    raise RuntimeError(_friendly_error(last_error, platform))


def _friendly_error(err: Optional[Exception], platform: str) -> str:
    msg = str(err) if err else "Unknown error"
    low = msg.lower()

    if "empty media response" in low or "cannot parse data" in low:
        return (
            f"{platform.capitalize()} ne empty response diya. "
            "Kaaran: (1) cookies set nahi hain, (2) post private hai, "
            "ya (3) server ka IP rate-limit hai. Render pe "
            f"{platform.upper()}_COOKIES env var set karein."
        )
    if "login" in low or "sign in" in low:
        return "Is content ke liye login zaroori hai. Cookies provide karein."
    if "private" in low:
        return "Ye post private hai – public URL use karein."
    if "not available" in low or "404" in low or "removed" in low:
        return "Content available nahi hai ya delete ho chuka hai."
    if "429" in low or "too many requests" in low:
        return "Rate-limit ho gaya. Thodi der baad try karein."
    if "timed out" in low or "timeout" in low:
        return "Request timeout. Dobara try karein."
    if "geo" in low or "not available in your country" in low:
        return "Ye content aapke region me available nahi hai."

    return f"Extraction failed: {msg[:200]}"


# ----------------------------------------------------------------------
# Transform
# ----------------------------------------------------------------------
def map_to_response(info: Dict[str, Any], platform: str) -> Dict[str, Any]:
    response = {
        "success": True,
        "platform": platform,
        "type": "video",
        "username": (
            info.get("uploader") or info.get("channel")
            or info.get("creator") or info.get("uploader_id") or None
        ),
        "profile_image_uri": None,
        "caption": info.get("description") or info.get("title"),
        "media": [],
    }

    def make_media_item(entry: Dict[str, Any]) -> Dict[str, Any]:
        has_video = entry.get("vcodec") not in (None, "none")
        has_audio = entry.get("acodec") not in (None, "none")
        media_type = "video" if has_video else "photo"

        dl_url = entry.get("url")
        if not dl_url:
            for f in reversed(entry.get("formats") or []):
                if f.get("url"):
                    dl_url = f["url"]
                    break

        return {
            "type": media_type,
            "id": entry.get("id"),
            "url": dl_url,
            "quality": entry.get("format_note") or entry.get("resolution"),
            "container": entry.get("ext"),
            "has_audio": has_audio,
            "has_video": has_video,
            "has_photo": not has_video,
            "width": entry.get("width"),
            "height": entry.get("height"),
            "fps": entry.get("fps"),
            "bitrate": entry.get("tbr"),
        }

    if info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if len(entries) > 1:
            response["type"] = "carousel"
        for entry in entries:
            response["media"].append(make_media_item(entry))
    else:
        response["media"].append(make_media_item(info))

    for t in (info.get("thumbnails") or []):
        u = t.get("url", "")
        if t.get("id") == "avatar" or "avatar" in u.lower():
            response["profile_image_uri"] = u
            break

    return response


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------
@app.get("/api/download")
async def download(url: str = Query(...)):
    if is_explicitly_unsupported(url):
        return JSONResponse(status_code=400, content={
            "success": False, "error": "ERROR",
            "message": f"Ye platform support nahi karta: {url}",
        })

    platform = detect_platform(url)
    if not platform:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "ERROR",
            "message": "URL recognize nahi hua ya unsupported platform hai.",
        })

    try:
        info = extract_info(url, platform)
    except RuntimeError as e:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "ERROR", "message": str(e),
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False, "error": "ERROR",
            "message": f"Internal error: {str(e)[:200]}",
        })

    try:
        return JSONResponse(content=map_to_response(info, platform))
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False, "error": "ERROR",
            "message": f"Response build failed: {str(e)[:200]}",
        })


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "platforms": list(SUPPORTED_PLATFORMS.keys()),
        "cookies_available": {
            p: bool(get_cookie_file(p)) for p in SUPPORTED_PLATFORMS
        },
    }


@app.get("/debug/cookies")
async def debug_cookies():
    """Debug: check karo har env var Render pe pahuncha ya nahi."""
    result = {}
    for platform in SUPPORTED_PLATFORMS.keys():
        env_key = f"{platform.upper()}_COOKIES"
        raw = os.getenv(env_key)
        result[platform] = {
            "env_key": env_key,
            "env_var_set": raw is not None,
            "env_var_length": len(raw) if raw else 0,
            "starts_with_netscape": raw.strip().startswith("# Netscape") if raw else False,
            "resolved_path": get_cookie_file(platform),
        }
    return result


# ----------------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")