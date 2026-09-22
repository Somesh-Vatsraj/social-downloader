from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import yt_dlp
import os
import tempfile
import shutil
import re
import json
import uuid
from pathlib import Path


app = FastAPI(
    title="Vatsraj Tech YouTube Downloader API",
    description="YouTube metadata, formats and download API using yt-dlp",
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# BASIC CONFIG
# ============================================================

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "yt_downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# YOUTUBE / YT-DLP OPTIONS
# ============================================================

BASE_YDL_OPTIONS = {
    "quiet": True,
    "no_warnings": False,

    # Don't download during information extraction
    "skip_download": True,

    # Single video only
    "noplaylist": True,

    # External JS runtime
    "js_runtimes": {
        "deno": {}
    },

    # Allow EJS scripts
    "remote_components": {
        "ejs": ["github"]
    },

    # Better compatibility
    "extractor_args": {
        "youtube": {
            "player_client": ["mweb"]
        }
    },
}


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def iso_duration(seconds):
    if not seconds:
        return None

    try:
        seconds = int(seconds)
    except Exception:
        return None

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours:
        return f"PT{hours}H{minutes}M{secs}S"

    if minutes:
        return f"PT{minutes}M{secs}S"

    return f"PT{secs}S"


def quality_from_format(fmt):
    height = fmt.get("height")

    if height:
        return f"{height}p"

    abr = fmt.get("abr")

    if abr:
        return f"{int(abr)}kbps"

    return "unknown"


def get_container(fmt):
    ext = fmt.get("ext")

    if ext:
        return f"{fmt.get('vcodec') != 'none' and 'video/' or 'audio/'}{ext}"

    return None


def safe_filename(name):
    name = clean_text(name)

    if not name:
        name = "youtube_video"

    name = re.sub(r'[\\/*?:"<>|]', "", name)

    return name[:180]


def get_formats(info):
    result = []

    formats = info.get("formats", [])

    for fmt in formats:
        format_id = fmt.get("format_id")

        if not format_id:
            continue

        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")

        has_video = vcodec not in (None, "none")
        has_audio = acodec not in (None, "none")

        if not has_video and not has_audio:
            continue

        width = fmt.get("width") or 0
        height = fmt.get("height") or 0

        filesize = (
            fmt.get("filesize")
            or fmt.get("filesize_approx")
            or 0
        )

        result.append({
            "format_id": format_id,
            "ext": fmt.get("ext"),
            "width": width,
            "height": height,
            "resolution": (
                f"{width}x{height}"
                if width and height
                else None
            ),
            "quality": quality_from_format(fmt),
            "fps": fmt.get("fps"),
            "filesize": filesize,
            "filesize_mb": (
                round(filesize / 1024 / 1024, 2)
                if filesize
                else None
            ),
            "has_audio": has_audio,
            "has_video": has_video,
            "vcodec": vcodec,
            "acodec": acodec,
            "container": get_container(fmt),
            "audio_quality": fmt.get("abr"),
            "url": fmt.get("url"),
        })

    return result


def extract_info(url):
    options = BASE_YDL_OPTIONS.copy()

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


def build_response(info):

    thumbnail = info.get("thumbnail")

    media = []

    # Main video information
    if info.get("url"):
        media.append({
            "type": "video",
            "id": "main_video",
            "url": info.get("url"),
            "width": info.get("width") or 0,
            "height": info.get("height") or 0,
            "container": (
                f"video/{info.get('ext')}"
                if info.get("ext")
                else None
            ),
            "has_audio": True,
            "has_video": True,
            "has_photo": False,
            "quality": (
                f"{info.get('height')}p"
                if info.get("height")
                else "unknown"
            ),
            "duration": iso_duration(info.get("duration"))
        })

    # Thumbnail
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
            "quality": "HD Full"
        })

    return {
        "success": True,
        "type": "video",
        "platform": "youtube",

        "id": info.get("id"),

        "username": (
            info.get("uploader_id")
            or info.get("channel_id")
            or info.get("uploader")
        ),

        "channel": info.get("channel"),

        "profile_image_uri": None,

        "title": info.get("title"),

        "caption": (
            info.get("description")
            or info.get("title")
            or ""
        ),

        "description": info.get("description"),

        "thumbnail": thumbnail,

        "duration": info.get("duration"),

        "duration_iso": iso_duration(
            info.get("duration")
        ),

        "upload_date": info.get("upload_date"),

        "view_count": info.get("view_count"),

        "like_count": info.get("like_count"),

        "webpage_url": info.get("webpage_url"),

        "media": media,

        "formats": get_formats(info)
    }


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():
    return {
        "success": True,
        "name": "Vatsraj Tech YouTube Downloader API",
        "version": "1.0.0",
        "status": "online",

        "endpoints": {
            "extract": "/api/extract?url=YOUTUBE_URL",
            "formats": "/api/formats?url=YOUTUBE_URL",
            "download": "/api/download?url=YOUTUBE_URL",
            "health": "/health",
            "docs": "/docs"
        }
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    return {
        "success": True,
        "status": "healthy"
    }


# ============================================================
# EXTRACT
# ============================================================

@app.get("/api/extract")
def api_extract(
    url: str = Query(..., description="YouTube URL")
):

    if not url:
        raise HTTPException(
            status_code=400,
            detail="URL is required"
        )

    if "youtube.com" not in url and "youtu.be" not in url:
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported"
        )

    try:
        info = extract_info(url)

        return build_response(info)

    except Exception as e:

        error = clean_text(str(e))

        raise HTTPException(
            status_code=500,
            detail=error
        )


