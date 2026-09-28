# ============================================================
#  app.py — Sarathi DL Details Fetcher
#  FREE OCR (ddddocr) + Flask + Render ready
# ============================================================

import os
import re
import time
import json
import base64
import traceback
from datetime import datetime

from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup

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


# ============================================================
#  Flask app
# ============================================================
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True


# ============================================================
#  Constants
# ============================================================
BASE = "https://sarathi.parivahan.gov.in/sarathiservice/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/153.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": "https://sarathi.parivahan.gov.in",
    "Referer": BASE + "envaction.do",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# ============================================================
#  Helper: new session
# ============================================================
def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ============================================================
#  Helper: extract Struts token from HTML
# ============================================================
def extract_token(html: str) -> str | None:
    # 1) BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
        inp = soup.find("input", {"name": "token"})
        if inp and inp.get("value"):
            return inp["value"].strip()
    except Exception:
        pass

    # 2) regex fallback
    for pat in (
        r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']',
        r'value=["\']([^"\']+)["\'][^>]*name=["\']token["\']',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1).strip()
    return None


# ============================================================
#  Helper: is this a real DL-detail page?
# ============================================================
def is_dl_page(html: str) -> bool:
    if not html:
        return False
    checks = [
        ("Date of Birth" in html and "Class of Vehicle" in html),
        ("Driving Licence Details" in html),
        ("DL Details" in html and "Date of Birth" in html),
    ]
    return any(checks)


# ============================================================
#  Helper: pull value next to a label
# ============================================================
def _val(soup: BeautifulSoup, label: str) -> str:
    label_lc = label.lower()
    # pass 1: exact-ish match
    for cell in soup.find_all(["td", "th"]):
        txt = cell.get_text(" ", strip=True).lower()
        if label_lc in txt:
            nxt = cell.find_next_sibling("td")
            if nxt:
                return re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
    # pass 2: contains (fallback)
    for cell in soup.find_all(["td", "th"]):
        txt = cell.get_text(" ", strip=True).lower()
        if any(w in txt for w in label_lc.split()):
            nxt = cell.find_next_sibling("td")
            if nxt:
                v = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
                if v:
                    return v
    return ""


