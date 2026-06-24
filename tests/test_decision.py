"""Pure tests for the combined entry-eligibility decision (Gate A + Gate B)."""

from datetime import datetime, timedelta

from config import DecisionConfig
from decision import Action, decide
from signals import Bias

NOW = datetime(2026, 6, 24, 10, 0, 0)
CFG = DecisionConfig()  # slippage 5%, window 15 min


def make_call(opt_type="CE", entry_max=110.0, stoploss=80.0, entry=None):
    entry = entry_max if entry is None else entry
    return {
        "symbol": "PFC",
        "strike": 350,
        "type": opt_type,
        "entry_min": str(entry),
        "entry_max": str(entry_max),
        "entry": str(entry),
        "stoploss": str(stoploss),
    }


def d(call, is_above, ltp, bias, now=NOW, received=NOW):
    return decide(call, is_above, ltp, bias, now, received, CFG)


# --- terminal price conditions (both call types) ---

def test_at_or_below_stoploss_skips():
    assert d(make_call(), False, 80.0, Bias.BULLISH).action == Action.SKIP
    assert d(make_call(), False, 70.0, Bias.BULLISH).action == Action.SKIP


def test_overshoot_beyond_slippage_cap_skips():
    # entry_max 110, +5% cap = 115.5
    assert d(make_call(), False, 116.0, Bias.BULLISH).action == Action.SKIP


# --- limit calls (isAbove=False): instant take/skip, but can WAIT on direction ---

def test_limit_in_band_aligned_takes():
    assert d(make_call("CE"), False, 100.0, Bias.BULLISH).action == Action.TAKE


def test_limit_below_band_above_sl_still_takes():
    # ltp 85 is below entry_max but above stoploss 80 -> cheaper-but-valid entry
    assert d(make_call("CE"), False, 85.0, Bias.BULLISH).action == Action.TAKE


def test_limit_within_slippage_cap_takes():
    assert d(make_call("CE"), False, 115.0, Bias.BULLISH).action == Action.TAKE


def test_limit_waits_when_underlying_not_aligned():
    # price fine, but underlying neutral -> WAIT (limit calls are no longer instant)
    assert d(make_call("CE"), False, 100.0, Bias.NEUTRAL).action == Action.WAIT
    # opposite bias also waits
    assert d(make_call("CE"), False, 100.0, Bias.BEARISH).action == Action.WAIT


def test_pe_alignment_is_bearish():
    assert d(make_call("PE"), False, 100.0, Bias.BEARISH).action == Action.TAKE
    assert d(make_call("PE"), False, 100.0, Bias.BULLISH).action == Action.WAIT


# --- trigger calls (isAbove=True): entry is the trigger ---

def test_trigger_below_trigger_waits_even_if_aligned():
    call = make_call("CE", entry_max=100.0, entry=100.0, stoploss=80.0)
    # ltp 95 is above SL but below trigger -> WAIT for the trigger
    assert d(call, True, 95.0, Bias.BULLISH).action == Action.WAIT


def test_trigger_hit_and_aligned_takes():
    call = make_call("CE", entry_max=100.0, entry=100.0, stoploss=80.0)
    assert d(call, True, 102.0, Bias.BULLISH).action == Action.TAKE


def test_trigger_overshoot_skips():
    call = make_call("CE", entry_max=100.0, entry=100.0, stoploss=80.0)
    # +5% of 100 = 105; 110 overshoots
    assert d(call, True, 110.0, Bias.BULLISH).action == Action.SKIP


# --- wait window expiry ---

def test_wait_becomes_skip_after_window():
    call = make_call("CE")
    later = NOW + timedelta(minutes=16)
    res = d(call, False, 100.0, Bias.NEUTRAL, now=later, received=NOW)
    assert res.action == Action.SKIP
    assert "window elapsed" in res.reason


def test_within_window_still_waits():
    call = make_call("CE")
    later = NOW + timedelta(minutes=14)
    assert d(call, False, 100.0, Bias.NEUTRAL, now=later, received=NOW).action == Action.WAIT
