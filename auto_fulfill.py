#!/usr/bin/env python3
"""
Auto-fulfillment script for WatchTower ASP.
Checks for pending A2A tasks, runs the agent, and sends responses back.
"""
import json
import subprocess
import sys
import os
import time

def run_cmd(cmd, timeout=300):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -1
    except Exception as e:
        return "", str(e), -1

def check_pending_tasks():
    """Check for pending A2A task requests."""
    stdout, stderr, code = run_cmd("okx-a2a task requests --json", timeout=30)
    if code != 0:
        print(f"Error checking tasks: {stderr}")
        return []

    try:
        data = json.loads(stdout)
        return data.get("payload", [])
    except json.JSONDecodeError:
        print(f"Failed to parse task response: {stdout}")
        return []

def extract_question(content):
    """Extract the prediction market question from task content."""
    try:
        # Try to parse as JSON first
        data = json.loads(content)
        if "content" in data:
            inner = json.loads(data["content"])
            return inner.get("question", "")
        return data.get("question", "")
    except (json.JSONDecodeError, KeyError):
        # Fall back to raw content
        return content

def send_response(job_id, to_agent_id, response_json):
    """Send response back via XMTP."""
    cmd = (
        f'okx-a2a xmtp-send --job-id {job_id} --to-agent-id {to_agent_id} '
        f'--message \'{json.dumps({"msgType": "a2a-agent-chat", "content": response_json})}\''
    )
    stdout, stderr, code = run_cmd(cmd, timeout=30)
    if code == 0:
        print(f"Response sent successfully for job {job_id}")
        return True
    else:
        print(f"Failed to send response: {stderr}")
        return False

def process_task(task):
    """Process a single task."""
    # Extract task details
    content = task.get("content", "")
    job_id = task.get("jobId", "")
    to_agent_id = task.get("fromAgentId", "")

    # Extract the question
    question = extract_question(content)
    if not question:
        print(f"Could not extract question from task {job_id}")
        return False

    print(f"Processing task {job_id}: {question[:100]}...")

    # Run the agent
    stdout, stderr, code = run_cmd(
        f'uv run python main.py "{question}"',
        timeout=300  # 5 minute timeout
    )

    if code != 0:
        print(f"Agent failed for task {job_id}: {stderr}")
        # Send error response
        error_response = json.dumps({
            "question": question,
            "error": f"Agent processing failed: {stderr[:200]}"
        })
        send_response(job_id, to_agent_id, error_response)
        return False

    # Send the response
    response = stdout.strip()
    if send_response(job_id, to_agent_id, response):
        print(f"Task {job_id} completed and response sent")
        return True
    return False

def main():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Checking for pending tasks...")

    tasks = check_pending_tasks()
    if not tasks:
        print("No pending tasks")
        return

    print(f"Found {len(tasks)} pending task(s)")

    for task in tasks:
        try:
            process_task(task)
        except Exception as e:
            print(f"Error processing task: {e}")
            continue

if __name__ == "__main__":
    main()
