# app.py
import os
import re
import time
import json
import base64
from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
import ddddocr

app = Flask(__name__)

BASE = "https://sarathi.parivahan.gov.in/sarathiservice/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")

# OCR मॉडल एक बार लोड करें (memory में रहेगा)
print("[*] Loading ddddocr model...")
OCR = ddddocr.DdddOcr(show_ad=False)
print("[*] ddddocr ready")


# ==============================================================
#  Helper functions
# ==============================================================

def new_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Origin": "https://sarathi.parivahan.gov.in",
        "Referer": BASE + "envaction.do",
        "Upgrade-Insecure-Requests": "1",
    })
    return s


def extract_token(html):
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "token"})
    if inp and inp.get("value"):
        return inp["value"]
    # fallback regex
    m = re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']+)', html, re.I)
    return m.group(1) if m else None


def is_dl_page(html):
    return (
        ("Date of Birth" in html and "Class of Vehicle" in html)
        or "Driving Licence Details" in html
    )


def _val(soup, label):
    """label वाले td/th के आगे वाले cell की value निकालें"""
    for cell in soup.find_all(["td", "th"]):
        txt = cell.get_text(" ", strip=True)
        if label.lower() in txt.lower():
            nxt = cell.find_next_sibling("td")
            if nxt:
                return re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
    return ""


def parse_dl(html):
    soup = BeautifulSoup(html, "html.parser")

    photo, sign = "", ""
    for img in soup.find_all("img"):
        src = img.get("src", "")
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
        else:
            sign = src

    return {
        "success":             True,
        "name":                _val(soup, "Name"),
        "father_name":         _val(soup, "Father's Name") or _val(soup, "Father Name"),
        "dob":                 _val(soup, "Date of Birth"),
        "blood_group":         _val(soup, "Blood Group"),
        "category":            _val(soup, "Category"),
        "present_address":     _val(soup, "Present Address") or _val(soup, "Address"),
        "last_endorsed_state": _val(soup, "State"),
        "last_endorsed_rto":   _val(soup, "RTO"),
        "class_of_vehicles":   _val(soup, "Class of Vehicle") or _val(soup, "COV"),
        "validity":            _val(soup, "Validity"),
        "badge_numbers":       _val(soup, "Badge"),
        "photo":               photo,
        "signature":           sign,
    }


# ==============================================================
#  Core: fetch DL
# ==============================================================

def fetch_dl(dlno, dob, state="Bihar", rto_code="BR-01",
             st_name="Bihar", rto_name="", max_attempts=8):
    attempts = []

    for attempt in range(1, max_attempts + 1):
        s = new_session()
        try:
            # 1) form load → token
            r = s.get(BASE + "envaction.do", timeout=30)
            if r.status_code != 200:
                attempts.append({"attempt": attempt, "error": f"form HTTP {r.status_code}"})
                continue

            token = extract_token(r.text)
            if not token:
                attempts.append({"attempt": attempt, "error": "no token"})
                continue

            # 2) captcha image
            r = s.get(
                BASE + "jsp/common/captchaimage.jsp",
                params={"_": int(time.time() * 1000)},
                timeout=30,
            )
            if r.status_code != 200 or len(r.content) < 100:
                attempts.append({"attempt": attempt, "error": "captcha fetch failed"})
                continue

            # 3) OCR (ddddocr)
            captcha = OCR.classification(r.content) or ""
            captcha = re.sub(r"[^A-Za-z0-9]", "", captcha)
            attempts.append({"attempt": attempt, "captcha": captcha})

            if not captcha:
                continue

            # 4) submit
            post = {
                "capToDisp":                              "",
                "captchaByApplicant":                     "",
                "dlno":                                   dlno,
                "dob":                                    dob,
                "entCaptha":                              captcha,   # only once!
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

            r = s.post(BASE + "envaction.do", data=post, timeout=45)

            if is_dl_page(r.text):
                result = parse_dl(r.text)
                result["attempts"] = attempts
                result["ocr_engine"] = "ddddocr"
                return result

        except Exception as e:
            attempts.append({"attempt": attempt, "error": str(e)})

    return {
        "success": False,
        "error": "max attempts reached (captcha mismatch)",
        "attempts": attempts,
        "ocr_engine": "ddddocr",
    }


# ==============================================================
#  Routes
# ==============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/dl")
def api_dl():
    dlno    = (request.args.get("dlno") or "").strip()
    dob     = (request.args.get("dob") or "").strip()
    state   = request.args.get("state", "Bihar")
    rto     = request.args.get("rto_code", "BR-01")
    st_name = request.args.get("st_name", "Bihar")
    rto_nm  = request.args.get("rto_name", "")

    if not dlno or not dob:
        return jsonify({"error": "dlno और dob ज़रूरी हैं"}), 400

    return jsonify(fetch_dl(dlno, dob, state, rto, st_name, rto_nm))


@app.route("/healthz")
def health():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
