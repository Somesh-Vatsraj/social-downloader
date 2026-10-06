from flask import Flask, request, jsonify
from pytubefix import YouTube
import re
import os

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
# Convert Stream Object to JSON
# =========================================================

def stream_to_json(stream):

    filesize = None

    try:
        filesize = stream.filesize
    except Exception:
        filesize = None

    return {
        "itag": stream.itag,
        "mimeType": stream.mime_type,
        "extension": stream.subtype,
        "quality": stream.resolution,
        "fps": stream.fps,
        "abr": stream.abr,
        "bitrate": stream.bitrate,
        "hasVideo": stream.includes_video_track,
        "hasAudio": stream.includes_audio_track,

        "filesize": filesize,

        "filesizeMB": (
            round(filesize / 1024 / 1024, 2)
            if filesize
            else None
        ),

        "url": stream.url
    }


# =========================================================
# Home
# =========================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "success": True,
        "service": "YouTube Downloader API",
        "status": "online",
        "endpoints": {
            "info": "/info?url=YOUTUBE_URL",
            "api_info": "/api/info?url=YOUTUBE_URL",
            "health": "/health"
        }
    })


# =========================================================
# Health Check
# =========================================================

@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "success": True,
        "status": "healthy"
    })


# =========================================================
# Main YouTube Info Function
# =========================================================

def get_youtube_info():

    # -----------------------------------------------------
    # GET
    # -----------------------------------------------------

    if request.method == "GET":

        url = request.args.get("url")

    # -----------------------------------------------------
    # POST
    # -----------------------------------------------------

    else:

        data = request.get_json(silent=True)

        if not data:

            return jsonify({
                "success": False,
                "error": "JSON body required"
            }), 400

        url = data.get("url")

    # -----------------------------------------------------
    # URL check
    # -----------------------------------------------------

    if not url:

        return jsonify({
            "success": False,
            "error": "YouTube URL is required"
        }), 400

    # -----------------------------------------------------
    # Extract video ID
    # -----------------------------------------------------

    video_id = extract_video_id(url)

    if not video_id:

        return jsonify({
            "success": False,
            "error": "Invalid YouTube URL",
            "received_url": url
        }), 400

    # -----------------------------------------------------
    # YouTube
    # -----------------------------------------------------

    try:

        yt = YouTube(url)

        # -------------------------------------------------
        # Progressive streams
        # Video + Audio
        # -------------------------------------------------

        formats = []

        try:

            progressive_streams = yt.streams.filter(
                progressive=True
            )

            for stream in progressive_streams:

                try:

                    formats.append(
                        stream_to_json(stream)
                    )

                except Exception:
                    continue

        except Exception:
            pass

        # -------------------------------------------------
        # Adaptive streams
        # Video / Audio separately
        # -------------------------------------------------

        adaptive_formats = []

        try:

            adaptive_streams = yt.streams.filter(
                adaptive=True
            )

            for stream in adaptive_streams:

                try:

                    adaptive_formats.append(
                        stream_to_json(stream)
                    )

                except Exception:
                    continue

        except Exception:
            pass

        # -------------------------------------------------
        # Video information
        # -------------------------------------------------

        try:
            title = yt.title
        except Exception:
            title = None

        try:
            author = yt.author
        except Exception:
            author = None

        try:
            channel_id = yt.channel_id
        except Exception:
            channel_id = None

        try:
            description = yt.description
        except Exception:
            description = None

        try:
            length = yt.length
        except Exception:
            length = None

        try:
            views = yt.views
        except Exception:
            views = None

        try:
            thumbnail = yt.thumbnail_url
        except Exception:
            thumbnail = None

        try:
            publish_date = (
                str(yt.publish_date)
                if yt.publish_date
                else None
            )
        except Exception:
            publish_date = None

        # -------------------------------------------------
        # Response
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "videoId": video_id,

            "url": url,

            "video": {

                "title": title,

                "author": author,

                "channelId": channel_id,

                "description": description,

                "length": length,

                "views": views,

                "publishDate": publish_date,

                "thumbnail": thumbnail
            },

            "formats": formats,

            "adaptiveFormats": adaptive_formats,

            "totalFormats": len(formats),

            "totalAdaptiveFormats": len(
                adaptive_formats
            )
        })

    except Exception as e:

        return jsonify({

            "success": False,

            "videoId": video_id,

            "error": str(e)

        }), 500


# =========================================================
# /info
# =========================================================

@app.route(
    "/info",
    methods=["GET", "POST"]
)
def info():

    return get_youtube_info()


# =========================================================
# /api/info
# =========================================================

@app.route(
    "/api/info",
    methods=["GET", "POST"]
)
def api_info():

    return get_youtube_info()


# =========================================================
# 404
# =========================================================

@app.errorhandler(404)
def not_found(error):

    return jsonify({

        "success": False,

        "error": "Endpoint not found",

        "available_endpoints": [
            "/",
            "/health",
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
def server_error(error):

    return jsonify({

        "success": False,

        "error": "Internal server error"

    }), 500


# =========================================================
# Start Server
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