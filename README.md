# WatchTower — Prediction Market Research Agent

**Agent ID:** #9643 | **Role:** ASP (Service Provider) | **Chain:** X Layer | **Status:** Under Review

---

## Overview

WatchTower is a deep research AI agent built for the OKX AI marketplace. It evaluates prediction market questions by spawning parallel expert analyst personas, each conducting web-search-backed investigations to gather evidence from multiple angles. The agent then synthesizes their opinions into a structured YES/NO/MAYBE decision with confidence percentage and cited sources.

Built on LangGraph's multi-agent architecture, WatchTower combines LLM reasoning with real-time web search to deliver data-driven predictions on crypto, politics, sports, and more.

## How It Works

WatchTower uses a 3-phase multi-agent workflow:

1. **Analyst Creation** — The agent spawns 3 specialized analyst personas, each with a unique perspective:
   - Domain expertise (crypto markets, political analysis, etc.)
   - Contrarian viewpoint (risk assessment, counter-arguments)
   - Quantitative/statistical analysis (data-driven patterns)

2. **Parallel Interviews** — Each analyst independently investigates the question using Tavily web search, gathering evidence for and against the predicted event. They produce detailed memos citing specific sources.

3. **Evidence Synthesis** — All analyst memos are compiled and synthesized into a final structured decision with:
   - **Decision:** YES / NO / MAYBE
   - **Confidence:** 0–100%
   - **Reasoning:** Detailed explanation of the consensus view
   - **Sources:** Cited URLs for verification

## Service

| Field | Value |
|-------|-------|
| **Service Name** | Prediction Analysis Agent |
| **Type** | Agent-to-Agent (A2A) |
| **Price** | 0.5 USDT per call |
| **Deliverable** | Structured JSON with decision, confidence, reasoning, and sources |

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Agent Framework** | LangGraph (StateGraph) |
| **LLM Providers** | Qwen (DashScope), Groq (Llama 3.3), Google Gemini |
| **Web Search** | Tavily Search API |
| **Web Framework** | FastAPI + Uvicorn |
| **Marketplace** | OKX A2A Protocol |
| **Deployment** | Render (Web Service) |
| **Package Manager** | uv |

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### 1. Clone the repository

```bash
git clone <repo-url>
cd watchtower
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Configure environment

Copy the example env file and fill in your API keys:

```bash
cp .env.examples .env
```

See [Configuration](#configuration) for all available variables.

### 4. Run locally

```bash
uv run python main.py 'Will Bitcoin reach 150k by end of 2026?'
```

## Configuration

Create a `.env` file in the project root with the following variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DASHSCOPE_API_KEY` | Yes | Alibaba DashScope API key for Qwen models |
| `DASHSCOPE_BASE_URL` | Yes | DashScope API base URL |
| `GROQ_API_KEY` | Yes | Groq API key for Llama models |
| `TAVILY_API_KEY` | Yes | Tavily Search API key for web search |
| `GOOGLE_API_KEY` | No | Google Gemini API key (fallback LLM) |
| `OPENAI_API_KEY` | No | OpenAI API key (for okx-a2a daemon) |

Example `.env`:

```env
DASHSCOPE_API_KEY=sk-your-key-here
DASHSCOPE_BASE_URL=https://ws-c8feaezgm1qadjxf.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
GROQ_API_KEY=gsk-your-key-here
TAVILY_API_KEY=tvly-your-key-here
```

## API Endpoints

WatchTower exposes a FastAPI server with the following endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check (UptimeRobot) |
| `GET` | `/health` | Service health status |
| `POST` | `/okx-webhook` | Webhook for OKX A2A daemon events |
| `POST` | `/run-task` | Manually trigger analysis |

### POST `/run-task`

Manually trigger a prediction market analysis.

**Request:**

```json
{
  "question": "Will Bitcoin reach 150k by end of 2026?"
}
```

**Response:**

```json
{
  "ok": true,
  "analysis": "{\"question\":\"Will Bitcoin reach 150k by end of 2026?\",\"decision\":\"YES\",\"confidence\":65.0,\"reasoning\":\"...\",\"sources\":[\"https://...\"]}"
}
```

### POST `/okx-webhook`

Receives task notifications from the OKX A2A daemon. Handles:

- `JobAspSelected` — Auto-applies with service fee
- `JobAccepted` — Runs analysis and delivers result
- `user_message` — Responds to user messages via XMTP

## Deployment

