import os
import re
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

app = FastAPI(
    title="Social Downloader API",
    description="YouTube video downloader API",
    version="1.0.0",
)


# --------------------------------------------------
# YouTube URL validation
# --------------------------------------------------

def is_youtube_url(url: str) -> bool:
    pattern = re.compile(
        r"^(https?://)?"
        r"(www\.)?"
        r"(youtube\.com|youtu\.be|youtube-nocookie\.com)"
        r"/",
        re.IGNORECASE,
    )

    return bool(pattern.match(url.strip()))


# --------------------------------------------------
# Common yt-dlp options
# --------------------------------------------------

def get_yt_options():
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,

        # Current YouTube extraction support
        "js_runtimes": {
            "deno": {}
        },

        "remote_components": {
            "ejs": ["npm"]
        },
    }


# --------------------------------------------------
# Root
# --------------------------------------------------

@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Social Downloader API",
        "version": "1.0.0",
        "platforms": ["youtube"],
    }


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok"
    }


# --------------------------------------------------
# API test
# --------------------------------------------------

@app.get("/test")
def test():
    return {
        "api": True,
        "youtube": True,
        "yt_dlp": True,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "deno": shutil.which("deno") is not None,
    }


# --------------------------------------------------
# Get YouTube video information
# --------------------------------------------------

@app.get("/info")
def video_info(
    url: str = Query(
        ...,
        description="YouTube video URL"
    )
):
    url = url.strip()

    if not is_youtube_url(url):
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported."
        )

    try:
        options = get_yt_options()
        options["skip_download"] = True

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(
                url,
                download=False
            )

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
            "view_count": info.get("view_count"),
            "upload_date": info.get("upload_date"),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"YouTube extraction failed: {str(e)}"
        )


# --------------------------------------------------
# Download YouTube video
# --------------------------------------------------

@app.get("/download")
def download_video(
    url: str = Query(
        ...,
        description="YouTube video URL"
    )
):
    url = url.strip()

    if not is_youtube_url(url):
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported."
        )

    temp_dir = tempfile.mkdtemp(
        prefix="youtube_"
    )

    try:
        output_template = str(
            Path(temp_dir) / "%(id)s.%(ext)s"
        )

        options = get_yt_options()

        options.update({
            "outtmpl": output_template,

            # Best MP4 video + M4A audio.
            # Fallback to a single MP4/other format.
            "format": (
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "best[ext=mp4]/"
                "best"
            ),

            "merge_output_format": "mp4",

            "noplaylist": True,
        })

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(
                url,
                download=True
            )

        # Find downloaded file
        downloaded_files = [
            file
            for file in Path(temp_dir).iterdir()
            if file.is_file()
        ]

        if not downloaded_files:
            raise Exception(
                "Downloaded video file was not found."
            )

        # Prefer MP4
        mp4_files = [
            file
            for file in downloaded_files
            if file.suffix.lower() == ".mp4"
        ]

        if mp4_files:
            downloaded_file = mp4_files[0]
        else:
            downloaded_file = downloaded_files[0]

        # Clean filename
        title = info.get("title") or "youtube-video"

        safe_title = re.sub(
            r'[\\/*?:"<>|]',
            "",
            title
        )

        safe_title = safe_title.strip()

        if not safe_title:
            safe_title = "youtube-video"

        # Keep actual extension
        extension = downloaded_file.suffix or ".mp4"

        filename = f"{safe_title}{extension}"

        return FileResponse(
            path=str(downloaded_file),
            media_type="video/mp4",
            filename=filename,
        )

    except Exception as e:
        # Remove temporary directory if something fails
        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        raise HTTPException(
            status_code=500,
            detail=f"Download failed: {str(e)}"
        )


# --------------------------------------------------
# Server startup
# --------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(
        os.environ.get("PORT", "8080")
    )

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
    )
