import os
import time
from typing import List, Any

from fastapi import FastAPI
from pydantic import BaseModel

from scrapling import StealthyFetcher

app = FastAPI(title="Scrap API", version="1.0.2")


class TrackRequest(BaseModel):
    trackCodes: List[str]


def get_status(resp: Any) -> int:
    """
    Compatível com variações do Scrapling:
    - resp.status_code (algumas versões)
    - resp.status (outras)
    - resp.response.status_code (quando encapsula lib interna)
    """
    for attr in ("status_code", "status"):
        v = getattr(resp, attr, None)
        if isinstance(v, int):
            return v

    inner = getattr(resp, "response", None)
    v2 = getattr(inner, "status_code", None) if inner is not None else None
    if isinstance(v2, int):
        return v2

    return 0


def get_text(resp: Any) -> str:
    t = getattr(resp, "text", None)
    if isinstance(t, str):
        return t
    c = getattr(resp, "content", None)
    if isinstance(c, (bytes, bytearray)):
        try:
            return c.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return ""


def scrape_one(code: str):
    code = (code or "").strip()
    url = f"https://www.rastreadordepacotes.com.br/rastreio/jadlog/{code}"

    fetcher = StealthyFetcher()

    # Obs: o log que você mostrou indica que ele já está usando referer/search por baixo.
    resp = fetcher.get(url)

    status = get_status(resp)
    html = get_text(resp)

    return {
        "trackCode": code,
        "http": status,
        "htmlSize": len(html),
        "url": url,
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
    return {"success": True, "count": len(results), "results": results}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)