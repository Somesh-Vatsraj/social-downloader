from flask import Flask, request, jsonify
from pytubefix import YouTube
import re
import os
import traceback

app = Flask(__name__)


# =========================================================
# Extract YouTube Video ID
# =========================================================

def extract_video_id(url):

    if not url:
        return None

    patterns = [
        r"(?:youtube\.com/watch\?v=)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/watch\?.*v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    ]

    for pattern in patterns:

        match = re.search(pattern, url)

        if match:
            return match.group(1)

    return None


# =========================================================
# Stream -> JSON
# =========================================================

def stream_to_json(stream):

    try:
        filesize = stream.filesize
    except Exception:
        filesize = None

    try:
        mime_type = stream.mime_type
    except Exception:
        mime_type = None

    try:
        resolution = stream.resolution
    except Exception:
        resolution = None

    try:
        fps = stream.fps
    except Exception:
        fps = None

    try:
        abr = stream.abr
    except Exception:
        abr = None

    try:
        bitrate = stream.bitrate
    except Exception:
        bitrate = None

    try:
        has_video = stream.includes_video_track
    except Exception:
        has_video = None

    try:
        has_audio = stream.includes_audio_track
    except Exception:
        has_audio = None

    try:
        stream_url = stream.url
    except Exception:
        stream_url = None

    return {
        "itag": stream.itag,
        "mimeType": mime_type,
        "extension": stream.subtype,
        "quality": resolution,
        "fps": fps,
        "abr": abr,
        "bitrate": bitrate,
        "hasVideo": has_video,
        "hasAudio": has_audio,
        "filesize": filesize,
        "filesizeMB": (
            round(filesize / 1024 / 1024, 2)
            if filesize
            else None
        ),
        "url": stream_url
    }


# =========================================================
# Home
# =========================================================

@app.route("/")
def home():

    return jsonify({
        "success": True,
        "service": "YouTube Debug API",
        "status": "online",
        "version": "debug-1.0",
        "endpoints": [
            "/health",
            "/info",
            "/api/info",
            "/debug"
        ]
    })


# =========================================================
# Health
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "success": True,
        "status": "healthy"
    })


# =========================================================
# DEBUG ENDPOINT
# =========================================================

@app.route("/debug")
def debug():

    return jsonify({

        "success": True,

        "python": os.sys.version,

        "pytubefix": get_package_version("pytubefix"),

        "flask": get_package_version("flask"),

        "environment": {
            "port": os.environ.get("PORT"),
            "render": os.environ.get("RENDER"),
            "service_name": os.environ.get(
                "RENDER_SERVICE_NAME"
            )
        }

    })


# =========================================================
# Package Version
# =========================================================

def get_package_version(package_name):

    try:

        from importlib.metadata import version

        return version(package_name)

    except Exception:

        return "unknown"


# =========================================================
# Main YouTube Function
# =========================================================

