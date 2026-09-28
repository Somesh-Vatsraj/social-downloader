# ============================================================
#  app.py — Sarathi DL Fetcher
#  Python + Flask + FREE OCR (ddddocr) + photo/sign fix
#  Render-ready
# ============================================================

import os
import re
import time
import base64
import html as html_lib
import traceback
from datetime import datetime

from flask import Flask, request, jsonify, render_template
import requests

# ---------- FREE OCR ----------
try:
    import ddddocr
    OCR = ddddocr.DdddOcr(show_ad=False)
    print("[*] ddddocr loaded", flush=True)
    OCR_OK = True
except Exception as e:
    print(f"[!] ddddocr load failed: {e}", flush=True)
    OCR = None
    OCR_OK = False


app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

BASE = "https://sarathi.parivahan.gov.in/sarathiservice"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/153.0.0.0 Safari/537.36")

# debug memory
LAST_HTML = {"envaction": "", "submit": "", "cookies": {}}


# ============================================================
#  Helpers
# ============================================================
def clean_text(s: str) -> str:
    if s is None:
        return ""
    s = re.sub(r"<[^>]*>", " ", s)
    s = html_lib.unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def rx(pattern: str, text: str, flags=re.S | re.I):
    m = re.search(pattern, text, flags)
    return clean_text(m.group(1)) if m else None


def extract_token(html: str):
    for pat in (
        r'<input[^>]+name=["\']token["\'][^>]+value=["\']([^"\']+)["\']',
        r'<input[^>]+value=["\']([^"\']+)["\'][^>]+name=["\']token["\']',
        r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1).strip()
    return None


# ============================================================
#  Robust image extractor (photo + signature)
# ============================================================
def extract_input_value(html: str, name: str):
    m = re.search(
        r'<input\b[^>]*\bname\s*=\s*["\']' + re.escape(name) + r'["\'][^>]*>',
        html, re.S | re.I
    )
    if not m:
        return None
    tag = m.group(0)
    vm = re.search(r'\bvalue\s*=\s*["\'](.*?)["\']', tag, re.S | re.I)
    if not vm:
        return None
    v = html_lib.unescape(vm.group(1))
    mm = re.match(r'^data:image/[^;]+;base64,(.+)$', v, re.S | re.I)
    if mm:
        v = mm.group(1)
    v = re.sub(r"\s+", "", v)
    try:
        if v and base64.b64decode(v, validate=True):
            return v
    except Exception:
        pass
    return None


def all_images(html: str):
    out = []
    # input name=... value="data:image/..."
    for m in re.finditer(
        r'<input\b[^>]*\bname\s*=\s*["\']([^"\']+)["\'][^>]*\bvalue\s*=\s*["\'](data:image/[^;]+;base64,[^"\']+)["\'][^>]*>',
        html, re.S | re.I
    ):
        out.append({"name": m.group(1), "data": html_lib.unescape(m.group(2))})
    # value पहले, name बाद
    for m in re.finditer(
        r'<input\b[^>]*\bvalue\s*=\s*["\'](data:image/[^;]+;base64,[^"\']+)["\'][^>]*\bname\s*=\s*["\']([^"\']+)["\'][^>]*>',
        html, re.S | re.I
    ):
        out.append({"name": m.group(2), "data": html_lib.unescape(m.group(1))})
    # <img src="data:image/...">
    for i, m in enumerate(re.finditer(
        r'<img\b[^>]*\bsrc\s*=\s*["\'](data:image/[^;]+;base64,[^"\']+)["\'][^>]*>',
        html, re.S | re.I
    )):
        out.append({"name": f"img_src_{i}", "data": html_lib.unescape(m.group(1))})
    # raw base64 hidden inputs
    for m in re.finditer(
        r'<input\b[^>]*\bname\s*=\s*["\']([^"\']+)["\'][^>]*\bvalue\s*=\s*["\']([A-Za-z0-9+/=\s]{200,})["\'][^>]*>',
        html, re.S | re.I
    ):
        v = re.sub(r"\s+", "", m.group(2))
        try:
            base64.b64decode(v, validate=True)
            out.append({"name": m.group(1), "data": v})
        except Exception:
            pass
    return out


