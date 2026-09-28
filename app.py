# ============================================================
#  app.py — Sarathi DL Details Fetcher (FIXED)
#  FREE OCR (ddddocr) + Flask + Render ready
# ============================================================

import os
import re
import time
import json
import traceback
from datetime import datetime

from flask import Flask, request, jsonify, render_template, Response
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


app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

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
    "Upgrade-Insecure-Requests": "1",
}

# debug: अंतिम response HTML को memory में रखें
LAST_HTML = {"envaction": "", "submit": ""}


# ============================================================
#  Session
# ============================================================
def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ============================================================
#  Token extractor
# ============================================================
def extract_token(html: str):
    try:
        soup = BeautifulSoup(html, "html.parser")
        inp = soup.find("input", {"name": "token"})
        if inp and inp.get("value"):
            return inp["value"].strip()
    except Exception:
        pass
    for pat in (
        r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']',
        r'value=["\']([^"\']+)["\'][^>]*name=["\']token["\']',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1).strip()
    return None


# ============================================================
#  STRICT: क्या यह असली DL result page है?
# ============================================================
def is_dl_page(html: str, dlno: str = "") -> bool:
    """
    असली result page में ये चीज़ें ज़रूरी हैं:
      1. DL number जो हमने भेजा था वो page में मौजूद हो
      2. "Driving Licence Number" heading हो
      3. Input form (name="dlno") मौजूद न हो (वरना वह form page है)
    """
    if not html:
        return False

    dlno_up = (dlno or "").upper()

    # 1) DL number मौजूद?
    if dlno_up and dlno_up not in html.upper():
        return False

    # 2) form page markers (input fields) न हों
    if re.search(r'name=["\']dlno["\']', html, re.I):
        return False
    if re.search(r'id=["\']dlno["\']', html, re.I):
        return False

    soup = BeautifulSoup(html, "html.parser")

    # 3) "Driving Licence Number" heading/table कहीं हो
    for t in soup.find_all(["td", "th", "div", "span", "h2", "h3", "h4"]):
        txt = t.get_text(" ", strip=True).lower()
        if "driving licence number" in txt:
            return True

    # 4) fallback — DL number किसी <td> में हो और "Date of Birth" heading भी हो
    if dlno_up:
        for td in soup.find_all("td"):
            if dlno_up in td.get_text(" ", strip=True).upper():
                return True

    return False


# ============================================================
#  Find the DL result table
# ============================================================
def find_result_table(soup: BeautifulSoup, dlno: str):
    dlno_up = (dlno or "").upper()
    candidates = []

    for table in soup.find_all("table"):
        txt = table.get_text(" ", strip=True)
        txt_up = txt.upper()
        score = 0
        if dlno_up and dlno_up in txt_up:
            score += 3
        if "driving licence number" in txt.lower():
            score += 3
        if "date of birth" in txt.lower():
            score += 2
        if "class of vehicle" in txt.lower():
            score += 1
        if score >= 4:
            candidates.append((score, table))

    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


# ============================================================
#  Label → value extraction (strict)
# ============================================================
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).rstrip(":").lower()


def _val(root, label: str) -> str:
    """
    root के अंदर label वाले cell की value निकालें।
    Exact match पहले, फिर "contains" match।
    """
    lab = _norm(label)

    # pass 1: exact match
    for cell in root.find_all(["td", "th"]):
        if _norm(cell.get_text(" ", strip=True)) == lab:
            nxt = cell.find_next_sibling("td")
            if nxt:
                v = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
                if v:
                    return v

    # pass 2: label ends with ':' or has label + value in same row
    for cell in root.find_all(["td", "th"]):
        txt = _norm(cell.get_text(" ", strip=True))
        if txt.startswith(lab):
            nxt = cell.find_next_sibling("td")
            if nxt:
                v = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
                if v and _norm(v) != lab:
                    return v

    # pass 3: contains (last resort)
    for cell in root.find_all(["td", "th"]):
        txt = _norm(cell.get_text(" ", strip=True))
        if lab in txt and len(txt) < len(lab) + 15:
            nxt = cell.find_next_sibling("td")
            if nxt:
                v = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
                if v and _norm(v) != lab:
                    return v
    return ""


