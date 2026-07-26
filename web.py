"""
WatchTower — FastAPI server

- /          → UptimeRobot health check (keeps Render alive)
- /health    → health check
- /okx-webhook → receives task notifications from okx-a2a daemon
- /run-task  → manually trigger task processing (for testing)
"""

import asyncio
import logging

from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("watchtower.web")

app = FastAPI(title="WatchTower")


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "ok", "agent": "WatchTower", "agent_id": "9643"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/okx-webhook")
async def okx_webhook(request: Request):
    """
    Webhook for okx-a2a daemon to notify about task events.
    The daemon POSTs task notifications here when events occur.
    """
    try:
        from okx_handler import process_webhook
        payload = await request.json()
        logger.info(f"Webhook: {payload.get('message', {}).get('event', 'unknown event')}")
        result = await process_webhook(payload)
        return result
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/run-task")
async def run_task(request: Request):
    """
    Manually trigger WatchTower analysis on a question.
    Useful for testing without the XMTP daemon.
    """
    try:
        from okx_handler import run_watchtower
        body = await request.json()
        question = body.get("question", body.get("content", ""))
        if not question:
            return {"ok": False, "error": "missing 'question' field"}

        logger.info(f"Manual task: {question[:80]}...")
        analysis = run_watchtower(question)
        return {"ok": True, "analysis": analysis}
    except Exception as e:
        logger.error(f"Task error: {e}")
        return {"ok": False, "error": str(e)}
