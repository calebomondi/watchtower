#!/usr/bin/env python3
"""
Auto-fulfillment script for WatchTower ASP.
Checks for pending A2A tasks, runs the agent, and sends responses back.

Two sources of tasks:
1. `okx-a2a task requests --json` — XMTP-level pending task requests (primary)
2. `onchainos agent active-tasks` — on-chain tasks where this ASP is designated (fallback)
"""
import json
import subprocess
import sys
import os
import time
import tempfile

AGENT_ID = "9643"


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


def run_cmd_args(args, timeout=300):
    """Run a command with a list of args (no shell quoting issues)."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -1
    except Exception as e:
        return "", str(e), -1


def check_pending_tasks():
    """Check for pending A2A task requests via okx-a2a (primary source)."""
    stdout, stderr, code = run_cmd("okx-a2a task requests --json", timeout=30)
    if code != 0:
        print(f"Warning: okx-a2a task requests failed: {stderr}")
        return []
    try:
        data = json.loads(stdout)
        tasks = data.get("payload", [])
        if tasks:
            print(f"Found {len(tasks)} pending XMTP task(s)")
        return tasks
    except json.JSONDecodeError:
        print(f"Failed to parse XMTP task response: {stdout}")
        return []


def check_active_tasks():
    """Check onchainos active-tasks for tasks where this ASP is designated (fallback)."""
    stdout, stderr, code = run_cmd("onchainos agent active-tasks", timeout=30)
    if code != 0:
        print(f"Warning: onchainos agent active-tasks failed: {stderr}")
        return []
    try:
        data = json.loads(stdout)
        tasks = data.get("data", {}).get("tasks", [])
        my_tasks = [t for t in tasks if t.get("myAgentId") == AGENT_ID and t.get("myRole") == "asp"]
        if my_tasks:
            print(f"Found {len(my_tasks)} active on-chain task(s) for ASP {AGENT_ID}")
        return my_tasks
    except json.JSONDecodeError:
        print(f"Failed to parse active-tasks response: {stdout}")
        return []


def check_task_in_progress():
    """Get detailed task info from onchainos task-in-progress."""
    stdout, stderr, code = run_cmd(
        f"onchainos agent task-in-progress --agent-ids {AGENT_ID}", timeout=30
    )
    if code != 0:
        print(f"Warning: task-in-progress failed: {stderr}")
        return {}
    try:
        data = json.loads(stdout)
        provider_tasks = data.get("data", {}).get("providerTasks", [])
        task_map = {}
        for t in provider_tasks:
            task_map[t.get("jobId", "")] = t
        return task_map
    except json.JSONDecodeError:
        print(f"Failed to parse task-in-progress response: {stdout}")
        return {}


def extract_question_from_task(task):
    """Extract the question/description from a task. Handles multiple formats."""
    # Handle XMTP task format — content may be nested in "messages" array
    content = task.get("content", "")
    if not content and "messages" in task:
        messages = task.get("messages", [])
        if messages:
            content = messages[0].get("content", "")
    if content:
        # Try JSON parsing for XMTP tasks
        try:
            data = json.loads(content)
            if "content" in data:
                inner_content = data["content"]
                # Try parsing as JSON; if fails, use as plain text
                try:
                    inner = json.loads(inner_content)
                    return inner.get("question", inner.get("description", inner_content))
                except (json.JSONDecodeError, ValueError):
                    return inner_content
            return data.get("question", data.get("description", ""))
        except (json.JSONDecodeError, KeyError):
            return content

    # For onchainos active-tasks, the question is in the task-in-progress description
    description = task.get("description", "")
    if description:
        return description

    title = task.get("title", "")
    if title:
        return title

    return ""


def send_response(job_id, to_agent_id, response_json):
    """Send response back via XMTP using a temp file to avoid shell quoting issues."""
    msg_obj = {"msgType": "a2a-agent-chat", "content": response_json}
    msg_str = json.dumps(msg_obj)
    # Write message to temp file and use $(cat) to avoid shell quoting issues
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, dir="/tmp") as f:
        f.write(msg_str)
        msg_file = f.name
    try:
        cmd = f'okx-a2a xmtp-send --job-id {job_id} --message "$(cat {msg_file})"'
        stdout, stderr, code = run_cmd(cmd, timeout=30)
        if code == 0:
            print(f"Response sent successfully via XMTP for job {job_id}")
            return True
        else:
            print(f"Failed to send XMTP response: {stderr}")
            return False
    finally:
        os.unlink(msg_file)


def deliver_result(job_id, response_json, agent_id):
    """Deliver the result on-chain via onchainos agent deliver.

    Uses --a2a-stdin for the deliverable text to avoid shell quoting issues.
    """
    deliverable = json.dumps(response_json, ensure_ascii=False)
    # Write deliverable to temp file, read via $(cat) to avoid quoting issues
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, dir="/tmp") as f:
        f.write(deliverable)
        deliverable_file = f.name
    try:
        cmd = (
            f"onchainos agent deliver {job_id} "
            f"--agent-id {agent_id} "
            f"--deliverable-text \"$(cat {deliverable_file})\" "
            f"--message \"Analysis complete. See deliverable for full report.\""
        )
        stdout, stderr, code = run_cmd(cmd, timeout=30)
        if code == 0:
            print(f"Deliverable submitted successfully for job {job_id}")
            print(f"Output: {stdout.strip()}")
            return True
        else:
            print(f"Delivery failed: {stderr.strip() or stdout.strip()}")
            return False
    finally:
        os.unlink(deliverable_file)


def try_accept_task(job_id, token_amount, token_symbol, agent_id):
    """Attempt to accept (apply for) a task that's in 'created' status."""
    cmd = (
        f"onchainos agent apply {job_id} "
        f"--token-amount {token_amount} "
        f"--token-symbol {token_symbol} "
        f"--agent-id {agent_id}"
    )
    stdout, stderr, code = run_cmd(cmd, timeout=30)
    if code == 0:
        print(f"Task accepted (applied) for job {job_id}")
        print(f"Output: {stdout.strip()}")
        return True
    else:
        print(f"Apply failed for job {job_id}: {stderr.strip() or stdout.strip()}")
        return False


def notify_user(job_id, provider_agent_id, token_amount, token_symbol):
    """Send a user notification about the apply submission."""
    content = (
        f"[Apply Submitted] Job {job_id} — your apply has been recorded on-chain.\n"
        f"  - ASP agentId: {provider_agent_id}\n"
        f"  Awaiting the User Agent's confirm-accept to fund escrow."
    )
    cmd = f'onchainos agent user-notify --content "{content}"'
    stdout, stderr, code = run_cmd(cmd, timeout=15)
    if code == 0:
        print(f"User notification sent for job {job_id}")
        return True
    else:
        print(f"Failed to send user notification: {stderr}")
        return False


def process_task(task, task_detail_map=None):
    """Process a single task. Handles both XMTP and onchainos task formats."""
    # Extract task details
    td_map = task_detail_map or {}

    if "content" in task or "messages" in task:  # XMTP task format
        content = task.get("content", "")
        if not content and "messages" in task:
            # Extract content from nested messages array (actual XMTP format)
            messages = task.get("messages", [])
            if messages:
                content = messages[0].get("content", "")
        job_id = task.get("jobId", "")
        to_agent_id = task.get("fromAgentId", "") or task.get("toAgentId", "")
        # XMTP tasks default to accepted; but if we have a task-in-progress
        # detail with a statusCode, use that (for tasks also in onchainos)
        status_code = 1  # XMTP tasks are already accepted
    else:  # onchainos active-tasks format
        job_id = task.get("jobId", "")
        detail = td_map.get(job_id, {})
        content = detail.get("description", task.get("title", ""))
        to_agent_id = task.get("counterpartyAgentId", "")
        status_code = task.get("statusCode", -1)

    # Extract the question
    if "content" in task or "messages" in task:
        question = extract_question_from_task(task)
    else:
        question = content

    if not question and job_id in td_map:
        question = td_map[job_id].get("description", "")

    if not question:
        print(f"Could not extract question from task {job_id}")
        return False

    print(f"Processing task {job_id}: {question[:100]}...")

    # Handle task status
    if status_code == 0:  # "created" — awaiting acceptance
        print(f"Task {job_id} is in 'created' status (awaiting acceptance)")
        token_amount = task.get("tokenAmount", "1")
        token_symbol = task.get("tokenSymbol", "USDT")

        # Check if we already applied and cached a result — skip duplicate apply
        cache_file = f"/tmp/watchtower_result_{job_id[:16]}.json"
        if os.path.exists(cache_file):
            print(f"Task {job_id} already applied and analyzed — result cached. Skipping apply & re-analysis.")
            print("Next cron run will deliver once task reaches 'accepted' status.")
            return True

        # Try to accept the task (apply)
        try_accept_task(job_id, token_amount, token_symbol, AGENT_ID)

        # Send user notification
        notify_user(job_id, AGENT_ID, token_amount, token_symbol)

        # Run analysis regardless — will save result for when task is accepted
        print("Running analysis while awaiting acceptance...")
    elif status_code == 1:  # "accepted" — ready for processing
        print(f"Task {job_id} is in 'accepted' status — processing deliverable")

    # Run the agent (analysis)
    stdout, stderr, code = run_cmd(
        f'uv run python main.py "{question}"',
        timeout=300,
    )

    if code != 0:
        print(f"Agent failed for task {job_id}: {stderr}")
        error_response = json.dumps({
            "question": question,
            "error": f"Agent processing failed: {stderr[:200]}"
        })
        send_response(job_id, to_agent_id, error_response)
        return False

    # Parse the agent output
    response = stdout.strip()
    try:
        response_json = json.loads(response)
    except json.JSONDecodeError:
        response_json = {"result": response}

    # Save result to cache for potential later delivery
    cache_file = f"/tmp/watchtower_result_{job_id[:16]}.json"
    with open(cache_file, "w") as f:
        json.dump({"jobId": job_id, "result": response_json, "timestamp": time.time()}, f)

    # Send response via XMTP and deliver on-chain
    if status_code >= 1:
        # Task is accepted — send response and deliver
        send_response(job_id, to_agent_id, json.dumps(response_json))
        deliver_result(job_id, response_json, AGENT_ID)
    else:
        # Task is in 'created' status — cache result, skip XMTP/deliver
        print(f"Task {job_id} still in 'created' status — skipping XMTP send and on-chain delivery.")
        print(f"Result cached at {cache_file}")
        print("Next cron run will send/deliver once task reaches 'accepted' status.")

    print(f"Task {job_id} processing complete")
    return True


def main():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Checking for pending tasks...")

    # Source 1: Check XMTP pending task requests (primary)
    xmtp_tasks = check_pending_tasks()

    # Source 2: Check onchainos active-tasks as fallback
    active_tasks = check_active_tasks()
    task_detail_map = {}
    if active_tasks:
        task_detail_map = check_task_in_progress()

    # Merge tasks — for overlapping jobIds, prefer onchainos version (has correct statusCode)
    # XMTP task objects have "messages" array but no "statusCode"; onchainos active-tasks
    # carry the authoritative statusCode. When the same jobId appears in both, the
    # onchainos version replaces the XMTP version so status_code is set correctly.
    onchain_job_ids = {at.get("jobId", "") for at in active_tasks}
    all_tasks = []
    # Add onchainos tasks first (they have the correct statusCode)
    for at in active_tasks:
        all_tasks.append(at)
    # Add XMTP-only tasks (not present in onchainos active-tasks)
    for t in xmtp_tasks:
        job_id = t.get("jobId", "")
        if job_id not in onchain_job_ids:
            all_tasks.append(t)

    if not all_tasks:
        print("No pending tasks")
        return

    print(f"Found {len(all_tasks)} pending task(s) total")

    for task in all_tasks:
        try:
            process_task(task, task_detail_map)
        except Exception as e:
            print(f"Error processing task: {e}")
            continue


if __name__ == "__main__":
    main()
