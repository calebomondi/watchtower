"""
WatchTower — Prediction Market Research Agent

Local entry point for testing the agent directly.
For Render deployment, web.py is the entry point (loaded by uvicorn).
"""

import logging
import sys

from experts_opinion_agent import build_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("watchtower")


def main():
    if len(sys.argv) < 2:
        logger.info("Usage: python main.py '<prediction market question>'")
        logger.info("Example: python main.py 'Will Bitcoin reach 150k by end of 2026?'")
        sys.exit(1)

    question = sys.argv[1]
    logger.info(f"🦉 WatchTower analyzing: {question}")

    agent = build_agent()
    result = agent.invoke({
        "messages": [{"role": "user", "content": question}]
    })

    # Print the final answer
    for msg in result.get("messages", []):
        if hasattr(msg, "content") and msg.content:
            print(msg.content)


if __name__ == "__main__":
    main()