# ============================================================
# FORMATS
# ============================================================

@app.get("/api/formats")
def api_formats(
    url: str = Query(..., description="YouTube URL")
):

    try:

        if (
            "youtube.com" not in url
            and "youtu.be" not in url
        ):
            raise HTTPException(
                status_code=400,
                detail="Only YouTube URLs are supported"
            )

        info = extract_info(url)

        formats = get_formats(info)

        return {
            "success": True,
            "id": info.get("id"),
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "formats": formats
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# DOWNLOAD
# ============================================================

@app.get("/api/download")
def api_download(
    url: str = Query(..., description="YouTube URL"),

    format_id: str = Query(
        "bestvideo+bestaudio/best",
        description="yt-dlp format"
    )
):

    if (
        "youtube.com" not in url
        and "youtu.be" not in url
    ):
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported"
        )

    job_id = uuid.uuid4().hex

    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_template = str(
        job_dir / "%(title)s.%(ext)s"
    )

    options = {
        "quiet": True,
        "no_warnings": False,

        "noplaylist": True,

        "format": format_id,

        "outtmpl": output_template,

        # Merge audio/video
        "merge_output_format": "mp4",

        # EJS
        "js_runtimes": {
            "deno": {}
        },

        "remote_components": {
            "ejs": ["github"]
        },

        # PO token provider
        "extractor_args": {
            "youtube": {
                "player_client": ["mweb"]
            }
        }
    }

    try:

        with yt_dlp.YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

            requested = info.get(
                "requested_downloads"
            )

            downloaded_file = None

            if requested:

                for item in requested:

                    filepath = item.get(
                        "filepath"
                    )

                    if filepath:
                        downloaded_file = filepath
                        break

            if not downloaded_file:

                prepared = ydl.prepare_filename(info)

                if os.path.exists(prepared):
                    downloaded_file = prepared

                else:

                    # Find downloaded file
                    files = list(
                        job_dir.glob("*")
                    )

                    if files:
                        downloaded_file = str(
                            files[0]
                        )

            if not downloaded_file:

                raise Exception(
                    "Downloaded file could not be found"
                )

        file_path = Path(downloaded_file)

        if not file_path.exists():

            raise Exception(
                "Downloaded file does not exist"
            )

        filename = safe_filename(
            file_path.stem
        )

        extension = file_path.suffix

        download_name = (
            filename + extension
        )

        def file_iterator():

            try:

                with open(
                    file_path,
                    "rb"
                ) as file:

                    while True:

                        chunk = file.read(
                            1024 * 1024
                        )

                        if not chunk:
                            break

                        yield chunk

            finally:

                try:
                    shutil.rmtree(
                        job_dir,
                        ignore_errors=True
                    )
                except Exception:
                    pass

        return StreamingResponse(
            file_iterator(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{download_name}"'
            }
        )

    except Exception as e:

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# TEST ENDPOINT
# ============================================================

@app.get("/api/test")
def test():

    return {
        "success": True,
        "message": "YouTube Downloader API is working",
        "yt_dlp": yt_dlp.version.__version__
    }
