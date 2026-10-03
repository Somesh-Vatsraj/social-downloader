from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import uuid

app = Flask(__name__)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "yt-dlp API is running"
    })


@app.route("/download", methods=["GET"])
def download():
    url = request.args.get("url")

    if not url:
        return jsonify({
            "status": "error",
            "message": "URL is required"
        }), 400

    file_id = str(uuid.uuid4())
    output = os.path.join(DOWNLOAD_DIR, file_id + ".%(ext)s")

    options = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": output,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            # yt-dlp may merge the file into MP4
            if not os.path.exists(filename):
                mp4_file = os.path.splitext(filename)[0] + ".mp4"
                if os.path.exists(mp4_file):
                    filename = mp4_file

        if not os.path.exists(filename):
            return jsonify({
                "status": "error",
                "message": "Downloaded file not found"
            }), 500

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
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
