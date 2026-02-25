import os
import re
import json
import time
import random
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

# Fallback: se o import do Scrapling mudar na sua versão, a API continua funcionando com requests
try:
    from scrapling import StealthySession  # comum em várias versões
    SCRAPLING_OK = True
except Exception:
    StealthySession = None
    SCRAPLING_OK = False

import requests

app = FastAPI(title="Scrap API", version="1.0.1")


class TrackRequest(BaseModel):
    trackCodes: List[str] = Field(..., min_length=1)


def get_carrier_path(code: str) -> str:
    """
    Mantive a mesma lógica do seu anexo: sempre acaba em 'jadlog'
    (você pode expandir aqui depois).
    """
    c = (code or "").strip()
    prefixes_jadlog = {
        2: ["53", "54"],
        3: [
            "100", "112", "115", "121", "124", "130", "131", "134", "181",
            "410", "411", "412", "413", "418", "438", "446", "448", "449",
            "450", "451", "453"
        ],
    }
    for size, prefixes in prefixes_jadlog.items():
        if c[:size] in prefixes:
            return "jadlog"
    return "jadlog"


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def build_headers() -> Dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.rastreadordepacotes.com.br/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
    }


def strip_tags_keep_text(html: str) -> str:
    text = re.sub(r"<br\s*/?\s*>", "\n", html or "", flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pacote_object(html: str) -> Optional[Dict[str, Any]]:
    """
    Extrai 'var pacote = {...}' do HTML (igual sua abordagem).
    """
    m = re.search(r"var\s+pacote\s*=\s*\{", html, flags=re.I)
    if not m:
        return None

    brace_start = html.find("{", m.start())
    if brace_start == -1:
        return None

    depth = 0
    in_str = False
    str_ch = ""
    esc = False

    for i in range(brace_start, len(html)):
        ch = html[i]

        if in_str:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == str_ch:
                in_str = False
                str_ch = ""
            continue

        if ch in ("'", '"'):
            in_str = True
            str_ch = ch
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj_text = html[brace_start : i + 1]
                try:
                    return json.loads(obj_text)
                except json.JSONDecodeError:
                    return None

    return None


def fallback_extract_events_from_list(html: str) -> List[Dict[str, str]]:
    """
    Fallback: tenta extrair eventos do HTML (lista <li>).
    """
    out: List[Dict[str, str]] = []
    section_match = re.search(
        r"Rastreamento detalhado([\s\S]*?)(Principais buscas|Advertise|</footer>|</body>)",
        html,
        flags=re.I,
    )
    if not section_match:
        return out

    block = section_match.group(1)
    li_matches = re.findall(r"<li[^>]*>[\s\S]*?</li>", block, flags=re.I)

    for li_html in li_matches:
        date_match = re.search(
            r"<span[^>]*>\s*(\d{1,2}\s+\w+\s+\d{4})\s*</span>[\s\S]*?"
            r"<span[^>]*>\s*(\d{2}:\d{2}:\d{2})\s*</span>",
            li_html,
            flags=re.I,
        )
        date_text = ""
        if date_match:
            date_text = f"{strip_tags_keep_text(date_match.group(1))} {strip_tags_keep_text(date_match.group(2))}"

        content_text = strip_tags_keep_text(li_html)
        if date_match:
            content_text = content_text.replace(strip_tags_keep_text(date_match.group(1)), "")
            content_text = content_text.replace(strip_tags_keep_text(date_match.group(2)), "")
        desc = re.sub(r"\s+", " ", content_text).strip()

        if date_text or desc:
            out.append({"datetime": date_text, "description": desc})

    return out


def dedupe_events(events: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    uniq = []
    for ev in events:
        key = f"{ev.get('datetime','')}||{ev.get('description','')}"
        if key not in seen:
            seen.add(key)
            uniq.append(ev)
    return uniq


def fetch_html(url: str) -> Dict[str, Any]:
    """
    Busca HTML com retry + backoff para 429.
    Tenta Scrapling (StealthySession) primeiro; se não der, cai pra requests.
    """
    waits = [0, 3, 10, 25]
    last_status = None
    last_text = ""

    for attempt, w in enumerate(waits, start=1):
        if w:
            time.sleep(w)

        headers = build_headers()

        # 1) Tenta Scrapling (se disponível)
        if SCRAPLING_OK and StealthySession is not None:
            try:
                with StealthySession() as s:
                    resp = s.get(url, headers=headers)
                    status = getattr(resp, "status_code", None) or 0
                    text = getattr(resp, "text", None) or ""
            except Exception as e:
                status = 0
                text = f"SCRAPLING_ERROR: {e}"
        else:
            status = 0
            text = "SCRAPLING_NOT_AVAILABLE"

        # 2) Se Scrapling não funcionou, tenta requests
        if status in (0, None) or (isinstance(text, str) and text.startswith("SCRAPLING_")):
            try:
                r = requests.get(url, headers=headers, timeout=30)
                status = r.status_code
                text = r.text
            except Exception as e:
                status = 0
                text = f"REQUESTS_ERROR: {e}"

        last_status = status
        last_text = text

        # Se não for 429, para
        if status != 429:
            return {"status": status, "text": text, "attempts": attempt, "used": "scrapling_or_requests"}

    return {"status": last_status or 0, "text": last_text or "", "attempts": len(waits), "used": "scrapling_or_requests"}


def scrape_one(track_code: str) -> Dict[str, Any]:
    track_code = (track_code or "").strip()
    if not track_code:
        return {"success": False, "trackCode": track_code, "error": "empty trackCode"}

    carrier = get_carrier_path(track_code)
    url = f"https://www.rastreadordepacotes.com.br/rastreio/{carrier}/{track_code}"

    fetched = fetch_html(url)
    status = int(fetched.get("status") or 0)
    html = fetched.get("text") or ""
    attempts = fetched.get("attempts") or 1

    if status >= 400 and status != 429:
        return {
            "success": False,
            "trackCode": track_code,
            "url": url,
            "http": status,
            "error": f"HTTP {status}",
            "debug": {"attempts": attempts, "htmlSize": len(html)},
        }

    if status == 429:
        return {
            "success": False,
            "trackCode": track_code,
            "url": url,
            "http": status,
            "error": "rate_limited_429",
            "debug": {"attempts": attempts, "htmlSize": len(html)},
        }

    events: List[Dict[str, str]] = []
    parser_used = "none"

    pacote = extract_pacote_object(html)
    if pacote and pacote.get("Success") and isinstance(pacote.get("Posicoes"), list):
        for p in pacote["Posicoes"]:
            dt = (p.get("Data") or "").strip() if isinstance(p, dict) else ""
            desc_raw = ""
            if isinstance(p, dict):
                desc_raw = p.get("DetalhesFormatado") or p.get("Detalhes") or ""
            desc = re.sub(r"\s+", " ", strip_tags_keep_text(str(desc_raw))).strip()
            if dt or desc:
                events.append({"datetime": dt, "description": desc})
        if events:
            parser_used = "pacote"

    if not events:
        events = fallback_extract_events_from_list(html)
        if events:
            parser_used = "html_list"

    events = dedupe_events(events)

    return {
        "success": True,
        "trackCode": track_code,
        "url": url,
        "http": status,
        "hasData": len(events) > 0,
        "eventCount": len(events),
        "events": events,
        "debug": {"parserUsed": parser_used, "attempts": attempts, "htmlSize": len(html)},
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/track")
def track(req: TrackRequest):
    results = []
    # throttle: evita pedir muitos de uma vez e tomar 429
    for i, code in enumerate(req.trackCodes):
        if i > 0:
            time.sleep(1.2)
        results.append(scrape_one(code))

    return {"success": True, "count": len(results), "results": results}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)