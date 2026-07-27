"""
WatchTower — OKX AI Agent Handler

Processes marketplace tasks directly using WatchTower's expert opinion agent.
"""

import json
import logging
import subprocess
import os
from typing import Any

logger = logging.getLogger("watchtower.okx-handler")

AGENT_ID = os.getenv("OKX_AGENT_ID", "9643")


# ── onchainos CLI wrapper ──────────────────────────────────────────────────────

def run_cli(args: list[str], timeout: int = 300) -> dict:
    """Run an onchainos CLI command and return parsed JSON."""
    cmd = ["onchainos"] + args
    logger.info(f"CLI: {' '.join(cmd[:8])}...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.stdout.strip():
            return json.loads(result.stdout)
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr or f"exit code {result.returncode}"}
        return {"ok": True}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"bad json: {e}", "raw": result.stdout[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def next_action(agent_id: str, message: dict) -> dict:
    return run_cli([
        "agent", "next-action",
        "--role", "asp",
        "--agent-id", agent_id,
        "--message", json.dumps(message),
    ])


def deliver(agent_id: str, job_id: str, text: str) -> dict:
    """Submit a text deliverable for a job."""
    return run_cli([
        "agent", "deliver",
        "--agent-id", agent_id,
        job_id,
        "--deliverable-text", text,
        "--message", "WatchTower analysis complete",
    ])


def apply_for_job(agent_id: str, job_id: str, amount: str, symbol: str) -> dict:
    """Apply for a job with a quoted price."""
    return run_cli([
        "agent", "apply",
        "--agent-id", agent_id,
        job_id,
        "--token-amount", amount,
        "--token-symbol", symbol,
    ])


def xmtp_send(job_id: str, to_agent_id: str, message: str) -> dict:
    """Send a peer message via XMTP."""
    return run_cli([
        "okx-a2a", "xmtp-send",
        "--job-id", job_id,
        "--to-agent-id", to_agent_id,
        "--message", message,
    ], timeout=60)


# ── WatchTower agent ───────────────────────────────────────────────────────────

from main import run_watchtower  # noqa: F401 — re-exported from main.py


# ── Task event handlers ────────────────────────────────────────────────────────

def handle_job_asp_selected(agent_id: str, event: dict) -> dict:
    """
    A user selected us for their task.
    Auto-apply with our service fee (0.5 USDT).
    """
    job_id = event.get("jobId")
    job_title = event.get("jobTitle", "prediction market analysis")
    logger.info(f"Job selected: {job_id} — {job_title}")

    # Our service fee is 0.5 USDT per call
    result = apply_for_job(agent_id, job_id, "0.5", "USDT")
    logger.info(f"Apply result: {result}")
    return result


def handle_job_accepted(agent_id: str, event: dict) -> dict:
    """
    Our application was accepted. Escrow is funded.
    Now we do the research and deliver.
    """
    job_id = event.get("jobId")
    job_title = event.get("jobTitle", "")
    job_description = event.get("jobDescription", event.get("description", ""))
    logger.info(f"Job accepted: {job_id} — running WatchTower analysis")

    # Run WatchTower's research agent
    question = job_description or job_title or "Analyze this prediction market question"
    analysis = run_watchtower(question)

    # Deliver the result
    result = deliver(agent_id, job_id, analysis)
    logger.info(f"Deliver result: {result}")
    return result


def handle_user_message(agent_id: str, event: dict) -> dict:
    """User sent us a message — analyze and respond."""
    job_id = event.get("jobId")
    content = event.get("content", "")
    sender = event.get("sender", {})
    sender_id = sender.get("agentId", "")

    logger.info(f"User message on job {job_id}: {content[:100]}...")

    # Run WatchTower analysis
    analysis = run_watchtower(content)

    # Send response via XMTP
    if sender_id:
        result = xmtp_send(job_id, sender_id, analysis)
    else:
        result = {"ok": True, "note": "no sender_id, analysis ready but not sent"}
    return result


def handle_next_action_fallback(agent_id: str, event: dict) -> dict:
    """Use next-action CLI to determine what to do."""
    result = next_action(agent_id, event)
    logger.info(f"next-action result: {json.dumps(result)[:300]}")

    # If next-action returns a script, we could parse and execute it
    # For now, just return the result
    return result


# ── Dispatch table ─────────────────────────────────────────────────────────────

EVENT_HANDLERS = {
    "JobAspSelected":        handle_job_asp_selected,
    "JobAccepted":           handle_job_accepted,
    "user_message":          handle_user_message,
}

TERMINAL_EVENTS = {
    "JobSubmitted", "JobRejected", "JobDisputed",
    "JobComplete", "JobClosed", "JobExpired", "JobFailed",
    "sub_complete_notify", "sub_close_notify", "sub_failed_notify",
}


def handle_event(agent_id: str, event: dict) -> dict:
    """Dispatch a system event to the appropriate handler."""
    event_type = event.get("event", "unknown")
    logger.info(f"Event: {event_type}")

    if event_type in TERMINAL_EVENTS:
        logger.info(f"Terminal event {event_type} — display only")
        return {"ok": True, "action": "display_only"}

    handler = EVENT_HANDLERS.get(event_type)
    if handler:
        return handler(agent_id, event)

    # Unknown event — use next-action as fallback
    return handle_next_action_fallback(agent_id, event)


def handle_a2a_chat(agent_id: str, message: dict) -> dict:
    """Handle an a2a-agent-chat message."""
    job_id = message.get("jobId", "")
    content = message.get("content", "")
    sender = message.get("sender", {})
    sender_role = sender.get("role", 0)
    sender_id = sender.get("agentId", "")

    # Terminal: user rejected
    if content.startswith("[user_rejected]"):
        logger.info(f"User rejected on job {job_id}")
        return {"ok": True, "action": "rejected"}

    # User Agent (role 1) sent us a message
    if sender_role == 1:
        return handle_user_message(agent_id, {
            "jobId": job_id,
            "content": content,
            "sender": {"agentId": sender_id, "role": sender_role},
        })

    return {"ok": True, "action": "ignored"}


# ── Webhook entry point ────────────────────────────────────────────────────────

async def process_webhook(payload: dict) -> dict:
    """
    Entry point called by web.py when the okx-a2a daemon sends a notification.

    Payload shapes:
      System event:  { "agentId": "9643", "message": { "source": "system", "event": "...", ... } }
      A2A chat:      { "agentId": "9643", "message": { "msgType": "a2a-agent-chat", ... } }
    """
    agent_id = payload.get("agentId", AGENT_ID)
    message = payload.get("message", {})

    if message.get("source") == "system" and message.get("event"):
        return handle_event(agent_id, message)

    if message.get("msgType") == "a2a-agent-chat":
        return handle_a2a_chat(agent_id, message)

    logger.warning(f"Unrecognized payload: {json.dumps(payload)[:200]}")
    return {"ok": False, "error": "unrecognized payload"}
