# app.py
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from eci import run_search

app = FastAPI(title="ECI Electoral Search API")


class SearchRequest(BaseModel):
    epic: str
    attempts: int = 5


@app.get("/")
def root():
    return {"status": "ok", "service": "eci-search"}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/search")
def search(req: SearchRequest):
    if not req.epic or len(req.epic) < 3:
        raise HTTPException(status_code=400, detail="invalid epic")
    result, attempts, captcha = run_search(req.epic, max_attempts=req.attempts)
    return {
        "epic": req.epic,
        "attempts": attempts,
        "captcha_text": captcha,
        "result": result,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
