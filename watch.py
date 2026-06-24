"""The watch/retry loop: the only place with live IO and timing.

``watch`` resolves the option + underlying once, then repeatedly fetches the live
option premium and the underlying's intraday candles, computes the confluence bias,
and calls the pure ``decide``. It returns as soon as the decision is TAKE or SKIP;
while the decision is WAIT it sleeps for ``poll_interval_seconds`` and re-evaluates.
That loop is the "retry" — re-checking both gates until the call becomes takeable or
the wait window elapses.

A ``Broker`` is duck-typed (see ``KiteBroker`` for the production adapter); tests
pass a fake. ``now_fn``/``sleep_fn`` are injectable so the loop is testable without
real wall-clock time.
"""

import time
from datetime import datetime, timedelta
from typing import Callable, List, Mapping, Optional, Protocol

from config import DecisionConfig
from decision import Action, Decision, decide
from signals import Bias, compute_signals, compute_underlying_bias
import instruments as instr


class Broker(Protocol):
    def resolve_option(self, symbol: str, strike, opt_type: str) -> Optional[Mapping]: ...
    def option_ltp(self, instrument: Mapping) -> float: ...
    def underlying_candles(self, underlying_key: str, cfg: DecisionConfig) -> List[Mapping]: ...
    def underlying_ltp(self, underlying_key: str) -> float: ...


def evaluate_once(call, is_above, instrument, underlying_key, broker, cfg, now, received_at) -> Decision:
    """One full evaluation: fetch live data, compute bias, run the pure decision."""
    ltp = broker.option_ltp(instrument)
    candles = broker.underlying_candles(underlying_key, cfg)
    underlying_ltp = broker.underlying_ltp(underlying_key)
    bias = compute_underlying_bias(compute_signals(candles, underlying_ltp, cfg), cfg)
    return decide(call, is_above, ltp, bias, now, received_at, cfg)


def watch(
    call,
    is_above,
    broker: Broker,
    cfg: Optional[DecisionConfig] = None,
    received_at: Optional[datetime] = None,
    now_fn: Callable[[], datetime] = datetime.now,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Decision:
    cfg = cfg or DecisionConfig()
    received_at = received_at or now_fn()

    instrument = broker.resolve_option(call["symbol"], call["strike"], call["type"])
    if instrument is None:
        return Decision(Action.SKIP, "could not resolve option instrument", float("nan"), Bias.NEUTRAL)

    underlying_key = instr.underlying_quote_key(call["symbol"])
    while True:
        decision = evaluate_once(
            call, is_above, instrument, underlying_key, broker, cfg, now_fn(), received_at
        )
        if decision.action in (Action.TAKE, Action.SKIP):
            return decision
        sleep_fn(cfg.poll_interval_seconds)


def watch_message(msg: str, broker: Broker, cfg: Optional[DecisionConfig] = None, **kwargs) -> Decision:
    """Convenience: parse a raw channel message with the existing parser, then watch.

    Reuses ``call_parser.parse_sg_opt_msgs`` (imported lazily so the core engine has
    no dependency on colorama)."""
    from call_parser import parse_sg_opt_msgs

    call, is_above = parse_sg_opt_msgs(msg)
    if not call or not call.get("symbol"):
        return Decision(Action.SKIP, "message did not parse into a tradable call", float("nan"), Bias.NEUTRAL)
    return watch(call, is_above, broker, cfg=cfg, **kwargs)


class KiteBroker:
    """Production ``Broker`` over a kiteconnect ``KiteConnect`` instance.

    All calls are read-only (instrument dump, LTP, intraday candles); this engine
    never places an order — that is the downstream concern triggered by a TAKE.
    Not exercised by the unit tests (it needs live credentials); the pure logic and
    the loop are covered with a fake broker instead.
    """

    def __init__(self, kite):
        self.kite = kite
        self._nfo = None
        self._token_cache = {}

    def _nfo_instruments(self):
        if self._nfo is None:
            self._nfo = self.kite.instruments("NFO")
        return self._nfo

    def resolve_option(self, symbol, strike, opt_type):
        return instr.resolve_option(self._nfo_instruments(), symbol, strike, opt_type)

    def option_ltp(self, instrument):
        key = f'{instrument["exchange"]}:{instrument["tradingsymbol"]}'
        return self.kite.ltp([key])[key]["last_price"]

    def underlying_ltp(self, underlying_key):
        return self.kite.ltp([underlying_key])[underlying_key]["last_price"]

    def _underlying_token(self, underlying_key):
        if underlying_key not in self._token_cache:
            exch, tsym = underlying_key.split(":", 1)
            token = None
            for i in self.kite.instruments(exch):
                if i["tradingsymbol"] == tsym:
                    token = i["instrument_token"]
                    break
            self._token_cache[underlying_key] = token
        return self._token_cache[underlying_key]

    def underlying_candles(self, underlying_key, cfg):
        token = self._underlying_token(underlying_key)
        if token is None:
            return []
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.kite.historical_data(token, start, now, cfg.candle_interval)