# ============================================================
#  Parse DL details
# ============================================================
def _abs_url(u: str) -> str:
    if not u:
        return ""
    if u.startswith("data:"):
        return u
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("/"):
        return "https://sarathi.parivahan.gov.in" + u
    return BASE + u.lstrip("./")


def _is_logo(src: str) -> bool:
    """header/footer के logos filter करें"""
    if not src:
        return True
    low = src.lower()
    bad = (
        "/images/logo/", "ministry-nic", "parivahan-logo",
        "digital_logo", "nhai", "emblem", "footer",
        ".ico", ".svg",
    )
    return any(b in low for b in bad)


def parse_dl(html: str, dlno: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")

    table = find_result_table(soup, dlno)
    root = table if table else soup

    # ---- photo / signature (सिर्फ result table के अंदर) ----
    photo, sign = "", ""
    for img in root.find_all("img"):
        src = img.get("src", "") or ""
        if _is_logo(src):
            continue
        if src.startswith("data:image") and "jpeg" not in src and "png" not in src and "jpg" not in src:
            # allow all data: URIs
            pass
        ctx = " ".join([
            img.get("id", "") or "",
            " ".join(img.get("class", []) or []),
            img.get("alt", "") or "",
        ]).lower()

        if not sign and ("sign" in ctx or "sign" in src.lower()):
            sign = src
        elif not photo and ("photo" in ctx or "photo" in src.lower() or src.startswith("data:image")):
            photo = src
        elif not photo:
            photo = src
        elif not sign:
            sign = src

    # अगर photo/sign न मिले तो पूरे page में देखें (logos filter करके)
    if not photo:
        for img in soup.find_all("img"):
            src = img.get("src", "") or ""
            if _is_logo(src):
                continue
            if src.startswith("data:image"):
                photo = src
                break

    return {
        "success":             True,
        "dlno":                _val(root, "Driving Licence Number") or dlno,
        "name":                _val(root, "Name"),
        "father_name":         _val(root, "Father's Name") or _val(root, "Father Name"),
        "dob":                 _val(root, "Date of Birth"),
        "blood_group":         _val(root, "Blood Group"),
        "category":            _val(root, "Category"),
        "present_address":     _val(root, "Present Address") or _val(root, "Address"),
        "permanent_address":   _val(root, "Permanent Address"),
        "last_endorsed_state": _val(root, "State"),
        "last_endorsed_rto":   _val(root, "RTO"),
        "class_of_vehicles":   _val(root, "Class of Vehicle") or _val(root, "COV"),
        "validity":            _val(root, "Validity"),
        "badge_numbers":       _val(root, "Badge"),
        "photo":               _abs_url(photo),
        "signature":           _abs_url(sign),
    }


# ============================================================
#  Core: fetch DL details
# ============================================================
def fetch_dl(
    dlno: str,
    dob: str,
    state: str = "Bihar",
    rto_code: str = "BR-01",
    st_name: str = "Bihar",
    rto_name: str = "",
    max_attempts: int = 10,
) -> dict:
    attempts = []
    started = datetime.utcnow().isoformat() + "Z"

    if not OCR_OK:
        return {
            "success":    False,
            "error":      "OCR engine (ddddocr) load नहीं हुआ",
            "ocr_engine": "none",
            "attempts":   attempts,
        }

    for attempt in range(1, max_attempts + 1):
        s = new_session()
        info = {"attempt": attempt}

        try:
            # 1) form load → token
            r = s.get(BASE + "envaction.do", timeout=30)
            info["form_http"] = r.status_code
            if r.status_code != 200:
                info["error"] = f"form HTTP {r.status_code}"
                attempts.append(info)
                continue

            LAST_HTML["envaction"] = r.text

            token = extract_token(r.text)
            if not token:
                info["error"] = "token नहीं मिला"
                attempts.append(info)
                continue
            info["token"] = token[:12] + "…"

            # 2) captcha image
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

            # 3) OCR
            try:
                raw = OCR.classification(r.content) or ""
            except Exception as ocr_err:
                info["error"] = f"OCR error: {ocr_err}"
                attempts.append(info)
                continue

            captcha = re.sub(r"[^A-Za-z0-9]", "", raw)
            info["captcha_raw"]   = raw
            info["captcha_clean"] = captcha

            if len(captcha) < 3 or len(captcha) > 8:
                info["error"] = "captcha length unexpected"
                attempts.append(info)
                continue

            # 4) submit
            post_data = {
                "capToDisp":                              "",
                "captchaByApplicant":                     "",
                "dlno":                                   dlno,
                "dob":                                    dob,
                "entCaptha":                              captcha,
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
            LAST_HTML["submit"] = r.text

            # 5) STRICT check
            if is_dl_page(r.text, dlno):
                result = parse_dl(r.text, dlno)
                result["attempts"]    = attempts + [info]
                result["ocr_engine"]  = "ddddocr"
                result["started_at"]  = started
                result["finished_at"] = datetime.utcnow().isoformat() + "Z"

                # यदि असली fields खाली हैं → failure मान लो
                if not result.get("name") and not result.get("dob"):
                    info["error"] = "result page मिला पर fields खाली"
                    attempts.append(info)
                    time.sleep(1)
                    continue

                return result

            # असली result नहीं → error पकड़ें
            if "Invalid Captcha" in r.text or "invalid captcha" in r.text.lower():
                info["error"] = "captcha गलत"
            elif "No record found" in r.text or "not found" in r.text.lower():
                info["error"] = "DL record नहीं मिला"
            else:
                info["error"] = "result page नहीं मिला"
            attempts.append(info)

            time.sleep(1)

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
        "error":       f"{max_attempts} attempts में DL details नहीं मिलीं",
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
    dlno = (request.args.get("dlno") or "").strip().upper()
    dob  = (request.args.get("dob")  or "").strip()

    if not dlno or not dob:
        return jsonify({"success": False, "error": "dlno और dob ज़रूरी हैं"}), 400

    if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", dob):
        return jsonify({"success": False, "error": "dob format DD-MM-YYYY"}), 400

    state    = request.args.get("state", "Bihar")
    rto_code = request.args.get("rto_code", "BR-01")
    st_name  = request.args.get("st_name", state)
    rto_name = request.args.get("rto_name", "")

    try:
        max_try = int(request.args.get("max_try", "10"))
    except ValueError:
        max_try = 10
    max_try = max(1, min(max_try, 15))

    return jsonify(fetch_dl(dlno, dob, state, rto_code, st_name, rto_name, max_try))


@app.route("/api/debug")
def api_debug():
    """अंतिम response HTML देखें (समस्या diagnose करने के लिए)"""
    which = request.args.get("which", "submit")
    html = LAST_HTML.get(which, "")
    if not html:
        return jsonify({"error": "कोई response नहीं मिला"}), 404

    # plain text preview
    if request.args.get("format") == "text":
        text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
        return Response(text[:5000], mimetype="text/plain")

    # keywords
    return jsonify({
        "length":       len(html),
        "has_form":     bool(re.search(r'name=["\']dlno["\']', html, re.I)),
        "has_dlno":     "MH0220100024875" in html.upper(),
        "has_dl_head":  "Driving Licence Number" in html,
        "has_captcha_err": "Invalid Captcha" in html or "invalid captcha" in html.lower(),
        "has_no_record": "No record found" in html or "not found" in html.lower(),
        "title":        (BeautifulSoup(html, "html.parser").title.string
                         if BeautifulSoup(html, "html.parser").title else None),
        "hint":         "format=text जोड़ें text देखने के लिए",
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
    return jsonify({
        "status": "ok",
        "ocr_ok": OCR_OK,
        "time":   datetime.utcnow().isoformat() + "Z",
    }), 200


@app.errorhandler(404)
def nf(_):
    return jsonify({"error": "not found"}), 404


@app.errorhandler(500)
def se(e):
    return jsonify({"error": "internal error", "detail": str(e)}), 500


# ============================================================
#  Entry
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
