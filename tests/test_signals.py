"""Pure tests for the underlying-direction sub-signals and the confluence vote."""

from config import DecisionConfig
from signals import (
    Bias,
    compute_signals,
    compute_underlying_bias,
    ema_signal,
    momentum_signal,
    structure_signal,
    vwap_signal,
)


def candle(o, h, l, c, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


CFG = DecisionConfig()


def test_vwap_signal_sides():
    candles = [candle(100, 102, 98, 100), candle(100, 102, 98, 100)]
    # vwap == 100; price above -> bullish, below -> bearish, equal -> neutral
    assert vwap_signal(candles, 105) == Bias.BULLISH
    assert vwap_signal(candles, 95) == Bias.BEARISH
    assert vwap_signal(candles, 100) == Bias.NEUTRAL


def test_vwap_falls_back_to_mean_when_no_volume():
    # index-style candles with zero volume still yield a usable reference
    candles = [candle(100, 110, 90, 100, v=0), candle(100, 110, 90, 100, v=0)]
    assert vwap_signal(candles, 105) == Bias.BULLISH


def test_ema_signal_sides():
    closes = [candle(0, 0, 0, c) for c in (10, 10, 10, 10, 10)]
    assert ema_signal(closes, 11, CFG) == Bias.BULLISH
    assert ema_signal(closes, 9, CFG) == Bias.BEARISH


def test_momentum_signal_relative_to_open():
    candles = [candle(100, 100, 100, 100)]
    assert momentum_signal(candles, 101) == Bias.BULLISH
    assert momentum_signal(candles, 99) == Bias.BEARISH
    assert momentum_signal([], 99) == Bias.NEUTRAL


def test_structure_signal_higher_highs_lows():
    cfg = DecisionConfig(structure_swing=1)
    # zigzag (trough/peak alternating) with rising peaks and rising troughs -> bullish
    highs = [10, 13, 11, 15, 12, 17, 13]
    lows = [6, 9, 7, 11, 8, 13, 9]
    candles = [candle((h + l) / 2, h, l, (h + l) / 2) for h, l in zip(highs, lows)]
    assert structure_signal(candles, 0, cfg) == Bias.BULLISH
    # reversed -> falling peaks and falling troughs -> bearish
    candles_down = [candle((h + l) / 2, h, l, (h + l) / 2)
                    for h, l in zip(highs[::-1], lows[::-1])]
    assert structure_signal(candles_down, 0, cfg) == Bias.BEARISH


def test_confluence_requires_all_by_default():
    cfg = DecisionConfig()  # default: all 3 signals must agree
    assert compute_underlying_bias(
        {"vwap": Bias.BULLISH, "ema": Bias.BULLISH, "momentum": Bias.BULLISH}, cfg
    ) == Bias.BULLISH
    # one dissenter -> neutral (not enough agreement)
    assert compute_underlying_bias(
        {"vwap": Bias.BULLISH, "ema": Bias.BULLISH, "momentum": Bias.NEUTRAL}, cfg
    ) == Bias.NEUTRAL
    assert compute_underlying_bias(
        {"vwap": Bias.BEARISH, "ema": Bias.BEARISH, "momentum": Bias.BEARISH}, cfg
    ) == Bias.BEARISH


def test_confluence_threshold_can_be_loosened():
    cfg = DecisionConfig(signal_set=("vwap", "ema", "momentum", "structure"), min_agreeing_signals=2)
    bias = compute_underlying_bias(
        {"vwap": Bias.BULLISH, "ema": Bias.BULLISH, "momentum": Bias.BEARISH, "structure": Bias.NEUTRAL},
        cfg,
    )
    assert bias == Bias.BULLISH  # 2 bullish >= 2 and outvotes 1 bearish


def test_compute_signals_runs_configured_set():
    cfg = DecisionConfig(signal_set=("momentum",))
    candles = [candle(100, 100, 100, 100)]
    assert compute_signals(candles, 101, cfg) == {"momentum": Bias.BULLISH}
