# ============================================================
#  app.py — Sarathi DL Fetcher (v4 — multipart fix)
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Origin": "https://sarathi.parivahan.gov.in",
    "Upgrade-Insecure-Requests": "1",
}

# State code map (State name → 2-letter code)
STATE_CODES = {
    "Maharashtra": "MH", "Bihar": "BR", "Delhi": "DL",
    "Karnataka": "KA", "Tamil Nadu": "TN", "Uttar Pradesh": "UP",
    "Gujarat": "GJ", "Rajasthan": "RJ", "West Bengal": "WB",
    "Madhya Pradesh": "MP", "Kerala": "KL", "Punjab": "PB",
    "Haryana": "HR", "Telangana": "TG", "Andhra Pradesh": "AP",
    "Odisha": "OD", "Assam": "AS", "Jharkhand": "JH",
    "Uttarakhand": "UK", "Himachal Pradesh": "HP", "Goa": "GA",
}

# debug
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
#  STATE SELECTION — सही तरीका (stateSelectBean.do + stName)
# ============================================================
def select_state(session: requests.Session, state_code: str) -> bool:
    """
    Working curl:
      POST https://sarathi.parivahan.gov.in/sarathiservice/stateSelectBean.do
      body: stName=BR
      referer: stateSelection.do
    """
    try:
        # 1) पहले selector page visit करें → JSESSIONID मिले
        r = session.get(BASE + "stateSelection.do", timeout=20)
        if r.status_code != 200:
            return False

        # 2) POST stateSelectBean.do with stName
        r2 = session.post(
            BASE + "stateSelectBean.do",
            data={"stName": state_code},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": BASE + "stateSelection.do",
                "Origin": "https://sarathi.parivahan.gov.in",
            },
            timeout=20,
            allow_redirects=True,
        )

        # 3) STATEID cookie मिली?
        ok = "STATEID" in session.cookies
        return ok
    except Exception as e:
        print(f"[!] select_state: {e}", flush=True)
        return False


# ============================================================
#  STRICT: DL result page detect
# ============================================================
def is_dl_page(html: str, dlno: str = "") -> bool:
    """
    असली DL details page में ये ज़रूरी हैं:
      - "Personal Details and Particulars of existing Licence" heading
      - DL number वही हो जो भेजा था
      - "Confirmed that the above Driving Licence details are mine" prompt
    """
    if not html:
        return False

    soup = BeautifulSoup(html, "html.parser")
    body_text = soup.get_text(" ", strip=True)

    # असली result page में यह heading ज़रूर होती है (form में नहीं दिखती)
    if "Personal Details and Particulars of existing Licence" not in body_text:
        # यह heading result page पर ही आती है जब DL मिल जाता है
        # लेकिन यह form में भी "display:none" के साथ है — पर text content में दिखेगा
        pass

    # ज़्यादा reliable: "Confirmed that the above Driving Licence details are mine"
    # + <select name="dispDLDet"> वाला section दिखने लगे (यानी dlSerReqPersDet खुला हो)
    if "dispDLDet" in html and "dlSerReqPersDet" in html:
        # पता लगाएँ कि dlSerReqPersDet का display none नहीं है
        # छोटा heuristic:
        if re.search(r'id=["\']dlSerReqPersDet["\'][^>]*style=["\'][^"\']*display\s*:\s*none', html, re.I):
            return False  # hidden है → form page
        # visible है → result
        if "Confirmed that the above Driving Licence details are mine" in body_text:
            # और DL number भी दिख रहा हो
            if dlno.upper() in html.upper():
                return True

    # backup: असली result में यह table मिलती है
    if "Class of Vehicles" in body_text and "Validity Period" in body_text:
        if "dispDLDet" in html and dlno.upper() in html.upper():
            if not re.search(r'id=["\']dlSerReqPersDet["\'][^>]*style=["\'][^"\']*display\s*:\s*none', html, re.I):
                return True

    return False


