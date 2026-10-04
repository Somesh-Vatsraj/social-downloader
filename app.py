import os
import re
import json
import uuid
import asyncio
import subprocess
import requests
from flask import Flask, request, render_template_string, send_from_directory

from deep_translator import GoogleTranslator
from faster_whisper import WhisperModel
import edge_tts

app = Flask(__name__)

# ---------------- CONFIG (Render Environment Variables) ----------------
KUAISHOU_COOKIE = os.environ.get("KUAISHOU_COOKIE", "").strip()
KUAISHOU_KWW    = os.environ.get("KUAISHOU_KWW", "").strip()
HINDI_VOICE     = os.environ.get("HINDI_VOICE", "hi-IN-SwaraNeural").strip()
WHISPER_MODEL   = os.environ.get("WHISPER_MODEL", "tiny").strip()

TEMP_DIR = "/tmp/kuaishou_dub"
os.makedirs(TEMP_DIR, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/154.0.0.0 Safari/537.36")


# ============================================================
# 1) URL → Photo ID
# ============================================================
def extract_photo_id(url: str):
    m = re.search(r"/short-video/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)

    if "v.kuaishou.com" in url or "kuaishou.com/fw/photo" in url:
        try:
            r = requests.head(url, allow_redirects=True, timeout=15,
                              headers={"User-Agent": UA})
            m = re.search(r"/short-video/([A-Za-z0-9_-]+)", r.url)
            if m:
                return m.group(1)
            m = re.search(r"photoId=([A-Za-z0-9_-]+)", r.url)
            if m:
                return m.group(1)
        except Exception:
            pass

    if re.fullmatch(r"[A-Za-z0-9_-]{8,}", url.strip()):
        return url.strip()

    return None


# ============================================================
# 2) Kuaishou GraphQL → video URL
# ============================================================
def fetch_kuaishou_video(photo_id: str):
    if not KUAISHOU_COOKIE or not KUAISHOU_KWW:
        raise RuntimeError(
            "KUAISHOU_COOKIE / KUAISHOU_KWW env vars missing. "
            "Render Dashboard → Environment mein add karein."
        )

    query = """
    fragment photoContent on PhotoEntity {
      __typename id duration caption photoUrl photoH265Url
      manifest manifestH265 videoResource videoRatio
    }
    query visionVideoDetail($photoId: String) {
      visionVideoDetail(photoId: $photoId) {
        result
        photo { ...photoContent __typename }
        __typename
      }
    }
    """
    payload = {
        "operationName": "visionVideoDetail",
        "variables": {"photoId": photo_id},
        "query": query,
    }
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://www.kuaishou.com",
        "referer": f"https://www.kuaishou.com/short-video/{photo_id}",
        "user-agent": UA,
        "kww": KUAISHOU_KWW,
        "cookie": KUAISHOU_COOKIE,
    }
    r = requests.post("https://www.kuaishou.com/graphql",
                      data=json.dumps(payload),
                      headers=headers, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"GraphQL HTTP {r.status_code}")

    try:
        data = r.json()
    except Exception:
        raise RuntimeError("GraphQL: invalid JSON response")

    photo = data.get("data", {}).get("visionVideoDetail", {}).get("photo")
    if not photo:
        feeds = data.get("data", {}).get("hotVideoData", {}).get("feeds", [])
        if feeds:
            photo = feeds[0].get("photo")

    if not photo:
        raise RuntimeError(
            "Video info nahi mila. Cookies/KWW expire ho gaye. "
            "Browser DevTools → Network → graphql request se fresh "
            "Cookie + kww copy karke Render env mein update karein."
        )

    best = None
    try:
        rep = photo["manifest"]["adaptationSet"][0]["representation"][0]
        best = {
            "url":     rep["url"],
            "backup":  (rep.get("backupUrl") or [None])[0],
            "width":   rep.get("width", 0),
            "height":  rep.get("height", 0),
            "quality": rep.get("qualityLabel", ""),
            "size":    rep.get("fileSize", 0),
        }
    except (KeyError, IndexError, TypeError):
        pass

    if not best and photo.get("photoUrl"):
        best = {"url": photo["photoUrl"], "backup": None,
                "width": 0, "height": 0, "quality": "", "size": 0}

    if not best:
        raise RuntimeError("Response mein koi video URL nahi mila.")

    return best


# ============================================================
# 3) Download video
# ============================================================
def download_video(info, out_path):
    urls = [u for u in [info.get("url"), info.get("backup")] if u]
    headers = {
        "Referer": "https://www.kuaishou.com/",
        "User-Agent": UA,
        "Accept": "*/*",
    }
    last_err = None
    for u in urls:
        try:
            with requests.get(u, headers=headers, stream=True, timeout=180) as r:
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            f.write(chunk)
            if os.path.getsize(out_path) > 50_000:
                return
        except Exception as e:
            last_err = e
            if os.path.exists(out_path):
                os.remove(out_path)
    raise RuntimeError(f"Video download fail: {last_err}")


# ============================================================
# 4) FFmpeg helpers
# ============================================================
def extract_audio(video_path, audio_path):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", video_path, "-vn", "-acodec", "libmp3lame",
           "-q:a", "2", audio_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg extract fail: {r.stderr[-300:]}")


def merge_audio_video(video_path, audio_path, out_path):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", video_path, "-i", audio_path,
           "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0",
           "-shortest", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg merge fail: {r.stderr[-300:]}")


# ============================================================
# 5) Whisper STT
# ============================================================
_WHISPER_MODEL = None

def get_whisper():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        _WHISPER_MODEL = WhisperModel(WHISPER_MODEL,
                                      device="cpu",
                                      compute_type="int8")
    return _WHISPER_MODEL


def transcribe_audio(audio_path: str) -> str:
    model = get_whisper()
    segments, _ = model.transcribe(audio_path, beam_size=1, vad_filter=True)
    return " ".join(seg.text for seg in segments).strip()


# ============================================================
# 6) Translate to Hindi
# ============================================================
def translate_to_hindi(text: str) -> str:
    if not text.strip():
        return ""
    out = []
    for i in range(0, len(text), 4500):
        chunk = text[i:i + 4500]
        try:
            t = GoogleTranslator(source="auto", target="hi").translate(chunk)
            out.append(t or "")
        except Exception as e:
            raise RuntimeError(f"Translation fail: {e}")
    return " ".join(out).strip()


# ============================================================
# 7) edge-tts Hindi voice
# ============================================================
async def _edge_save(text, voice, path):
    await edge_tts.Communicate(text, voice).save(path)


def generate_hindi_voice(text: str, out_path: str):
    if not text.strip():
        raise RuntimeError("Hindi text khaali hai, TTS skip.")
    asyncio.run(_edge_save(text, HINDI_VOICE, out_path))


# ============================================================
# WEB UI
# ============================================================
HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Kuaishou → Hindi Voiceover (Free)</title>
<style>
 body{font-family:system-ui,sans-serif;background:#0d1117;color:#c9d1d9;
      max-width:840px;margin:40px auto;padding:20px;}
 h1{color:#58a6ff;}
 input[type=text]{width:100%;padding:12px;font-size:16px;border-radius:6px;
      border:1px solid #30363d;background:#161b22;color:#c9d1d9;}
 button{padding:12px 24px;font-size:16px;font-weight:bold;background:#238636;
      color:#fff;border:none;border-radius:6px;cursor:pointer;margin-top:10px;}
 button:hover{background:#2ea043;}
 .log{background:#161b22;padding:16px;border-radius:6px;margin-top:20px;
      font-family:monospace;font-size:13px;white-space:pre-wrap;
      border:1px solid #30363d;}
 a.dl{display:inline-block;margin-top:14px;padding:12px 20px;background:#1f6feb;
      color:#fff;text-decoration:none;border-radius:6px;font-weight:600;}
 .err{color:#f85149;} .ok{color:#3fb950;}
 small{color:#8b949e;}
</style>
</head>
<body>
<h1>🎬 Kuaishou → Hindi Voiceover (100% Free)</h1>
<form method="POST">
  <input type="text" name="url" placeholder="Kuaishou video URL ya photo ID" required>
  <button type="submit">🚀 Hindi Video Banayein</button>
</form>
<p><small>Error aaye to Render env mein fresh KUAISHOU_COOKIE + KUAISHOU_KWW daalein.
<a href="/debug-env" style="color:#58a6ff;">/debug-env</a> se check karein.</small></p>
{% if log %}<div class="log">{{ log|safe }}</div>{% endif %}
{% if download_link %}<a class="dl" href="{{ download_link }}">⬇️ Download Hindi Video</a>{% endif %}
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template_string(HTML)

    url = (request.form.get("url") or "").strip()
    if not url:
        return render_template_string(HTML, log="<span class='err'>URL daalein.</span>")

    job = uuid.uuid4().hex[:8]
    video_path = f"{TEMP_DIR}/{job}_video.mp4"
    audio_path = f"{TEMP_DIR}/{job}_audio.mp3"
    voice_path = f"{TEMP_DIR}/{job}_hindi.mp3"
    final_path = f"{TEMP_DIR}/{job}_final.mp4"
    logs = []

    def L(msg, cls=""):
        logs.append(f"<span class='{cls}'>{msg}</span>" if cls else msg)

    try:
        # 1) Photo ID
        L("▶ Step 1/6: Photo ID nikaal rahe hain...")
        pid = extract_photo_id(url)
        if not pid:
            raise RuntimeError("URL se photo ID nahi mila.")
        L(f"✅ Photo ID: {pid}", "ok")

        # 2) GraphQL
        L("▶ Step 2/6: Kuaishou GraphQL...")
        info = fetch_kuaishou_video(pid)
        L(f"✅ Quality: {info.get('quality','?')} "
          f"({info.get('width',0)}x{info.get('height',0)}), "
          f"Size: {round(info.get('size',0)/1048576, 2)} MB", "ok")

        # 3) Download
        L("▶ Step 3/6: Video download...")
        download_video(info, video_path)
        L(f"✅ Downloaded: {round(os.path.getsize(video_path)/1048576, 2)} MB", "ok")

        # 4) Audio extract
        L("▶ Step 4/6: Audio extract (ffmpeg)...")
        extract_audio(video_path, audio_path)
        L("✅ Audio ready.", "ok")

        # 5) Whisper
        L("▶ Step 5/6: Speech-to-text (faster-whisper)...")
        transcript = transcribe_audio(audio_path)
        if not transcript:
            raise RuntimeError("Transcript khaali aaya.")
        L(f"✅ Transcript ({len(transcript)} chars): {transcript[:120]}...", "ok")

        # 6) Translate + TTS + Merge
        L("▶ Step 6/6: Hindi translate...")
        hindi = translate_to_hindi(transcript)
        L(f"✅ Hindi: {hindi[:100]}...", "ok")

        L("🎙️ edge-tts voice generate...")
        generate_hindi_voice(hindi, voice_path)
        L(f"✅ Voice: {round(os.path.getsize(voice_path)/1024, 1)} KB", "ok")

        L("🔗 Merge audio + video...")
        merge_audio_video(video_path, voice_path, final_path)

        for f in (video_path, audio_path, voice_path):
            try: os.remove(f)
            except: pass

        L("🎉 Ho gaya!", "ok")
        return render_template_string(
            HTML,
            log="\n".join(logs),
            download_link=f"/download/{os.path.basename(final_path)}"
        )

    except Exception as e:
        L(f"❌ Error: {e}", "err")
        for f in (video_path, audio_path, voice_path):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except: pass
        return render_template_string(HTML, log="\n".join(logs))


@app.route("/download/<path:fname>")
def download_file(fname):
    return send_from_directory(TEMP_DIR, fname, as_attachment=True)


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/debug-env")
def debug_env():
    return {
        "cookie_set": bool(KUAISHOU_COOKIE),
        "cookie_len": len(KUAISHOU_COOKIE),
        "cookie_preview": KUAISHOU_COOKIE[:50] + "..." if KUAISHOU_COOKIE else "",
        "kww_set": bool(KUAISHOU_KWW),
        "kww_len": len(KUAISHOU_KWW),
        "kww_preview": KUAISHOU_KWW[:50] + "..." if KUAISHOU_KWW else "",
        "whisper_model": WHISPER_MODEL,
        "hindi_voice": HINDI_VOICE,
        "temp_dir_exists": os.path.isdir(TEMP_DIR),
        "ffmpeg_available": subprocess.run(
            ["which", "ffmpeg"], capture_output=True
        ).returncode == 0,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
