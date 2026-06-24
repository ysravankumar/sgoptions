"""The pure entry-eligibility decision (combines Gate A + Gate B).

``decide`` takes a parsed call, the live option premium, a precomputed underlying
``bias`` (from ``signals.compute_underlying_bias``) and the clock, and returns one
of TAKE / WAIT / SKIP. It performs no IO and reads no clock of its own — ``now``
and ``received_at`` are passed in — so every branch is deterministically testable.

Rules (see ``retry-plan-cozy-jellyfish.md``):

* ``ltp <= stoploss``                         -> SKIP   (invalidated; dominates all)
* price ran beyond the slippage cap           -> SKIP   (missed; don't chase)
* price in take-zone AND underlying aligned   -> TAKE
* otherwise (price pending and/or unaligned)  -> WAIT until the N-minute window
                                                 from receipt elapses, then SKIP

Gate B (price) take-zone:
  * limit call  (isAbove=False): stoploss < ltp <= entry_max * (1 + cap)
  * trigger call (isAbove=True) : entry      <= ltp <= entry     * (1 + cap)
    and ``stoploss < ltp < entry`` is "pending price" (wait for the trigger).

Gate A (direction): CE requires a BULLISH underlying, PE requires BEARISH.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from signals import Bias


class Action(str, Enum):
    TAKE = "TAKE"
    WAIT = "WAIT"
    SKIP = "SKIP"


@dataclass
class Decision:
    action: Action
    reason: str
    ltp: float
    bias: Bias


def aligned(opt_type: str, bias: Bias) -> bool:
    """CE wants a bullish underlying, PE wants a bearish one."""
    if opt_type == "CE":
        return bias == Bias.BULLISH
    if opt_type == "PE":
        return bias == Bias.BEARISH
    return False


def call_levels(call):
    """Coerce the parser's string fields to floats. Raises ValueError/KeyError if
    the call lacks a usable numeric entry/stop-loss (the caller should SKIP it)."""
    entry_max = float(call["entry_max"])
    entry = float(call.get("entry", entry_max))
    stoploss = float(call["stoploss"])
    return entry, entry_max, stoploss


def decide(call, is_above, ltp, bias, now, received_at, cfg) -> Decision:
    opt_type = call["type"]
    entry, entry_max, stoploss = call_levels(call)
    cap = 1.0 + cfg.slippage_cap_pct / 100.0

    # --- Gate B: terminal price conditions ---
    if ltp <= stoploss:
        return Decision(Action.SKIP, "price at/below stop-loss (invalidated)", ltp, bias)

    ceiling = entry if is_above else entry_max
    if ltp > ceiling * cap:
        return Decision(Action.SKIP, "price ran beyond slippage cap (missed)", ltp, bias)

    if is_above:
        in_zone = entry <= ltp <= ceiling * cap          # trigger hit, not overshot
    else:
        in_zone = stoploss < ltp <= ceiling * cap        # limit calls: always in-zone here

    # --- Gate A: direction ---
    is_aligned = aligned(opt_type, bias)

    if in_zone and is_aligned:
        return Decision(Action.TAKE, "price in zone and underlying aligned", ltp, bias)

    # Not takeable yet. WAIT unless the entry window has elapsed.
    pending = []
    if not in_zone:
        pending.append("price below trigger" if is_above else "price not in entry zone")
    if not is_aligned:
        pending.append(f"underlying not aligned (bias={bias.value})")

    if now - received_at >= timedelta(minutes=cfg.wait_window_minutes):
        return Decision(Action.SKIP, "wait window elapsed: " + ", ".join(pending), ltp, bias)

    return Decision(Action.WAIT, "; ".join("waiting: " + p for p in pending), ltp, bias)
