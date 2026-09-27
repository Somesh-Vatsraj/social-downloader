"""
Instagram Reel Downloader — Flask
Modes:
    /?url=...&mode=json      → JSON output
    /?url=...&mode=debug     → Debug info
    /?url=...&mode=download  → Merged MP4 (video+audio) via ffmpeg
"""

import json
import re
import html
import shutil
import subprocess
from urllib.parse import urlencode, quote

import requests
from flask import Flask, request, Response, jsonify

app = Flask(__name__)

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


# ============================================================
# Helpers
# ============================================================
def clean_url(u: str) -> str:
    if not isinstance(u, str):
        return u or ""
    return html.unescape(u)


def find_key_recursive(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key_recursive(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key_recursive(v, key)
            if r is not None:
                return r
    return None


def fetch_html(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print("fetch error:", e)
    return None


def extract_media_data(html_text: str) -> dict | None:
    pattern = re.compile(
        r'<script\s+type="application/json"[^>]*>(.*?)</script>',
        re.DOTALL,
    )
    for m in pattern.finditer(html_text):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found = find_key_recursive(data, "xig_polaris_media")
        if found:
            return found.get("if_not_gated_logged_out", found)
    return None


# ============================================================
# DASH Parser (regex only)
# ============================================================
def parse_dash(xml: str) -> dict:
    out = {"video": [], "audio": []}

    # ---------- VIDEO ----------
    video_set = re.search(
        r'<AdaptationSet[^>]*contentType="video"[^>]*>(.*?)</AdaptationSet>',
        xml, re.DOTALL,
    )
    if video_set:
        reps = re.findall(
            r'<Representation\s+([^>]+?)\s*>(.*?)</Representation>',
            video_set.group(1), re.DOTALL,
        )
        for attrs, body in reps:
            base = re.search(r"<BaseURL>(.*?)</BaseURL>", body, re.DOTALL)
            if not base:
                continue
            url = base.group(1).strip()
            if not url:
                continue

            def get(pat, src=attrs, grp=1, cast=str):
                mm = re.search(pat, src)
                return cast(mm.group(grp)) if mm else None

            out["video"].append({
                "id":      get(r'id="([^"]+)"'),
                "url":     clean_url(url),
                "codecs":  get(r'codecs="([^"]+)"'),
                "quality": get(r'FBQualityLabel="([^"]+)"') or "DASH",
                "width":   get(r'width="(\d+)"', cast=int),
                "height":  get(r'height="(\d+)"', cast=int),
                "bitrate": get(r'bandwidth="(\d+)"', cast=int),
            })

    # ---------- AUDIO ----------
    audio_set = re.search(
        r'<AdaptationSet[^>]*contentType="audio"[^>]*>(.*?)</AdaptationSet>',
        xml, re.DOTALL,
    )
    if audio_set:
        reps = re.findall(
            r'<Representation\s+([^>]+?)\s*>(.*?)</Representation>',
            audio_set.group(1), re.DOTALL,
        )
        for attrs, body in reps:
            base = re.search(r"<BaseURL>(.*?)</BaseURL>", body, re.DOTALL)
            if not base:
                continue
            url = base.group(1).strip()
            if not url:
                continue

            def get(pat, src=attrs, grp=1, cast=str):
                mm = re.search(pat, src)
                return cast(mm.group(grp)) if mm else None

            ch_match = re.search(
                r'<AudioChannelConfiguration[^>]*value="([^"]+)"', body,
            )
            out["audio"].append({
                "id":       get(r'id="([^"]+)"'),
                "url":      clean_url(url),
                "codecs":   get(r'codecs="([^"]+)"'),
                "bitrate":  get(r'bandwidth="(\d+)"', cast=int),
                "sampling": get(r'audioSamplingRate="(\d+)"', cast=int),
                "channels": ch_match.group(1) if ch_match else None,
            })

    return out


# ============================================================
# Instagram Data Extractor
# ============================================================
def extract_all(url: str) -> dict | None:
    html_text = fetch_html(url)
    if not html_text:
        return None

    media_data = extract_media_data(html_text)
    if not media_data:
        return None

    username          = (media_data.get("user") or {}).get("username", "")
    profile_image_uri = clean_url((media_data.get("user") or {}).get("profile_pic_url", ""))
    caption           = (media_data.get("caption") or {}).get("text", "")

    # Progressive MP4 URLs (deduplicated)
    progressive = []
    for v in media_data.get("video_versions") or []:
        u = clean_url(v.get("url", ""))
        if u and u not in progressive:
            progressive.append(u)

    # DASH parse
    dash_xml = media_data.get("video_dash_manifest") or ""
    dash = parse_dash(dash_xml) if isinstance(dash_xml, str) and len(dash_xml) > 50 else {"video": [], "audio": []}

    # Best DASH video (highest height, then bitrate)
    best_video = None
    for v in dash["video"]:
        if (
            best_video is None
            or (v.get("height") or 0) > (best_video.get("height") or 0)
            or (
                (v.get("height") or 0) == (best_video.get("height") or 0)
                and (v.get("bitrate") or 0) > (best_video.get("bitrate") or 0)
            )
        ):
            best_video = v
    best_audio = dash["audio"][0] if dash["audio"] else None

    return {
        "username":          username,
        "profile_image_uri": profile_image_uri,
        "caption":           caption,
        "progressive":       progressive,
        "dash_video":        dash["video"],
        "dash_audio":        dash["audio"],
        "best_video":        best_video,
        "best_audio":        best_audio,
        "dash_xml_length":   len(dash_xml) if isinstance(dash_xml, str) else 0,
        "ffmpeg":            shutil.which("ffmpeg") or "NOT FOUND",
    }


# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def index():
    url  = request.args.get("url", "").strip()
    mode = request.args.get("mode", "json").strip().lower()

    if not url:
        if mode == "json":
            return jsonify({"success": False, "error": "url parameter required"}), 400
        return Response("url parameter required", status=400, mimetype="text/plain")

    data = extract_all(url)
    if not data:
        if mode == "json":
            return jsonify({"success": False, "error": "Failed to fetch/extract Instagram data"}), 502
        return Response("Failed to fetch/extract Instagram data", status=502, mimetype="text/plain")

    # ---------- DEBUG MODE ----------
    if mode == "debug":
        return jsonify({
            "instagram_url":      url,
            "username":           data["username"],
            "progressive_count":  len(data["progressive"]),
            "progressive_urls":   data["progressive"],
            "dash_video_count":   len(data["dash_video"]),
            "dash_video_all":     data["dash_video"],
            "dash_audio_count":   len(data["dash_audio"]),
            "dash_audio_all":     data["dash_audio"],
            "best_video":         data["best_video"],
            "best_audio":         data["best_audio"],
            "dash_xml_length":    data["dash_xml_length"],
            "ffmpeg_available":   data["ffmpeg"],
        })

    # ---------- JSON MODE ----------
    if mode == "json":
        media = []
        for pu in data["progressive"]:
            media.append({
                "type": "video", "source": "progressive",
                "quality": "HD", "url": pu, "has_audio": False,
            })
        for v in data["dash_video"]:
            media.append({
                "type": "video", "source": "dash",
                "quality": v.get("quality"), "url": v.get("url"),
                "codecs": v.get("codecs"),
                "width": v.get("width"), "height": v.get("height"),
                "bitrate": v.get("bitrate"), "has_audio": False,
            })
        for a in data["dash_audio"]:
            media.append({
                "type": "audio", "source": "dash",
                "quality": "AUDIO", "url": a.get("url"),
                "codecs": a.get("codecs"), "bitrate": a.get("bitrate"),
                "sampling": a.get("sampling"), "channels": a.get("channels"),
                "has_audio": True,
            })

        download_url = "/?mode=download&" + urlencode({"url": url})
        return jsonify({
            "success":           True,
            "username":          data["username"],
            "profile_image_uri": data["profile_image_uri"],
            "caption":           data["caption"],
            "media":             media,
            "download_url":      download_url,
        })

    # ---------- DOWNLOAD MODE ----------
    if mode == "download":
        best_video = data["best_video"]
        best_audio = data["best_audio"]
        ffmpeg     = shutil.which("ffmpeg")

        # Fallback: ffmpeg नहीं है या DASH अधूरा है → progressive भेज दो
        if not (best_video and best_audio and ffmpeg):
            if data["progressive"]:
                fb = data["progressive"][0]
                def stream_progressive():
                    with requests.get(fb, headers=HEADERS, stream=True) as r:
                        for chunk in r.iter_content(chunk_size=64 * 1024):
                            if chunk:
                                yield chunk
                return Response(
                    stream_progressive(),
                    mimetype="video/mp4",
                    headers={
                        "Content-Disposition": 'attachment; filename="ig_fallback.mp4"',
                        "Cache-Control": "no-cache",
                    },
                )
            return Response(
                "Video not available. Run debug mode.",
                status=500, mimetype="text/plain",
            )

        # ffmpeg merge: DASH video + DASH audio → merged MP4 stream
        cmd = [
            ffmpeg, "-loglevel", "error",
            "-i", best_video["url"],
            "-i", best_audio["url"],
            "-c", "copy",
            "-movflags", "frag_keyframe+empty_moov",
            "-f", "mp4",
            "pipe:1",
        ]

        def stream_merged():
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            try:
                while True:
                    chunk = proc.stdout.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                proc.stdout.close()
                proc.wait()

        return Response(
            stream_merged(),
            mimetype="video/mp4",
            headers={
                "Content-Disposition": 'attachment; filename="ig_merged.mp4"',
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ---------- Unknown mode ----------
    return Response("Invalid mode. Use: json | debug | download", status=400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
