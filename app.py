import os
import uuid
import subprocess
import torch
import uvicorn
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from TTS.api import TTS

# ---------- Setup ----------
os.makedirs("outputs", exist_ok=True)
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[INFO] Loading XTTS v2 on {DEVICE} ...")
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(DEVICE)
print("[INFO] Model ready.")

SUPPORTED_LANGS = {"hi", "en", "es", "fr", "de", "it", "pt", "pl",
                   "tr", "ru", "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko"}


# ---------- Routes ----------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok", "device": DEVICE}


@app.post("/clone")
async def clone_voice(
    text: str = Form(...),
    language: str = Form("hi"),
    ref_audio: UploadFile = File(...),
):
    if language not in SUPPORTED_LANGS:
        return JSONResponse({"error": f"Unsupported language: {language}"}, status_code=400)
    if not text.strip():
        return JSONResponse({"error": "Text is empty"}, status_code=400)

    job_id = str(uuid.uuid4())
    raw_path = f"/tmp/{job_id}_raw"
    ref_wav = f"/tmp/{job_id}_ref.wav"
    out_path = f"outputs/{job_id}.wav"

    try:
        # 1. Save uploaded audio
        with open(raw_path, "wb") as f:
            f.write(await ref_audio.read())

        # 2. Convert to mono 22050 Hz WAV (XTTS को यही चाहिए)
        subprocess.run(
            ["ffmpeg", "-y", "-i", raw_path,
             "-ar", "22050", "-ac", "1", ref_wav],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 3. Generate cloned audio
        tts.tts_to_file(
            text=text,
            speaker_wav=ref_wav,
            language=language,
            file_path=out_path,
        )

        return JSONResponse({"audio_url": f"/outputs/{job_id}.wav"})

    except subprocess.CalledProcessError:
        return JSONResponse({"error": "ऑडियो फाइल पढ़ी नहीं जा सकी।"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        for p in (raw_path, ref_wav):
            if os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