WatchTower is deployed on Render as a Web Service.

### Render Environment Variables

Set these in the Render dashboard:

| Variable | Value |
|----------|-------|
| `PYTHON_VERSION` | `3.12` |
| `DASHSCOPE_API_KEY` | Your DashScope key |
| `DASHSCOPE_BASE_URL` | DashScope API URL |
| `GROQ_API_KEY` | Your Groq key |
| `TAVILY_API_KEY` | Your Tavily key |
| `GOOGLE_API_KEY` | Your Gemini key (optional) |
| `OPENAI_API_KEY` | Your OpenAI key (for okx-a2a) |

### Build Process

The `render.yaml` and `start.sh` handle:

1. Install Node.js 22 and npm packages (`@okxweb3/a2a-node`)
2. Install `onchainos` CLI for OKX marketplace integration
3. Sync Python dependencies via `uv sync --frozen`
4. Start FastAPI server on port 10000

### Live URL

**https://watchtower-tlkf.onrender.com**

## Architecture

### File Structure

```
watchtower/
├── main.py                      # Entry point, CLI, run_watchtower()
├── experts_opinion_agent.py     # Core agent logic (LangGraph StateGraph)
├── okx_handler.py               # OKX marketplace event handling
├── web.py                       # FastAPI server
├── config.py                    # Configuration management
├── start.sh                     # Render startup script
├── render.yaml                  # Render deployment config
├── pyproject.toml               # Python dependencies
├── .env                         # Environment variables (gitignored)
├── .env.examples                # Example env file
├── notebook/                    # Jupyter notebooks for experimentation
│   ├── experts_opinion_agent.ipynb
│   └── llm.ipynb
├── tests/
│   └── test_markets_api.py      # API tests
└── assets/
    └── watchtower.png           # Agent logo
```

### Workflow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      Request Input                          │
│               (CLI, Webhook, or API call)                   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Agent Builder                            │
│              build_agent() → StateGraph                     │
│         Generates 3 analyst personas dynamically            │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Parallel Analyst Investigations                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ Analyst 1│  │ Analyst 2│  │ Analyst 3│                  │
│  │ (Domain) │  │(Contrarian)│ │(Quant)   │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │              │              │                        │
│       ▼              ▼              ▼                        │
│    Web Search    Web Search    Web Search                    │
│    (Tavily)      (Tavily)      (Tavily)                     │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                 Evidence Synthesis                          │
│         Compile memos → Final decision                      │
│     YES/NO/MAYBE + Confidence + Reasoning + Sources         │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Output JSON                              │
│           Structured response with citations                │
└─────────────────────────────────────────────────────────────┘
```

## Example Output

```json
{
  "question": "Will Bitcoin reach 150k by end of 2026?",
  "decision": "YES",
  "confidence": 65.0,
  "reasoning": "The consensus evidence points toward Bitcoin reaching $150k by the end of 2026, driven primarily by strong price momentum and structural market maturation. Bitcoin had already surged to the $105,000–$110,700 range by September 2025, establishing a high baseline from which to reach the $150k target...",
  "sources": [
    "https://aminagroup.com/research/post-halving-bitcoin-miners-landscape/",
    "https://www.binance.com/en/square/post/29359547183273",
    "https://cryptonews.net/news/bitcoin/33090903/",
    "https://bankingjournal.aba.com/2026/03/sec-cftc-announce-agreement-to-coordinate-regulation-enforcement/",
    "https://cryptoslate.com/bitcoin-options-oi-flips-futures-the-new-volatility-regime/"
  ]
}
```

## Development

### Running Tests

```bash
uv run pytest tests/
```

### Adding Features

The agent logic lives in `experts_opinion_agent.py`. Key extension points:

- **Add analyst personas:** Modify the `analyst_prompt` or `create_analysts` function
- **Add LLM providers:** Extend `_llm()` with new provider configurations
- **Add search sources:** Extend the `TavilySearch` configuration
- **Add event handlers:** Add new handlers in `okx_handler.py` and register in `EVENT_HANDLERS`

### Local Development

```bash
# Run the agent directly
uv run python main.py 'Your question here'

# Start the API server
uv run uvicorn web:app --host 0.0.0.0 --port 8000 --reload

# Test the API
curl -X POST http://localhost:8000/run-task \
  -H "Content-Type: application/json" \
  -d '{"question": "Will ETH hit 10k by 2027?"}'
```

## License

Private — OKX AI Agent Marketplace
