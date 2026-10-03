"""Limit order book with price-time priority. Deterministic; no RNG here.

A market order is a limit order with ``price=None``: it crosses the whole
opposite side at resting prices until filled or the book is empty.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from itertools import count


class Side(Enum):
    BID = "bid"  # buy
    ASK = "ask"  # sell


@dataclass
class Order:
    order_id: str
    agent_id: str
    symbol: str
    side: Side
    quantity: float
    price: float | None = None  # None means market order
    seq: int = 0

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        if self.price is not None and self.price <= 0:
            raise ValueError("limit price must be positive")


@dataclass
class Trade:
    symbol: str
    price: float
    quantity: float
    buyer_id: str
    seller_id: str
    step: int


@dataclass
class Quote:
    bid: float | None
    ask: float | None

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid


class LimitOrderBook:
    """One instrument. Bids and asks are price -> FIFO deque (time priority)."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._bids: dict[float, deque[Order]] = {}
        self._asks: dict[float, deque[Order]] = {}
        self._seq = count()
        self.trades: list[Trade] = []

    # -- book state -----------------------------------------------------
    def best_bid(self) -> float | None:
        return max(self._bids) if self._bids else None

    def best_ask(self) -> float | None:
        return min(self._asks) if self._asks else None

    def quote(self) -> Quote:
        return Quote(bid=self.best_bid(), ask=self.best_ask())

    def depth(self, side: Side, levels: int = 5) -> list[tuple[float, float]]:
        book = self._bids if side == Side.BID else self._asks
        prices = sorted(book, reverse=(side == Side.BID))[:levels]
        return [(p, sum(o.quantity for o in book[p])) for p in prices]

    def open_quantity(self) -> float:
        return sum(o.quantity for dq in self._bids.values() for o in dq) + sum(
            o.quantity for dq in self._asks.values() for o in dq
        )

    # -- order entry ----------------------------------------------------
    def add(self, order: Order, step: int = 0) -> list[Trade]:
        """Match against the opposite side, then rest any remainder."""
        if order.symbol != self.symbol:
            raise ValueError(f"order for {order.symbol} sent to {self.symbol} book")
        order.seq = next(self._seq)
        trades = self._match(order, step)
        if order.quantity > 0:
            if order.price is None:
                # Unfilled market order: discarded, never rests. Recorded by caller.
                return trades
            book = self._bids if order.side == Side.BID else self._asks
            book.setdefault(order.price, deque()).append(order)
        return trades

    def _match(self, taker: Order, step: int) -> list[Trade]:
        trades: list[Trade] = []
        is_buy = taker.side == Side.BID
        book = self._asks if is_buy else self._bids
        while taker.quantity > 0 and book:
            best = min(book) if is_buy else max(book)
            # Limit orders only cross when prices overlap.
            if taker.price is not None:
                if is_buy and taker.price < best:
                    break
                if not is_buy and taker.price > best:
                    break
            resting = book[best][0]
            qty = min(taker.quantity, resting.quantity)
            # Trade prints at the resting order's price (price priority).
            trades.append(
                Trade(
                    symbol=self.symbol,
                    price=best,
                    quantity=qty,
                    buyer_id=taker.agent_id if is_buy else resting.agent_id,
                    seller_id=resting.agent_id if is_buy else taker.agent_id,
                    step=step,
                )
            )
            taker.quantity -= qty
            resting.quantity -= qty
            if resting.quantity <= 0:
                book[best].popleft()
                if not book[best]:
                    del book[best]
        self.trades.extend(trades)
        return trades

    def cancel_agent_orders(self, agent_id: str) -> int:
        """Remove all resting orders for an agent. Returns count removed."""
        removed = 0
        for book in (self._bids, self._asks):
            for price in list(book):
                kept = deque(o for o in book[price] if o.agent_id != agent_id)
                removed += len(book[price]) - len(kept)
                if kept:
                    book[price] = kept
                else:
                    del book[price]
        return removed

    def resting_orders(self) -> list[Order]:
        out: list[Order] = []
        for book in (self._bids, self._asks):
            for dq in book.values():
                out.extend(dq)
        return out