def fix_data_uri(d):
    if not d:
        return None
    if d.startswith("data:image"):
        return d
    try:
        bin_data = base64.b64decode(d, validate=True)
    except Exception:
        return None
    if bin_data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif bin_data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif bin_data[:6] in (b"GIF87a", b"GIF89a"):
        mime = "image/gif"
    else:
        mime = "image/jpeg"
    return f"data:{mime};base64,{d}"


def pick_photo_sign(html: str):
    imgs = all_images(html)
    photo, sign = None, None

    # Pass 1: name based
    for im in imgs:
        n = im["name"].lower()
        if not photo and re.search(r"(photo|img|image|pic)", n) \
                and not re.search(r"sign|sig", n):
            photo = im["data"]; continue
        if not sign and re.search(r"(sign|sig)", n):
            sign = im["data"]; continue

    # Pass 2: known names
    if not photo:
        for n in ["imgHid", "photoHid", "imageHid", "dlphoto",
                  "dlPhoto", "photo", "imgPhoto"]:
            v = extract_input_value(html, n)
            if v:
                photo = "data:image/jpeg;base64," + v; break
    if not sign:
        for n in ["sigHid", "signHid", "signatureHid",
                  "sign", "signature", "imgSign"]:
            v = extract_input_value(html, n)
            if v:
                sign = "data:image/png;base64," + v; break

    # Pass 3: पहले दो अलग images
    if not photo and imgs:
        photo = imgs[0]["data"]
    if not sign and imgs:
        for im in imgs:
            if im["data"] != photo:
                sign = im["data"]; break

    return {"photo": fix_data_uri(photo), "signature": fix_data_uri(sign)}


# ============================================================
#  Multipart builder
# ============================================================
def build_multipart(boundary: str, fields: list) -> bytes:
    parts = []
    for name, value in fields:
        parts.append(f"--{boundary}\r\n")
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        parts.append(f"{value}\r\n")
    parts.append(f"--{boundary}--\r\n")
    return "".join(parts).encode("utf-8")


# ============================================================
#  Result detection
# ============================================================
def is_dl_page(html: str, dlno: str = "") -> bool:
    if not html:
        return False
    if re.search(r'name=["\']dlno["\']', html, re.I):
        return False  # यह form page है
    if "driving licence number" in html.lower():
        return True
    if dlno and dlno.upper() in html.upper() and "date of birth" in html.lower():
        return True
    return False


def detect_error(html: str) -> str:
    low = html.lower()
    if "invalid captcha" in low or "captcha is invalid" in low:
        return "captcha_invalid"
    if "no record" in low or "record not found" in low:
        return "no_record"
    if "session expired" in low or "session timeout" in low:
        return "session_expired"
    if "invalid dl" in low or "invalid licence" in low:
        return "invalid_dl"
    return "unknown"


# ============================================================
#  Parse DL details from result HTML
# ============================================================
def parse_result(html: str, dlno: str = "") -> dict:
    addr = []
    m = re.search(r'Present Address\s*:\s*</td>(.*?)</table>', html,
                  re.S | re.I)
    if m:
        for l in re.findall(r'<td class="text-left">(.*?)</td>', m.group(1),
                            re.S | re.I):
            v = clean_text(l)
            if v:
                addr.append(v)

    cov = []
    for row in re.finditer(
        r'<td>\s*([A-Z0-9\-]{2,12})\s*</td>.*?<td>\s*<b class="control-label">\s*([^<]*)',
        html, re.S | re.I
    ):
        cov.append({"cov": row.group(1).strip(),
                    "issue_by": clean_text(row.group(2))})

    badges = []
    for b in re.findall(r'\)\s*([A-Z0-9/\-]{4,})\s*</div>', html, re.S | re.I):
        badges.append(b.strip())

    imgs = pick_photo_sign(html)

    return {
        "success": True,
        "dlno": dlno,
        "name": rx(r'class="text-right text-success">\s*Name\s*:\s*</td>\s*<td[^>]*>(.*?)</td>', html),
        "father_name": rx(r'class="text-right text-success">\s*Father[^<]*?Name\s*:\s*</td>\s*<td[^>]*>(.*?)</td>', html),
        "dob": rx(r'class="text-right text-success">\s*Date of Birth\s*:\s*</td>\s*<td[^>]*>(.*?)</td>', html),
        "blood_group": rx(r'class="text-right text-success">\s*Blood Group\s*:\s*</td>\s*<td[^>]*>(.*?)</td>', html),
        "category": rx(r'class="text-right text-success">\s*Category of the Driving Licence Holder\s*:\s*</td>\s*<td[^>]*>(.*?)</td>', html),
        "present_address": ", ".join(addr) if addr else None,
        "last_endorsed_state": rx(r'<b class="text-success">\s*State-\s*</b>\s*([^<]+)', html),
        "last_endorsed_rto": rx(r'<b class="text-success">\s*RTO\s*-\s*</b>\s*([^<]+)', html),
        "class_of_vehicles": cov,
        "validity": rx(r'Transport\s*:\s*</label>\s*</div>\s*<div[^>]*>(.*?)</div>', html),
        "badge_numbers": badges,
        "photo": imgs["photo"],
        "signature": imgs["signature"],
    }


