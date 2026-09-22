from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import yt_dlp

import tempfile
import shutil
import os
import re
import uuid
import subprocess
import urllib.request
import urllib.error

from pathlib import Path


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Vatsraj Tech YouTube Downloader API",
    description="YouTube downloader API using FastAPI + yt-dlp + BgUtils",
    version="2.1.0"
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# DIRECTORIES
# =========================================================

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "vatsraj_ytdlp"

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# =========================================================
# CONSTANTS
# =========================================================

BGUTIL_URL = "http://127.0.0.1:4416"


# =========================================================
# YT-DLP BASE OPTIONS
# =========================================================

BASE_OPTIONS = {

    # General
    "quiet": True,
    "no_warnings": False,

    # One video only
    "noplaylist": True,

    # Extraction only
    "skip_download": True,

    # -----------------------------------------------------
    # EJS / DENO
    # -----------------------------------------------------

    "js_runtimes": {
        "deno": {}
    },

    "remote_components": {
        "ejs": ["github"]
    },

    # -----------------------------------------------------
    # YOUTUBE
    # -----------------------------------------------------

    "extractor_args": {

        "youtube": {
            "player_client": ["mweb"]
        },

        # -------------------------------------------------
        # BGUTIL PO TOKEN PROVIDER
        # -------------------------------------------------

        "youtubepot-bgutilhttp": {
            "base_url": BGUTIL_URL
        }
    }
}


# =========================================================
# HELPERS
# =========================================================

def is_youtube_url(url: str) -> bool:

    if not url:
        return False

    url = url.lower()

    return (
        "youtube.com" in url
        or "youtu.be" in url
    )


def clean_filename(value: str) -> str:

    if not value:
        return "youtube_video"

    value = str(value)

    value = re.sub(
        r'[\\/*?:"<>|]',
        "",
        value
    )

    value = value.strip()

    if not value:
        return "youtube_video"

    return value[:150]


def iso_duration(seconds):

    if seconds is None:
        return None

    try:
        seconds = int(seconds)
    except Exception:
        return None

    hours = seconds // 3600

    minutes = (
        seconds % 3600
    ) // 60

    secs = seconds % 60

    if hours:

        return (
            f"PT{hours}H"
            f"{minutes}M"
            f"{secs}S"
        )

    if minutes:

        return (
            f"PT{minutes}M"
            f"{secs}S"
        )

    return f"PT{secs}S"


def format_quality(fmt):

    height = fmt.get("height")

    if height:
        return f"{height}p"

    abr = fmt.get("abr")

    if abr:

        try:
            return f"{int(abr)}kbps"
        except Exception:
            return f"{abr}kbps"

    return "unknown"


def extract_formats(info):

    output = []

    formats = info.get(
        "formats",
        []
    )

    for fmt in formats:

        format_id = fmt.get(
            "format_id"
        )

        if not format_id:
            continue

        vcodec = fmt.get(
            "vcodec"
        )

        acodec = fmt.get(
            "acodec"
        )

        has_video = (
            vcodec not in
            [None, "none"]
        )

        has_audio = (
            acodec not in
            [None, "none"]
        )

        if not has_video and not has_audio:
            continue

        width = fmt.get(
            "width"
        ) or 0

        height = fmt.get(
            "height"
        ) or 0

        filesize = (
            fmt.get("filesize")
            or
            fmt.get("filesize_approx")
            or
            0
        )

        output.append({

            "format_id":
                format_id,

            "ext":
                fmt.get("ext"),

            "resolution":
                (
                    f"{width}x{height}"
                    if width and height
                    else None
                ),

            "width":
                width,

            "height":
                height,

            "quality":
                format_quality(fmt),

            "fps":
                fmt.get("fps"),

            "filesize":
                filesize,

            "filesize_mb":
                (
                    round(
                        filesize /
                        1024 /
                        1024,
                        2
                    )
                    if filesize
                    else None
                ),

            "has_video":
                has_video,

            "has_audio":
                has_audio,

            "vcodec":
                vcodec,

            "acodec":
                acodec,

            "video_bitrate":
                fmt.get("vbr"),

            "audio_bitrate":
                fmt.get("abr"),

            "container":
                fmt.get("ext"),

            "url":
                fmt.get("url")
        })

    return output


