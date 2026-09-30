# eci.py
import base64
import io
import json
import os
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CAPTCHA_URL = "https://gateway-voters.eci.gov.in/api/v1/captcha-service/getCaptcha/sir"
SEARCH_URL = (
    "https://gateway-voters.eci.gov.in/api/v1/elastic/"
    "search-by-epic-from-national-display-v1"
)

CAPTCHA_AES_KEY = base64.b64decode("e855n97lc4tcPkj7WWsi38yNWpalLBLZzQdkqHWYbZ0=")

PUBLIC_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArb7++BxL/YN8OIln+6FL9Gnw5DNm"
    "Q/VFZXss+J+TuQyJc891JbqbijxYQNEin2c2u+CnpXpoGQ/1gUSzDMJeNS3sNSlIUykp2dt7"
    "xIm/cmV4sZ/c769vCxVRosMfRaZJnBAah+m1X26lEhnOo0wpAB9Txr8RIyBe6h7PiQWykeJe"
    "h6UacOBBX28kgkq7+vJhW8HgB38lt32XRocznRYwS9LqR7ZweFmQhTr1+EGrqiEKCOCxMYgH"
    "R2SQckb96hZ9kWzfzeun4bUO5oXKJciLkiS1IgKieADEvYLgu129ZIpn1H+8H+8ikNNVETqE"
    "DDMtqcQcQmWppJvcWHaXAs+f8QIDAQAB"
)

COMMON_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Origin": "https://electoralsearch.eci.gov.in",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    ),
    "appName": "ELECTORAL-SEARCH",
    "applicationName": "ELECTORAL-SEARCH",
    "channelidobo": "ELECTORAL-SEARCH",
    "sec-ch-ua": '"Chromium";v="154", "Google Chrome";v="154", "Not A(Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

_PUBLIC_KEY = None
_OCR = None


def _get_public_key():
    global _PUBLIC_KEY
    if _PUBLIC_KEY is None:
        der = base64.b64decode(PUBLIC_KEY_B64)
        _PUBLIC_KEY = serialization.load_der_public_key(der)
    return _PUBLIC_KEY


def _get_ocr():
    global _OCR
    if _OCR is None:
        import ddddocr
        _OCR = ddddocr.DdddOcr(show_ad=False)
    return _OCR


def decrypt_captcha(encrypted_b64: str) -> dict:
    raw = base64.b64decode(encrypted_b64)
    iv, body = raw[:12], raw[12:]
    tag, ciphertext = body[-16:], body[:-16]
    pt = AESGCM(CAPTCHA_AES_KEY).decrypt(iv, ciphertext + tag, None)
    return json.loads(pt.decode("utf-8"))


def fetch_captcha() -> dict:
    headers = {**COMMON_HEADERS, "Content-Type": "application/json"}
    r = requests.get(CAPTCHA_URL, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json().get("data")
    if not data:
        raise RuntimeError("captcha data missing")
    dec = decrypt_captcha(data)
    return {
        "captcha_b64": dec.get("captcha"),
        "id": dec.get("id"),
        "raw_data": data,
    }


def rsa_oaep_sha256_encrypt(msg: bytes) -> bytes:
    return _get_public_key().encrypt(
        msg,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def encrypt_payload(data: dict) -> dict:
    json_bytes = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    aes_key = os.urandom(32)
    iv = os.urandom(12)
    ct_tag = AESGCM(aes_key).encrypt(iv, json_bytes, None)
    ek = rsa_oaep_sha256_encrypt(aes_key)
    return {
        "encryptedPayload": base64.b64encode(ct_tag).decode(),
        "encryptedKey": base64.b64encode(ek).decode(),
        "iv": base64.b64encode(iv).decode(),
    }


def search_by_epic(epic: str, captcha_id, captcha_text: str) -> dict:
    payload = {
        "epicNumber": epic,
        "isPortal": True,
        "captchaId": captcha_id,
        "captchaData": captcha_text,
        "securityKey": "na",
        "eSEARCHYNEFjd3S": "1021",
    }
    encrypted = encrypt_payload(payload)
    headers = {**COMMON_HEADERS, "Content-Type": "application/json"}
    r = requests.post(SEARCH_URL, headers=headers, data=json.dumps(encrypted), timeout=45)
    try:
        return r.json()
    except ValueError:
        return {"_status_code": r.status_code, "_text": r.text}


def solve_captcha(image_bytes: bytes) -> str:
    text = _get_ocr().classification(image_bytes) or ""
    return text.strip()


def run_search(epic: str, max_attempts: int = 5, delay: float = 0.6):
    """Returns (result_dict, attempts_used, last_captcha_text)."""
    last_text = None
    for attempt in range(1, max_attempts + 1):
        cap = fetch_captcha()
        img = base64.b64decode(cap["captcha_b64"])
        text = solve_captcha(img)
        last_text = text
        if not text:
            time.sleep(delay)
            continue
        result = search_by_epic(epic, cap["id"], text)
        blob = json.dumps(result)
        if any(k in blob for k in ("Invalid Captcha", "invalid captcha", "captcha is invalid")):
            time.sleep(delay)
            continue
        return result, attempt, text
    return {"error": "captcha_failed", "attempts": max_attempts}, max_attempts, last_text
