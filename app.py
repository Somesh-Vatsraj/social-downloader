# ============================================================
#  app.py — Sarathi DL Fetcher — Simple API
#  API: POST /api/dl  {dlno, dob, state} → DL details JSON
#  FREE OCR (ddddocr) with auto-retry
# ============================================================
import os, re, time, json, uuid, random, string
from urllib.parse import urlencode
from flask import Flask, request, jsonify, Response
import requests

try:
    import ddddocr
    OCR = ddddocr.DdddOcr(show_ad=False)
    OCR_OK = True
    print("[*] ddddocr loaded", flush=True)
except Exception as e:
    print(f"[!] ddddocr load failed: {e}", flush=True)
    OCR = None
    OCR_OK = False

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

BASE = "https://sarathi.parivahan.gov.in/sarathiservice/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/153.0.0.0 Safari/537.36")

STATE_CODES = {
    "Maharashtra":"MH","Bihar":"BR","Delhi":"DL","Karnataka":"KA",
    "Tamil Nadu":"TN","Uttar Pradesh":"UP","Gujarat":"GJ","Rajasthan":"RJ",
    "West Bengal":"WB","Madhya Pradesh":"MP","Kerala":"KL","Punjab":"PB",
    "Haryana":"HR","Telangana":"TG","Andhra Pradesh":"AP","Odisha":"OD",
    "Assam":"AS","Jharkhand":"JH","Uttarakhand":"UK","Himachal Pradesh":"HP","Goa":"GA",
}

TMP = "/tmp" if os.path.isdir("/tmp") else os.environ.get("TEMP", ".")

# ============================================================
#  Session dir (per sid — but API uses fresh sid each call)
# ============================================================
def sid_dir(sid):
    sid = re.sub(r"[^a-f0-9]", "", sid) or "default"
    d = os.path.join(TMP, f"sarathi_sid_{sid}")
    os.makedirs(d, exist_ok=True)
    return d

def sid_jar(sid): return os.path.join(sid_dir(sid), "jar.txt")
def sid_state(sid): return os.path.join(sid_dir(sid), "state.json")

def state_load(sid):
    p = sid_state(sid)
    if not os.path.isfile(p): return {}
    try:
        with open(p) as f: return json.load(f)
    except Exception: return {}

def state_save(sid, s):
    with open(sid_state(sid), "w") as f: json.dump(s, f)

def cleanup_old():
    try:
        now = time.time()
        for d in os.listdir(TMP):
            if not d.startswith("sarathi_sid_"): continue
            p = os.path.join(TMP, d)
            if not os.path.isdir(p): continue
            if now - os.path.getmtime(p) > 1800:
                for f in os.listdir(p):
                    try: os.remove(os.path.join(p, f))
                    except Exception: pass
                try: os.rmdir(p)
                except Exception: pass
    except Exception: pass

# ============================================================
#  Cookie helpers
# ============================================================
def _load_cookies(session, jar_path):
    if not os.path.isfile(jar_path): return
    try:
        with open(jar_path) as f: data = json.load(f)
        for c in data:
            session.cookies.set(
                c.get("name", ""), c.get("value", ""),
                domain=c.get("domain") or None,
                path=c.get("path") or "/",
            )
    except Exception as e:
        print(f"[!] load cookies: {e}", flush=True)

def _save_cookies(session, jar_path):
    try:
        cookies = [{"name": c.name, "value": c.value,
                    "domain": c.domain, "path": c.path} for c in session.cookies]
        with open(jar_path, "w") as f: json.dump(cookies, f)
    except Exception as e:
        print(f"[!] save cookies: {e}", flush=True)

# ============================================================
#  HTTP helpers
# ============================================================
def chrome_boundary():
    chars = string.ascii_letters + string.digits
    return "----WebKitFormBoundary" + "".join(random.choices(chars, k=16))

def req(sid, url, post=None, referer=None, ajax=False):
    jar_path = sid_jar(sid)
    s = requests.Session()
    _load_cookies(s, jar_path)

    headers = {
        "User-Agent": UA,
        "Accept": ("application/json, text/javascript, */*; q=0.01" if ajax
                   else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Origin": "https://sarathi.parivahan.gov.in",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer: headers["Referer"] = referer
    if ajax: headers["X-Requested-With"] = "XMLHttpRequest"

    try:
        if post is None:
            r = s.get(url, headers=headers, timeout=45, verify=True, allow_redirects=True)
        else:
            if ajax:
                headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            r = s.post(url, headers=headers, data=post, timeout=45,
                       verify=True, allow_redirects=True)
        _save_cookies(s, jar_path)
        return {"text": r.text, "body": r.content, "http": r.status_code, "err": ""}
    except Exception as e:
        _save_cookies(s, jar_path)
        return {"text": "", "body": b"", "http": 0, "err": str(e)}


def req_multipart(sid, url, pairs, referer=None):
    jar_path = sid_jar(sid)
    s = requests.Session()
    _load_cookies(s, jar_path)

    boundary = chrome_boundary()
    parts = []
    for name, value in pairs:
        parts.append(f"--{boundary}\r\n")
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        parts.append(str(value))
        parts.append("\r\n")
    parts.append(f"--{boundary}--\r\n")
    body_str = "".join(parts)

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Origin": "https://sarathi.parivahan.gov.in",
        "Upgrade-Insecure-Requests": "1",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if referer: headers["Referer"] = referer

    try:
        r = s.post(url, headers=headers, data=body_str.encode("utf-8"),
                   timeout=60, verify=True, allow_redirects=True)
        _save_cookies(s, jar_path)
        return {"text": r.text, "body": r.content, "http": r.status_code, "err": ""}
    except Exception as e:
        _save_cookies(s, jar_path)
        return {"text": "", "body": b"", "http": 0, "err": str(e)}

# ============================================================
#  Parsers
# ============================================================
def extract_token(html):
    m = re.search(r'<input[^>]*name=["\']token["\'][^>]*value=["\']([^"\']+)', html, re.I)
    if m: return m.group(1)
    m = re.search(r'<input[^>]*value=["\']([^"\']+)["\'][^>]*name=["\']token["\']', html, re.I)
    return m.group(1) if m else None

def clean_html(html):
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    return html

def is_dl_page(html):
    clean = clean_html(html)
    if re.search(r'name="imgHid"\s+value="data:image', clean, re.I): return True
    m = re.search(
        r'<td[^>]*text-success[^>]*>\s*Name\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)</td>',
        clean, re.I)
    if m and len(m.group(1).strip()) > 2: return True
    return False

def parse_dl(html):
    html = clean_html(html)
    out = {"dlno":"","name":"","father_name":"","dob":"","blood_group":"","category":"",
           "present_address":"","last_endorsed_state":"","last_endorsed_rto":"",
           "class_of_vehicles":[],"validity":"","badge_numbers":[],
           "photo":"","signature":""}
    def find(p):
        m = re.search(p, html, re.I|re.S)
        return m.group(1).strip() if m else ""
    def clean(s): return re.sub(r"\s+", " ", s).strip()

    out["name"]        = clean(find(r'<td[^>]*text-success[^>]*>\s*Name\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))
    out["father_name"] = clean(find(r'<td[^>]*text-success[^>]*>\s*Father\'?s?\s*Name\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))
    out["dob"]         = clean(find(r'<td[^>]*text-success[^>]*>\s*Date of Birth\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))
    out["blood_group"] = clean(find(r'<td[^>]*text-success[^>]*>\s*Blood Group\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))
    out["category"]    = clean(find(r'<td[^>]*text-success[^>]*>\s*Category[^<:]*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))

    m = re.search(r'Present Address\s*:\s*</td>\s*<td[^>]*>([^<]*)</td>(.*?)</table>', html, re.I|re.S)
    if m:
        addr = clean(m.group(1))
        for line in re.findall(r'<td[^>]*class="text-left"[^>]*>([^<]+)</td>', m.group(2), re.I):
            line = clean(line)
            if line: addr = (addr + ", " + line) if addr else line
        out["present_address"] = addr

    out["last_endorsed_state"] = clean(find(
        r'<b[^>]*class="[^"]*text-success[^"]*"[^>]*>\s*State\s*-\s*</b>\s*([^<\s][^<]*)'))
    out["last_endorsed_rto"] = clean(find(
        r'<b[^>]*class="[^"]*text-success[^"]*"[^>]*>\s*RTO\s*-\s*</b>\s*([^<\s][^<]*)'))

    m = re.search(r'Class of Vehicles\s*:.*?<table[^>]*>(.*?)</table>', html, re.I|re.S)
    if m:
        for cov, issue in re.findall(
            r'<tr>\s*<td[^>]*>([A-Z0-9\-]+)</td>.*?<b class="control-label">\s*([^<]+?)</b>',
            m.group(1), re.I|re.S):
            out["class_of_vehicles"].append({"cov": cov.strip(), "issue": clean(issue)})

    vals = re.findall(
        r'<label[^>]*class="text-success"[^>]*>\s*(Transport|Non[\s-]?Transport)\s*:?\s*</label>.*?'
        r'<div[^>]*class="col-md-6 text-center"[^>]*>\s*([^<]+?)\s*</div>',
        html, re.I|re.S)
    if vals:
        out["validity"] = " | ".join(f"{t}: {clean(v)}" for t,v in vals)

    m = re.search(r'Badge No\s*:.*?</label>(.*?)</fieldset>', html, re.I|re.S)
    if m:
        for _, b in re.findall(
            r'<div[^>]*class="col-md-6 text-center"[^>]*>\s*(\d+)\s*\)\s*([^<\s]+)\s*</div>',
            m.group(1), re.I|re.S):
            out["badge_numbers"].append(b.strip())

    m = re.search(r'name="imgHid"\s+value="([^"]+)"', html, re.I)
    if m:
        v = m.group(1).replace("&amp;", "&").strip()
        if v.startswith("data:image"): out["photo"] = v
    m = re.search(r'name="sigHid"\s+value="([^"]+)"', html, re.I)
    if m:
        v = m.group(1).replace("&amp;", "&").strip()
        if v.startswith("data:image"): out["signature"] = v

    return out

# ============================================================
#  Core: single attempt
# ============================================================
def try_once(dlno, dob, state, sid=None):
    """एक attempt — नया सिड, नया captcha, OCR, submit. Returns (ok, data_or_error)."""
    state_code = STATE_CODES.get(state, state[:2].upper())
    sid = sid or uuid.uuid4().hex
    sid_dir(sid)

    # state select + form load
    req(sid, BASE + "stateSelection.do")
    req(sid, BASE + "stateSelectBean.do", {"stName": state_code}, BASE + "stateSelection.do")
    req(sid, BASE + "dlServicesDet.do", None, BASE + "stateSelectBean.do")

    r = req(sid, BASE + "envaction.do", None, BASE + "dlServicesDet.do")
    if r["http"] != 200:
        return False, f"envaction HTTP {r['http']}"

    token = extract_token(r["text"])
    if not token:
        return False, "token नहीं मिला"
    if "Application for Services on Driving Licence" not in r["text"]:
        return False, "landing page मिला (state selection fail)"

    # captcha
    cap = req(sid, BASE + "jsp/common/captchaimage.jsp?_=" + str(int(time.time()*1000)),
              None, BASE + "envaction.do")
    if cap["http"] != 200 or len(cap["body"]) < 100:
        return False, "captcha fetch failed"

    if not OCR_OK:
        return False, "OCR unavailable"

    try:
        captcha = OCR.classification(cap["body"]) or ""
        captcha = re.sub(r"[^A-Za-z0-9]", "", captcha)
    except Exception as e:
        return False, f"OCR error: {e}"

    if len(captcha) < 3 or len(captcha) > 10:
        return False, f"OCR text length: {len(captcha)}"

    # AJAX verify
    ajax_body = urlencode({"dlno": dlno, "dob": dob, "captchaByApplicant": captcha})
    ajax = req(sid, BASE + "getLastEndorsedRtoDLserReq.do?",
               ajax_body, BASE + "envaction.do", ajax=True)

    try:
        j = json.loads((ajax["text"] or "").strip())
    except Exception:
        return False, f"captcha गलत (OCR='{captcha}')"

    if not isinstance(j, list) or len(j) < 2 or j[1] != "OK":
        status = j[1] if isinstance(j, list) and len(j) > 1 else "INVALID"
        return False, f"captcha गलत (OCR='{captcha}', status='{status}')"

    combined = str(j[2]) if len(j) > 2 else ""
    dl_name, dl_state = ("", combined)
    if "@" in combined:
        dl_state, dl_name = combined.split("@", 1)
    dl_name = dl_name.strip()
    dl_state = dl_state.strip()
    dl_rto = str(j[3]).strip() if len(j) > 3 else ""

    # POST envaction.do
    pairs = [
        ("capToDisp", ""), ("captchaByApplicant", ""),
        ("dlno", dlno), ("dob", dob),
        ("entCaptha", captcha),
        ("PrivacyPolicyTermsofService", "true"),
        ("__checkbox_PrivacyPolicyTermsofService", "true"),
        ("dispDLDet", "Select"),
        ("applcatgDLserReq", "General"),
        ("PincodeDLserReq", ""),
        ("stateCodeDLTr", state),
        ("rtoCodeDLTr", "-1"),
        ("struts.token.name", "token"),
        ("token", token),
        ("reset", "formsubmit"),
        ("s4msg", ""),
        ("entCaptha", ""),
        ("rtoNameSelPreAppl", ""),
        ("dlno1", ""),
        ("applnotransreq", ""),
        ("dob1", ""),
        ("stEndName", dl_state),
        ("rtoEndName", dl_rto),
        ("ApplFullNameDLSReq", dl_name),
        ("isMatch", ""),
        ("firstCap", "true"),
        ("CapPho", ""),
        ("idpchecked", ""),
        ("SelDiplomat", ""),
        ("scFaceAuthReqAiLib", ""),
        ("faceauthmodel", "https://sarathi.parivahan.gov.in/cdn-sarathi/models"),
        ("videoDevicesDetected", ""),
    ]
    post = req_multipart(sid, BASE + "envaction.do", pairs, BASE + "envaction.do")

    if post["http"] != 200:
        return False, f"POST HTTP {post['http']}"

    if is_dl_page(post["text"]):
        data = parse_dl(post["text"])
        data["dlno"] = dlno
        return True, data

    # Save for debug
    with open(os.path.join(sid_dir(sid), "last_response.html"),
              "w", encoding="utf-8", errors="ignore") as f:
        f.write(post["text"] or "")

    return False, "DL details page नहीं मिला (server ने form वापस भेजा)"

# ============================================================
#  API — main endpoint
# ============================================================
@app.route("/api/dl", methods=["GET", "POST"])
def api_dl():
    """
    Query / Body params:
      dlno      (required)  e.g. MH0220100024875
      dob       (required)  DD-MM-YYYY
      state     (optional, default "Bihar")
      max_try   (optional, default 15, max 25)

    Returns JSON with DL details on success.
    """
    data = request.get_json(silent=True) or request.form or request.args
    dlno = re.sub(r"\s+", "", (data.get("dlno") or "").strip().upper())
    dob  = (data.get("dob") or "").strip()
    state = (data.get("state") or "Bihar").strip()

    if not dlno or not dob:
        return jsonify({"success": False, "error": "dlno और dob ज़रूरी हैं"}), 400
    if not re.match(r"^\d{2}-\d{2}-\d{4}$", dob):
        return jsonify({"success": False, "error": "dob format DD-MM-YYYY"}), 400

    try:
        max_try = int(data.get("max_try") or 15)
    except (ValueError, TypeError):
        max_try = 15
    max_try = max(1, min(max_try, 25))

    if not OCR_OK:
        return jsonify({"success": False,
                        "error": "OCR unavailable (ddddocr load नहीं हुआ)"}), 503

    attempts = []
    started = time.time()

    for i in range(1, max_try + 1):
        ok, result = try_once(dlno, dob, state)

        if ok:
            result["success"] = True
            result["attempts"] = i
            result["elapsed_sec"] = round(time.time() - started, 2)
            return jsonify(result)

        attempts.append({"try": i, "reason": result})
        time.sleep(0.4)  # polite delay

    return jsonify({
        "success": False,
        "error": f"{max_try} attempts में DL details नहीं मिलीं",
        "attempts": attempts,
    }), 422

# ============================================================
#  Debug (per-sid last response)
# ============================================================
@app.route("/debug")
def debug():
    sid = re.sub(r"[^a-f0-9]", "", (request.args.get("sid") or "").strip())
    if not sid:
        return Response("?sid=<sid> चाहिए", mimetype="text/plain; charset=utf-8")
    p = os.path.join(sid_dir(sid), "last_response.html")
    if not os.path.isfile(p):
        return Response("no last_response.html", mimetype="text/plain; charset=utf-8")
    with open(p, "rb") as f:
        return Response(f.read()[:8000], mimetype="text/html; charset=utf-8")

# ============================================================
#  Health
# ============================================================
@app.route("/healthz")
def healthz():
    cleanup_old()
    return jsonify({"ok": True, "ocr_ok": OCR_OK})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
