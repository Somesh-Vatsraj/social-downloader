#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — YouTube extractor + streamer (Multi-client Innertube + visitorData)

Endpoints:
    GET /                        -> HTML UI
    GET /health                  -> health check
    GET /info?url=...            -> JSON (formats + links)
    GET /stream360?url=...       -> 360p stream (combined → direct proxy)
    GET /stream720?url=...       -> 720p stream (ffmpeg merge)
    GET /audio?url=...&fmt=m4a   -> audio (m4a / mp3)
"""

import os
import re
import sys
import json
import shutil
import subprocess
from urllib.parse import unquote

from flask import (
    Flask, request, Response, jsonify,
    stream_with_context, render_template_string, url_for
)

try:
    import requests
except ImportError:
    print("Install: pip install requests")
    sys.exit(1)


# ============================================================
# Setup
# ============================================================
app = Flask(__name__)

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
CHUNK  = 65536

INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"


# ============================================================
# 1. MULTI-CLIENT ROTATION (datacenter IP fix)
# ============================================================
CLIENTS = [
    # TV Embedded — sabse kam restricted, embed URL use karta hai
    {
        "clientName": "TVHTML5_SIMPLY_EMBEDDED_PLAYER",
        "clientVersion": "2.0",
        "clientId": "85",
        "ua": "Mozilla/5.0 (PlayStation; PlayStation 4/12.00) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
        "embed": True,
    },
    # ANDROID_VR — JS-less, n-param deciphering nahi chahiye
    {
        "clientName": "ANDROID_VR",
        "clientVersion": "1.62.27",
        "clientId": "28",
        "ua": "com.google.android.apps.youtube.vr.oculus/1.62.27 (Linux; U; Android 12L) gzip",
        "embed": False,
    },
    # MWEB — mobile web fallback
    {
        "clientName": "MWEB",
        "clientVersion": "2.20250310.01.00",
        "clientId": "2",
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "embed": False,
    },
]


# ============================================================
# 2. VIDEO ID
# ============================================================
YT_RE = re.compile(
    r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)'
    r'([A-Za-z0-9_-]{11})'
)

def get_video_id(url: str) -> str | None:
    m = YT_RE.search(url or "")
    return m.group(1) if m else None


# ============================================================
# 3. VISITOR DATA — watch page se nikaalo
# ============================================================
def fetch_visitor_data(video_id: str, ua: str) -> str | None:
    """Watch page se visitorData nikaalo. Keyless anonymous calls isi se
    'Sign in to confirm you're not a bot' se bach jaate hain."""
    try:
        r = requests.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"},
            timeout=15,
        )
        m = re.search(r'"visitorData":"([^"]+)"', r.text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


# ============================================================
# 4. INNERTUBE CALL — client rotation + visitorData
# ============================================================
def call_innertube(video_id: str) -> dict:
    errors = []
    for c in CLIENTS:
        try:
            # Step 1: visitorData fetch karo
            visitor_data = fetch_visitor_data(video_id, c["ua"])

            # Step 2: payload banao
            client_ctx = {
                "hl": "en", "gl": "US",
                "clientName": c["clientName"],
                "clientVersion": c["clientVersion"],
                "userAgent": c["ua"],
            }
            if visitor_data:
                client_ctx["visitorData"] = visitor_data

            payload = {
                "context": {
                    "client": client_ctx,
                    "request": {"useSsl": True},
                },
                "videoId": video_id,
                "contentCheckOk": True,
                "racyCheckOk": True,
            }
            if c["embed"]:
                payload["context"]["thirdParty"] = {
                    "embedUrl": f"https://www.youtube.com/embed/{video_id}"
                }

            headers = {
                "Content-Type": "application/json",
                "User-Agent": c["ua"],
                "X-YouTube-Client-Name": c["clientId"],
                "X-YouTube-Client-Version": c["clientVersion"],
                "Origin": "https://www.youtube.com",
            }

            r = requests.post(INNERTUBE_URL, data=json.dumps(payload),
                              headers=headers, timeout=20)

            if r.status_code != 200:
                errors.append(f"{c['clientName']}: HTTP {r.status_code}")
                continue

            data = r.json()
            status = data.get("playabilityStatus", {}).get("status", "")
            reason = data.get("playabilityStatus", {}).get("reason", "")

            if status == "OK":
                data["_client_used"] = c["clientName"]
                return data

            errors.append(f"{c['clientName']}: {status} — {reason}")

        except Exception as e:
            errors.append(f"{c['clientName']}: {e}")
            continue

    raise RuntimeError("All clients failed. " + " | ".join(errors))


# ============================================================
# 5. HELPERS
# ============================================================
def decode_signature_cipher(cipher: str) -> str | None:
    if not cipher:
        return None
    idx = cipher.find("url=")
    if idx == -1:
        return None
    raw = cipher[idx + 4:]
    amp = raw.find("&")
    if amp != -1:
        raw = raw[:amp]
    return unquote(unquote(raw))


def normalize_format(f: dict) -> dict | None:
    url = f.get("url")
    if not url and f.get("signatureCipher"):
        url = decode_signature_cipher(f["signatureCipher"])
    if not url:
        return None

    mime = f.get("mimeType", "")
    is_v = mime.startswith("video/")
    is_a = mime.startswith("audio/")
    container = mime.split("/")[1].split(";")[0] if "/" in mime else ""
    codec = ""
    cm = re.search(r'codecs="([^"]+)"', mime)
    if cm:
        codec = cm.group(1)

    return {
        "itag":           f.get("itag"),
        "url":            url,
        "type":           "video" if is_v else ("audio" if is_a else "unknown"),
        "has_video":      is_v,
        "has_audio":      is_a or (is_v and f.get("audioQuality") is not None),
        "container":      container,
        "codec":          codec,
        "quality":        f.get("qualityLabel") or f.get("audioQuality") or "",
        "width":          f.get("width"),
        "height":         f.get("height"),
        "fps":            f.get("fps"),
        "bitrate":        f.get("bitrate"),
        "content_length": f.get("contentLength"),
    }


def extract_all_formats(data: dict) -> list[dict]:
    sd = data.get("streamingData", {})
    raw = (sd.get("formats") or []) + (sd.get("adaptiveFormats") or [])
    return [n for f in raw if (n := normalize_format(f))]


def pick_combined(formats, q, container="mp4"):
    pool = [f for f in formats
            if f["has_video"] and f["has_audio"]
            and f["height"] and f["height"] <= q
            and f["container"] == container]
    if not pool:
        return None
    best = max(f["height"] for f in pool)
    return next(f for f in pool if f["height"] == best)


def pick_video(formats, q, container="mp4"):
    pool = [f for f in formats
            if f["has_video"] and not f["has_audio"]
            and f["height"] and f["height"] <= q
            and f["container"] == container]
    if not pool:
        return None
    best = max(f["height"] for f in pool)
    pool = [f for f in pool if f["height"] == best]
    if container == "mp4":
        pool.sort(key=lambda f: (0 if f["codec"].startswith("avc1") else 1,
                                 -(f["bitrate"] or 0)))
    else:
        pool.sort(key=lambda f: -(f["bitrate"] or 0))
    return pool[0]


def pick_audio(formats, container="mp4"):
    ext = "mp4" if container == "mp4" else "webm"
    pool = [f for f in formats
            if f["has_audio"] and not f["has_video"]
            and f["container"] == ext]
    if not pool:
        return None
    pool.sort(key=lambda f: (0 if f["codec"].startswith("mp4a.40.2") else 1,
                             -(f["bitrate"] or 0)))
    return pool[0]


# ============================================================
# 6. STREAM HELPERS
# ============================================================
YT_HEADERS = {
    "Origin": "https://www.youtube.com",
    "Referer": "https://www.youtube.com/",
    "User-Agent": "Mozilla/5.0 (PlayStation; PlayStation 4/12.00) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
}


def proxy_direct(media, ctype="video/mp4", filename=None):
    rng = request.headers.get("Range")
    headers = dict(YT_HEADERS)
    if rng:
        headers["Range"] = rng

    try:
        r = requests.get(media["url"], headers=headers, stream=True, timeout=60)
    except Exception as e:
        return jsonify({"success": False, "message": f"upstream: {e}"}), 502

    def gen():
        try:
            for chunk in r.iter_content(chunk_size=CHUNK):
                if chunk:
                    yield chunk
        finally:
            r.close()

    hdr = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
        if h in r.headers:
            hdr[h] = r.headers[h]
    hdr.setdefault("Content-Type", ctype)
    if filename:
        hdr["Content-Disposition"] = f'attachment; filename="{filename}"'

    return Response(stream_with_context(gen()),
                    status=r.status_code, headers=hdr,
                    direct_passthrough=True)


def ffmpeg_pipe(video_media, audio_media, fmt="mp4", filename=None):
    hdr_v = (f"Origin: https://www.youtube.com\r\n"
             f"Referer: https://www.youtube.com/\r\n"
             f"User-Agent: {YT_HEADERS['User-Agent']}\r\n")
    hdr_a = hdr_v

    if fmt == "webm":
        codec_opts = ["-c", "copy", "-f", "webm"]
    else:
        codec_opts = ["-c", "copy",
                      "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                      "-f", "mp4"]

    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
           "-headers", hdr_v, "-i", video_media["url"],
           "-headers", hdr_a, "-i", audio_media["url"],
           *codec_opts, "pipe:1"]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, bufsize=0)
    except FileNotFoundError:
        return jsonify({"success": False, "message": "ffmpeg not installed"}), 500

    def gen():
        try:
            while True:
                chunk = proc.stdout.read(CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            try: proc.stdout.close()
            except Exception: pass
            try:
                proc.terminate(); proc.wait(timeout=5)
            except Exception:
                try: proc.kill()
                except Exception: pass

    hdr = {
        "Content-Type": "video/webm" if fmt == "webm" else "video/mp4",
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
        "Accept-Ranges": "none",
    }
    if filename:
        hdr["Content-Disposition"] = f'attachment; filename="{filename}"'

    return Response(stream_with_context(gen()), headers=hdr,
                    direct_passthrough=True)


def ffmpeg_audio_pipe(audio_media, fmt="m4a", filename=None):
    hdr = (f"Origin: https://www.youtube.com\r\n"
           f"Referer: https://www.youtube.com/\r\n"
           f"User-Agent: {YT_HEADERS['User-Agent']}\r\n")

    src_codec = audio_media.get("codec", "")
    src_ext   = audio_media.get("container", "")

    if fmt == "mp3":
        codec_opts = ["-vn", "-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3"]
        ctype = "audio/mpeg"
    else:
        if src_ext == "mp4" and src_codec.startswith("mp4a"):
            codec_opts = ["-vn", "-c:a", "copy", "-f", "mp4"]
        else:
            codec_opts = ["-vn", "-c:a", "aac", "-b:a", "192k", "-f", "mp4"]
        ctype = "audio/mp4"

    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
           "-headers", hdr, "-i", audio_media["url"], *codec_opts, "pipe:1"]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, bufsize=0)
    except FileNotFoundError:
        return jsonify({"success": False, "message": "ffmpeg not installed"}), 500

    def gen():
        try:
            while True:
                chunk = proc.stdout.read(CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            try: proc.stdout.close()
            except Exception: pass
            try:
                proc.terminate(); proc.wait(timeout=5)
            except Exception:
                try: proc.kill()
                except Exception: pass

    hdr_out = {"Content-Type": ctype, "Cache-Control": "no-store",
               "X-Accel-Buffering": "no"}
    if filename:
        hdr_out["Content-Disposition"] = f'attachment; filename="{filename}"'

    return Response(stream_with_context(gen()), headers=hdr_out,
                    direct_passthrough=True)


# ============================================================
# 7. ROUTES
# ============================================================
@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "ffmpeg": FFMPEG,
        "clients": [c["clientName"] for c in CLIENTS],
    })


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/info")
def route_info():
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"success": False, "message": "url required"}), 400

    video_id = get_video_id(url)
    if not video_id:
        return jsonify({"success": False, "message": "Invalid YouTube URL"}), 400

    try:
        data = call_innertube(video_id)
    except Exception as e:
        return jsonify({"success": False, "message": str(e) or repr(e)}), 502

    details = data.get("videoDetails", {})
    formats = extract_all_formats(data)

    def self_url(endpoint, **kw):
        return url_for(endpoint, _external=True, **kw)

    seen = set()
    media_out = []
    for f in formats:
        key = ("v" if f["has_video"] else "a") + str(f["itag"])
        if key in seen:
            continue
        seen.add(key)
        media_out.append(f)

    video_list = [r for r in media_out if r["has_video"]]
    audio_list = [r for r in media_out if r["has_audio"] and not r["has_video"]]

    return jsonify({
        "success":       True,
        "videoId":       video_id,
        "title":         details.get("title", ""),
        "author":        details.get("author", ""),
        "duration":      int(details.get("lengthSeconds", 0) or 0),
        "client_used":   data.get("_client_used"),
        "thumbnails": [
            {"url": t.get("url"),
             "width": t.get("width"),
             "height": t.get("height")}
            for t in details.get("thumbnail", {}).get("thumbnails", [])
            if t.get("url")
        ],
        "stream_links": {
            "360p":      self_url("route_stream360", url=url),
            "720p":      self_url("route_stream720", url=url),
            "audio_m4a": self_url("route_audio", url=url, fmt="m4a"),
            "audio_mp3": self_url("route_audio", url=url, fmt="mp3"),
        },
        "media":         media_out,
        "video_formats": video_list,
        "audio_formats": audio_list,
        "total_formats": len(media_out),
    })


@app.route("/stream360")
def route_stream360():
    url = (request.args.get("url") or "").strip()
    video_id = get_video_id(url)
    if not video_id:
        return jsonify({"success": False, "message": "Invalid URL"}), 400

    try:
        data = call_innertube(video_id)
    except Exception as e:
        return jsonify({"success": False, "message": str(e) or repr(e)}), 502

    formats = extract_all_formats(data)
    pick = pick_combined(formats, 360, "mp4") or pick_combined(formats, 480, "mp4")
    if not pick:
        return jsonify({"success": False, "message": "360p combined nahi mila"}), 404

    return proxy_direct(pick, "video/mp4", f"{video_id}_360p.mp4")


@app.route("/stream720")
def route_stream720():
    url = (request.args.get("url") or "").strip()
    fmt = (request.args.get("fmt") or "mp4").lower()
    if fmt not in ("mp4", "webm"):
        fmt = "mp4"
    video_id = get_video_id(url)
    if not video_id:
        return jsonify({"success": False, "message": "Invalid URL"}), 400

    try:
        data = call_innertube(video_id)
    except Exception as e:
        return jsonify({"success": False, "message": str(e) or repr(e)}), 502

    formats = extract_all_formats(data)

    comb = pick_combined(formats, 720, fmt)
    if comb:
        return proxy_direct(comb, "video/mp4", f"{video_id}_720p.{fmt}")

    v = pick_video(formats, 720, fmt)
    a = pick_audio(formats, "mp4" if fmt == "mp4" else "webm")
    if not v or not a:
        return jsonify({"success": False,
                        "message": f"720p {fmt} ke liye video+audio nahi mila",
                        "have_v": bool(v), "have_a": bool(a)}), 404

    return ffmpeg_pipe(v, a, fmt, f"{video_id}_720p.{fmt}")


@app.route("/audio")
def route_audio():
    url = (request.args.get("url") or "").strip()
    fmt = (request.args.get("fmt") or "m4a").lower()
    if fmt not in ("m4a", "mp3"):
        fmt = "m4a"
    video_id = get_video_id(url)
    if not video_id:
        return jsonify({"success": False, "message": "Invalid URL"}), 400

    try:
        data = call_innertube(video_id)
    except Exception as e:
        return jsonify({"success": False, "message": str(e) or repr(e)}), 502

    formats = extract_all_formats(data)
    a = pick_audio(formats, "mp4") or pick_audio(formats, "webm")
    if not a:
        return jsonify({"success": False, "message": "audio nahi mila"}), 404

    ext = "m4a" if fmt == "m4a" else "mp3"
    return ffmpeg_audio_pipe(a, fmt, f"{video_id}.{ext}")


# ============================================================
# 8. HTML UI
# ============================================================
INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>YT Downloader (Multi-Client)</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{font-family:system-ui,Arial;max-width:780px;margin:20px auto;padding:0 14px;color:#111}
  input,button{padding:10px 12px;font-size:15px;border-radius:8px;border:1px solid #ccc}
  input{width:100%;box-sizing:border-box}
  button{background:#0d6efd;color:#fff;border:0;cursor:pointer}
  .row{margin-top:12px}
  .q a,.audio a{display:inline-block;margin:4px 6px 0 0;padding:8px 12px;border-radius:8px;
       background:#f1f3f5;text-decoration:none;color:#0d6efd;font-weight:600}
  pre{background:#f6f8fa;padding:12px;border-radius:8px;overflow:auto;max-height:340px}
  img{max-width:100%;border-radius:10px;margin-top:10px}
  h1{font-size:20px}
</style>
</head>
<body>
<h1>YouTube Downloader (Multi-Client Innertube)</h1>
<div class="row"><input id="url" placeholder="https://youtu.be/XXXX"></div>
<div class="row"><button onclick="go()">Load</button></div>
<div id="out"></div>
<script>
async function go(){
  const url = document.getElementById('url').value.trim();
  if(!url) return alert('Paste YouTube URL');
  document.getElementById('out').innerHTML = 'Loading...';
  const r = await fetch('/info?url=' + encodeURIComponent(url));
  const j = await r.json();
  if(!j.success){
    document.getElementById('out').innerHTML = '<pre>'+JSON.stringify(j,null,2)+'</pre>';
    return;
  }
  const s = j.stream_links;
  let html = '<h3>'+(j.title||'')+'</h3>';
  html += '<div><b>By:</b> '+(j.author||'')+' &nbsp; <b>Duration:</b> '+(j.duration||0)+'s</div>';
  if(j.thumbnails && j.thumbnails.length) html += '<img src="'+j.thumbnails[j.thumbnails.length-1].url+'">';
  html += '<div class="q"><b>Video:</b><br>';
  html += '<a href="'+s['360p']+'">360p MP4</a>';
  html += '<a href="'+s['720p']+'">720p MP4</a>';
  html += '</div>';
  html += '<div class="audio"><b>Audio:</b><br>';
  html += '<a href="'+s['audio_m4a']+'">M4A</a>';
  html += '<a href="'+s['audio_mp3']+'">MP3</a>';
  html += '</div>';
  html += '<h4>Client used: '+(j.client_used||'?')+'</h4>';
  document.getElementById('out').innerHTML = html;
}
</script>
</body>
</html>
"""


# ============================================================
# 9. MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
