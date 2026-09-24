import os
import re
import tempfile
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

app = FastAPI(
    title="YouTube Video Downloader",
    version="1.0.0"
)


def is_youtube_url(url: str) -> bool:
    pattern = r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)/"
    return bool(re.match(pattern, url.strip(), re.IGNORECASE))


def yt_options():
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,

        # YouTube JS challenge support
        "js_runtimes": {
            "deno": {}
        },

        # Allow yt-dlp to use its EJS components
        "remote_components": {
            "ejs": ["npm"]
        },
    }


@app.get("/")
def home():
    return {
        "status": "online",
        "service": "YouTube Video Downloader API",
        "version": "1.0.0"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.get("/info")
def video_info(
    url: str = Query(..., description="YouTube video URL")
):
    if not is_youtube_url(url):
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported."
        )

    try:
        options = yt_options()
        options["skip_download"] = True

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)

        return {
            "success": True,
            "id": info.get("id"),
            "title": info.get("title"),
            "description": info.get("description"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "channel": info.get("channel"),
            "channel_url": info.get("channel_url"),
            "webpage_url": info.get("webpage_url"),
            "view_count": info.get("view_count")
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"YouTube extraction failed: {str(e)}"
        )


@app.get("/download")
def download_video(
    url: str = Query(..., description="YouTube video URL")
):
    if not is_youtube_url(url):
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported."
        )

    temp_dir = tempfile.mkdtemp(prefix="yt_")

    try:
        output_template = str(
            Path(temp_dir) / "%(id)s.%(ext)s"
        )

        options = yt_options()

        options.update({
            "outtmpl": output_template,

            # Video only / best MP4-compatible combination
            "format": (
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "best[ext=mp4]/best"
            ),

            "merge_output_format": "mp4",

            # Do not download playlist
            "noplaylist": True,
        })

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        video_id = info.get("id")

        files = list(Path(temp_dir).glob("*"))

        if not files:
            raise Exception("Downloaded file was not found.")

        downloaded_file = files[0]

        safe_title = re.sub(
            r'[\\/*?:"<>|]',
            "",
            info.get("title") or "youtube-video"
        )

        filename = f"{safe_title}.mp4"

        return FileResponse(
            path=str(downloaded_file),
            media_type="video/mp4",
            filename=filename
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Download failed: {str(e)}"
        )


@app.get("/test")
def test():
    return {
        "message": "API working",
        "youtube": True,
        "yt_dlp": True,
        "deno": True
    }
