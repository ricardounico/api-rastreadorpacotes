from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import requests

app = FastAPI()

class TrackRequest(BaseModel):
    trackCodes: List[str]

@app.get("/")
def root():
    return {"status": "online"}

@app.post("/track")
def track(req: TrackRequest):
    results = []

    for code in req.trackCodes:
        url = f"https://www.rastreadordepacotes.com.br/rastreio/jadlog/{code}"
        r = requests.get(url)

        results.append({
            "trackCode": code,
            "http": r.status_code,
            "htmlSize": len(r.text)
        })

    return {"success": True, "results": results}