"""Instrument resolution: option contract + its underlying.

Pure helpers given an already-fetched instrument dump (so they are testable).
``resolve_option`` picks the nearest non-expired contract matching
symbol/strike/type from a Kite ``instruments("NFO")`` list.
``underlying_quote_key`` maps an option's symbol to the exchange:tradingsymbol of
the thing it derives from — the index for index options, the NSE equity otherwise.
"""

from datetime import date, datetime
from typing import List, Mapping, Optional

# Index option symbols whose underlying is an index, not an equity.
INDEX_UNDERLYINGS = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT",
    "SENSEX": "BSE:SENSEX",
    "BANKEX": "BSE:BANKEX",
}


def underlying_quote_key(symbol: str) -> str:
    sym = symbol.upper()
    return INDEX_UNDERLYINGS.get(sym, f"NSE:{sym}")


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def resolve_option(
    instruments: List[Mapping],
    symbol: str,
    strike,
    opt_type: str,
    today: Optional[date] = None,
) -> Optional[Mapping]:
    """Nearest-expiry NFO option contract matching symbol/strike/type, or None."""
    today = today or date.today()
    matches = [
        i for i in instruments
        if str(i.get("name", "")).upper() == symbol.upper()
        and i.get("instrument_type") == opt_type
        and int(float(i.get("strike", 0))) == int(strike)
        and str(i.get("segment", "")).endswith("OPT")
    ]
    future = [i for i in matches if _as_date(i["expiry"]) >= today]
    future.sort(key=lambda i: _as_date(i["expiry"]))
    return future[0] if future else None
