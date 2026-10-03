import os
import tempfile
import shutil
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI(title="Railway yt-dlp API")


def get_ydl_opts(download=False, output_dir=None, format_type="mp4"):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": not download,
        "noplaylist": True,
        "retries": 5,
        "fragment_retries": 5,
        # Less-tracked player clients that hit different YouTube API endpoints
        "extractor_args": {
            "youtube": {
                "player_client": ["tv", "mweb", "web_safari", "android_vr"],
                "player_skip": ["webpage", "configs"],
            }
        },
        # Safari UA to match the web_safari client expectations
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Safari/605.1.15"
            )
        },
    }

    # Cookies (still helpful as a secondary signal)
    cookie_file = os.getenv("YTDLP_COOKIE_FILE", "/app/cookies.txt")
    if os.path.exists(cookie_file):
        opts["cookiefile"] = cookie_file

    # POT provider (the critical fix)
    pot_provider = os.getenv("YTDLP_POT_PROVIDER", "http://bgutil-provider:4416")
    opts["extractor_args"]["youtube"]["po_token"] = [f"web+{pot_provider}"]

    if download:
        opts["outtmpl"] = os.path.join(output_dir, "%(title)s.%(ext)s")
        if format_type == "mp3":
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            opts.update({
                "format": "bestvideo[height<=720]+bestaudio/best[height<=720]",
                "merge_output_format": "mp4",
            })
    return opts


def format_to_media(fmt):
    vcodec = fmt.get("vcodec")
    acodec = fmt.get("acodec")
    ext = fmt.get("ext")
    mime = fmt.get("mime_type") or (
        f"video/{ext}" if vcodec not in (None, "none") else f"audio/{ext}"
    )
    has_video = vcodec not in (None, "none")
    has_audio = acodec not in (None, "none")

    if has_video:
        type_ = "video"
        quality = f"{fmt.get('height')}p" if fmt.get("height") else fmt.get("format_note")
    elif has_audio:
        type_ = "audio"
        quality = f"{fmt.get('abr')}kbps" if fmt.get("abr") else fmt.get("format_note")
    else:
        return None

    if not fmt.get("url"):
        return None

    return {
        "type": type_,
        "id": fmt.get("format_id"),
        "url": fmt.get("url"),
        "width": fmt.get("width"),
        "height": fmt.get("height"),
        "container": mime,
        "has_audio": has_audio,
        "has_video": has_video,
        "has_photo": False,
        "quality": quality,
    }


def build_response(info):
    media = []
    thumb = info.get("thumbnail")
    if thumb:
        media.append({
            "type": "photo",
            "id": "thumbnail",
            "url": thumb,
            "width": None,
            "height": None,
            "container": "image/jpeg",
            "has_audio": False,
            "has_video": False,
            "has_photo": True,
            "quality": "Thumbnail",
        })

    for fmt in info.get("formats", []) or []:
        item = format_to_media(fmt)
        if item:
            media.append(item)

    has_video = any(m["has_video"] for m in media)

    return {
        "success": True,
        "type": "video" if has_video else "audio",
        "id": info.get("id"),
        "username": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        "profile_image_uri": thumb,
        "caption": info.get("title"),
        "media": media,
        "tags": info.get("tags", []) or [],
        "duration": info.get("duration"),
        "width": info.get("width"),
        "height": info.get("height"),
        "errors": [],
        "source": "yt-dlp",
        "proxy_used": "direct",
        "proxies_tried": [],
    }


@app.get("/info")
async def get_info(url: str = Query(..., description="Video URL")):
    try:
        ydl_opts = get_ydl_opts(download=False)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return build_response(info)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "type": None,
                "id": None,
                "username": None,
                "profile_image_uri": None,
                "caption": None,
                "media": [],
                "tags": [],
                "duration": None,
                "width": None,
                "height": None,
                "errors": [str(e)],
                "source": "yt-dlp",
                "proxy_used": "direct",
                "proxies_tried": [],
            },
        )


class DownloadRequest(BaseModel):
    url: str
    format: str = "mp4"


def cleanup_temp_dir(temp_dir: str):
    shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/download")
async def download_video(req: DownloadRequest, background_tasks: BackgroundTasks):
    temp_dir = tempfile.mkdtemp(prefix="ytdlp_")
    try:
        ydl_opts = get_ydl_opts(download=True, output_dir=temp_dir, format_type=req.format)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            filename = ydl.prepare_filename(info)
            if req.format == "mp3":
                filename = os.path.splitext(filename)[0] + ".mp3"

        if not os.path.exists(filename):
            raise HTTPException(status_code=500, detail="Downloaded file not found.")

        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            path=filename,
            media_type="application/octet-stream",
            filename=os.path.basename(filename),
        )
    except Exception as e:
        cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def root():
    return {
        "message": "Railway yt-dlp API",
        "endpoints": {
            "info": "GET /info?url=...",
            "download": "POST /download",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}