def process_youtube():

    # -----------------------------------------------------
    # Get URL
    # -----------------------------------------------------

    if request.method == "GET":

        url = request.args.get("url")

    else:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({

                "success": False,

                "error": "JSON body required"

            }), 400

        url = data.get("url")

    # -----------------------------------------------------
    # URL validation
    # -----------------------------------------------------

    if not url:

        return jsonify({

            "success": False,

            "error": "YouTube URL is required"

        }), 400

    # -----------------------------------------------------
    # Video ID
    # -----------------------------------------------------

    video_id = extract_video_id(url)

    if not video_id:

        return jsonify({

            "success": False,

            "error": "Invalid YouTube URL",

            "url": url

        }), 400

    # -----------------------------------------------------
    # Debug information
    # -----------------------------------------------------

    debug_info = {

        "videoId": video_id,

        "pytubefix": get_package_version(
            "pytubefix"
        ),

        "python": os.sys.version

    }

    # -----------------------------------------------------
    # Create YouTube object
    # -----------------------------------------------------

    try:

        yt = YouTube(url)

    except Exception as e:

        return jsonify({

            "success": False,

            "stage": "YouTube object creation",

            "error": str(e),

            "errorType": type(e).__name__,

            "debug": debug_info

        }), 500

    # =====================================================
    # BASIC INFORMATION
    # =====================================================

    video = {

        "title": None,

        "author": None,

        "channelId": None,

        "description": None,

        "length": None,

        "views": None,

        "publishDate": None,

        "thumbnail": None

    }

    # -----------------------------------------------------
    # Title
    # -----------------------------------------------------

    try:
        video["title"] = yt.title
    except Exception as e:
        debug_info["titleError"] = str(e)

    # -----------------------------------------------------
    # Author
    # -----------------------------------------------------

    try:
        video["author"] = yt.author
    except Exception as e:
        debug_info["authorError"] = str(e)

    # -----------------------------------------------------
    # Channel
    # -----------------------------------------------------

    try:
        video["channelId"] = yt.channel_id
    except Exception as e:
        debug_info["channelError"] = str(e)

    # -----------------------------------------------------
    # Description
    # -----------------------------------------------------

    try:
        video["description"] = yt.description
    except Exception as e:
        debug_info["descriptionError"] = str(e)

    # -----------------------------------------------------
    # Length
    # -----------------------------------------------------

    try:
        video["length"] = yt.length
    except Exception as e:
        debug_info["lengthError"] = str(e)

    # -----------------------------------------------------
    # Views
    # -----------------------------------------------------

    try:
        video["views"] = yt.views
    except Exception as e:
        debug_info["viewsError"] = str(e)

    # -----------------------------------------------------
    # Publish Date
    # -----------------------------------------------------

    try:

        if yt.publish_date:

            video["publishDate"] = str(
                yt.publish_date
            )

    except Exception as e:

        debug_info["publishDateError"] = str(e)

    # -----------------------------------------------------
    # Thumbnail
    # -----------------------------------------------------

    try:
        video["thumbnail"] = yt.thumbnail_url
    except Exception as e:
        debug_info["thumbnailError"] = str(e)

    # =====================================================
    # STREAMS
    # =====================================================

    formats = []

    adaptive_formats = []

    stream_error = None

    # -----------------------------------------------------
    # Get stream object
    # -----------------------------------------------------

    try:

        streams = yt.streams

        debug_info["streamsObject"] = str(
            type(streams)
        )

    except Exception as e:

        stream_error = str(e)

        debug_info["streamsError"] = str(e)

        return jsonify({

            "success": False,

            "videoId": video_id,

            "video": video,

            "formats": [],

            "adaptiveFormats": [],

            "debug": debug_info,

            "error": str(e),

            "errorType": type(e).__name__

        }), 500

    # =====================================================
    # ALL STREAMS DEBUG
    # =====================================================

    try:

        all_streams = list(
            yt.streams
        )

        debug_info["allStreamsCount"] = len(
            all_streams
        )

        debug_info["allStreamItags"] = [
            s.itag
            for s in all_streams
        ]

    except Exception as e:

        debug_info["allStreamsError"] = str(e)

    # =====================================================
    # PROGRESSIVE
    # =====================================================

    try:

        progressive_streams = (
            yt.streams.filter(
                progressive=True
            )
        )

        debug_info["progressiveCount"] = len(
            progressive_streams
        )

        for stream in progressive_streams:

            try:

                formats.append(
                    stream_to_json(stream)
                )

            except Exception as e:

                debug_info.setdefault(
                    "streamConversionErrors",
                    []
                ).append(str(e))

    except Exception as e:

        debug_info["progressiveError"] = str(e)

    # =====================================================
    # ADAPTIVE
    # =====================================================

    try:

        adaptive_streams = (
            yt.streams.filter(
                adaptive=True
            )
        )

        debug_info["adaptiveCount"] = len(
            adaptive_streams
        )

        for stream in adaptive_streams:

            try:

                adaptive_formats.append(
                    stream_to_json(stream)
                )

            except Exception as e:

                debug_info.setdefault(
                    "adaptiveConversionErrors",
                    []
                ).append(str(e))

    except Exception as e:

        debug_info["adaptiveError"] = str(e)

    # =====================================================
    # FINAL RESPONSE
    # =====================================================

    response = {

        "success": True,

        "videoId": video_id,

        "url": url,

        "video": video,

        "formats": formats,

        "adaptiveFormats": adaptive_formats,

        "totalFormats": len(formats),

        "totalAdaptiveFormats": len(
            adaptive_formats
        ),

        "debug": debug_info

    }

    # =====================================================
    # IMPORTANT WARNING
    # =====================================================

    if (
        len(formats) == 0
        and len(adaptive_formats) == 0
    ):

        response["warning"] = (
            "YouTube metadata was available, "
            "but no stream formats were returned "
            "by pytubefix."
        )

    return jsonify(response)


# =========================================================
# /info
# =========================================================

@app.route(
    "/info",
    methods=["GET", "POST"]
)
def info():

    return process_youtube()


# =========================================================
# /api/info
# =========================================================

@app.route(
    "/api/info",
    methods=["GET", "POST"]
)
def api_info():

    return process_youtube()


# =========================================================
# 404
# =========================================================

@app.errorhandler(404)
def not_found(error):

    return jsonify({

        "success": False,

        "error": "Endpoint not found",

        "availableEndpoints": [
            "/",
            "/health",
            "/debug",
            "/info",
            "/api/info"
        ]

    }), 404


# =========================================================
# 405
# =========================================================

@app.errorhandler(405)
def method_not_allowed(error):

    return jsonify({

        "success": False,

        "error": "Method not allowed"

    }), 405


# =========================================================
# 500
# =========================================================

@app.errorhandler(500)
def internal_error(error):

    return jsonify({

        "success": False,

        "error": "Internal server error"

    }), 500


# =========================================================
# Start
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )