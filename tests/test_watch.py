"""Tests for the watch/retry loop using a fake broker and an injectable clock.

The loop logic is exercised with a single ``momentum`` signal so the underlying
bias is controlled purely by (underlying_ltp vs session open) — the signal
internals are covered separately in test_signals.
"""

from datetime import datetime, timedelta

from config import DecisionConfig
from decision import Action
from watch import watch

OPEN = 100.0  # session open for the underlying; momentum compares u_ltp to this


def candles():
    return [{"open": OPEN, "high": OPEN, "low": OPEN, "close": OPEN, "volume": 0}]


class FakeBroker:
    """Serves a scripted list of (option_ltp, underlying_ltp) steps; advances one
    step per evaluation. Records how many times the loop slept."""

    def __init__(self, steps):
        self.steps = steps
        self.k = 0
        self.sleeps = 0

    def resolve_option(self, symbol, strike, opt_type):
        return {"tradingsymbol": "PFC25JUN350CE", "exchange": "NFO"}

    def _cur(self):
        return self.steps[min(self.k, len(self.steps) - 1)]

    def option_ltp(self, instrument):
        return self._cur()[0]

    def underlying_candles(self, underlying_key, cfg):
        return candles()

    def underlying_ltp(self, underlying_key):
        u = self._cur()[1]
        self.k += 1  # advance after the last fetch of an evaluation
        return u


def make_call(opt_type="CE", entry_max=110.0, stoploss=80.0):
    return {
        "symbol": "PFC", "strike": 350, "type": opt_type,
        "entry_min": str(entry_max), "entry_max": str(entry_max),
        "entry": str(entry_max), "stoploss": str(stoploss),
    }


def clock(start, step_minutes):
    t = {"v": start}

    def now_fn():
        cur = t["v"]
        t["v"] = cur + timedelta(minutes=step_minutes)
        return cur

    return now_fn


def test_takes_after_underlying_aligns():
    # option price in-zone throughout; underlying flips bullish on the 3rd poll
    steps = [(90.0, 99.0), (90.0, 99.0), (90.0, 101.0)]
    broker = FakeBroker(steps)
    cfg = DecisionConfig(signal_set=("momentum",))
    sleeps = {"n": 0}

    res = watch(
        make_call("CE"), False, broker, cfg=cfg,
        received_at=datetime(2026, 6, 24, 10, 0, 0),
        now_fn=clock(datetime(2026, 6, 24, 10, 0, 0), 1),  # +1 min/poll, window 15
        sleep_fn=lambda s: sleeps.__setitem__("n", sleeps["n"] + 1),
    )
    assert res.action == Action.TAKE
    assert sleeps["n"] == 2  # waited twice before taking on the third evaluation


def test_skips_at_window_expiry_when_never_aligns():
    steps = [(90.0, 99.0)]  # underlying stays bearish for a CE -> never aligns
    broker = FakeBroker(steps)
    cfg = DecisionConfig(signal_set=("momentum",))

    res = watch(
        make_call("CE"), False, broker, cfg=cfg,
        received_at=datetime(2026, 6, 24, 10, 0, 0),
        now_fn=clock(datetime(2026, 6, 24, 10, 0, 0), 10),  # +10 min/poll
        sleep_fn=lambda s: None,
    )
    assert res.action == Action.SKIP
    assert "window elapsed" in res.reason


def test_unresolvable_instrument_skips():
    class NoInstrument(FakeBroker):
        def resolve_option(self, *a):
            return None

    res = watch(make_call(), False, NoInstrument([(90.0, 101.0)]), cfg=DecisionConfig(signal_set=("momentum",)))
    assert res.action == Action.SKIP
    assert "resolve" in res.reason
