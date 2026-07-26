"""
Tests for markets_api.py — Polymarket Gamma API wrapper.

Run: python3 tests/test_markets_api.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets_api import (
    _parse_outcomes,
    _format_single_market,
    format_market_context,
    search_markets,
    fetch_market_odds,
    close,
)

# ── Mock Data ────────────────────────────────────────────────────────────────

MOCK_MARKET = {
    "question": "Will Bitcoin reach $100,000 in July?",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.65", "0.35"]',
    "volume": "2450000",
    "volume24hr": 185000,
    "liquidity": "340000",
    "endDate": "2025-07-31T23:59:59Z",
    "active": True,
    "closed": False,
    "bestBid": 0.64,
    "bestAsk": 0.66,
    "lastTradePrice": 0.65,
    "oneDayPriceChange": 0.02,
    "oneWeekPriceChange": -0.05,
    "slug": "will-bitcoin-reach-100000-in-july",
    "description": "This market resolves to Yes if Bitcoin reaches $100,000 at any point in July 2025.",
}

MOCK_MARKET_MINIMAL = {
    "question": "Will the Fed cut rates?",
    "outcomes": "[]",
    "outcomePrices": "[]",
}

MOCK_MARKET_CLOSED = {
    "question": "Will ETH hit $5k?",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["1.0", "0.0"]',
    "active": False,
    "closed": True,
}

MOCK_EVENT = {
    "title": "What price will Bitcoin hit in July?",
    "markets": [MOCK_MARKET],
}

MOCK_EVENT_WITH_CLOSED = {
    "title": "ETH price markets",
    "markets": [MOCK_MARKET, MOCK_MARKET_CLOSED],
}

MOCK_EVENT_NO_MARKETS = {
    "title": "Empty event",
    "markets": [],
}

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


# ── Unit Tests: _parse_outcomes ──────────────────────────────────────────────

def test_parse_outcomes_valid():
    result = _parse_outcomes(MOCK_MARKET)
    check("valid outcomes", result["outcomes"] == ["Yes", "No"])
    check("valid prices", result["prices"] == [0.65, 0.35])
    check("valid price_map", result["price_map"] == {"Yes": 0.65, "No": 0.35})


def test_parse_outcomes_empty():
    result = _parse_outcomes(MOCK_MARKET_MINIMAL)
    check("empty outcomes", result["outcomes"] == [])
    check("empty prices", result["prices"] == [])
    check("empty price_map", result["price_map"] == {})


def test_parse_outcomes_invalid_json():
    bad = {"outcomes": "not json", "outcomePrices": "also not json"}
    result = _parse_outcomes(bad)
    check("invalid json outcomes", result["outcomes"] == [])
    check("invalid json prices", result["prices"] == [])


def test_parse_outcomes_missing_fields():
    result = _parse_outcomes({})
    check("missing all fields", result["outcomes"] == [])
    check("missing all prices", result["prices"] == [])


# ── Unit Tests: _format_single_market ────────────────────────────────────────

def test_format_single_market():
    output = _format_single_market(MOCK_MARKET)
    check("contains question", "Bitcoin reach $100,000" in output)
    check("contains odds", "Yes: 65.0%" in output)
    check("contains bid/ask", "0.640 / 0.660" in output)
    check("contains volume", "$2,450,000" in output)
    check("contains 24h volume", "$185,000" in output)
    check("contains liquidity", "$340,000" in output)
    check("contains resolution date", "2025-07-31" in output)
    check("contains link", "polymarket.com/event/will-bitcoin-reach" in output)
    check("contains 24h change", "+0.020" in output)
    check("contains 7d change", "-0.050" in output)


def test_format_single_market_minimal():
    output = _format_single_market(MOCK_MARKET_MINIMAL)
    check("minimal has question", "Will the Fed cut rates?" in output)
    check("minimal no odds line", "Current Odds" not in output)
    check("minimal no bid/ask", "Bid/Ask" not in output)


# ── Unit Tests: format_market_context ────────────────────────────────────────

def test_format_market_context_empty():
    output = format_market_context([])
    check("empty returns message", "No matching prediction markets" in output)


def test_format_market_context_filters_closed():
    output = format_market_context([MOCK_EVENT_WITH_CLOSED], max_markets=5)
    check("filters closed market", "ETH hit $5k" not in output)
    check("keeps active market", "Bitcoin reach $100,000" in output)


def test_format_market_context_respects_max():
    event = {
        "title": "Multi",
        "markets": [
            {**MOCK_MARKET, "question": f"Market {i}"}
            for i in range(10)
        ],
    }
    # All markets are active copies of MOCK_MARKET
    for m in event["markets"]:
        m["active"] = True
        m["closed"] = False

    output = format_market_context([event], max_markets=3)
    check("respects max_markets", output.count("Market ") == 3)


def test_format_market_context_no_active():
    event = {"title": "Dead event", "markets": [MOCK_MARKET_CLOSED]}
    output = format_market_context([event])
    check("no active returns message", "No active matching" in output)


def test_format_market_context_valid():
    output = format_market_context([MOCK_EVENT], max_markets=5)
    check("has header", "Polymarket Data" in output)
    check("has event title", "What price will Bitcoin" in output)
    check("has market question", "Bitcoin reach $100,000" in output)


# ── Integration Tests (live API) ─────────────────────────────────────────────

async def test_search_markets():
    events = await search_markets("bitcoin", limit=3)
    check("search returns list", isinstance(events, list))
    check("search returns results", len(events) > 0)
    if events:
        first = events[0]
        check("event has title", "title" in first)
        check("event has markets", "markets" in first)
        print(f"         → {len(events)} events, first: '{first.get('title', '?')}'")


async def test_search_markets_gibberish():
    events = await search_markets("xyzzyplugh9876543", limit=3)
    check("gibberish returns empty list", isinstance(events, list))
    check("gibberish returns no results", len(events) == 0)


async def test_fetch_market_odds():
    output = await fetch_market_odds("bitcoin", max_markets=3)
    check("fetch_market_odds returns string", isinstance(output, str))
    check("fetch_market_odds non-empty", len(output) > 50)
    print(f"         → {len(output)} chars returned")
    # Print a snippet for visual inspection
    lines = output.split("\n")[:8]
    print("         → Preview:")
    for line in lines:
        print(f"            {line}")


async def run_integration():
    print("\n── Integration Tests (live Polymarket API) ──")
    await test_search_markets()
    await test_search_markets_gibberish()
    await test_fetch_market_odds()
    await close()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    global passed, failed

    print("── Unit Tests: _parse_outcomes ──")
    test_parse_outcomes_valid()
    test_parse_outcomes_empty()
    test_parse_outcomes_invalid_json()
    test_parse_outcomes_missing_fields()

    print("\n── Unit Tests: _format_single_market ──")
    test_format_single_market()
    test_format_single_market_minimal()

    print("\n── Unit Tests: format_market_context ──")
    test_format_market_context_empty()
    test_format_market_context_filters_closed()
    test_format_market_context_respects_max()
    test_format_market_context_no_active()
    test_format_market_context_valid()

    asyncio.run(run_integration())

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
