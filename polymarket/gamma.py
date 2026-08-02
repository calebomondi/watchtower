import logging
from typing import Optional
import httpx
from .models import MarketEvent, Market

logger = logging.getLogger("polymarket.gamma")

BASE_URL = "https://gamma-api.polymarket.com"


class GammaClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=15.0)

    async def close(self):
        await self.client.aclose()

    async def list_events(
        self,
        closed: bool = False,
        limit: int = 50,
        tag: Optional[str] = None,
        cursor: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[MarketEvent], Optional[str]]:
        params: dict = {
            "closed": str(closed).lower(),
            "limit": str(min(limit, 50)),
        }
        if tag:
            params["tag"] = tag
        if cursor:
            params["cursor"] = cursor
        if search:
            params["search"] = search

        resp = await self.client.get(f"{self.base_url}/events", params=params)
        resp.raise_for_status()
        data = resp.json()

        next_cursor = None
        if isinstance(data, dict):
            next_cursor = data.get("next_cursor")
            events_data = data.get("data", [])
        else:
            events_data = data

        events = []
        for raw in events_data:
            try:
                events.append(self._parse_event(raw))
            except Exception as e:
                logger.warning("Skipping event %s: %s", raw.get("id"), e)

        return events, next_cursor

    async def get_event(self, event_id: str) -> Optional[MarketEvent]:
        resp = await self.client.get(f"{self.base_url}/events/{event_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        raw = resp.json()
        return self._parse_event(raw)

    async def list_markets(
        self,
        closed: bool = False,
        limit: int = 50,
        tag: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> tuple[list[Market], Optional[str]]:
        params: dict = {
            "closed": str(closed).lower(),
            "limit": str(min(limit, 50)),
        }
        if tag:
            params["tag"] = tag
        if cursor:
            params["cursor"] = cursor

        resp = await self.client.get(f"{self.base_url}/markets", params=params)
        resp.raise_for_status()
        data = resp.json()

        next_cursor = None
        if isinstance(data, dict):
            next_cursor = data.get("next_cursor")
            markets_data = data.get("data", [])
        else:
            markets_data = data

        markets = []
        for raw in markets_data:
            try:
                markets.append(self._parse_market(raw))
            except Exception as e:
                logger.warning("Skipping market %s: %s", raw.get("id"), e)

        return markets, next_cursor

    async def get_market(self, market_id: str) -> Optional[Market]:
        resp = await self.client.get(f"{self.base_url}/markets/{market_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        raw = resp.json()
        return self._parse_market(raw)

    def _parse_event(self, raw: dict) -> MarketEvent:
        event_title = raw.get("title", "")
        event_id = str(raw.get("id", ""))
        markets = []
        for m in raw.get("markets", []):
            try:
                market = self._parse_market(m)
                market.event_title = event_title
                market.event_id = event_id
                markets.append(market)
            except Exception as e:
                logger.warning("Skipping market %s: %s", m.get("id"), e)

        return MarketEvent(
            id=event_id,
            slug=raw.get("slug", ""),
            title=event_title,
            description=raw.get("description", ""),
            image=raw.get("image", ""),
            closed=bool(raw.get("closed", False)),
            active=bool(raw.get("active", False)),
            volume=float(raw.get("volume", 0) or 0),
            volume_24hr=float(raw.get("volume24hr", 0) or 0),
            liquidity=float(raw.get("liquidity", 0) or 0),
            open_interest=float(raw.get("openInterest", 0) or 0),
            tags=raw.get("tags", []),
            markets=markets,
        )

    def _parse_market(self, raw: dict) -> Market:
        import json as _json

        outcomes_raw = raw.get("outcomes", "[]")
        if isinstance(outcomes_raw, str):
            outcomes = _json.loads(outcomes_raw)
        else:
            outcomes = list(outcomes_raw)

        prices_raw = raw.get("outcomePrices", "[]")
        if isinstance(prices_raw, str):
            outcome_prices = _json.loads(prices_raw)
        else:
            outcome_prices = list(prices_raw) if prices_raw else []

        clob_raw = raw.get("clobTokenIds", "[]")
        if isinstance(clob_raw, str):
            clob_token_ids = _json.loads(clob_raw)
        else:
            clob_token_ids = list(clob_raw) if clob_raw else []

        events_raw = raw.get("events", [])
        event_id = None
        event_title = None
        if events_raw and isinstance(events_raw, list) and len(events_raw) > 0:
            event_id = str(events_raw[0].get("id", ""))
            event_title = events_raw[0].get("title", "")

        return Market(
            id=str(raw.get("id", "")),
            question=raw.get("question", ""),
            condition_id=raw.get("conditionId", ""),
            slug=raw.get("slug", ""),
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            volume=float(raw.get("volumeNum", raw.get("volume", 0) or 0)),
            volume_24hr=float(raw.get("volume24hr", raw.get("volume24hrClob", 0) or 0)),
            liquidity=float(raw.get("liquidityNum", raw.get("liquidity", 0) or 0)),
            spread=float(raw.get("spread", 0) or 0),
            last_trade_price=float(raw.get("lastTradePrice", 0) or 0),
            best_ask=float(raw.get("bestAsk", 0)) if raw.get("bestAsk") else None,
            best_bid=float(raw.get("bestBid", 0)) if raw.get("bestBid") else None,
            clob_token_ids=clob_token_ids,
            end_date=raw.get("endDateIso", raw.get("endDate", "")),
            closed=bool(raw.get("closed", False)),
            neg_risk=bool(raw.get("negRisk", False)),
            enable_order_book=bool(raw.get("enableOrderBook", False)),
            accepting_orders=bool(raw.get("acceptingOrders", False)),
            image=raw.get("image", ""),
            description=raw.get("description", ""),
            event_id=event_id,
            event_title=event_title,
            group_item_title=raw.get("groupItemTitle", ""),
        )
