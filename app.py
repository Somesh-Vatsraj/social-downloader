
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, request, render_template_string, send_file, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["30 per hour"],
    storage_uri="memory://",
)

PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#833ab4">
<title>InstaSave - Reel, Story & Photo Downloader</title>
<style>
*{box-sizing:border-box}
body{
  margin:0;min-height:100vh;font-family:Arial,sans-serif;
  color:#26202c;
  background:linear-gradient(135deg,#fff1f7,#f3eaff,#fff8e9);
}
header{text-align:center;padding:35px 15px 10px}
.logo{
  font-size:35px;font-weight:800;
  background:linear-gradient(45deg,#f58529,#dd2a7b,#8134af);
  color:transparent;background-clip:text;
}
header p{color:#68616c;margin-top:8px}
main{
  width:min(92%,520px);margin:22px auto 35px;padding:25px;
  background:#fff;border-radius:22px;
  box-shadow:0 12px 45px #5c326b15;
}
.tabs{display:flex;gap:8px;margin-bottom:22px}
.tab{
  flex:1;padding:12px 5px;border:1px solid #eee;
  border-radius:12px;background:white;font-weight:700;
  cursor:pointer;color:#5c5262
}
.tab.active{background:#833ab4;color:white;border-color:#833ab4}
h1{font-size:24px;text-align:center;margin:10px 0}
.desc{text-align:center;color:#777;font-size:14px;line-height:1.6}
input{
  width:100%;padding:15px;border:1px solid #ded8e2;
  border-radius:12px;font-size:15px;outline:none;margin:20px 0 12px
}
input:focus{border-color:#833ab4}
.submit{
  width:100%;padding:15px;border:0;border-radius:12px;
  background:linear-gradient(90deg,#833ab4,#dd2a7b);
  color:white;font-size:16px;font-weight:bold;cursor:pointer
}
.submit:disabled{opacity:.6;cursor:wait}
#status{margin-top:18px;text-align:center;line-height:1.6;font-size:14px}
.note{font-size:12px;color:#777;text-align:center;line-height:1.7;margin-top:22px}
footer{text-align:center;padding:0 15px 30px;font-size:12px;color:#777}
</style>
</head>
<body>
<header>
  <div class="logo">InstaSave</div>
  <p>Download public Instagram media</p>
</header>
<main>
  <div class="tabs">
    <button class="tab active" data-type="reel">▶ Reels</button>
    <button class="tab" data-type="story">◉ Story</button>
    <button class="tab" data-type="photo">▧ Photo</button>
  </div>
  <h1 id="heading">Reels Downloader</h1>
  <p class="desc" id="desc">Paste a public Instagram Reel link below.</p>
  <form id="form">
    <input id="url" type="url" placeholder="https://www.instagram.com/reel/..."
      aria-label="Instagram URL" required>
    <button class="submit" id="submit" type="submit">Get Download</button>
  </form>
  <div id="status" role="status"></div>
  <p class="note">
    Public content only. Download only media you own or have permission to save.
    Private content and login-required Stories are not supported.
  </p>
</main>
<footer>Use responsibly · Instagram is a third-party service</footer>
<script>
let type = "reel";
const details = {
  reel: ["Reels Downloader", "Paste a public Instagram Reel link below."],
  story: ["Story Downloader", "Paste a supported public Story link."],
  photo: ["Photo Downloader", "Paste a public Instagram photo or post link."]
};
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    type = btn.dataset.type;
    document.querySelectorAll(".tab").forEach(b =>
      b.classList.toggle("active", b === btn)
    );
    document.getElementById("heading").textContent = details[type][0];
    document.getElementById("desc").textContent = details[type][1];
    document.getElementById("status").textContent = "";
  });
});

document.getElementById("form").addEventListener("submit", async e => {
  e.preventDefault();
  const status = document.getElementById("status");
  const button = document.getElementById("submit");
  button.disabled = true;
  status.textContent = "Processing… Please wait.";
  try {
    const response = await fetch("/download", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        url: document.getElementById("url").value.trim(),
        type
      })
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "Download failed. Try another public link.");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match ? match[1] : "instagram-media";
    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
    status.textContent = "Download started.";
  } catch (err) {
    status.textContent = err.message;
  } finally {
    button.disabled = false;
  }
});
</script>
</body>
</html>
"""


def validate_instagram_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return False

    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and host in {
                "instagram.com",
                "www.instagram.com",
                "m.instagram.com",
            }
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


@app.get("/")
def home():
    return render_template_string(PAGE)


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/download")
@limiter.limit("5 per minute")
def download():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    media_type = data.get("type", "reel")

    if not validate_instagram_url(url):
        return jsonify(error="Enter a valid HTTPS Instagram URL."), 400

    if media_type not in {"reel", "story", "photo"}:
        return jsonify(error="Unsupported media type."), 400

    workdir = tempfile.mkdtemp(prefix="instasave_")
    output_dir = Path(workdir) / "media"
    output_dir.mkdir()
    result_path = None

    try:
        if media_type == "reel":
            options = {
                "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
                "format": "best[filesize<100M]/best",
                "noplaylist": True,
                "restrictfilenames": True,
                "max_filesize": 100 * 1024 * 1024,
                "socket_timeout": 20,
                "retries": 1,
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([url])
        else:
            # gallery-dl supports many public Instagram photo/post URLs.
            # Public Stories may still require authentication or may be
            # unavailable; this app does not bypass private access controls.
            subprocess.run(
                [
                    "gallery-dl",
                    "--no-mtime",
                    "-D", str(output_dir),
                    url,
                ],
                check=True,
                timeout=75,
                capture_output=True,
                text=True,
            )

        files = [
            p for p in output_dir.rglob("*")
            if p.is_file() and p.stat().st_size > 0
        ]

        if not files:
            raise RuntimeError(
                "No downloadable media found. The post may be private, "
                "unsupported, or require Instagram login."
            )

        if len(files) == 1:
            result_path = files[0]
            download_name = re.sub(
                r"[^A-Za-z0-9._-]", "_", result_path.name
            )
        else:
            result_path = Path(workdir) / "instagram_media.zip"
            with zipfile.ZipFile(
                result_path, "w", zipfile.ZIP_DEFLATED
            ) as archive:
                for file in files:
                    archive.write(file, arcname=file.name)
            download_name = "instagram_media.zip"

        response = send_file(
            result_path,
            as_attachment=True,
            download_name=download_name,
        )
        response.call_on_close(lambda: shutil.rmtree(workdir, ignore_errors=True))
        return response

    except subprocess.TimeoutExpired:
        shutil.rmtree(workdir, ignore_errors=True)
        return jsonify(error="Download timed out. Please try again."), 504
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        return jsonify(
            error=(
                "Could not download this media. Check the public link "
                "and try again. Some Instagram links are unsupported."
            )
        ), 422


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