# ============================================================
#  Helper: parse DL details from HTML
# ============================================================
def parse_dl(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # ---- photo / signature ----
    photo, sign = "", ""
    for img in soup.find_all("img"):
        src = img.get("src", "") or ""
        if not src:
            continue
        ctx = " ".join([
            img.get("id", "") or "",
            " ".join(img.get("class", []) or []),
            img.get("alt", "") or "",
        ]).lower()

        if not sign and ("sign" in ctx or "sign" in src.lower()):
            sign = src
        elif not photo:
            photo = src
        elif not sign:
            sign = src

    # ---- convert relative URLs to absolute ----
    def _abs(u: str) -> str:
        if not u:
            return ""
        if u.startswith("data:"):
            return u
        if u.startswith("http://") or u.startswith("https://"):
            return u
        if u.startswith("/"):
            return "https://sarathi.parivahan.gov.in" + u
        return BASE + u.lstrip("./")

    return {
        "success":             True,
        "name":                _val(soup, "Name"),
        "father_name":         _val(soup, "Father's Name") or _val(soup, "Father Name"),
        "dob":                 _val(soup, "Date of Birth"),
        "blood_group":         _val(soup, "Blood Group"),
        "category":            _val(soup, "Category"),
        "present_address":     _val(soup, "Present Address") or _val(soup, "Address"),
        "permanent_address":   _val(soup, "Permanent Address"),
        "last_endorsed_state": _val(soup, "State"),
        "last_endorsed_rto":   _val(soup, "RTO"),
        "class_of_vehicles":   _val(soup, "Class of Vehicle") or _val(soup, "COV"),
        "validity":            _val(soup, "Validity"),
        "badge_numbers":       _val(soup, "Badge"),
        "photo":               _abs(photo),
        "signature":           _abs(sign),
    }


# ============================================================
#  Core: fetch DL details with retry loop
# ============================================================
def fetch_dl(
    dlno: str,
    dob: str,
    state: str = "Bihar",
    rto_code: str = "BR-01",
    st_name: str = "Bihar",
    rto_name: str = "",
    max_attempts: int = 8,
) -> dict:
    attempts = []
    started = datetime.utcnow().isoformat() + "Z"

    if not OCR_OK:
        return {
            "success":     False,
            "error":       "OCR engine (ddddocr) load नहीं हुआ",
            "ocr_engine":  "none",
            "attempts":    attempts,
            "started_at":  started,
        }

    for attempt in range(1, max_attempts + 1):
        s = new_session()
        info = {"attempt": attempt}

        try:
            # -------- 1) load form page → token --------
            r = s.get(BASE + "envaction.do", timeout=30, allow_redirects=True)
            info["form_http"] = r.status_code
            if r.status_code != 200:
                info["error"] = f"form HTTP {r.status_code}"
                attempts.append(info)
                continue

            token = extract_token(r.text)
            if not token:
                info["error"] = "token नहीं मिला"
                attempts.append(info)
                continue
            info["token"] = token[:12] + "…"

            # -------- 2) download captcha --------
            r = s.get(
                BASE + "jsp/common/captchaimage.jsp",
                params={"_": int(time.time() * 1000)},
                timeout=30,
                headers={"Referer": BASE + "envaction.do"},
            )
            if r.status_code != 200 or len(r.content) < 100:
                info["error"] = "captcha fetch failed"
                attempts.append(info)
                continue
            info["captcha_bytes"] = len(r.content)

            # -------- 3) OCR with ddddocr --------
            try:
                raw = OCR.classification(r.content) or ""
            except Exception as ocr_err:
                info["error"] = f"OCR error: {ocr_err}"
                attempts.append(info)
                continue

            captcha = re.sub(r"[^A-Za-z0-9]", "", raw)
            info["captcha_raw"]  = raw
            info["captcha_clean"] = captcha

            if len(captcha) < 3 or len(captcha) > 8:
                info["error"] = "captcha length unexpected"
                attempts.append(info)
                continue

            # -------- 4) submit form --------
            post_data = {
                "capToDisp":                              "",
                "captchaByApplicant":                     "",
                "dlno":                                   dlno,
                "dob":                                    dob,
                "entCaptha":                              captcha,   # only ONE key
                "PrivacyPolicyTermsofService":            "true",
                "__checkbox_PrivacyPolicyTermsofService": "true",
                "dispDLDet":                              "Select",
                "applcatgDLserReq":                       "General",
                "PincodeDLserReq":                        "",
                "stateCodeDLTr":                          state,
                "rtoCodeDLTr":                            rto_code,
                "struts.token.name":                      "token",
                "token":                                  token,
                "reset":                                  "formsubmit",
                "s4msg":                                  "",
                "firstCap":                               "true",
                "faceauthmodel":                          "https://sarathi.parivahan.gov.in/cdn-sarathi/models",
                "stEndName":                              st_name,
                "rtoEndName":                             rto_name,
            }

            r = s.post(BASE + "envaction.do", data=post_data, timeout=45)
            info["submit_http"] = r.status_code

            if is_dl_page(r.text):
                result = parse_dl(r.text)
                result["attempts"]    = attempts + [info]
                result["ocr_engine"]  = "ddddocr"
                result["started_at"]  = started
                result["finished_at"] = datetime.utcnow().isoformat() + "Z"
                return result

            info["error"] = "captcha गलत या DL page नहीं मिला"
            attempts.append(info)

            # अगले attempt से पहले थोड़ा रुकें (rate limit से बचाव)
            time.sleep(1.0)

        except requests.exceptions.Timeout:
            info["error"] = "timeout"
            attempts.append(info)
        except requests.exceptions.RequestException as e:
            info["error"] = f"network: {e}"
            attempts.append(info)
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {e}"
            info["trace"] = traceback.format_exc()[:500]
            attempts.append(info)

    return {
        "success":     False,
        "error":       f"{max_attempts} attempts में captcha match नहीं हुआ",
        "ocr_engine":  "ddddocr",
        "attempts":    attempts,
        "started_at":  started,
        "finished_at": datetime.utcnow().isoformat() + "Z",
    }


# ============================================================
#  Routes
# ============================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/dl")
def api_dl():
    """
    Query params:
      dlno      (required)
      dob       (required, DD-MM-YYYY)
      state     (default Bihar)
      rto_code  (default BR-01)
      st_name   (default = state)
      rto_name
      max_try   (default 8, max 12)
    """
    dlno = (request.args.get("dlno") or "").strip().upper()
    dob  = (request.args.get("dob")  or "").strip()

    if not dlno or not dob:
        return jsonify({
            "success": False,
            "error":   "dlno और dob ज़रूरी हैं",
        }), 400

    # basic validation
    if not re.fullmatch(r"[A-Z]{2}[0-9A-Z]{8,20}", dlno):
        # allow looseness but warn
        pass
    if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", dob):
        return jsonify({
            "success": False,
            "error":   "dob का format DD-MM-YYYY होना चाहिए",
        }), 400

    state    = request.args.get("state", "Bihar")
    rto_code = request.args.get("rto_code", "BR-01")
    st_name  = request.args.get("st_name", state)
    rto_name = request.args.get("rto_name", "")

    try:
        max_try = int(request.args.get("max_try", "8"))
    except ValueError:
        max_try = 8
    max_try = max(1, min(max_try, 12))

    result = fetch_dl(dlno, dob, state, rto_code, st_name, rto_name, max_try)
    return jsonify(result)


@app.route("/api/ocr-test", methods=["POST"])
def api_ocr_test():
    """कैप्चा image upload करके OCR टेस्ट करें"""
    if "image" not in request.files:
        return jsonify({"error": "image field चाहिए (multipart/form-data)"}), 400

    img = request.files["image"].read()
    if not img:
        return jsonify({"error": "empty file"}), 400

    if not OCR_OK:
        return jsonify({"error": "OCR engine unavailable"}), 503

    try:
        raw = OCR.classification(img) or ""
        clean = re.sub(r"[^A-Za-z0-9]", "", raw)
        return jsonify({"raw": raw, "clean": clean})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/healthz")
def healthz():
    return jsonify({
        "status":     "ok",
        "ocr_ok":     OCR_OK,
        "time":       datetime.utcnow().isoformat() + "Z",
    }), 200


@app.errorhandler(404)
def nf(_):
    return jsonify({"error": "not found"}), 404


@app.errorhandler(500)
def se(e):
    return jsonify({"error": "internal error", "detail": str(e)}), 500


# ============================================================
#  Entrypoint
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
