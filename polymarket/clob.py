import logging
from typing import Optional
import httpx
from .models import OrderBook

logger = logging.getLogger("polymarket.clob")

BASE_URL = "https://clob.polymarket.com"


class ClobClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=10.0)

    async def close(self):
        await self.client.aclose()

    async def get_book(self, token_id: str) -> Optional[OrderBook]:
        resp = await self.client.get(
            f"{self.base_url}/book",
            params={"token_id": token_id},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        raw = resp.json()
        return OrderBook(
            market=raw.get("market", ""),
            asset_id=raw.get("asset_id", ""),
            bids=raw.get("bids", []),
            asks=raw.get("asks", []),
        )

    async def get_last_price(self, token_id: str, side: str = "SELL") -> Optional[float]:
        resp = await self.client.get(
            f"{self.base_url}/price",
            params={"token_id": token_id, "side": side},
        )
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
            if "price" in data:
                return float(data["price"])
            return None
        except Exception:
            return None

    async def get_price_history(
        self,
        token_id: str,
        interval: str = "max",
        fidelity: int = 240,
    ) -> list[dict]:
        resp = await self.client.get(
            f"{self.base_url}/prices-history",
            params={
                "token_id": token_id,
                "interval": interval,
                "fidelity": str(fidelity),
            },
        )
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []
