"""
WatchTower — Prediction Market Research Agent

Main entry point for the agent:
- Re-exports build_agent() for use by other modules
- Provides run_watchtower() for task processing
- CLI interface for local testing
"""

import json
import logging
import sys
import uuid

from experts_opinion_agent import build_agent  # noqa: F401 — re-exported

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("watchtower")


def run_watchtower(question: str) -> str:
    """
    Run WatchTower's expert opinion agent on a prediction market question.
    Returns the analysis as a JSON string.
    """
    try:
        agent = build_agent()
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = agent.invoke(
            {"topic": question, "max_analysts": 3},
            config=config,
        )
        output = result.get("final_output", "")
        if output:
            return output
        return json.dumps({
            "question": question,
            "decision": result.get("final_decision", "MAYBE"),
            "confidence": result.get("confidence", 0),
            "reasoning": result.get("reasoning", ""),
            "sources": result.get("sources", []),
        })
    except Exception as e:
        logger.error(f"WatchTower agent error: {e}")
        return json.dumps({"error": str(e)})


def main():
    if len(sys.argv) < 2:
        logger.info("Usage: uv run python main.py '<prediction market question>'")
        logger.info("Example: python main.py 'Will Bitcoin reach 150k by end of 2026?'")
        sys.exit(1)

    question = sys.argv[1]
    logger.info(f"🦉 WatchTower analyzing: {question}")

    result = run_watchtower(question)
    print(result)

    return result


if __name__ == "__main__":
    main()