# ============================================================
#  OCR
# ============================================================
def solve_captcha_with_ocr(img_bytes: bytes) -> str:
    if not OCR_OK:
        return ""
    try:
        raw = OCR.classification(img_bytes) or ""
    except Exception as e:
        print(f"[!] OCR error: {e}", flush=True)
        return ""
    clean = re.sub(r"[^A-Za-z0-9]", "", raw)
    return clean


# ============================================================
#  CORE: single attempt
# ============================================================
def attempt_once(dlno: str, dob: str,
                 state_code: str = "BR",
                 state_name: str = "Bihar",
                 st_name: str = "Maharashtra",
                 rto_name: str = "RTO,BORIVALI",
                 manual_captcha: str = "",
                 manual_token: str = "",
                 cookie_str: str = ""):
    """
    Return dict with either:
      {"success": True, ...fields...}   — DL found
      {"success": False, "error": "...", "stage": "...", "captcha": "..."} 
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Origin": "https://sarathi.parivahan.gov.in",
    })

    # Cookie preset (अगर दिया हो)
    if cookie_str:
        for pair in cookie_str.split(";"):
            if "=" in pair:
                k, v = pair.strip().split("=", 1)
                s.cookies.set(k.strip(), v.strip(),
                              domain="sarathi.parivahan.gov.in")

    log = []

    try:
        # -------- 0) state select --------
        try:
            r = s.post(BASE + "/stateSelectBean.do", data="stName=" + state_code,
                       headers={"content-type": "application/x-www-form-urlencoded",
                                "referer": BASE + "/stateSelection.do"},
                       timeout=20, allow_redirects=True)
            log.append({"state_select": r.status_code,
                        "state_cookie": bool(s.cookies.get("STATEID"))})
        except Exception as e:
            log.append({"state_select_err": str(e)})

        # -------- 1) form page → token --------
        r = s.get(BASE + "/envaction.do", timeout=30)
        log.append({"form_http": r.status_code})
        if r.status_code != 200:
            return {"success": False, "error": f"form HTTP {r.status_code}",
                    "stage": "form", "log": log}

        LAST_HTML["envaction"] = r.text
        LAST_HTML["cookies"] = dict(s.cookies)

        token = manual_token or extract_token(r.text)
        if not token:
            return {"success": False, "error": "token not found",
                    "stage": "token", "log": log}

        # -------- 2) captcha image --------
        r = s.get(BASE + "/jsp/common/captchaimage.jsp",
                  params={"_": int(time.time() * 1000)},
                  headers={"Referer": BASE + "/envaction.do"},
                  timeout=30)
        if r.status_code != 200 or len(r.content) < 100:
            return {"success": False, "error": "captcha fetch failed",
                    "stage": "captcha", "log": log}

        captcha_bytes_len = len(r.content)

        # -------- 3) OCR or manual --------
        if manual_captcha:
            captcha = manual_captcha
            ocr_raw = "(manual)"
        else:
            if not OCR_OK:
                return {"success": False, "error": "OCR unavailable",
                        "stage": "ocr", "log": log}
            try:
                ocr_raw = OCR.classification(r.content) or ""
            except Exception as oe:
                return {"success": False, "error": f"OCR error: {oe}",
                        "stage": "ocr", "log": log}
            captcha = re.sub(r"[^A-Za-z0-9]", "", ocr_raw)

        if len(captcha) < 3 or len(captcha) > 8:
            return {"success": False,
                    "error": f"bad captcha length ({len(captcha)})",
                    "stage": "ocr", "captcha": captcha,
                    "captcha_bytes": captcha_bytes_len,
                    "log": log}

        # -------- 4) getLastEndorsedRto --------
        try:
            r2 = s.post(BASE + "/getLastEndorsedRtoDLserReq.do?",
                        data={"dlno": dlno, "dob": dob,
                              "captchaByApplicant": captcha},
                        headers={
                            "accept": "application/json, text/javascript, */*; q=0.01",
                            "content-type":
                                "application/x-www-form-urlencoded; charset=UTF-8",
                            "referer": BASE + "/envaction.do",
                            "x-requested-with": "XMLHttpRequest",
                        },
                        timeout=30)
            log.append({"last_rto": r2.status_code, "body": r2.text[:150]})
        except Exception as e:
            log.append({"last_rto_err": str(e)})

        # -------- 5) envaction multipart POST --------
        boundary = "----WebKitFormBoundary" + base64.b16encode(
            os.urandom(12)).decode()

        fields = [
            ("capToDisp", ""),
            ("captchaByApplicant", ""),
            ("dlno", dlno),
            ("dob", dob),
            ("entCaptha", captcha),                # only once!
            ("PrivacyPolicyTermsofService", "true"),
            ("__checkbox_PrivacyPolicyTermsofService", "true"),
            ("dispDLDet", "Select"),
            ("applcatgDLserReq", "General"),
            ("PincodeDLserReq", ""),
            ("stateCodeDLTr", state_name),
            ("rtoCodeDLTr", "-1"),
            ("struts.token.name", "token"),
            ("token", token),
            ("reset", "formsubmit"),
            ("s4msg", ""),
            ("rtoNameSelPreAppl", ""),
            ("dlno1", ""),
            ("applnotransreq", ""),
            ("dob1", ""),
            ("stEndName", st_name),
            ("rtoEndName", rto_name),
            ("ApplFullNameDLSReq", ""),
            ("isMatch", ""),
            ("firstCap", "true"),
            ("CapPho", ""),
            ("idpchecked", ""),
            ("SelDiplomat", ""),
            ("scFaceAuthReqAiLib", ""),
            ("faceauthmodel",
             "https://sarathi.parivahan.gov.in/cdn-sarathi/models"),
            ("videoDevicesDetected", ""),
        ]

        body = build_multipart(boundary, fields)

        r = s.post(BASE + "/envaction.do", data=body,
                   headers={
                       "content-type": f"multipart/form-data; boundary={boundary}",
                       "referer": BASE + "/envaction.do",
                   },
                   timeout=60)
        log.append({"submit_http": r.status_code, "len": len(r.text)})
        LAST_HTML["submit"] = r.text
        LAST_HTML["cookies"] = dict(s.cookies)

        # -------- 6) result check --------
        if is_dl_page(r.text, dlno):
            result = parse_result(r.text, dlno)
            # अगर असली fields खाली हैं → fail
            if not result.get("name") and not result.get("dob"):
                return {"success": False,
                        "error": "result page मिला पर fields खाली",
                        "stage": "parse_empty",
                        "captcha": captcha,
                        "log": log}
            result["captcha"] = captcha
            result["ocr_raw"] = ocr_raw
            result["log"] = log
            return result

        err = detect_error(r.text)
        return {"success": False,
                "error": f"result page नहीं मिला ({err})",
                "stage": err,
                "captcha": captcha,
                "ocr_raw": ocr_raw,
                "log": log}

    except requests.exceptions.Timeout:
        return {"success": False, "error": "timeout", "log": log}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"network: {e}", "log": log}
    except Exception as e:
        return {"success": False,
                "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()[:600],
                "log": log}


# ============================================================
#  CORE: retry loop
# ============================================================
def fetch_dl(dlno: str, dob: str,
             state_code: str = "BR",
             state_name: str = "Bihar",
             st_name: str = "Maharashtra",
             rto_name: str = "RTO,BORIVALI",
             max_attempts: int = 10,
             debug: bool = False) -> dict:

    attempts = []
    started = datetime.utcnow().isoformat() + "Z"

    if not OCR_OK:
        return {"success": False,
                "error": "OCR engine (ddddocr) load नहीं हुआ",
                "ocr_engine": "none",
                "attempts": attempts}

    for i in range(1, max_attempts + 1):
        res = attempt_once(dlno, dob, state_code, state_name, st_name, rto_name)

        attempts.append({
            "attempt": i,
            "success": res.get("success"),
            "error": res.get("error"),
            "stage": res.get("stage"),
            "captcha": res.get("captcha"),
            "ocr_raw": res.get("ocr_raw"),
            "log": res.get("log"),
        })

        if res.get("success"):
            res["attempts"] = attempts
            res["ocr_engine"] = "ddddocr"
            res["started_at"] = started
            res["finished_at"] = datetime.utcnow().isoformat() + "Z"
            if not debug:
                res.pop("_debug", None)
            return res

        # "No record" जैसी non-retryable errors पर रुक जाएँ
        stage = res.get("stage", "")
        if stage in ("no_record", "invalid_dl"):
            break

        time.sleep(1.0)

    return {
        "success": False,
        "error": f"{max_attempts} attempts में DL details नहीं मिलीं",
        "ocr_engine": "ddddocr",
        "attempts": attempts,
        "started_at": started,
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "hint": "/api/debug?which=submit&format=text पर असली response देखें",
    }


# ============================================================
#  Routes
# ============================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/dl", methods=["GET", "POST"])
def api_dl():
    src = request.form if request.method == "POST" else request.args

    dlno = (src.get("dlno") or "").strip().upper()
    dob = (src.get("dob") or "").strip()

    if not dlno or not re.match(r"^\d{2}-\d{2}-\d{4}$", dob):
        return jsonify({"success": False,
                        "error": "dlno और dob (DD-MM-YYYY) ज़रूरी हैं"}), 400

    state_name = src.get("stateCodeDLTr", "Bihar")
    state_code = src.get("state_code", "BR")
    st_name = src.get("stEndName", "Maharashtra")
    rto_name = src.get("rtoEndName", "RTO,BORIVALI")

    try:
        max_try = int(src.get("max_try", "10"))
    except ValueError:
        max_try = 10
    max_try = max(1, min(max_try, 15))

    debug = src.get("debug", "0") in ("1", "true", "yes")

    return jsonify(fetch_dl(dlno, dob, state_code, state_name,
                            st_name, rto_name, max_try, debug))


@app.route("/api/debug")
def api_debug():
    which = request.args.get("which", "submit")
    html = LAST_HTML.get(which, "")
    if not html:
        return jsonify({"error": f"कोई '{which}' response save नहीं"}), 404

    if request.args.get("format") == "text":
        from flask import Response
        soup_text = re.sub(r"<[^>]+>", " ", html)
        soup_text = re.sub(r"\s+", " ", soup_text)
        return Response(soup_text[:8000], mimetype="text/plain; charset=utf-8")

    return jsonify({
        "length": len(html),
        "has_form": bool(re.search(r'name=["\']dlno["\']', html, re.I)),
        "has_dl_head": "Driving Licence Number" in html,
        "detected_error": detect_error(html),
        "cookies": LAST_HTML.get("cookies", {}),
        "images_found": [
            {"name": im["name"], "len": len(im["data"]),
             "head": im["data"][:60]}
            for im in all_images(html)
        ],
    })


@app.route("/api/ocr-test", methods=["POST"])
def api_ocr_test():
    if "image" not in request.files:
        return jsonify({"error": "image field चाहिए"}), 400
    img = request.files["image"].read()
    if not img:
        return jsonify({"error": "empty file"}), 400
    if not OCR_OK:
        return jsonify({"error": "OCR unavailable"}), 503
    try:
        raw = OCR.classification(img) or ""
        clean = re.sub(r"[^A-Za-z0-9]", "", raw)
        return jsonify({"raw": raw, "clean": clean})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "ocr_ok": OCR_OK,
                    "time": datetime.utcnow().isoformat() + "Z"}), 200


@app.errorhandler(404)
def nf(_): return jsonify({"error": "not found"}), 404

@app.errorhandler(500)
def se(e): return jsonify({"error": "internal error", "detail": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)