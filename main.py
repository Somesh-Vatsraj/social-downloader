import re
from typing import Optional, Dict, Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
from yt_dlp.utils import DownloadError

app = FastAPI(title="VidDrop Clone")

# Allow all origins (frontend is served from same origin, but this helps during dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------------------
# Platform detection
# ----------------------------------------------------------------------
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

def detect_platform(url: str) -> Optional[str]:
    for platform, pattern in SUPPORTED_PLATFORMS.items():
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return None

def is_explicitly_unsupported(url: str) -> bool:
    for bad in UNSUPPORTED_PLATFORMS:
        if bad in url.lower():
            return True
    return False

# ----------------------------------------------------------------------
# yt-dlp extraction
# ----------------------------------------------------------------------
def extract_info(url: str) -> Dict[str, Any]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "format": "best[ext=mp4]/best",  # prefer single-file formats (no merge needed)
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

# ----------------------------------------------------------------------
# Transform yt-dlp info → your JSON schema
# ----------------------------------------------------------------------
def map_to_response(info: Dict[str, Any], platform: str) -> Dict[str, Any]:
    response = {
        "success": True,
        "platform": platform,
        "type": "video",
        "username": info.get("uploader")
                     or info.get("channel")
                     or info.get("creator")
                     or info.get("uploader_id"),
        "profile_image_uri": None,
        "caption": info.get("description") or info.get("title"),
        "media": [],
    }

    def make_media_item(entry: Dict[str, Any]) -> Dict[str, Any]:
        has_video = entry.get("vcodec") not in (None, "none")
        has_audio = entry.get("acodec") not in (None, "none")
        media_type = "video" if has_video else "photo"
        return {
            "type": media_type,
            "id": entry.get("id"),
            "url": entry.get("url"),
            "quality": entry.get("format_note"),
            "container": entry.get("ext"),
            "has_audio": has_audio,
            "has_video": has_video,
            "has_photo": not has_video,
            "width": entry.get("width"),
            "height": entry.get("height"),
            "fps": entry.get("fps"),
            "bitrate": entry.get("tbr"),
        }

    if "entries" in info and info["entries"]:
        response["type"] = "carousel"
        for entry in info["entries"]:
            response["media"].append(make_media_item(entry))
    else:
        response["media"].append(make_media_item(info))

    # Try to grab profile image from thumbnails
    thumbs = info.get("thumbnails") or []
    for t in thumbs:
        if t.get("id") == "avatar" or "avatar" in t.get("url", "").lower():
            response["profile_image_uri"] = t["url"]
            break

    return response

# ----------------------------------------------------------------------
# API endpoint
# ----------------------------------------------------------------------
@app.get("/api/download")
async def download(url: str = Query(..., description="Public media URL")):
    if is_explicitly_unsupported(url):
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "ERROR",
                "message": f"Platform not supported: {url}",
            },
        )

    platform = detect_platform(url)
    if not platform:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "ERROR",
                "message": "Unrecognised or unsupported platform",
            },
        )

    try:
        info = extract_info(url)
    except DownloadError as e:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "ERROR",
                "message": str(e),
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "ERROR",
                "message": f"Internal error: {str(e)}",
            },
        )

    response = map_to_response(info, platform)
    return JSONResponse(content=response)

# ----------------------------------------------------------------------
# Serve static frontend
# ----------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")