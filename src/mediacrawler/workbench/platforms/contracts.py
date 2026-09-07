"""Extension contracts. Categories are metadata; executable abilities are explicit.

Future book/price adapters can emit their own validated fields inside common records
without changing the browser, scheduler, or download queue.
"""
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Any
from pydantic import BaseModel, Field


class ProductRecord(BaseModel):
    product_id: str
    sku_id: str = ''
    title: str
    source_url: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class PriceObservation(BaseModel):
    product_id: str
    sku_id: str = ''
    amount: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    price_type: str  # e.g. displayed, member, coupon; never silently compare these
    observed_at: datetime
    source_url: str

    def comparison_key(self):
        return self.product_id, self.sku_id, self.currency.upper(), self.price_type


class WebsiteAdapter(Protocol):
    """Implementations run in workers and use the shared cooperative runtime."""
    async def discover(self, config: dict, session: Any): ...
    async def read_content(self, target: Any, session: Any) -> dict: ...
    async def resolve_resources(self, content: dict, session: Any) -> list[dict]: ...
