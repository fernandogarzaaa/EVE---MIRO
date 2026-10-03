"""MarketSim: a purpose-built market simulation engine (MIT).

Grounds agent-based market scenarios in observed WorldState data and
produces SIMULATED price trajectories for stress-testing, never forecasts.
"""

from marketsim.agents import (
    FundamentalTrader,
    MarketMaker,
    MarketView,
    MomentumTrader,
    NoiseTrader,
    TraderAgent,
)
from marketsim.engine import MarketSimEngine
from marketsim.orderbook import LimitOrderBook, Order, Side, Trade

__all__ = [
    "FundamentalTrader",
    "LimitOrderBook",
    "MarketMaker",
    "MarketSimEngine",
    "MarketView",
    "MomentumTrader",
    "NoiseTrader",
    "Order",
    "Side",
    "Trade",
    "TraderAgent",
]
