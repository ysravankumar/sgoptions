"""Underlying-direction sub-signals and the confluence vote (Gate A).

All functions here are **pure**: they take already-fetched intraday candles (and
the live underlying price) and return a direction. The candle-fetching IO lives in
``watch.py`` so this module stays trivially unit-testable.

A *candle* is a mapping with ``open``/``high``/``low``/``close``/``volume`` keys
(the shape returned by Kite ``historical_data``). The candle list passed in is
expected to be the **current session's** intraday candles, so VWAP is session-
anchored and momentum is measured from the day's open.
"""

from enum import Enum
from typing import Dict, List, Mapping, Optional

Candle = Mapping[str, float]


class Bias(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


def _side(price: float, reference: Optional[float]) -> Bias:
    if reference is None:
        return Bias.NEUTRAL
    if price > reference:
        return Bias.BULLISH
    if price < reference:
        return Bias.BEARISH
    return Bias.NEUTRAL


def _vwap(candles: List[Candle]) -> Optional[float]:
    """Volume-weighted average of typical price. Falls back to a simple mean of
    typical prices when there is no volume (e.g. index candles report volume 0)."""
    num = den = 0.0
    typicals = []
    for c in candles:
        tp = (c["high"] + c["low"] + c["close"]) / 3.0
        typicals.append(tp)
        vol = c.get("volume") or 0
        num += tp * vol
        den += vol
    if den > 0:
        return num / den
    return sum(typicals) / len(typicals) if typicals else None


def _ema(values: List[float], period: int) -> Optional[float]:
    if not values:
        return None
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _pivots(series: List[float], swing: int, want_high: bool) -> List[float]:
    """Local maxima (want_high) or minima with ``swing`` bars on each side."""
    out = []
    n = len(series)
    for i in range(swing, n - swing):
        window = series[i - swing:i + swing + 1]
        if want_high and series[i] == max(window):
            out.append(series[i])
        elif not want_high and series[i] == min(window):
            out.append(series[i])
    return out


def vwap_signal(candles: List[Candle], ltp: float, cfg=None) -> Bias:
    return _side(ltp, _vwap(candles))


def ema_signal(candles: List[Candle], ltp: float, cfg) -> Bias:
    return _side(ltp, _ema([c["close"] for c in candles], cfg.ema_period))


def momentum_signal(candles: List[Candle], ltp: float, cfg=None) -> Bias:
    """Direction of the live price relative to the session open."""
    if not candles:
        return Bias.NEUTRAL
    return _side(ltp, candles[0]["open"])


def structure_signal(candles: List[Candle], ltp: float, cfg) -> Bias:
    """Higher-highs & higher-lows => BULLISH; lower-highs & lower-lows => BEARISH."""
    swing = cfg.structure_swing if cfg else 2
    highs = _pivots([c["high"] for c in candles], swing, want_high=True)
    lows = _pivots([c["low"] for c in candles], swing, want_high=False)
    if len(highs) >= 2 and len(lows) >= 2:
        higher = highs[-1] > highs[-2] and lows[-1] > lows[-2]
        lower = highs[-1] < highs[-2] and lows[-1] < lows[-2]
        if higher:
            return Bias.BULLISH
        if lower:
            return Bias.BEARISH
    return Bias.NEUTRAL


SIGNAL_FUNCS = {
    "vwap": vwap_signal,
    "ema": ema_signal,
    "momentum": momentum_signal,
    "structure": structure_signal,
}


def compute_signals(candles: List[Candle], ltp: float, cfg) -> Dict[str, Bias]:
    """Run every sub-signal named in ``cfg.signal_set``."""
    return {name: SIGNAL_FUNCS[name](candles, ltp, cfg) for name in cfg.signal_set}


def compute_underlying_bias(signals: Mapping[str, Bias], cfg) -> Bias:
    """Confluence vote: return a direction only when at least
    ``cfg.required_agreement()`` sub-signals point the same way and that direction
    strictly outvotes the other; otherwise NEUTRAL."""
    required = cfg.required_agreement()
    bull = sum(1 for b in signals.values() if b == Bias.BULLISH)
    bear = sum(1 for b in signals.values() if b == Bias.BEARISH)
    if bull >= required and bull > bear:
        return Bias.BULLISH
    if bear >= required and bear > bull:
        return Bias.BEARISH
    return Bias.NEUTRAL
