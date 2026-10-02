# app.py
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from eci import run_search

app = FastAPI(title="ECI Electoral Search")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class SearchRequest(BaseModel):
    epic: str
    attempts: int = 5


# ---------------- UI ----------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------------- API ----------------

@app.post("/search")
def search(req: SearchRequest):
    if not req.epic or len(req.epic.strip()) < 3:
        raise HTTPException(status_code=400, detail="invalid epic")
    if req.attempts < 1 or req.attempts > 15:
        raise HTTPException(status_code=400, detail="attempts must be 1-15")

    result, attempts, captcha_text = run_search(
        req.epic.strip(), max_attempts=req.attempts
    )
    return {
        "epic": req.epic.strip(),
        "attempts": attempts,
        "captcha_text": captcha_text,
        "result": result,
    }


# ---------------- Server-rendered result (optional) ----------------

@app.post("/search-form", response_class=HTMLResponse)
def search_form(request: Request, epic: str, attempts: int = 5):
    result, used, captcha_text = run_search(epic.strip(), max_attempts=attempts)
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "epic": epic.strip(),
            "attempts": used,
            "captcha_text": captcha_text,
            "result": result,
        },
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
