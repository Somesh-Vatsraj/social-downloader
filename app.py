# ============================================================
#  app.py — Sarathi DL Details Fetcher
#  FREE OCR (ddddocr) + Manual fallback + Flask
# ============================================================
import os
import re
import time
import json
import uuid
import base64
import random
import string
import traceback
from datetime import datetime
from urllib.parse import urlencode

from flask import Flask, request, jsonify, render_template, Response
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
    "Maharashtra": "MH", "Bihar": "BR", "Delhi": "DL",
    "Karnataka": "KA", "Tamil Nadu": "TN", "Uttar Pradesh": "UP",
    "Gujarat": "GJ", "Rajasthan": "RJ", "West Bengal": "WB",
    "Madhya Pradesh": "MP", "Kerala": "KL", "Punjab": "PB",
    "Haryana": "HR", "Telangana": "TG", "Andhra Pradesh": "AP",
    "Odisha": "OD", "Assam": "AS", "Jharkhand": "JH",
    "Uttarakhand": "UK", "Himachal Pradesh": "HP", "Goa": "GA",
}

TMP = "/tmp"
if not os.path.isdir(TMP):
    TMP = os.environ.get("TEMP", ".")

# ============================================================
#  File-based session
# ============================================================
def sid_dir(sid: str) -> str:
    sid = re.sub(r"[^a-f0-9]", "", sid) or "default"
    d = os.path.join(TMP, f"sarathi_sid_{sid}")
    os.makedirs(d, exist_ok=True)
    return d

def sid_jar(sid):      return os.path.join(sid_dir(sid), "jar.txt")
def sid_state(sid):    return os.path.join(sid_dir(sid), "state.json")
def sid_file(sid, n):  return os.path.join(sid_dir(sid), n)

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
    except Exception:
        pass

# ============================================================
#  Chrome-like boundary
# ============================================================
def chrome_boundary():
    chars = string.ascii_letters + string.digits
    return "----WebKitFormBoundary" + "".join(random.choices(chars, k=16))

# ============================================================
#  Cookie helpers
# ============================================================
def _load_cookies(session, jar_path):
    if not os.path.isfile(jar_path): return
    try:
        with open(jar_path) as f: data = json.load(f)
        for c in data:
            session.cookies.set(
                c.get("name", ""),
                c.get("value", ""),
                domain=c.get("domain") or None,
                path=c.get("path") or "/",
            )
    except Exception as e:
        print(f"[!] load cookies: {e}", flush=True)

def _save_cookies(session, jar_path):
    try:
        cookies = []
        for c in session.cookies:
            cookies.append({
                "name": c.name, "value": c.value,
                "domain": c.domain, "path": c.path,
            })
        with open(jar_path, "w") as f: json.dump(cookies, f)
    except Exception as e:
        print(f"[!] save cookies: {e}", flush=True)

# ============================================================
#  HTTP helpers
# ============================================================
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
    if ajax:    headers["X-Requested-With"] = "XMLHttpRequest"

    try:
        if post is None:
            r = s.get(url, headers=headers, timeout=45, verify=True, allow_redirects=True)
        else:
            if ajax:
                headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            r = s.post(url, headers=headers, data=post, timeout=45,
                       verify=True, allow_redirects=True)
        _save_cookies(s, jar_path)
        return {"body": r.content, "text": r.text, "http": r.status_code, "err": ""}
    except Exception as e:
        _save_cookies(s, jar_path)
        return {"body": b"", "text": "", "http": 0, "err": str(e)}


def req_multipart_pairs(sid, url, pairs, referer=None):
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
        return {"body": r.content, "text": r.text, "http": r.status_code,
                "err": "", "sent_body": body_str}
    except Exception as e:
        _save_cookies(s, jar_path)
        return {"body": b"", "text": "", "http": 0, "err": str(e),
                "sent_body": body_str}

# ============================================================
#  Parsers
# ============================================================
def extract_token(html: str):
    m = re.search(r'<input[^>]*name=["\']token["\'][^>]*value=["\']([^"\']+)', html, re.I)
    if m: return m.group(1)
    m = re.search(r'<input[^>]*value=["\']([^"\']+)["\'][^>]*name=["\']token["\']', html, re.I)
    if m: return m.group(1)
    return None

def page_title(html: str) -> str:
    m = re.search(r'<title>([^<]*)</title>', html, re.I)
    return m.group(1).strip() if m else "unknown"

