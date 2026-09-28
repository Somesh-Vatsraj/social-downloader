# ============================================================
#  app.py — Sarathi DL Fetcher (MANUAL CAPTCHA)
#  कोई OCR नहीं — user खुद कैप्चा टाइप करता है
#  Render-ready, Flask
# ============================================================

import os
import re
import time
import uuid
import threading
import traceback
from datetime import datetime

from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup

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

STATE_CODES = {
    "Maharashtra": "MH", "Bihar": "BR", "Delhi": "DL",
    "Karnataka": "KA", "Tamil Nadu": "TN", "Uttar Pradesh": "UP",
    "Gujarat": "GJ", "Rajasthan": "RJ", "West Bengal": "WB",
    "Madhya Pradesh": "MP", "Kerala": "KL", "Punjab": "PB",
    "Haryana": "HR", "Telangana": "TG", "Andhra Pradesh": "AP",
    "Odisha": "OD", "Assam": "AS", "Jharkhand": "JH",
    "Uttarakhand": "UK", "Himachal Pradesh": "HP", "Goa": "GA",
}

# ============================================================
#  Session store (in-memory, 5-min TTL)
# ============================================================
SESSIONS = {}          # sid -> {"session": requests.Session, "token": str, "params": dict, "ts": float}
SESSIONS_LOCK = threading.Lock()
SESSION_TTL = 300      # 5 minutes


def _cleanup_sessions():
    now = time.time()
    with SESSIONS_LOCK:
        dead = [sid for sid, d in SESSIONS.items() if now - d["ts"] > SESSION_TTL]
        for sid in dead:
            del SESSIONS[sid]


def _save_session(sid, req_session, token, params):
    with SESSIONS_LOCK:
        SESSIONS[sid] = {
            "session": req_session,
            "token": token,
            "params": params,
            "ts": time.time(),
        }


def _get_session(sid):
    with SESSIONS_LOCK:
        d = SESSIONS.get(sid)
        if not d:
            return None
        if time.time() - d["ts"] > SESSION_TTL:
            del SESSIONS[sid]
            return None
        return d


def _del_session(sid):
    with SESSIONS_LOCK:
        SESSIONS.pop(sid, None)


# ============================================================
#  Helper: session / token
# ============================================================
def new_http_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


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


def select_state(session: requests.Session, state_code: str) -> bool:
    """stateSelectBean.do + stName=BR (या जो भी code)"""
    try:
        session.get(BASE + "stateSelection.do", timeout=20)
        session.post(
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
        return "STATEID" in session.cookies
    except Exception as e:
        print(f"[!] select_state: {e}", flush=True)
        return False


# ============================================================
#  STRICT: असली DL page है या नहीं
# ============================================================
def is_dl_page(html: str, dlno: str = "") -> bool:
    if not html:
        return False
    # hidden form page पहचानें
    if re.search(
        r'id=["\']dlSerReqPersDet["\'][^>]*style=["\'][^"\']*display\s*:\s*none',
        html, re.I
    ):
        return False

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    if "Confirmed that the above Driving Licence details are mine" in text:
        if dlno.upper() in html.upper() or not dlno:
            return True

    if "Class of Vehicles" in text and "Validity Period" in text and "dlSerReqPersDet" in html:
        return True

    return False


def detect_error(html: str) -> str:
    low = html.lower()
    if "invalid captcha" in low:
        return "captcha_invalid"
    if "please enter captcha" in low:
        return "captcha_empty"
    if "no record" in low or "no data found" in low:
        return "no_record"
    if "session expired" in low:
        return "session_expired"
    if "invalid dl" in low or "not valid" in low:
        return "invalid_dl"
    return "unknown"


def preview(html: str, n: int = 300) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for sel in [".error", ".errormessage", ".alert", "#errormsg",
                    "div[class*='error']", "span[class*='error']"]:
            for el in soup.select(sel):
                t = el.get_text(" ", strip=True)
                if t:
                    return t[:n]
        body = soup.find("body")
        if body:
            return re.sub(r"\s+", " ", body.get_text(" ", strip=True))[:n]
    except Exception:
        pass
    return re.sub(r"<[^>]+>", " ", html)[:n]


# ============================================================
#  Parse result
# ============================================================
def _norm(s): return re.sub(r"\s+", " ", (s or "").strip()).rstrip(":").lower()


def _val(root, label):
    lab = _norm(label)
    for cell in root.find_all(["td", "th"]):
        if _norm(cell.get_text(" ", strip=True)) == lab:
            nxt = cell.find_next_sibling("td")
            if nxt:
                v = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
                if v:
                    return v
    for cell in root.find_all(["td", "th"]):
        txt = _norm(cell.get_text(" ", strip=True))
        if txt.startswith(lab) and len(txt) < len(lab) + 20:
            nxt = cell.find_next_sibling("td")
            if nxt:
                v = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
                if v and _norm(v) != lab:
                    return v
    return ""


def _abs(u):
    if not u: return ""
    if u.startswith("data:"): return u
    if u.startswith("http"): return u
    if u.startswith("/"): return "https://sarathi.parivahan.gov.in" + u
    return BASE + u.lstrip("./")


def _is_logo(src):
    if not src: return True
    low = src.lower()
    for b in ("/images/logo/", "ministry-nic", "parivahan-logo", "digital_logo",
              "nhai", "emblem", "footer", ".ico", ".svg",
              "nophoto", "nosignature", "refresh", "calendar"):
        if b in low:
            return True
    return False


def parse_dl(html, dlno=""):
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find(id="dlSerReqPersDet") or soup

    photo, sign = "", ""
    for img in root.find_all("img"):
        src = img.get("src", "") or ""
        if _is_logo(src):
            continue
        if src.startswith("data:image"):
            if not photo: photo = src
            elif not sign: sign = src
        else:
            l = src.lower()
            if "photo" in l and not photo: photo = src
            elif "sign" in l and not sign: sign = src
            elif not photo: photo = src
            elif not sign: sign = src

    return {
        "success":             True,
        "dlno":                dlno,
        "name":                _val(root, "Name"),
        "father_name":         _val(root, "S/W/D of"),
        "dob":                 _val(root, "Date of Birth"),
        "blood_group":         _val(root, "Blood Group"),
        "category":            _val(root, "Category"),
        "present_address":     _val(root, "Present Address") or _val(root, "Address"),
        "last_endorsed_state": _val(root, "State"),
        "last_endorsed_rto":   _val(root, "RTO"),
        "class_of_vehicles":   _val(root, "Class of Vehicle") or _val(root, "COV"),
        "validity":            _val(root, "Validity"),
        "badge_numbers":       _val(root, "Badge"),
        "photo":               _abs(photo),
        "signature":           _abs(sign),
    }


# ============================================================
#  Multipart fields builder
# ============================================================
def build_multipart_fields(token, captcha, dlno, dob, state, rto_code,
                           st_name, rto_name, state_iso):
    return [
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
        ("entCaptha", captcha),
        ("PrivacyPolicyTermsofService", "true"),
        ("__checkbox_PrivacyPolicyTermsofService", "true"),
        ("dispDLDet", "Select"),
        ("applcatgDLserReq", "General"),
        ("PincodeDLserReq", ""),
        ("stateCodeDLTr", state),
        ("rtoCodeDLTr", rto_code or "-1"),
        ("dlconfirm", "Proceed"),
        ("struts.token.name", "token"),
        ("token", token),
        ("reset", ""),
        ("s4msg", ""),
        ("entCaptha", captcha),
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
        ("umfPresent", "false"),
        ("FaceAuthReq", "false"),
        ("StateName", state),
    ]


# ============================================================
#  STEP 1: captcha लाओ, session save करो
# ============================================================
def start_session(dlno, dob, state, rto_code, st_name, rto_name):
    _cleanup_sessions()

    state_iso = STATE_CODES.get(state, state[:2].upper())
    s = new_http_session()

    # state select
    select_state(s, state_iso)

    # form load → token
    r = s.get(
        BASE + "envaction.do",
        timeout=30,
        headers={"Referer": BASE + "dlServicesDet.do"},
    )
    if r.status_code != 200:
        raise RuntimeError(f"form HTTP {r.status_code}")

    token = extract_token(r.text)
    if not token:
        raise RuntimeError("token नहीं मिला")

    # captcha image
    cap = s.get(
        BASE + "jsp/common/captchaimage.jsp",
        params={"_": int(time.time() * 1000)},
        timeout=30,
        headers={"Referer": BASE + "envaction.do"},
    )
    if cap.status_code != 200 or len(cap.content) < 100:
        raise RuntimeError("captcha fetch failed")

    # session save
    sid = uuid.uuid4().hex
    _save_session(sid, s, token, {
        "dlno": dlno, "dob": dob, "state": state,
        "rto_code": rto_code, "st_name": st_name, "rto_name": rto_name,
        "state_iso": state_iso,
    })

    import base64
    b64 = base64.b64encode(cap.content).decode()
    return sid, b64


# ============================================================
#  STEP 2: user-typed captcha के साथ submit
# ============================================================
def submit_with_captcha(sid, captcha):
    d = _get_session(sid)
    if not d:
        return {"success": False, "error": "session expired — दोबारा captcha लें"}

    s = d["session"]
    token = d["token"]
    p = d["params"]

    fields = build_multipart_fields(
        token, captcha,
        p["dlno"], p["dob"], p["state"], p["rto_code"],
        p["st_name"], p["rto_name"], p["state_iso"],
    )
    files = [(name, (None, str(val))) for name, val in fields]

    try:
        r = s.post(
            BASE + "envaction.do",
            files=files,
            timeout=60,
            headers={
                "Referer": BASE + "envaction.do",
                "Origin": "https://sarathi.parivahan.gov.in",
            },
        )
    except Exception as e:
        _del_session(sid)
        return {"success": False, "error": f"network: {e}"}

    # एक बार इस्तेमाल → हटाओ
    _del_session(sid)

    if is_dl_page(r.text, p["dlno"]):
        result = parse_dl(r.text, p["dlno"])
        if not result.get("name") and not result.get("dob"):
            return {
                "success": False,
                "error":   "result page मिला पर fields खाली",
                "preview": preview(r.text, 500),
            }
        return result

    err = detect_error(r.text)
    msg = {
        "captcha_invalid":  "कैप्चा गलत था — दोबारा try करें",
        "captcha_empty":    "कैप्चा खाली था",
        "no_record":        "इस DL number/DOB का record नहीं मिला",
        "session_expired":  "session expire — दोबारा captcha लें",
        "invalid_dl":       "DL number गलत है",
        "state_not_selected": "state नहीं चुना गया",
        "unknown":          "असफल — दोबारा try करें",
    }.get(err, "असफल")

    return {
        "success": False,
        "error":   msg,
        "code":    err,
        "preview": preview(r.text, 500),
    }


# ============================================================
#  Routes
# ============================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or request.form
    dlno     = (data.get("dlno") or "").strip().upper()
    dob      = (data.get("dob")  or "").strip()
    state    = (data.get("state") or "Bihar").strip()
    rto_code = (data.get("rto_code") or "").strip()
    st_name  = (data.get("st_name") or state).strip()
    rto_name = (data.get("rto_name") or "").strip()

    if not dlno or not dob:
        return jsonify({"success": False, "error": "dlno और dob ज़रूरी हैं"}), 400
    if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", dob):
        return jsonify({"success": False, "error": "DOB format DD-MM-YYYY"}), 400

    try:
        sid, img_b64 = start_session(dlno, dob, state, rto_code, st_name, rto_name)
        return jsonify({"success": True, "sid": sid, "captcha": img_b64})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/submit", methods=["POST"])
def api_submit():
    data = request.get_json(silent=True) or request.form
    sid     = (data.get("sid") or "").strip()
    captcha = (data.get("captcha") or "").strip()

    if not sid or not captcha:
        return jsonify({"success": False, "error": "sid और captcha ज़रूरी हैं"}), 400

    captcha = re.sub(r"[^A-Za-z0-9]", "", captcha)
    if not (3 <= len(captcha) <= 10):
        return jsonify({"success": False, "error": "captcha की लंबाई गलत"}), 400

    return jsonify(submit_with_captcha(sid, captcha))


@app.route("/healthz")
def healthz():
    _cleanup_sessions()
    with SESSIONS_LOCK:
        n = len(SESSIONS)
    return jsonify({"status": "ok", "active_sessions": n,
                    "time": datetime.utcnow().isoformat() + "Z"}), 200


@app.errorhandler(404)
def nf(_): return jsonify({"error": "not found"}), 404

@app.errorhandler(500)
def se(e): return jsonify({"error": "internal error", "detail": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
