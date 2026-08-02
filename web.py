import asyncio
import json
import logging
from contextlib import asynccontextmanager

import os
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("watchtower.web")

from polymarket.gamma import GammaClient
from polymarket.clob import ClobClient
from chat_session import create_session, get_session, run_analysis_with_progress, chat_completion


gamma: GammaClient | None = None
clob: ClobClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global gamma, clob
    gamma = GammaClient()
    clob = ClobClient()
    yield
    await gamma.close()
    await clob.close()


app = FastAPI(title="WatchTower", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    if os.path.isfile(NEXT_HTML):
        return FileResponse(NEXT_HTML, media_type="text/html")
    return {"status": "ok", "agent": "WatchTower", "agent_id": "9643"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/okx-webhook")
async def okx_webhook(request: Request):
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


TURBO_MODE = False


@app.get("/api/config")
async def get_config():
    return {"ok": True, "turbo_mode": TURBO_MODE}


@app.post("/api/config/turbo")
async def set_turbo_mode(request: Request):
    global TURBO_MODE
    body = await request.json()
    TURBO_MODE = bool(body.get("enabled", False))
    return {"ok": True, "turbo_mode": TURBO_MODE}


# ----- Polymarket API Routes -----

@app.get("/api/tags")
async def list_tags():
    try:
        events, _ = await gamma.list_events(closed=False, limit=50)
        tag_map: dict[str, dict] = {}
        for ev in events:
            ev_slugs = {t["slug"] for t in ev.tags}
            open_markets = [m for m in ev.markets if not m.closed and m.enable_order_book is not False]
            for tag in ev.tags:
                slug = tag["slug"]
                if slug not in tag_map:
                    tag_map[slug] = {"label": tag["label"], "slug": slug, "market_count": 0}
                tag_map[slug]["market_count"] += len(open_markets)
        tags = sorted(tag_map.values(), key=lambda t: -t["market_count"])
        return {"ok": True, "tags": tags}
    except Exception as e:
        logger.error(f"list_tags error: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/api/markets")
async def list_markets(closed: bool = False, limit: int = 50, tag: str | None = None, q: str | None = None):
    try:
        events, cursor = await gamma.list_events(closed=closed, limit=limit, tag=tag, search=q)
        result = []
        for ev in events:
            ev_dict = ev.model_dump()
            ev_dict["markets"] = [m.model_dump() for m in ev.markets]
            result.append(ev_dict)
        return {"ok": True, "events": result, "next_cursor": cursor}
    except Exception as e:
        logger.error(f"list_markets error: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/api/markets/{market_id}")
async def get_market(market_id: str):
    try:
        market = await gamma.get_market(market_id)
        if not market:
            return {"ok": False, "error": "market not found"}

        book = None
        if market.yes_token_id:
            try:
                book = await clob.get_book(market.yes_token_id)
            except Exception as e:
                logger.warning(f"Failed to fetch order book: {e}")

        md = market.model_dump()
        if book:
            md["order_book"] = book.model_dump()
        return {"ok": True, "market": md}
    except Exception as e:
        logger.error(f"get_market error: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/api/markets/{market_id}/analyze")
async def analyze_market(market_id: str, request: Request):
    try:
        body = await request.json()
        question = body.get("question", "")

        market = await gamma.get_market(market_id)
        if not market:
            return {"ok": False, "error": "market not found"}

        book = None
        best_bid = None
        best_ask = None
        if market.yes_token_id:
            try:
                book = await clob.get_book(market.yes_token_id)
                best_bid = book.best_bid
                best_ask = book.best_ask
            except Exception:
                pass

        if not question:
            question = market.question

        market_context = {
            "yes_price": market.yes_price,
            "no_price": market.no_price,
            "volume": market.volume,
            "volume_24hr": market.volume_24hr,
            "liquidity": market.liquidity,
            "spread": market.spread,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "end_date": market.end_date,
            "outcomes": market.outcomes,
            "closed": market.closed,
            "description": market.description[:500] if market.description else "",
        }

        session = create_session(market_id, question, market_context)

        return {
            "ok": True,
            "session_id": session.session_id,
            "market": market.model_dump(),
        }
    except Exception as e:
        logger.error(f"analyze_market error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


@app.websocket("/api/chat/ws/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = get_session(session_id)

    if not session:
        await websocket.send_json({"type": "error", "content": "session not found"})
        await websocket.close()
        return

    loop = asyncio.get_event_loop()

    if not session.analysis_complete:
        progress_queue: asyncio.Queue = asyncio.Queue()

        def progress_callback(msg_type: str, content: str):
            asyncio.run_coroutine_threadsafe(
                progress_queue.put({"type": msg_type, "content": content}),
                loop,
            )

        async def run_and_report():
            try:
                await loop.run_in_executor(
                    None,
                    run_analysis_with_progress,
                    session,
                    progress_callback,
                )
            except Exception as e:
                await progress_queue.put({"type": "error", "content": f"Analysis failed: {e}"})
                logger.error(f"Analysis error for session {session_id}: {e}", exc_info=True)
            finally:
                await progress_queue.put(None)

        asyncio.create_task(run_and_report())

        try:
            while True:
                msg = await progress_queue.get()
                if msg is None:
                    break
                await websocket.send_json(msg)

            if session.analysis:
                analysis_data = json.loads(session.analysis) if isinstance(session.analysis, str) else session.analysis
                await websocket.send_json({"type": "analysis", "content": analysis_data})
        except WebSocketDisconnect:
            logger.info(f"Client disconnected from session {session_id} during analysis")
            return

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                user_text = msg.get("message", data)
            except json.JSONDecodeError:
                user_text = data

            await websocket.send_json({"type": "status", "content": "thinking..."})

            response = await loop.run_in_executor(None, chat_completion, session, user_text)

            await websocket.send_json({
                "type": "message",
                "content": response,
            })
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


NEXT_BUILD_DIR = os.path.join(os.path.dirname(__file__), "frontend", ".next")
NEXT_STATIC_DIR = os.path.join(NEXT_BUILD_DIR, "static")
NEXT_HTML = os.path.join(NEXT_BUILD_DIR, "server", "app", "index.html")


if os.path.isdir(NEXT_STATIC_DIR):
    app.mount("/_next/static", StaticFiles(directory=NEXT_STATIC_DIR), name="next_assets")

    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc):
        path = request.url.path.split("?")[0]
        if not path.startswith("/api/"):
            next_file = os.path.join(NEXT_BUILD_DIR, "server", "app", path.lstrip("/"))
            if os.path.isfile(next_file) and not path.endswith(".meta") and not path.endswith(".body") and not path.endswith(".rsc"):
                return FileResponse(next_file)
            if os.path.isfile(NEXT_HTML):
                return FileResponse(NEXT_HTML, media_type="text/html")
        return {"error": "not found"}

    logger.info("Serving frontend SPA from %s", NEXT_BUILD_DIR)
else:
    logger.warning("Frontend build not found. API-only mode.")
