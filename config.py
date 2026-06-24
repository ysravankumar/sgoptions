"""Configuration for the call entry-eligibility decision engine.

A single ``DecisionConfig`` carries every tunable used by the price gate, the
underlying-direction gate, and the wait/retry loop. Defaults are the ones agreed
in the plan (``retry-plan-cozy-jellyfish.md``): strict confluence (all signals in
``signal_set`` must agree), intraday 5-minute candles, and a ``slippage_cap``
expressed as a percentage of the entry ceiling so it is scale-invariant across a
cheap (~Rs.5) and an expensive (~Rs.400) premium.
"""

from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class DecisionConfig:
    # --- Price gate ---
    slippage_cap_pct: float = 5.0          # % above the entry ceiling still takeable

    # --- Wait loop / timing ---
    wait_window_minutes: float = 15.0      # N minutes from receipt before giving up
    poll_interval_seconds: float = 30.0    # how often the watcher re-evaluates

    # --- Underlying direction gate ---
    candle_interval: str = "5minute"       # Kite historical_data interval
    ema_period: int = 20                   # short EMA on the chosen interval
    structure_swing: int = 2               # bars each side for swing-pivot detection
    # Trend sub-signals to combine. "structure" is implemented and selectable but
    # left out of the default set: in clean trends without pullbacks it produces no
    # swing pivots and reads NEUTRAL, which would needlessly block an otherwise
    # confirmed direction. Add it via config when pullback structure matters.
    signal_set: Tuple[str, ...] = ("vwap", "ema", "momentum")
    min_agreeing_signals: int = 0          # 0 => require ALL signals in signal_set

    def required_agreement(self) -> int:
        """Number of sub-signals that must agree for a non-neutral bias."""
        return self.min_agreeing_signals or len(self.signal_set)
