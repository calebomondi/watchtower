"""
OKX AI Agent Handler for WatchTower

Bridges XMTP messages from okx-a2a daemon to WatchTower's analysis logic.
When a task is assigned to WatchTower via the OKX AI marketplace, this handler
processes it using the expert opinion agent.
"""

import asyncio
import json
import logging
import subprocess
import sys
from typing import Any

logger = logging.getLogger("watchtower.okx-handler")

# Import WatchTower's agent
try:
    from experts_opinion_agent import build_agent
    watchtower_agent = build_agent()
    WATCHTOWER_AVAILABLE = True
except Exception as e:
    logger.warning(f"WatchTower agent not available: {e}")
    WATCHTOWER_AVAILABLE = False


def run_onchainos_command(args: list[str]) -> dict:
    """Run an onchainos CLI command and return the result."""
    cmd = ["onchainos"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode == 0:
            return json.loads(result.stdout) if result.stdout.strip() else {"ok": True}
        else:
            return {"ok": False, "error": result.stderr}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "Invalid JSON response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def handle_task_event(agent_id: str, message: dict) -> dict:
    """
    Handle a system event from the okx-a2a daemon.
    
    This is called when a task-related event occurs (job created, accepted, etc.)
    """
    logger.info(f"Handling task event for agent {agent_id}: {message.get('event', 'unknown')}")
    
    # Run next-action to get the action script
    result = run_onchainos_command([
        "agent", "next-action",
        "--role", "auto",
        "--agent-id", agent_id,
        "--message", json.dumps(message)
    ])
    
    if not result.get("ok"):
        logger.error(f"next-action failed: {result.get('error')}")
        return result
    
    # The result contains a script to execute
    script = result.get("data", {}).get("script", "")
    if script:
        logger.info(f"Executing action script: {script[:100]}...")
        # Execute the script (this would be the CLI commands from next-action)
        # For now, log it - in production, you'd parse and execute
        return {"ok": True, "action": "script_ready", "script": script}
    
    return {"ok": True, "action": "no_action_needed"}


def handle_a2a_chat(agent_id: str, job_id: str, sender_role: int, content: str) -> dict:
    """
    Handle an agent-to-agent chat message.
    
    This is called when another agent sends a message (e.g., task description).
    """
    logger.info(f"Handling A2A chat for agent {agent_id}, job {job_id}")
    
    # If WatchTower agent is available and this is a task request, process it
    if WATCHTOWER_AVAILABLE and sender_role == 1:  # sender_role 1 = User Agent
        try:
            # Run WatchTower's analysis
            result = watchtower_agent.invoke({
                "messages": [{"role": "user", "content": content}]
            })
            
            # Extract the response
            response = result.get("messages", [{}])[-1].get("content", "")
            
            # Deliver the result via onchainos
            deliver_result = run_onchainos_command([
                "agent", "deliver",
                "--agent-id", agent_id,
                "--job-id", job_id,
                "--content", response
            ])
            
            return deliver_result
        except Exception as e:
            logger.error(f"WatchTower analysis failed: {e}")
            return {"ok": False, "error": str(e)}
    
    return {"ok": True, "action": "delegated_to_daemon"}


# Webhook endpoint for okx-a2a to notify about tasks
async def process_webhook(payload: dict) -> dict:
    """
    Process a webhook notification from okx-a2a daemon.
    
    Expected payload format:
    {
        "agentId": "9643",
        "event": "job_created" | "job_accepted" | ...,
        "message": { ... }
    }
    """
    agent_id = payload.get("agentId")
    event = payload.get("event")
    message = payload.get("message", {})
    
    if not agent_id:
        return {"ok": False, "error": "Missing agentId"}
    
    if event:
        return handle_task_event(agent_id, message)
    
    # Check for a2a-agent-chat
    if message.get("msgType") == "a2a-agent-chat":
        return handle_a2a_chat(
            agent_id=agent_id,
            job_id=message.get("jobId", ""),
            sender_role=message.get("sender", {}).get("role", 0),
            content=message.get("content", "")
        )
    
    return {"ok": True, "action": "unhandled_event"}
