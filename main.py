import os
import tempfile
import shutil
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI(title="Railway yt-dlp Downloader")


class DownloadRequest(BaseModel):
    url: str
    format: str = "mp4"  # "mp4" or "mp3"


def get_ydl_opts(output_dir: str, format_type: str):
    """Return yt-dlp options tailored for Railway."""
    outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        "noplaylist": True,
    }

    # Use cookies if a cookies.txt file exists
    cookie_file = os.getenv("YTDLP_COOKIE_FILE", "cookies.txt")
    if os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file

    if format_type == "mp3":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:  # mp4
        ydl_opts.update({
            "format": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "merge_output_format": "mp4",
        })

    return ydl_opts


def cleanup_temp_dir(temp_dir: str):
    """Remove temporary directory and all its contents."""
    shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/download")
async def download_video(req: DownloadRequest, background_tasks: BackgroundTasks):
    temp_dir = tempfile.mkdtemp(prefix="ytdlp_")
    try:
        ydl_opts = get_ydl_opts(temp_dir, req.format)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            filename = ydl.prepare_filename(info)

            # For MP3 post‑processing the extension changes
            if req.format == "mp3":
                filename = os.path.splitext(filename)[0] + ".mp3"

        if not os.path.exists(filename):
            raise HTTPException(status_code=500, detail="Downloaded file not found.")

        # Schedule cleanup after the response is sent
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
def read_root():
    return {
        "message": "Railway yt-dlp Downloader",
        "usage": "POST /download with JSON {url, format}",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
