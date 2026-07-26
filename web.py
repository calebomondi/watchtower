"""
WatchTower — FastAPI server

- UptimeRobot pings / to keep Render alive
- /okx-webhook receives task notifications from okx-a2a daemon
"""

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
    """
    try:
        from okx_handler import process_webhook
        payload = await request.json()
        logger.info(f"Received OKX webhook: {payload.get('event', 'unknown')}")
        result = await process_webhook(payload)
        return result
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}
