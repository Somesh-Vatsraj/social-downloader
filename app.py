import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(
    title="Social Media Video Downloader API",
    version="1.0.0"
)


DOWNLOAD_DIR = Path("/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


class DownloadRequest(BaseModel):
    url: str
    quality: str = "best"


def run_yt_dlp(url: str, output: str):
    command = [
        "yt-dlp",

        # VIDEO ONLY / MP4
        "-f",
        "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",

        "--merge-output-format",
        "mp4",

        "--no-playlist",

        "--restrict-filenames",

        "-o",
        output,

        url
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return result


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "Social Media Video Downloader API",
        "version": "1.0.0"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.post("/api/download")
def download_video(data: DownloadRequest):

    if not data.url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="Invalid URL"
        )

    file_id = str(uuid.uuid4())

    output_template = str(
        DOWNLOAD_DIR / f"{file_id}.%(ext)s"
    )

    try:

        run_yt_dlp(
            data.url,
            output_template
        )

        files = list(
            DOWNLOAD_DIR.glob(f"{file_id}.*")
        )

        if not files:
            raise HTTPException(
                status_code=500,
                detail="Video download failed"
            )

        file_path = files[0]

        return FileResponse(
            path=str(file_path),
            filename="video.mp4",
            media_type="video/mp4"
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Download timeout"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