# ============================================================
#  Detect error
# ============================================================
def detect_error(html: str) -> str:
    low = html.lower()
    if "invalid captcha" in low or "captcha is invalid" in low:
        return "captcha_invalid"
    if "please enter captcha" in low:
        return "captcha_empty"
    if "no record found" in low or "no data found" in low:
        return "no_record"
    if "session expired" in low or "session timeout" in low:
        return "session_expired"
    if "please select the state" in low:
        return "state_not_selected"
    if "invalid dl" in low or "invalid licence" in low or "not valid" in low:
        return "invalid_dl"
    if "dob" in low and "not match" in low:
        return "dob_mismatch"
    return "unknown"


def html_preview(html: str, max_len: int = 400) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        texts = []
        for sel in [".error", ".errormessage", ".alert", "#errormsg",
                    ".success", ".info", "div[class*='error']",
                    "div[class*='Error']", "span[class*='error']"]:
            for el in soup.select(sel):
                t = el.get_text(" ", strip=True)
                if t:
                    texts.append(t[:200])
        if texts:
            return " | ".join(texts)[:max_len]
        body = soup.find("body")
        if body:
            t = re.sub(r"\s+", " ", body.get_text(" ", strip=True))
            return t[:max_len]
    except Exception:
        pass
    return re.sub(r"<[^>]+>", " ", html)[:max_len]


# ============================================================
#  Parse DL details from visible result section
# ============================================================
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).rstrip(":").lower()


def _val_from_pair(root, label: str) -> str:
    """label cell के next sibling td की value"""
    lab = _norm(label)
    for cell in root.find_all(["td", "th"]):
        if _norm(cell.get_text(" ", strip=True)) == lab:
            nxt = cell.find_next_sibling("td")
            if nxt:
                v = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
                if v:
                    return v
    # prefix / contains
    for cell in root.find_all(["td", "th"]):
        txt = _norm(cell.get_text(" ", strip=True))
        if txt.startswith(lab) and len(txt) < len(lab) + 20:
            nxt = cell.find_next_sibling("td")
            if nxt:
                v = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
                if v and _norm(v) != lab:
                    return v
    return ""


def _abs_url(u: str) -> str:
    if not u:
        return ""
    if u.startswith("data:"):
        return u
    if u.startswith("http"):
        return u
    if u.startswith("/"):
        return "https://sarathi.parivahan.gov.in" + u
    return BASE + u.lstrip("./")


def _is_logo(src: str) -> bool:
    if not src:
        return True
    low = src.lower()
    for b in ("/images/logo/", "ministry-nic", "parivahan-logo",
              "digital_logo", "nhai", "emblem", "footer", ".ico", ".svg",
              "nophoto", "nosignature", "refresh", "calendar"):
        if b in low:
            return True
    return False


