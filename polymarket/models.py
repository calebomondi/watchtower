from pydantic import BaseModel, computed_field
from typing import Optional


class Market(BaseModel):
    id: str
    question: str
    condition_id: str
    slug: str
    outcomes: list[str]
    outcome_prices: list[str]
    volume: float
    volume_24hr: float
    liquidity: float
    spread: float
    last_trade_price: float
    best_ask: Optional[float] = None
    best_bid: Optional[float] = None
    clob_token_ids: list[str]
    end_date: str
    closed: bool
    neg_risk: bool
    enable_order_book: bool
    accepting_orders: bool
    image: str = ""
    description: str = ""
    event_id: Optional[str] = None
    event_title: Optional[str] = None
    group_item_title: str = ""

    @computed_field
    @property
    def yes_price(self) -> float:
        return float(self.outcome_prices[0]) if self.outcome_prices else 0.0

    @computed_field
    @property
    def no_price(self) -> float:
        return float(self.outcome_prices[1]) if len(self.outcome_prices) > 1 else 0.0

    @property
    def yes_token_id(self) -> str:
        return self.clob_token_ids[0] if len(self.clob_token_ids) > 0 else ""

    @property
    def no_token_id(self) -> str:
        return self.clob_token_ids[1] if len(self.clob_token_ids) > 1 else ""


class MarketEvent(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    image: str
    closed: bool
    active: bool
    volume: float
    volume_24hr: float
    liquidity: float
    open_interest: float
    markets: list[Market] = []
    tags: list[dict] = []


class OrderBook(BaseModel):
    market: str
    asset_id: str
    bids: list[dict]
    asks: list[dict]

    @property
    def best_bid(self) -> Optional[float]:
        if not self.bids:
            return None
        return max(float(b["price"]) for b in self.bids)

    @property
    def best_ask(self) -> Optional[float]:
        if not self.asks:
            return None
        return min(float(a["price"]) for a in self.asks)

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None
