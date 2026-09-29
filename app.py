import base64
import json
import os
from typing import Any

import requests
from flask import Flask, render_template, request, session
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ------------------------------------------------------------------ config
AES_KEY_B64 = os.environ.get(
    "ECI_AES_KEY_B64",
    "e855n97lc4tcPkj7WWsi38yNWpalLBLZzQdkqHWYbZ0=",
)
PUBLIC_KEY_B64 = os.environ.get(
    "ECI_PUBLIC_KEY_B64",
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArb7++BxL/YN8OIln+6FL9Gnw5DNmQ/VFZXss"
    "+J+TuQyJc891JbqbijxYQNEin2c2u+CnpXpoGQ/1gUSzDMJeNS3sNSlIUykp2dt7xIm/cmV4sZ/c769v"
    "CxVRosMfRaZJnBAah+m1X26lEhnOo0wpAB9Txr8RIyBe6h7PiQWykeJeh6UacOBBX28kgkq7+vJhW8Hg"
    "B38lt32XRocznRYwS9LqR7ZweFmQhTr1+EGrqiEKCOCxMYgHR2SQckb96hZ9kWzfzeun4bUO5oXKJciL"
    "kiS1IgKieADEvYLgu129ZIpn1H+8H+8ikNNVETqEDDMtqcQcQmWppJvcWHaXAs+f8QIDAQAB",
)

CAPTCHA_URL = "https://gateway-voters.eci.gov.in/api/v1/captcha-service/getCaptcha/sir"
SEARCH_URL = (
    "https://gateway-voters.eci.gov.in/api/v1/elastic/"
    "search-by-epic-from-national-display-v1"
)

HEADERS_COMMON = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://electoralsearch.eci.gov.in",
    "Referer": "https://electoralsearch.eci.gov.in/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "appName": "ELECTORAL-SEARCH",
    "applicationName": "ELECTORAL-SEARCH",
    "channelidobo": "ELECTORAL-SEARCH",
    "sec-ch-ua": '"Google Chrome";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(32))


# ------------------------------------------------------------------ crypto
def _fixed_key() -> bytes:
    return base64.b64decode(AES_KEY_B64)


def decrypt_fixed(blob_b64: str) -> Any:
    raw = base64.b64decode(blob_b64)
    iv, body = raw[:12], raw[12:]
    tag, ciphertext = body[-16:], body[:-16]
    plain = AESGCM(_fixed_key()).decrypt(iv, ciphertext + tag, None)
    return json.loads(plain.decode("utf-8"))


def _public_key():
    pem = (
        "-----BEGIN PUBLIC KEY-----\n"
        + "\n".join(PUBLIC_KEY_B64[i : i + 64] for i in range(0, len(PUBLIC_KEY_B64), 64))
        + "\n-----END PUBLIC KEY-----\n"
    )
    return serialization.load_pem_public_key(pem.encode())


def encrypt_payload(data: dict) -> dict:
    aes_key = os.urandom(32)
    iv = os.urandom(12)
    plaintext = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    ct = AESGCM(aes_key).encrypt(iv, plaintext, None)
    enc_key = _public_key().encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return {
        "encryptedPayload": base64.b64encode(ct).decode(),
        "encryptedKey": base64.b64encode(enc_key).decode(),
        "iv": base64.b64encode(iv).decode(),
    }


# ------------------------------------------------------------------ ECI calls
def fetch_captcha() -> dict:
    r = requests.get(CAPTCHA_URL, headers=HEADERS_COMMON, timeout=30)
    r.raise_for_status()
    blob = r.json().get("data")
    if not blob:
        raise RuntimeError(f"CAPTCHA response invalid: {r.text[:200]}")
    data = decrypt_fixed(blob)
    return {"id": data.get("id", ""), "img_b64": data.get("captcha", "")}


def search_epic(epic: str, captcha_text: str, captcha_id: str) -> Any:
    payload = {
        "epicNumber": epic,
        "captcha": captcha_text,
        "captchaId": captcha_id,
    }
    enc = encrypt_payload(payload)
    r = requests.post(
        SEARCH_URL,
        headers={**HEADERS_COMMON, "Content-Type": "application/json"},
        data=json.dumps(enc),
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Search HTTP {r.status_code}: {r.text[:300]}")
    j = r.json()
    blob = j.get("data")
    return decrypt_fixed(blob) if blob else j


# ------------------------------------------------------------------ routes
@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    result = None
    captcha_id = request.form.get("captcha_id", "")
    captcha_img = request.form.get("captcha_img", "")
    epic_value = request.form.get("epic", "")

    if request.method == "POST":
        epic = (request.form.get("epic") or "").strip()
        captcha_text = (request.form.get("captcha_text") or "").strip()

        if not epic or not captcha_text:
            error = "EPIC aur CAPTCHA dono bharo."
        else:
            try:
                result = search_epic(epic, captcha_text, captcha_id)
            except Exception as e:
                error = str(e)

    # Naya CAPTCHA sirf GET par ya error ke baad fetch karo
    if request.method == "GET" or error or result is not None:
        try:
            cap = fetch_captcha()
            captcha_id = cap["id"]
            captcha_img = cap["img_b64"]
        except Exception as e:
            error = (error + " | " if error else "") + f"CAPTCHA fetch failed: {e}"

    return render_template(
        "index.html",
        error=error,
        result=result,
        captcha_id=captcha_id,
        captcha_img=captcha_img,
        epic_value=epic_value,
    )


@app.route("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
