"""Lean calibration runner: agents against a limit order book, no engine overhead.

The full MarketSimEngine path (WorldState, pydantic per-step actions,
traces) costs ~13s per 72h window, which makes hundreds of MSM objective
evaluations infeasible. This runner steps the same archetypes against the
same order book directly and records hourly mids only: ~0.8s per
126-day replication with 32 agents.

Baseline dynamics only: no shock interventions. MSM calibrates the
everyday market mechanism; shock scenarios are scored separately by the
alignment module.
"""

from __future__ import annotations

from marketsim.agents import MarketMaker, MarketView
from marketsim.orderbook import LimitOrderBook, Order, Side

from eve_miro.core.calibration.params import (
    AGENTS_TOTAL,
    CalibrationParams,
    build_agents,
)


def simulate_daily_closes(
    params: CalibrationParams,
    *,
    days: int,
    steps_per_day: int = 24,
    warmup_days: int = 2,
    seed: int = 101,
    symbol: str = "ACME",
    initial_price: float = 100.0,
    total_agents: int = AGENTS_TOTAL,
) -> list[float]:
    """Run the baseline market and return daily closes (post-warmup).

    Raises ValueError on bad input (fail closed); never returns a partial
    series silently.
    """
    if days <= 0:
        raise ValueError(f"days must be positive, got {days}")
    if steps_per_day <= 0:
        raise ValueError(f"steps_per_day must be positive, got {steps_per_day}")
    if warmup_days < 0 or warmup_days >= days:
        raise ValueError(f"warmup_days={warmup_days} invalid for days={days}")
    if initial_price <= 0:
        raise ValueError(f"initial_price must be positive, got {initial_price}")

    book = LimitOrderBook(symbol)
    book.add(
        Order(order_id="bootstrap-bid", agent_id="bootstrap", symbol=symbol,
              side=Side.BID, quantity=1000.0, price=round(initial_price * 0.999, 4)),
        step=-1,
    )
    book.add(
        Order(order_id="bootstrap-ask", agent_id="bootstrap", symbol=symbol,
              side=Side.ASK, quantity=1000.0, price=round(initial_price * 1.001, 4)),
        step=-1,
    )
    agents = build_agents(params, symbol, seed, total_agents, initial_price)
    by_id = {a.agent_id: a for a in agents}
    mid_history = [initial_price]
    closes: list[float] = []
    total_steps = (warmup_days + days) * steps_per_day
    for hour in range(total_steps):
        for agent in agents:
            if isinstance(agent, MarketMaker):
                book.cancel_agent_orders(agent.agent_id)
            quote = book.quote()
            mid = quote.mid if quote.mid is not None else mid_history[-1]
            view = MarketView(
                symbol=symbol,
                mid=mid,
                spread=quote.spread,
                mid_history=mid_history,
                inventory=agent.inventory,
                fair_value=initial_price,
                step=hour,
            )
            for order in agent.decide(view):
                for trade in book.add(order, step=hour):
                    buyer = by_id.get(trade.buyer_id)
                    seller = by_id.get(trade.seller_id)
                    if buyer is not None:
                        buyer.on_fill(Side.BID, trade.quantity)
                    if seller is not None:
                        seller.on_fill(Side.ASK, trade.quantity)
        quote = book.quote()
        mid_history.append(quote.mid if quote.mid is not None else mid_history[-1])
        if (hour + 1) % steps_per_day == 0 and hour + 1 > warmup_days * steps_per_day:
            closes.append(mid_history[-1])
    if len(closes) != days:
        raise RuntimeError(
            f"runner produced {len(closes)} closes for {days} requested days"
        )
    if any(c <= 0 for c in closes):
        raise RuntimeError("runner produced non-positive close prices")
    return closes
