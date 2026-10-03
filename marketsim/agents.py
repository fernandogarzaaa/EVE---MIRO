"""Trader archetypes. Each decides limit/market orders from a market view.

All randomness comes from a caller-supplied ``random.Random`` so runs are
seed-deterministic. Agents never see the future: the view only carries
history up to the current step.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from marketsim.orderbook import Order, Side


@dataclass
class MarketView:
    symbol: str
    mid: float | None  # None when the book is empty
    spread: float | None
    mid_history: list[float]  # mids up to and including the current step
    inventory: float  # agent's net position in shares
    fair_value: float
    step: int
    vol_multiplier: float = 1.0  # >1 during a volatility-spike intervention
    flow_shock: float = 0.0  # signed one-sided pressure: -1 heavy selling, +1 heavy buying


class TraderAgent:
    kind = "base"

    def __init__(self, agent_id: str, symbol: str, *, size: float = 100.0, seed: int = 0) -> None:
        self.agent_id = agent_id
        self.symbol = symbol
        self.size = size
        self.rng = Random(seed)
        self.inventory = 0.0
        self._order_n = 0

    def _new_order(self, side: Side, quantity: float, price: float | None) -> Order:
        self._order_n += 1
        return Order(
            order_id=f"{self.agent_id}-{self._order_n}",
            agent_id=self.agent_id,
            symbol=self.symbol,
            side=side,
            quantity=quantity,
            price=price,
        )

    def decide(self, view: MarketView) -> list[Order]:
        raise NotImplementedError

    def on_fill(self, side: Side, quantity: float) -> None:
        self.inventory += quantity if side == Side.BID else -quantity


class MarketMaker(TraderAgent):
    """Quotes a small ladder on both sides around mid; skews against inventory.

    The ladder (size and spread multiples of the base) gives the book graduated
    depth: small flow is absorbed at the top, large sweeps walk the price down.
    """

    kind = "market_maker"

    # (size multiple, spread multiple) per ladder level, best to deepest.
    LADDER = ((1.0, 1.0), (2.0, 4.0), (4.0, 16.0))

    def __init__(
        self,
        agent_id: str,
        symbol: str,
        *,
        size: float = 25.0,
        seed: int = 0,
        spread_bps: float = 20.0,
        skew_k: float = 2.0,
        inventory_limit: float = 5000.0,
    ) -> None:
        super().__init__(agent_id, symbol, size=size, seed=seed)
        self.spread_bps = spread_bps
        self.skew_k = skew_k
        self.inventory_limit = inventory_limit

    def decide(self, view: MarketView) -> list[Order]:
        if view.mid is None or view.mid <= 0:
            return []
        # Caller cancels this agent's resting quotes before decide() each step.
        # Adverse selection: pull back on toxic one-sided flow.
        shock = abs(view.flow_shock)
        size_mult = max(1.0 - 0.7 * shock, 0.1)
        spread_mult = 1.0 + 2.0 * shock
        size = self.size * size_mult
        half = view.mid * (self.spread_bps * spread_mult / 1e4) / 2.0
        skew = self.skew_k * (self.inventory / max(self.inventory_limit, 1.0)) * view.mid * 0.001
        orders: list[Order] = []
        if self.inventory < self.inventory_limit:
            for size_m, spread_m in self.LADDER:
                orders.append(
                    self._new_order(
                        Side.BID, size * size_m,
                        round(view.mid - half * spread_m - skew, 4),
                    )
                )
        if self.inventory > -self.inventory_limit:
            for size_m, spread_m in self.LADDER:
                orders.append(
                    self._new_order(
                        Side.ASK, size * size_m,
                        round(view.mid + half * spread_m - skew, 4),
                    )
                )
        return orders


class MomentumTrader(TraderAgent):
    """Buys recent uptrends, sells recent downtrends (market orders)."""

    kind = "momentum"

    def __init__(
        self,
        agent_id: str,
        symbol: str,
        *,
        size: float = 100.0,
        seed: int = 0,
        lookback: int = 5,
        threshold: float = 0.003,
    ) -> None:
        super().__init__(agent_id, symbol, size=size, seed=seed)
        self.lookback = lookback
        self.threshold = threshold

    def decide(self, view: MarketView) -> list[Order]:
        hist = view.mid_history
        if len(hist) <= self.lookback or hist[-self.lookback - 1] <= 0:
            return []
        ret = hist[-1] / hist[-self.lookback - 1] - 1.0
        qty = self.size * view.vol_multiplier
        if ret > self.threshold:
            return [self._new_order(Side.BID, qty, None)]
        if ret < -self.threshold:
            return [self._new_order(Side.ASK, qty, None)]
        return []


class NoiseTrader(TraderAgent):
    """Uninformed flow. Random side, small size, scaled by vol_multiplier."""

    kind = "noise"

    def __init__(
        self,
        agent_id: str,
        symbol: str,
        *,
        size: float = 50.0,
        seed: int = 0,
        trade_prob: float = 0.35,
    ) -> None:
        super().__init__(agent_id, symbol, size=size, seed=seed)
        self.trade_prob = trade_prob

    def decide(self, view: MarketView) -> list[Order]:
        if view.mid is None:
            return []
        if self.rng.random() > self.trade_prob:
            return []
        side = Side.BID if self.rng.random() < 0.5 else Side.ASK
        qty = self.size * view.vol_multiplier * self.rng.uniform(0.5, 1.5)
        return [self._new_order(side, round(qty, 2), None)]


class FundamentalTrader(TraderAgent):
    """Mean-reverts toward a scenario-given fair value (market orders)."""

    kind = "fundamental"

    def __init__(
        self,
        agent_id: str,
        symbol: str,
        *,
        size: float = 100.0,
        seed: int = 0,
        fair_value: float = 100.0,
        tolerance: float = 0.01,
    ) -> None:
        super().__init__(agent_id, symbol, size=size, seed=seed)
        self.fair_value = fair_value
        self.tolerance = tolerance

    def decide(self, view: MarketView) -> list[Order]:
        if view.mid is None or view.mid <= 0:
            return []
        # The engine may shift fair_value on a rate_shock intervention.
        self.fair_value = view.fair_value
        if view.mid < self.fair_value * (1.0 - self.tolerance):
            return [self._new_order(Side.BID, self.size, None)]
        if view.mid > self.fair_value * (1.0 + self.tolerance):
            return [self._new_order(Side.ASK, self.size, None)]
        return []


ARCHETYPES: dict[str, type[TraderAgent]] = {
    "market_maker": MarketMaker,
    "momentum": MomentumTrader,
    "noise": NoiseTrader,
    "fundamental": FundamentalTrader,
}