# =========================================================
# GET VIDEO INFO
# =========================================================

def get_video_info(url):

    options = BASE_OPTIONS.copy()

    with yt_dlp.YoutubeDL(
        options
    ) as ydl:

        return ydl.extract_info(
            url,
            download=False
        )


# =========================================================
# BUILD JSON
# =========================================================

def build_json(info):

    thumbnail = info.get(
        "thumbnail"
    )

    duration = info.get(
        "duration"
    )

    media = []

    # -----------------------------------------------------
    # VIDEO
    # -----------------------------------------------------

    media.append({

        "type":
            "video",

        "id":
            "main_video",

        "url":
            info.get("url"),

        "width":
            info.get("width") or 0,

        "height":
            info.get("height") or 0,

        "container":
            (
                f"video/{info.get('ext')}"
                if info.get("ext")
                else None
            ),

        "has_audio":
            True,

        "has_video":
            True,

        "has_photo":
            False,

        "quality":
            (
                f"{info.get('height')}p"
                if info.get("height")
                else "unknown"
            ),

        "duration":
            iso_duration(duration)
    })

    # -----------------------------------------------------
    # THUMBNAIL
    # -----------------------------------------------------

    if thumbnail:

        media.append({

            "type":
                "photo",

            "id":
                "thumbnail",

            "url":
                thumbnail,

            "width":
                0,

            "height":
                0,

            "container":
                "image/jpeg",

            "has_audio":
                False,

            "has_video":
                False,

            "has_photo":
                True,

            "quality":
                "HD Full"
        })

    return {

        "success":
            True,

        "type":
            "video",

        "platform":
            "youtube",

        "id":
            info.get("id"),

        "username":
            (
                info.get("uploader_id")
                or
                info.get("channel_id")
                or
                info.get("uploader")
            ),

        "channel":
            info.get("channel"),

        "profile_image_uri":
            None,

        "title":
            info.get("title"),

        "caption":
            (
                info.get("description")
                or
                info.get("title")
                or
                ""
            ),

        "description":
            info.get("description"),

        "thumbnail":
            thumbnail,

        "duration":
            duration,

        "duration_iso":
            iso_duration(duration),

        "upload_date":
            info.get("upload_date"),

        "view_count":
            info.get("view_count"),

        "like_count":
            info.get("like_count"),

        "webpage_url":
            info.get("webpage_url"),

        "media":
            media,

        "formats":
            extract_formats(info)
    }


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():

    return {

        "success":
            True,

        "name":
            "Vatsraj Tech YouTube Downloader",

        "version":
            "2.1.0",

        "status":
            "online",

        "yt_dlp":
            yt_dlp.version.__version__,

        "endpoints": {

            "extract":
                "/api/extract?url=YOUTUBE_URL",

            "formats":
                "/api/formats?url=YOUTUBE_URL",

            "download":
                "/api/download?url=YOUTUBE_URL",

            "test":
                "/api/test-youtube?url=YOUTUBE_URL",

            "health":
                "/health",

            "debug":
                "/api/debug",

            "docs":
                "/docs"
        }
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {

        "success":
            True,

        "status":
            "healthy",

        "yt_dlp":
            yt_dlp.version.__version__
    }


# =========================================================
# DEBUG
# =========================================================

@app.get("/api/debug")
def debug():

    deno_version = None
    deno_error = None

    try:

        result = subprocess.run(
            ["deno", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )

        deno_version = result.stdout.strip()

        if result.returncode != 0:
            deno_error = result.stderr.strip()

    except Exception as error:

        deno_error = str(error)


    # -----------------------------------------------------
    # BGUTIL CONNECTIVITY
    # -----------------------------------------------------

    bgutil_status = "unknown"
    bgutil_error = None

    try:

        response = urllib.request.urlopen(
            BGUTIL_URL,
            timeout=5
        )

        bgutil_status = (
            f"reachable ({response.status})"
        )

    except urllib.error.HTTPError as error:

        bgutil_status = (
            f"reachable ({error.code})"
        )

    except Exception as error:

        bgutil_status = "not_reachable"
        bgutil_error = str(error)


    return {

        "success":
            True,

        "yt_dlp":
            yt_dlp.version.__version__,

        "deno":
            {
                "available":
                    deno_version is not None,

                "version":
                    deno_version,

                "error":
                    deno_error
            },

        "bgutil":
            {
                "url":
                    BGUTIL_URL,

                "status":
                    bgutil_status,

                "error":
                    bgutil_error
            },

        "js_runtime":
            "deno",

        "ejs":
            "github",

        "youtube_client":
            "mweb"
    }


# =========================================================
# YOUTUBE DIAGNOSTIC TEST
# =========================================================

@app.get("/api/test-youtube")
def test_youtube(
    url: str = Query(
        "https://www.youtube.com/watch?v=jn6J5By5hRI",
        description="YouTube URL for diagnostic test"
    )
):

    result = {

        "success":
            False,

        "url":
            url,

        "checks":
            {}
    }


    # -----------------------------------------------------
    # CHECK 1 - URL
    # -----------------------------------------------------

    if not is_youtube_url(url):

        result["checks"]["url"] = {

            "passed":
                False,

            "message":
                "URL is not a valid YouTube URL."
        }

        return result


    result["checks"]["url"] = {

        "passed":
            True,

        "message":
            "YouTube URL detected."
    }


    # -----------------------------------------------------
    # CHECK 2 - DENO
    # -----------------------------------------------------

    try:

        deno = subprocess.run(
            ["deno", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if deno.returncode == 0:

            result["checks"]["deno"] = {

                "passed":
                    True,

                "version":
                    deno.stdout.strip()
            }

        else:

            result["checks"]["deno"] = {

                "passed":
                    False,

                "error":
                    deno.stderr.strip()
            }

    except Exception as error:

        result["checks"]["deno"] = {

            "passed":
                False,

            "error":
                str(error)
        }


    # -----------------------------------------------------
    # CHECK 3 - BGUTIL
    # -----------------------------------------------------

    try:

        response = urllib.request.urlopen(
            BGUTIL_URL,
            timeout=5
        )

        result["checks"]["bgutil"] = {

            "passed":
                True,

            "status":
                response.status,

            "message":
                "BgUtils HTTP server is reachable."
        }

    except urllib.error.HTTPError as error:

        # HTTP 404/405 still proves server is alive.
        result["checks"]["bgutil"] = {

            "passed":
                True,

            "status":
                error.code,

            "message":
                "BgUtils server is reachable."
        }

    except Exception as error:

        result["checks"]["bgutil"] = {

            "passed":
                False,

            "error":
                str(error)
        }


    # -----------------------------------------------------
    # CHECK 4 - YT-DLP EXTRACTION
    # -----------------------------------------------------

    try:

        options = BASE_OPTIONS.copy()

        options["quiet"] = False

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=False
            )


        result["checks"]["youtube"] = {

            "passed":
                True,

            "id":
                info.get("id"),

            "title":
                info.get("title"),

            "duration":
                info.get("duration"),

            "formats":
                len(
                    info.get(
                        "formats",
                        []
                    )
                )
        }

        result["success"] = True

        result["message"] = (
            "YouTube extraction is working."
        )

    except Exception as error:

        error_text = str(error)

        result["checks"]["youtube"] = {

            "passed":
                False,

            "error":
                error_text
        }

        # -------------------------------------------------
        # ERROR CLASSIFICATION
        # -------------------------------------------------

        if (
            "Sign in to confirm" in error_text
            or
            "not a bot" in error_text
            or
            "LOGIN_REQUIRED" in error_text
        ):

            result["message"] = (
                "YouTube is rejecting this server request "
                "with an authentication/bot check."
            )

        elif (
            "PO Token" in error_text
            or
            "pot" in error_text.lower()
        ):

            result["message"] = (
                "The request appears to have a PO-token/provider issue."
            )

        elif (
            "deno" in error_text.lower()
            or
            "javascript" in error_text.lower()
            or
            "ejs" in error_text.lower()
        ):

            result["message"] = (
                "The YouTube JavaScript/EJS runtime setup "
                "appears to have a problem."
            )

        else:

            result["message"] = (
                "yt-dlp extraction failed. "
                "See checks.youtube.error."
            )


    return result


# =========================================================
# EXTRACT
# =========================================================

@app.get("/api/extract")
def extract(
    url: str = Query(
        ...,
        description="YouTube URL"
    )
):

    if not is_youtube_url(url):

        raise HTTPException(
            status_code=400,
            detail="Please provide a valid YouTube URL."
        )

    try:

        info = get_video_info(
            url
        )

        return build_json(
            info
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# =========================================================
# FORMATS
# =========================================================

@app.get("/api/formats")
def formats(
    url: str = Query(
        ...,
        description="YouTube URL"
    )
):

    if not is_youtube_url(url):

        raise HTTPException(
            status_code=400,
            detail="Please provide a valid YouTube URL."
        )

    try:

        info = get_video_info(
            url
        )

        return {

            "success":
                True,

            "id":
                info.get("id"),

            "title":
                info.get("title"),

            "thumbnail":
                info.get("thumbnail"),

            "formats":
                extract_formats(info)
        }

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# =========================================================
# DOWNLOAD
# =========================================================

@app.get("/api/download")
def download(
    url: str = Query(
        ...,
        description="YouTube URL"
    ),

    format_id: str = Query(
        "bestvideo+bestaudio/best",
        description="yt-dlp format"
    )
):

    if not is_youtube_url(url):

        raise HTTPException(
            status_code=400,
            detail="Please provide a valid YouTube URL."
        )


    # -----------------------------------------------------
    # JOB FOLDER
    # -----------------------------------------------------

    job_id = uuid.uuid4().hex

    job_dir = (
        DOWNLOAD_DIR /
        job_id
    )

    job_dir.mkdir(
        parents=True,
        exist_ok=True
    )


    output_template = str(
        job_dir /
        "%(title)s.%(ext)s"
    )


    # -----------------------------------------------------
    # DOWNLOAD OPTIONS
    # -----------------------------------------------------

    options = {

        "quiet":
            True,

        "no_warnings":
            False,

        "noplaylist":
            True,

        "format":
            format_id,

        "outtmpl":
            output_template,

        "merge_output_format":
            "mp4",

        # EJS
        "js_runtimes": {
            "deno": {}
        },

        "remote_components": {
            "ejs": ["github"]
        },

        # YouTube
        "extractor_args": {

            "youtube": {
                "player_client":
                    ["mweb"]
            },

            # BgUtils
            "youtubepot-bgutilhttp": {
                "base_url":
                    BGUTIL_URL
            }
        }
    }


    try:

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )


            # -------------------------------------------------
            # FIND DOWNLOADED FILE
            # -------------------------------------------------

            downloaded_file = None

            requested_downloads = (
                info.get(
                    "requested_downloads"
                )
            )

            if requested_downloads:

                for item in requested_downloads:

                    filepath = item.get(
                        "filepath"
                    )

                    if (
                        filepath
                        and
                        os.path.exists(filepath)
                    ):

                        downloaded_file = filepath

                        break


            # -------------------------------------------------
            # FALLBACK
            # -------------------------------------------------

            if not downloaded_file:

                prepared = (
                    ydl.prepare_filename(
                        info
                    )
                )

                if os.path.exists(
                    prepared
                ):

                    downloaded_file = (
                        prepared
                    )


            # -------------------------------------------------
            # SEARCH FOLDER
            # -------------------------------------------------

            if not downloaded_file:

                files = list(
                    job_dir.iterdir()
                )

                if files:

                    downloaded_file = str(
                        files[0]
                    )


            if not downloaded_file:

                raise Exception(
                    "Downloaded file was not found."
                )


        file_path = Path(
            downloaded_file
        )


        if not file_path.exists():

            raise Exception(
                "Downloaded file does not exist."
            )


        # -----------------------------------------------------
        # FILENAME
        # -----------------------------------------------------

        filename = clean_filename(
            file_path.stem
        )

        extension = (
            file_path.suffix
        )

        download_name = (
            filename +
            extension
        )


        # -----------------------------------------------------
        # STREAM FILE
        # -----------------------------------------------------

        def stream_file():

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

                shutil.rmtree(
                    job_dir,
                    ignore_errors=True
                )


        return StreamingResponse(

            stream_file(),

            media_type=(
                "video/mp4"
                if extension.lower() == ".mp4"
                else "application/octet-stream"
            ),

            headers={

                "Content-Disposition":
                    (
                        f'attachment; '
                        f'filename="{download_name}"'
                    )
            }
        )


    except Exception as error:

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