def parse_ajax(body: str):
    body = (body or "").strip()
    if not body:
        return {"ok": False, "status": "EMPTY", "raw": ""}
    try:
        j = json.loads(body)
    except Exception as e:
        return {"ok": False, "status": "PARSE_ERROR", "raw": body[:500], "err": str(e)}
    if not isinstance(j, list) or len(j) < 3:
        return {"ok": False, "status": "PARSE_ERROR", "raw": body[:500]}
    status = j[1] if len(j) > 1 else ""
    if status != "OK":
        return {"ok": False, "status": str(status), "raw": body[:500]}
    combined = str(j[2]) if len(j) > 2 else ""
    state, name = "", ""
    if "@" in combined:
        state, name = combined.split("@", 1)
    else:
        name = combined
    return {
        "ok": True,
        "state": state.strip(),
        "name": name.strip(),
        "rto": str(j[3]).strip() if len(j) > 3 else "",
        "raw": body[:500],
    }

def clean_html_for_matching(html: str) -> str:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    return html

def is_dl_page(html: str) -> bool:
    clean = clean_html_for_matching(html)
    if re.search(r'name="imgHid"\s+value="data:image', clean, re.I): return True
    if re.search(r'name="sigHid"\s+value="data:image', clean, re.I): return True
    m = re.search(
        r'<td[^>]*text-success[^>]*>\s*Name\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)</td>',
        clean, re.I
    )
    if m and len(m.group(1).strip()) > 2 and "text-left" not in m.group(1).lower():
        return True
    m = re.search(
        r'<td[^>]*text-success[^>]*>\s*Father\'?s?\s*Name\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)</td>',
        clean, re.I
    )
    if m and len(m.group(1).strip()) > 2 and "text-left" not in m.group(1).lower():
        return True
    return False

