from flask import Flask, request, jsonify
from pytubefix import YouTube
import re
import os

app = Flask(__name__)


def extract_video_id(url):
    patterns = [
        r"(?:youtube\.com/watch\?v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def stream_to_json(stream):
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
        "filesize": stream.filesize,
        "filesizeMB": (
            round(stream.filesize / 1024 / 1024, 2)
            if stream.filesize
            else None
        ),
        "url": stream.url
    }


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "success": True,
        "service": "YouTube API",
        "status": "online",
        "endpoint": "/api/info"
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "status": "healthy"
    })


@app.route("/api/info", methods=["GET", "POST"])
def api_info():

    try:

        # -----------------------------
        # GET request
        # -----------------------------
        if request.method == "GET":
            url = request.args.get("url")

        # -----------------------------
        # POST request
        # -----------------------------
        else:
            data = request.get_json(silent=True)

            if not data:
                return jsonify({
                    "success": False,
                    "error": "JSON body required"
                }), 400

            url = data.get("url")

        # -----------------------------
        # Validate URL
        # -----------------------------
        if not url:
            return jsonify({
                "success": False,
                "error": "YouTube URL is required"
            }), 400

        video_id = extract_video_id(url)

        if not video_id:
            return jsonify({
                "success": False,
                "error": "Invalid YouTube URL"
            }), 400

        # -----------------------------
        # YouTube
        # -----------------------------
        yt = YouTube(url)

        # -----------------------------
        # Progressive streams
        # Video + Audio
        # -----------------------------
        progressive = []

        for stream in yt.streams.filter(progressive=True):
            progressive.append(
                stream_to_json(stream)
            )

        # -----------------------------
        # Adaptive streams
        # Video OR Audio
        # -----------------------------
        adaptive = []

        for stream in yt.streams.filter(adaptive=True):
            adaptive.append(
                stream_to_json(stream)
            )

        # -----------------------------
        # Response
        # -----------------------------
        return jsonify({
            "success": True,
            "videoId": video_id,

            "video": {
                "title": yt.title,
                "author": yt.author,
                "channelId": yt.channel_id,
                "description": yt.description,
                "length": yt.length,
                "views": yt.views,
                "publishDate": str(yt.publish_date)
                    if yt.publish_date else None,
                "thumbnail": yt.thumbnail_url
            },

            "formats": progressive,
            "adaptiveFormats": adaptive,

            "totalFormats": len(progressive),
            "totalAdaptiveFormats": len(adaptive)
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ------------------------------------
# Error handlers
# ------------------------------------

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Endpoint not found"
    }), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        "success": False,
        "error": "Method not allowed"
    }), 405


@app.errorhandler(500)
def server_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error"
    }), 500


# ------------------------------------
# Run
# ------------------------------------

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )