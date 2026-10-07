#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — YouTube Downloader (Render-ready)
Endpoints:
    GET  /                       -> HTML UI
    GET  /health                 -> health check
    GET  /info?url=...           -> JSON info + links
    GET  /stream?url=...&q=720   -> live stream (proxy ya ffmpeg merge)
    GET  /download?url=...&q=..  -> attachment download
    GET  /audio?url=...&fmt=m4a  -> audio only (m4a / mp3)
"""

import os
import sys
import shutil
import subprocess

from flask import (
    Flask, request, Response, jsonify,
    stream_with_context, render_template_string, url_for
)

try:
    import yt_dlp
except ImportError:
    print("Install: pip install yt-dlp")
    sys.exit(1)

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
DENO   = shutil.which("deno")   or "deno"

# ---------- yt-dlp options: 2026 fixes applied ----------
YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
    "nocheckcertificate": True,
    "nocheckformats": False,

    # JS runtime (Deno) — signature solver ke liye zaroori
    "js_runtime": "deno",

    # Cloudflare / bot detection bypass
    "impersonate": "chrome",

    # Extractor tuning
    "extractor_args": {
        "youtube": {
            # tv + mweb + android_vr = 2026 me sabse reliable combo
            "player_client": ["tv", "mweb", "android_vr"],
            # PO token (403 / bot-check bypass)
            "po_token": ["web+https"],
            # web page config skip (bot detector trigger nahi hoga)
            "player_skip": ["webpage", "configs"],
        }
    },

    # Timeouts
    "socket_timeout": 30,
    "retries": 3,
    "fragment_retries": 3,
}

CHUNK = 65536


# ============================================================
# Helpers
# ============================================================
def extract_info(url: str) -> dict:
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        return ydl.extract_info(url, download=False)


def quality_name(f: dict) -> str:
    h = f.get("height")
    if h:
        if h >= 1080:
            return f"{h}p Full HD"
        if h >= 720:
            return f"{h}p HD"
        return f"{h}p"
    abr = f.get("abr")
    return f"{int(abr)}kbps" if abr else ""


def yt_headers(ua: str) -> dict:
    return {
        "User-Agent": ua or "Mozilla/5.0",
        "Referer": "https://www.youtube.com/",
        "Origin": "https://www.youtube.com",
    }


# ---------- Format pickers ----------
def pick_combined(info, q, fmt="mp4"):
    """Audio+video ek URL wala (itag 18, 22)."""
    cands = [f for f in info.get("formats", [])
             if f.get("vcodec") not in (None, "none")
             and f.get("acodec") not in (None, "none")
             and f.get("height") and f["height"] <= q
             and f.get("ext") == fmt and f.get("url")]
    if not cands:
        return None
    bh = max(f["height"] for f in cands)
    return next(f for f in cands if f["height"] == bh)


def pick_video(info, q, fmt="mp4"):
    """Video-only adaptive stream."""
    cands = [f for f in info.get("formats", [])
             if f.get("vcodec") not in (None, "none")
             and f.get("acodec") in (None, "none")
             and f.get("height") and f["height"] <= q
             and f.get("ext") == fmt and f.get("url")]
    if not cands:
        return None
    bh = max(f["height"] for f in cands)
    cands = [f for f in cands if f["height"] == bh]
    if fmt == "mp4":
        cands.sort(key=lambda f: (
            0 if str(f.get("vcodec", "")).startswith("avc1") else 1,
            -(f.get("tbr") or 0)))
    else:
        cands.sort(key=lambda f: -(f.get("tbr") or 0))
    return cands[0]


def pick_audio(info, prefer="mp4"):
    """Audio-only stream."""
    target_ext = "m4a" if prefer == "mp4" else "webm"
    cands = [f for f in info.get("formats", [])
             if f.get("acodec") not in (None, "none")
             and f.get("vcodec") in (None, "none")
             and f.get("ext") == target_ext and f.get("url")]
    if not cands:
        return None
    cands.sort(key=lambda f: (
        0 if str(f.get("acodec", "")).startswith("mp4a.40.2") else 1,
        -(f.get("abr") or 0)))
    return cands[0]


# ---------- Streaming helpers ----------
def proxy_stream(media: dict, filename=None):
    """Combined URL ko direct proxy (Range support)."""
    headers = yt_headers(media.get("http_headers", {}).get("User-Agent"))
    rng = request.headers.get("Range")
    if rng:
        headers["Range"] = rng

    try:
        r = requests.get(media["url"], headers=headers, stream=True, timeout=60)
    except Exception as e:
        return jsonify({"success": False, "message": f"upstream error: {e}"}), 502

    def generate():
        try:
            for chunk in r.iter_content(chunk_size=CHUNK):
                if chunk:
                    yield chunk
        finally:
            r.close()

    resp_headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
        if h in r.headers:
            resp_headers[h] = r.headers[h]
    resp_headers.setdefault("Content-Type", "video/mp4")
    if filename:
        resp_headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return Response(stream_with_context(generate()),
                    status=r.status_code, headers=resp_headers,
                    direct_passthrough=True)


def ffmpeg_merge_pipe(video_media, audio_media, fmt="mp4", filename=None):
    """Video-only + audio-only ko ffmpeg se live merge + pipe."""
    ua_v = video_media.get("http_headers", {}).get("User-Agent") or "Mozilla/5.0"
    ua_a = audio_media.get("http_headers", {}).get("User-Agent") or "Mozilla/5.0"

    hdr_v = (f"Origin: https://www.youtube.com\r\n"
             f"Referer: https://www.youtube.com/\r\n"
             f"User-Agent: {ua_v}\r\n")
    hdr_a = (f"Origin: https://www.youtube.com\r\n"
             f"Referer: https://www.youtube.com/\r\n"
             f"User-Agent: {ua_a}\r\n")

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
        return jsonify({"success": False, "message": "ffmpeg missing"}), 500

    def generate():
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

    headers = {
        "Content-Type": "video/webm" if fmt == "webm" else "video/mp4",
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
        "Accept-Ranges": "none",
    }
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return Response(stream_with_context(generate()),
                    headers=headers, direct_passthrough=True)


def ffmpeg_audio_pipe(audio_media, fmt="m4a", filename=None):
    """Audio-only pipe (m4a copy / mp3 re-encode)."""
    ua = audio_media.get("http_headers", {}).get("User-Agent") or "Mozilla/5.0"
    hdr = (f"Origin: https://www.youtube.com\r\n"
           f"Referer: https://www.youtube.com/\r\n"
           f"User-Agent: {ua}\r\n")

    src_codec = str(audio_media.get("acodec") or "")
    src_ext   = audio_media.get("ext") or ""

    if fmt == "mp3":
        codec_opts = ["-vn", "-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3"]
        ctype = "audio/mpeg"
    else:
        if src_ext == "m4a" and src_codec.startswith("mp4a"):
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
        return jsonify({"success": False, "message": "ffmpeg missing"}), 500

    def generate():
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

    headers = {"Content-Type": ctype, "Cache-Control": "no-store",
               "X-Accel-Buffering": "no"}
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return Response(stream_with_context(generate()),
                    headers=headers, direct_passthrough=True)


# ============================================================
# Routes
# ============================================================
@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "ffmpeg": FFMPEG,
        "deno": DENO,
        "yt_dlp": getattr(yt_dlp.version, "__version__", "?"),
    })


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/info")
def route_info():
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"success": False, "message": "url required"}), 400
    try:
        info = extract_info(url)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 502

    def self_url(endpoint, **kw):
        return url_for(endpoint, _external=True, **kw)

    seen = set()
    video_list, audio_list = [], []
    for f in info.get("formats", []):
        itag = str(f.get("format_id") or "")
        has_v = f.get("vcodec") not in (None, "none")
        has_a = f.get("acodec") not in (None, "none")
        key = ("v" if has_v else "a") + itag
        if key in seen: continue
        seen.add(key)
        if not (has_v or has_a): continue

        row = {
            "type": "video" if has_v else "audio",
            "id": itag,
            "url": f.get("url"),
            "width": f.get("width"),
            "height": f.get("height"),
            "ext": f.get("ext"),
            "container": f.get("ext"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "has_video": has_v,
            "has_audio": has_a,
            "quality": quality_name(f),
            "quality_label": f.get("format_note") or f.get("quality"),
            "fps": f.get("fps"),
            "tbr": f.get("tbr"),
            "abr": f.get("abr"),
            "vbr": f.get("vbr"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "type_combined": has_v and has_a,
        }
        (video_list if has_v else audio_list).append(row)

    video_list.sort(key=lambda r: (r["height"] or 0, r["tbr"] or 0))
    audio_list.sort(key=lambda r: -(r["abr"] or 0))

    video_q = sorted({r["quality"] for r in video_list if r["quality"]})
    audio_q = sorted({r["quality"] for r in audio_list if r["quality"]})

    thumbnails = info.get("thumbnails") or []
    thumb_url = info.get("thumbnail") or \
                f"https://i.ytimg.com/vi/{info['id']}/hqdefault.jpg"

    def stream_link(q, fmt="mp4"):
        return self_url("route_stream", url=url, q=q, fmt=fmt)
    def dl_link(q, fmt="mp4"):
        return self_url("route_download", url=url, q=q, fmt=fmt)
    def audio_link(fmt="m4a"):
        return self_url("route_audio", url=url, fmt=fmt)

    return jsonify({
        "success": True,
        "type": "video",
        "id": info.get("id"),
        "username": info.get("uploader"),
        "profile_image_uri": thumb_url,
        "caption": info.get("title"),
        "description": info.get("description"),
        "thumbnails": thumbnails,
        "available_qualities": {"video": video_q, "audio": audio_q},
        "has_1080p": any((r["height"] or 0) == 1080 for r in video_list),
        "stream_links": {
            "360p_mp4":  stream_link(360),
            "480p_mp4":  stream_link(480),
            "720p_mp4":  stream_link(720),
            "1080p_mp4": stream_link(1080),
            "1080p_webm": stream_link(1080, "webm"),
        },
        "download_links": {
            "480p_mp4":  dl_link(480),
            "720p_mp4":  dl_link(720),
            "1080p_mp4": dl_link(1080),
        },
        "audio_links": {"m4a": audio_link("m4a"), "mp3": audio_link("mp3")},
        "media": video_list + audio_list,
        "duration": info.get("duration"),
        "tags": info.get("tags") or [],
        "source": "youtube",
    })


@app.route("/stream")
def route_stream():
    url = (request.args.get("url") or "").strip()
    q = int(request.args.get("q") or 1080)
    fmt = request.args.get("fmt") or "mp4"
    if fmt not in ("mp4", "webm"): fmt = "mp4"
    if not url:
        return jsonify({"success": False, "message": "url required"}), 400

    try:
        info = extract_info(url)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 502

    video_id = info.get("id") or "video"

    # 1) combined (itag 18 / 22) -> proxy
    comb = pick_combined(info, q, fmt)
    if comb:
        fname = f"{video_id}_{comb.get('height','')}p.{fmt}"
        return proxy_stream(comb, filename=fname)

    # 2) adaptive: ffmpeg merge
    v = pick_video(info, q, fmt)
    a = pick_audio(info, "mp4" if fmt == "mp4" else "webm")
    if not v or not a:
        return jsonify({"success": False,
                        "message": f"q={q} fmt={fmt} ke liye stream nahi mila"}), 404

    fname = f"{video_id}_{v.get('height','')}p.{fmt}"
    return ffmpeg_merge_pipe(v, a, fmt=fmt, filename=fname)


@app.route("/download")
def route_download():
    return route_stream()


@app.route("/audio")
def route_audio():
    url = (request.args.get("url") or "").strip()
    fmt = (request.args.get("fmt") or "m4a").lower()
    if fmt not in ("m4a", "mp3"): fmt = "m4a"
    if not url:
        return jsonify({"success": False, "message": "url required"}), 400

    try:
        info = extract_info(url)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 502

    a = pick_audio(info, "mp4") or pick_audio(info, "webm")
    if not a:
        return jsonify({"success": False, "message": "audio nahi mila"}), 404

    video_id = info.get("id") or "audio"
    ext = "m4a" if fmt == "m4a" else "mp3"
    return ffmpeg_audio_pipe(a, fmt=fmt, filename=f"{video_id}.{ext}")


# ============================================================
# HTML UI
# ============================================================
INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>YT Downloader</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{font-family:system-ui,Arial;max-width:760px;margin:20px auto;padding:0 14px;color:#111}
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
<h1>YouTube Downloader (Render + yt-dlp + ffmpeg)</h1>
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
  if(!j.success){ document.getElementById('out').innerHTML = '<pre>' + JSON.stringify(j,null,2) + '</pre>'; return; }
  const s = j.stream_links, a = j.audio_links;
  let html = '<h3>' + (j.caption||'') + '</h3>';
  html += '<div><b>By:</b> ' + (j.username||'') + ' &nbsp; <b>Duration:</b> ' + (j.duration||0) + 's</div>';
  if(j.thumbnail) html += '<img src="'+j.thumbnail+'">';
  html += '<div class="q"><b>Stream:</b><br>';
  html += '<a href="'+s['360p_mp4']+'">360p</a>';
  html += '<a href="'+s['480p_mp4']+'">480p</a>';
  html += '<a href="'+s['720p_mp4']+'">720p</a>';
  html += '<a href="'+s['1080p_mp4']+'">1080p</a>';
  html += '<a href="'+s['1080p_webm']+'">1080p webm</a>';
  html += '</div>';
  html += '<div class="audio"><b>Audio:</b><br>';
  html += '<a href="'+a['m4a']+'">M4A</a>';
  html += '<a href="'+a['mp3']+'">MP3</a>';
  html += '</div>';
  html += '<div style="margin-top:14px"><b>Download:</b> ';
  for(const k in j.download_links){ html += '<a href="'+j.download_links[k]+'">'+k+'</a> '; }
  html += '</div>';
  document.getElementById('out').innerHTML = html;
}
</script>
</body>
</html>
"""


# ============================================================
# Local run
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