def parse_dl(html: str) -> dict:
    html = clean_html_for_matching(html)
    out = {
        "dlno":"","name":"","father_name":"","dob":"","blood_group":"","category":"",
        "present_address":"","last_endorsed_state":"","last_endorsed_rto":"",
        "class_of_vehicles":[],"validity":"","badge_numbers":[],"photo":"","signature":"",
    }
    def find(p, src=None, flags=re.I|re.S):
        m = re.search(p, src if src is not None else html, flags)
        return m.group(1).strip() if m else ""
    def clean(s): return re.sub(r"\s+", " ", s).strip()

    out["name"] = clean(find(r'<td[^>]*text-success[^>]*>\s*Name\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))
    out["father_name"] = clean(find(r'<td[^>]*text-success[^>]*>\s*Father\'?s?\s*Name\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))
    out["dob"] = clean(find(r'<td[^>]*text-success[^>]*>\s*Date of Birth\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))
    out["blood_group"] = clean(find(r'<td[^>]*text-success[^>]*>\s*Blood Group\s*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))
    out["category"] = clean(find(r'<td[^>]*text-success[^>]*>\s*Category[^<:]*:\s*</td>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>'))

    m = re.search(r'Present Address\s*:\s*</td>\s*<td[^>]*>([^<]*)</td>(.*?)</table>', html, re.I|re.S)
    if m:
        addr = clean(m.group(1))
        for line in re.findall(r'<td[^>]*class="text-left"[^>]*>([^<]+)</td>', m.group(2), re.I):
            line = clean(line)
            if line: addr = (addr + ", " + line) if addr else line
        out["present_address"] = addr

    out["last_endorsed_state"] = clean(find(
        r'<b[^>]*class="[^"]*text-success[^"]*"[^>]*>\s*State\s*-\s*</b>\s*([^<\s][^<]*)'
    ))
    out["last_endorsed_rto"] = clean(find(
        r'<b[^>]*class="[^"]*text-success[^"]*"[^>]*>\s*RTO\s*-\s*</b>\s*([^<\s][^<]*)'
    ))

    m = re.search(r'Class of Vehicles\s*:.*?<table[^>]*>(.*?)</table>', html, re.I|re.S)
    if m:
        for cov, issue in re.findall(
            r'<tr>\s*<td[^>]*>([A-Z0-9\-]+)</td>.*?<b class="control-label">\s*([^<]+?)</b>',
            m.group(1), re.I|re.S
        ):
            out["class_of_vehicles"].append({"cov":cov.strip(), "issue":clean(issue)})

    vals = re.findall(
        r'<label[^>]*class="text-success"[^>]*>\s*(Transport|Non[\s-]?Transport)\s*:?\s*</label>.*?'
        r'<div[^>]*class="col-md-6 text-center"[^>]*>\s*([^<]+?)\s*</div>',
        html, re.I|re.S
    )
    if vals:
        out["validity"] = " | ".join(f"{t}: {clean(v)}" for t,v in vals)

    m = re.search(r'Badge No\s*:.*?</label>(.*?)</fieldset>', html, re.I|re.S)
    if m:
        for _, b in re.findall(
            r'<div[^>]*class="col-md-6 text-center"[^>]*>\s*(\d+)\s*\)\s*([^<\s]+)\s*</div>',
            m.group(1), re.I|re.S
        ):
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
#  Core: start & submit
# ============================================================
def start_session(dlno, dob, state):
    state_code = STATE_CODES.get(state, state[:2].upper())
    sid = uuid.uuid4().hex
    sid_dir(sid)

    req(sid, BASE + "stateSelection.do")
    req(sid, BASE + "stateSelectBean.do", {"stName": state_code}, BASE + "stateSelection.do")
    req(sid, BASE + "dlServicesDet.do", None, BASE + "stateSelectBean.do")

    r = req(sid, BASE + "envaction.do", None, BASE + "dlServicesDet.do")
    if r["http"] != 200:
        raise RuntimeError(f"envaction.do HTTP {r['http']}")

    with open(sid_file(sid, "form.html"), "wb") as f:
        f.write(r["body"])

    token = extract_token(r["text"])
    if not token:
        raise RuntimeError("token नहीं मिला")
    if "Application for Services on Driving Licence" not in r["text"]:
        raise RuntimeError("envaction.do returned landing page — state selection fail")

    cap = req(sid, BASE + "jsp/common/captchaimage.jsp?_=" + str(int(time.time()*1000)),
              None, BASE + "envaction.do")
    if cap["http"] != 200 or len(cap["body"]) < 100:
        raise RuntimeError("captcha fetch failed")

    state_save(sid, {
        "dlno": dlno, "dob": dob, "state": state,
        "state_code": state_code, "token1": token, "ts": time.time(),
    })
    return sid, cap["body"], token


def submit_with_captcha(sid, captcha):
    s = state_load(sid)
    if not s: raise RuntimeError("state नहीं मिला")
    if time.time() - s.get("ts", 0) > 300:
        raise RuntimeError("session expire — नया कैप्चा लें")

    dlno, dob, state, token1 = s["dlno"], s["dob"], s["state"], s["token1"]

    # AJAX verify — urlencoded body
    ajax_body = urlencode({"dlno": dlno, "dob": dob, "captchaByApplicant": captcha})
    ajax = req(sid, BASE + "getLastEndorsedRtoDLserReq.do?",
               ajax_body, BASE + "envaction.do", ajax=True)

    with open(sid_file(sid, "ajax.txt"), "w", encoding="utf-8", errors="ignore") as f:
        f.write(ajax["text"] or "")

    parsed = parse_ajax(ajax["text"])
    if not parsed["ok"]:
        raw_preview = parsed.get("raw", "")[:300]
        raise RuntimeError(
            f"कैप्चा गलत (status: {parsed.get('status','INVALID')}) | raw: {raw_preview}"
        )

    dl_name, dl_state, dl_rto = parsed["name"], parsed["state"], parsed["rto"]

    pairs = [
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
        ("rtoCodeDLTr", "-1"),
        ("struts.token.name", "token"),
        ("token", token1),
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

    post = req_multipart_pairs(sid, BASE + "envaction.do", pairs, BASE + "envaction.do")

    with open(sid_file(sid, "last_response.html"), "w", encoding="utf-8", errors="ignore") as f:
        f.write(post["text"] or "")
    with open(sid_file(sid, "submit_http.txt"), "w") as f:
        f.write(str(post["http"]))
    with open(sid_file(sid, "sent_body.txt"), "w", encoding="utf-8", errors="ignore") as f:
        f.write(post.get("sent_body", ""))

    if post["http"] != 200:
        raise RuntimeError(f"envaction POST HTTP {post['http']}")

    if is_dl_page(post["text"]):
        details = parse_dl(post["text"])
        details["success"] = True
        details["ocr_engine"] = "manual"
        details["dlno"] = dlno
        return details

    title = page_title(post["text"])
    clean = clean_html_for_matching(post["text"])
    for pat in [r"Incorrect captcha", r"Invalid Captcha", r"Please enter captcha"]:
        if re.search(pat, clean, re.I):
            raise RuntimeError("Server ने कैप्चा invalid बताया — नया कैप्चा लें")
    for pat in [r"No record found", r"not available", r"Invalid DL"]:
        if re.search(pat, clean, re.I):
            raise RuntimeError("इस DL का record नहीं मिला")

    preview = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", clean))[:250]
    raise RuntimeError(f"DL details नहीं मिलीं (title: {title})। Preview: {preview}")

# ============================================================
#  Routes
# ============================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or request.form
    dlno = (data.get("dlno") or "").strip().upper()
    dob  = (data.get("dob") or "").strip()
    state = (data.get("state") or "Bihar").strip()
    use_ocr = str(data.get("use_ocr") or "1") == "1"

    if not dlno or not dob:
        return jsonify({"success": False, "error": "DL number और DOB ज़रूरी हैं"}), 400
    if not re.match(r"^\d{2}-\d{2}-\d{4}$", dob):
        return jsonify({"success": False, "error": "DOB format DD-MM-YYYY"}), 400

    try:
        sid, captcha_bytes, token = start_session(dlno, dob, state)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    b64 = base64.b64encode(captcha_bytes).decode()

    ocr_text = ""
    if use_ocr and OCR_OK:
        try:
            ocr_text = OCR.classification(captcha_bytes) or ""
            ocr_text = re.sub(r"[^A-Za-z0-9]", "", ocr_text)
        except Exception as e:
            print(f"[!] OCR error: {e}", flush=True)
            ocr_text = ""

    return jsonify({
        "success": True, "sid": sid, "captcha": b64,
        "token": token[:8] + "…",
        "ocr_text": ocr_text,
        "ocr_available": OCR_OK and use_ocr,
    })


@app.route("/api/submit", methods=["POST"])
def api_submit():
    data = request.get_json(silent=True) or request.form
    sid = re.sub(r"[^a-f0-9]", "", (data.get("sid") or "").strip())
    captcha = re.sub(r"[^A-Za-z0-9]", "", (data.get("captcha") or "").strip())

    if not sid or not os.path.isdir(sid_dir(sid)):
        return jsonify({"success": False, "error": "session गायब"}), 400
    if not captcha:
        return jsonify({"success": False, "error": "कैप्चा खाली है"}), 400
    if not (3 <= len(captcha) <= 10):
        return jsonify({"success": False, "error": "कैप्चा की लंबाई गलत"}), 400

    try:
        return jsonify(submit_with_captcha(sid, captcha))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/retry_ocr", methods=["POST"])
def api_retry_ocr():
    data = request.get_json(silent=True) or request.form
    b64 = data.get("captcha_b64") or ""
    if not b64:
        return jsonify({"success": False, "error": "captcha_b64 चाहिए"}), 400
    if not OCR_OK:
        return jsonify({"success": False, "error": "OCR unavailable"}), 503
    try:
        raw = base64.b64decode(b64)
        txt = OCR.classification(raw) or ""
        return jsonify({"success": True, "text": re.sub(r"[^A-Za-z0-9]", "", txt)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/debug")
def api_debug():
    sid = re.sub(r"[^a-f0-9]", "", (request.args.get("sid") or "").strip())
    if not sid or not os.path.isdir(sid_dir(sid)):
        return Response("?sid=<sid> ज़रूरी है", mimetype="text/plain; charset=utf-8")
    out = [f"=== SID: {sid} ===\n"]
    for f in ["state.json","form.html","ajax.txt","submit_http.txt",
              "last_response.html","sent_body.txt"]:
        p = sid_file(sid, f)
        out.append(f"========== {f} ==========\n")
        if os.path.isfile(p):
            with open(p, "rb") as fh: c = fh.read()
            out.append(f"(len={len(c)})\n")
            out.append(c.decode("utf-8", "ignore")[:6000] + "\n\n")
        else:
            out.append("(missing)\n\n")
    return Response("".join(out), mimetype="text/plain; charset=utf-8")


@app.route("/healthz")
def healthz():
    cleanup_old()
    return jsonify({"ok": True, "ocr_ok": OCR_OK,
                    "time": datetime.utcnow().isoformat() + "Z"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
