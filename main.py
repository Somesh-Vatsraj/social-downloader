import os
import uuid
import glob
from flask import Flask, request, jsonify, send_file
import yt_dlp

app = Flask(__name__)

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def get_cookie_file():
    path = os.environ.get("YTDLP_COOKIE_FILE", "").strip()

    if path and os.path.isfile(path):
        return path

    return None


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "success",
        "service": "yt-dlp API",
        "cookie_file": bool(get_cookie_file())
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy"
    })


@app.route("/info", methods=["GET"])
def info():
    url = request.args.get("url", "").strip()

    if not url:
        return jsonify({
            "status": "error",
            "message": "URL is required"
        }), 400

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True
    }

    cookie_file = get_cookie_file()

    if cookie_file:
        options["cookiefile"] = cookie_file

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=False)

        return jsonify({
            "status": "success",
            "id": data.get("id"),
            "title": data.get("title"),
            "uploader": data.get("uploader"),
            "duration": data.get("duration"),
            "thumbnail": data.get("thumbnail"),
            "webpage_url": data.get("webpage_url")
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route("/download", methods=["GET"])
def download():
    url = request.args.get("url", "").strip()

    if not url:
        return jsonify({
            "status": "error",
            "message": "URL is required"
        }), 400

    file_id = str(uuid.uuid4())

    output_template = os.path.join(
        DOWNLOAD_DIR,
        file_id + ".%(ext)s"
    )

    options = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True
    }

    cookie_file = get_cookie_file()

    if cookie_file:
        options["cookiefile"] = cookie_file

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        files = glob.glob(
            os.path.join(DOWNLOAD_DIR, file_id + ".*")
        )

        files = [
            f for f in files
            if not f.endswith((".part", ".ytdl"))
        ]

        if not files:
            return jsonify({
                "status": "error",
                "message": "Downloaded file was not found"
            }), 500

        filename = files[0]

        return send_file(
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename)
        )

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))

    app.run(
        host="0.0.0.0",
        port=port
    )
