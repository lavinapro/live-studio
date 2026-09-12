"""
Прокси между приложением и LLM.

Нужен, чтобы API-ключ жил на сервере, а не в исходнике страницы,
который может открыть кто угодно.

Запуск:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...
    export ALLOWED_ORIGIN=https://USERNAME.github.io
    uvicorn app:app --host 127.0.0.1 --port 8787
"""

import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

PROVIDER = os.environ.get("PROVIDER", "anthropic")  # anthropic | openai
KEY = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
SECRET = os.environ.get("LIVE_SECRET", "")  # необязательный пароль
ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGIN", "*").split(",")]

if not KEY:
    raise RuntimeError("Не задан ANTHROPIC_API_KEY или OPENAI_API_KEY")

app = FastAPI(title="Live Studio proxy")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"ok": True, "provider": PROVIDER}


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()

    if SECRET and body.get("secret") != SECRET:
        raise HTTPException(status_code=403, detail="bad secret")

    prompt = str(body.get("prompt", ""))[:4000]
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if PROVIDER == "openai":
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {KEY}"},
                    json={
                        "model": os.environ.get("MODEL", "gpt-4o-mini"),
                        "max_tokens": 400,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                # приводим к формату, который ждёт фронтенд
                return {"content": [{"text": text}]}

            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": os.environ.get("MODEL", "claude-haiku-4-5-20251001"),
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            return r.json()

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"upstream {e.response.status_code}")
    except httpx.RequestError:
        raise HTTPException(status_code=504, detail="upstream timeout")
