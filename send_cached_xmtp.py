#!/usr/bin/env python3
"""Send a cached XMTP response for a task that was already submitted on-chain.

Reads the cached result from /tmp/watchtower_result_<prefix>.json,
constructs the a2a-agent-chat message envelope, and sends it via
okx-a2a xmtp-send with the correct --job-id and --to-agent-id flags.
"""
import json
import os
import subprocess
import sys
import tempfile


def send_cached_xmtp(job_id: str, to_agent_id: str):
    cache_file = f"/tmp/watchtower_result_{job_id[:16]}.json"
    if not os.path.exists(cache_file):
        print(f"Cache file not found: {cache_file}")
        return False

    with open(cache_file) as f:
        cached = json.load(f)

    response_json = cached["result"]
    # The result JSON is serialized as the "content" field (matches send_response in auto_fulfill.py)
    content_str = json.dumps(response_json, ensure_ascii=False)
    msg_obj = {"msgType": "a2a-agent-chat", "content": content_str}
    msg_str = json.dumps(msg_obj, ensure_ascii=False)

    # Write to temp file and use $(cat) to avoid shell quoting
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, dir="/tmp") as f:
        f.write(msg_str)
        msg_file = f.name

    try:
        cmd = (
            f'okx-a2a xmtp-send --job-id {job_id} --to-agent-id {to_agent_id} '
            f'--message "$(cat {msg_file})"'
        )
        print(f"Sending XMTP response for job {job_id} to agent {to_agent_id}...")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        print(f"Exit code: {result.returncode}")
        if result.stdout:
            print(f"stdout: {result.stdout.strip()}")
        if result.stderr:
            print(f"stderr: {result.stderr.strip()}")

        combined = (result.stdout + result.stderr).strip()
        if result.returncode == 0 and "ok=true" in combined:
            print(f"✅ XMTP response sent successfully for job {job_id}")
            return True
        else:
            print(f"❌ XMTP send failed for job {job_id}: {combined[:200]}")
            return False
    finally:
        os.unlink(msg_file)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: uv run python send_cached_xmtp.py <job_id> <to_agent_id>")
        sys.exit(1)
    job_id = sys.argv[1]
    to_agent_id = sys.argv[2]
    send_cached_xmtp(job_id, to_agent_id)
