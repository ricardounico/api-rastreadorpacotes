import os
import time
import random
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel

from scrapling import Fetcher

app = FastAPI()

class TrackRequest(BaseModel):
    trackCodes: List[str]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def build_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.rastreadordepacotes.com.br/"
    }

def scrape_one(code: str):
    url = f"https://www.rastreadordepacotes.com.br/rastreio/jadlog/{code}"

    fetcher = Fetcher()
    resp = fetcher.get(url, headers=build_headers())

    return {
        "trackCode": code,
        "http": resp.status_code,
        "htmlSize": len(resp.text)
    }

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/track")
def track(req: TrackRequest):
    results = []

    for i, code in enumerate(req.trackCodes):
        if i > 0:
            time.sleep(1.2)

        results.append(scrape_one(code))

    return {"success": True, "results": results}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)