def parse_dl(html: str, dlno: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # परिणाम section ढूँढें
    result_section = soup.find(id="dlSerReqPersDet")
    if result_section is None:
        result_section = soup  # fallback

    photo, sign = "", ""
    for img in result_section.find_all("img"):
        src = img.get("src", "") or ""
        if _is_logo(src):
            continue
        if src.startswith("data:image"):
            if not photo:
                photo = src
            elif not sign:
                sign = src
        else:
            # relative photo URL हो सकती है
            src_low = src.lower()
            if "photo" in src_low and not photo:
                photo = src
            elif "sign" in src_low and not sign:
                sign = src
            elif not photo:
                photo = src
            elif not sign:
                sign = src

    name = _val_from_pair(result_section, "Name")
    swd  = _val_from_pair(result_section, "S/W/D of") or _val_from_pair(result_section, "S/W/D")
    dob  = _val_from_pair(result_section, "Date of Birth")

    # State / RTO
    state = _val_from_pair(result_section, "State")
    rto   = _val_from_pair(result_section, "RTO")

    return {
        "success":             True,
        "dlno":                dlno,
        "name":                name,
        "father_name":         swd,
        "dob":                 dob,
        "blood_group":         _val_from_pair(result_section, "Blood Group"),
        "category":            _val_from_pair(result_section, "Category"),
        "present_address":     _val_from_pair(result_section, "Present Address") or _val_from_pair(result_section, "Address"),
        "last_endorsed_state": state,
        "last_endorsed_rto":   rto,
        "class_of_vehicles":   _val_from_pair(result_section, "Class of Vehicle") or _val_from_pair(result_section, "COV"),
        "validity":            _val_from_pair(result_section, "Validity"),
        "badge_numbers":       _val_from_pair(result_section, "Badge"),
        "photo":               _abs_url(photo),
        "signature":           _abs_url(sign),
    }


# ============================================================
#  Build multipart body — DUPLICATE entCaptha + reset EMPTY
# ============================================================
def build_multipart_fields(token, captcha, dlno, dob, state, rto_code,
                           st_name, rto_name, state_iso="BR"):
    """
    Form में entCaptha दो बार है (visible + hidden)।
    reset field खाली होना चाहिए (Reset button = 'Clear All' नहीं भेजना)।
    """
    fields = [
        # header hidden fields
        ("serday", "28"),
        ("sermth", "9"),
        ("seryr", str(datetime.utcnow().year)),
        ("pincodeForIDPStateOfDL", ""),
        ("rtopinMappingReqd", ""),
        ("st_Cd_", state_iso),
        ("capToDisp", ""),
        ("captchaByApplicant", ""),
        ("dlno", dlno),
        ("dob", dob),

        # visible captcha input
        ("entCaptha", captcha),

        ("PrivacyPolicyTermsofService", "true"),
        ("__checkbox_PrivacyPolicyTermsofService", "true"),

        # result section defaults
        ("dispDLDet", "Select"),
        ("applcatgDLserReq", "General"),
        ("PincodeDLserReq", ""),
        ("stateCodeDLTr", state),
        ("rtoCodeDLTr", rto_code or "-1"),

        # submit button (हो सके तो)
        ("dlconfirm", "Proceed"),

        # token
        ("struts.token.name", "token"),
        ("token", token),

        # IMPORTANT: reset खाली, "Clear All" नहीं
        ("reset", ""),
        ("s4msg", ""),

        # दूसरा entCaptha (hidden) — same value भेजें
        ("entCaptha", captcha),

        # hidden defaults
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
        ("faceauthmodel", "https://sarathi.parivahan.gov.in/cdn-sarathi/models"),
        ("videoDevicesDetected", ""),

        # extra hidden inputs
        ("umfPresent", "false"),
        ("FaceAuthReq", "false"),
        ("StateName", state),
    ]
    return fields


# ============================================================
#  Core fetch
# ============================================================
def fetch_dl(dlno, dob, state="Bihar", rto_code="", st_name="",
             rto_name="", max_attempts=12, do_state_select=True):

    attempts = []
    started = datetime.utcnow().isoformat() + "Z"

    if not OCR_OK:
        return {"success": False, "error": "OCR not loaded",
                "ocr_engine": "none", "attempts": attempts}

    if not st_name:
        st_name = state

    state_iso = STATE_CODES.get(state, state[:2].upper())

    for attempt in range(1, max_attempts + 1):
        s = new_session()
        info = {"attempt": attempt}

        try:
            # 0) state selection (only first attempt)
            if do_state_select and attempt == 1:
                ok = select_state(s, state_iso)
                info["state_selected"] = ok
                info["state_code"] = state_iso
                if not ok:
                    info["error"] = "state selection failed"
                    attempts.append(info)
                    continue
            elif attempt > 1:
                # refresh cookies
                ok = select_state(s, state_iso)
                info["state_selected"] = ok

            # 1) form load (referer = dlServicesDet.do — जैसा browser में होता है)
            r = s.get(
                BASE + "envaction.do",
                timeout=30,
                headers={"Referer": BASE + "dlServicesDet.do"},
            )
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

            # 2) captcha
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
            except Exception as oe:
                info["error"] = f"OCR error: {oe}"
                attempts.append(info)
                continue

            captcha = re.sub(r"[^A-Za-z0-9]", "", raw)
            info["captcha_raw"]   = raw
            info["captcha_clean"] = captcha

            if len(captcha) < 4 or len(captcha) > 8:
                info["error"] = "captcha length unexpected"
                attempts.append(info)
                continue

            # 4) build multipart fields
            fields = build_multipart_fields(
                token, captcha, dlno, dob, state, rto_code,
                st_name, rto_name, state_iso
            )

            # requests को multipart भेजने के लिए files=[] trick
            # (None, value) = regular form field, कोई filename नहीं
            files = [(name, (None, str(val))) for name, val in fields]

            r = s.post(
                BASE + "envaction.do",
                files=files,
                timeout=60,
                headers={
                    "Referer": BASE + "envaction.do",
                    "Origin": "https://sarathi.parivahan.gov.in",
                },
            )
            info["submit_http"] = r.status_code
            info["submit_url"]  = r.url
            info["resp_len"]    = len(r.text)
            LAST_HTML["submit"] = r.text

            # 5) strict check
            if is_dl_page(r.text, dlno):
                result = parse_dl(r.text, dlno)

                # name/dob न मिले तो भी "details page मिला" यह अच्छा signal है
                if not result.get("name") and not result.get("dob"):
                    info["error"] = "result page मिला पर fields खाली"
                    info["preview"] = html_preview(r.text, 250)
                    attempts.append(info)
                    time.sleep(1)
                    continue

                result["attempts"]    = attempts + [info]
                result["ocr_engine"]  = "ddddocr"
                result["started_at"]  = started
                result["finished_at"] = datetime.utcnow().isoformat() + "Z"
                return result

            # 6) error detect
            err = detect_error(r.text)
            info["error"]   = f"result page नहीं मिला ({err})"
            info["preview"] = html_preview(r.text, 300)
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
            info["trace"] = traceback.format_exc()[:400]
            attempts.append(info)

    return {
        "success":     False,
        "error":       f"{max_attempts} attempts में DL details नहीं मिलीं",
        "ocr_engine":  "ddddocr",
        "attempts":    attempts,
        "started_at":  started,
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "hint":        "/api/debug?which=submit&format=text पर असली response देखें",
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
    rto_code = request.args.get("rto_code", "")
    st_name  = request.args.get("st_name", state)
    rto_name = request.args.get("rto_name", "")

    try:
        max_try = int(request.args.get("max_try", "12"))
    except ValueError:
        max_try = 12
    max_try = max(1, min(max_try, 20))

    do_state = request.args.get("state_select", "1") == "1"

    return jsonify(fetch_dl(dlno, dob, state, rto_code, st_name,
                            rto_name, max_try, do_state))


@app.route("/api/debug")
def api_debug():
    which = request.args.get("which", "submit")
    html = LAST_HTML.get(which, "")
    if not html:
        return jsonify({"error": f"कोई '{which}' response save नहीं"}), 404

    if request.args.get("format") == "text":
        text = html_preview(html, 8000)
        return Response(text, mimetype="text/plain; charset=utf-8")

    if request.args.get("format") == "html":
        return Response(html[:100000], mimetype="text/html; charset=utf-8")

    soup = BeautifulSoup(html, "html.parser")
    return jsonify({
        "length":          len(html),
        "title":           soup.title.string if soup.title else None,
        "has_form":        bool(re.search(r'name=["\']dlno["\']', html, re.I)),
        "has_dl_head":     "Driving Licence Number" in html,
        "has_result_sect": "dlSerReqPersDet" in html,
        "result_visible":  not bool(re.search(
            r'id=["\']dlSerReqPersDet["\'][^>]*style=["\'][^"\']*display\s*:\s*none',
            html, re.I)),
        "detected_error":  detect_error(html),
        "preview":         html_preview(html, 500),
        "hint":            "format=text या format=html जोड़कर पूरा देखें",
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
