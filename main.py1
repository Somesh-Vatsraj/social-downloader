from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.parse import urlparse
import os
import re
import yt_dlp


app = FastAPI(
    title="Social Media Downloader API",
    version="1.0.0"
)

# Allow all origins (change to specific domain in production if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- CONFIG ----------
COOKIE_FILE = os.environ.get("COOKIE_FILE", "/etc/secrets/cookies.txt")
PROXY_URL = os.environ.get("PROXY_URL", None)  # optional: set in Render env if needed


class URLRequest(BaseModel):
    url: str


# ---------- HELPERS ----------
def iso_duration(seconds):
    if not seconds:
        return None

    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h:
        return f"PT{h}H{m}M{s}S"
    if m:
        return f"PT{m}M{s}S"
    return f"PT{s}S"


def clean_filename(value):
    if not value:
        return "media"
    return re.sub(r'[\\/*?:"<>|]', "_", value)


def get_quality(height):
    if not height:
        return None

    if height >= 2160:
        return "2160p"
    elif height >= 1440:
        return "1440p"
    elif height >= 1080:
        return "1080p"
    elif height >= 720:
        return "720p"
    elif height >= 480:
        return "480p"
    elif height >= 360:
        return "360p"
    else:
        return f"{height}p"


def detect_platform(url):
    host = urlparse(url).netloc.lower()

    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "instagram.com" in host:
        return "instagram"
    if "facebook.com" in host or "fb.watch" in host:
        return "facebook"
    if "tiktok.com" in host:
        return "tiktok"
    if "linkedin.com" in host:
        return "linkedin"
    if "x.com" in host or "twitter.com" in host:
        return "x"
    if "pinterest.com" in host:
        return "pinterest"
    return "unknown"


def build_ydl_options():
    """Common yt-dlp options for Render deployment."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "ignoreerrors": False,
        # Use cookies if file exists (for YouTube bot check)
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        },
    }

    if os.path.exists(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE

    if PROXY_URL:
        opts["proxy"] = PROXY_URL

    return opts


def extract_media(info):
    media = []
    formats = info.get("formats") or []
    seen = set()

    for f in formats:
        url = f.get("url")
        if not url:
            continue

        height = f.get("height")
        width = f.get("width")
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")

        has_video = vcodec not in (None, "none")
        has_audio = acodec not in (None, "none")

        if not has_video and not has_audio:
            continue

        if has_video:
            media_type = "video"
            container = f.get("ext")
            if container:
                container = f"video/{container}"
            quality = get_quality(height)
        else:
            media_type = "audio"
            container = f.get("ext")
            if container:
                container = f"audio/{container}"
            quality = None

        key = (
            media_type,
            height,
            width,
            f.get("format_id"),
            f.get("abr")
        )
        if key in seen:
            continue
        seen.add(key)

        media.append({
            "type": media_type,
            "id": f"format_{f.get('format_id')}",
            "url": url,
            "width": width or 0,
            "height": height or 0,
            "container": container,
            "has_audio": has_audio,
            "has_video": has_video,
            "has_photo": False,
            "quality": quality,
            "duration": iso_duration(
                f.get("duration") or info.get("duration")
            ),
            "format_id": f.get("format_id"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "fps": f.get("fps"),
            "bitrate": f.get("tbr")
        })

    thumbnail = info.get("thumbnail")
    if thumbnail:
        media.append({
            "type": "photo",
            "id": "thumbnail",
            "url": thumbnail,
            "width": 0,
            "height": 0,
            "container": "image/jpeg",
            "has_audio": False,
            "has_video": False,
            "has_photo": True,
            "quality": "HD Full",
            "duration": None
        })

    return media


# ---------- ROUTES ----------
@app.get("/")
def home():
    return {
        "success": True,
        "message": "Social Media Downloader API is running",
        "docs": "/docs"
    }


@app.get("/api/platform")
def platform(url: str):
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Valid URL required")

    return {
        "success": True,
        "platform": detect_platform(url),
        "url": url
    }


@app.post("/api/extract")
def extract(request: URLRequest):
    url = request.url.strip()

    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Valid URL required")

    platform_name = detect_platform(url)
    ydl_options = build_ydl_options()

    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise HTTPException(status_code=404, detail="No media information found")

        # Handle playlist / multiple entries
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            if not entries:
                raise HTTPException(status_code=404, detail="No media found in playlist")
            info = entries[0]

        media = extract_media(info)

        result = {
            "success": True,
            "type": "video" if any(x["type"] == "video" for x in media) else "photo",
            "platform": platform_name,
            "id": info.get("id"),
            "username": (
                info.get("uploader_id")
                or info.get("channel")
                or info.get("uploader")
                or info.get("creator")
            ),
            "profile_image_uri": (
                info.get("channel_favicon")
                or info.get("thumbnail")
            ),
            "caption": (
                info.get("description")
                or info.get("title")
                or ""
            ),
            "title": info.get("title"),
            "duration": iso_duration(info.get("duration")),
            "webpage_url": info.get("webpage_url"),
            "thumbnail": info.get("thumbnail"),
            "media": media
        }

        return result

    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
