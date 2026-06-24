# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-module library (`call_parser.py`) that extracts structured option-trade
signals from the free-text messages posted in the "SG Options Training Group"
Telegram channel. There is no app, server, or CLI here — only the parser and a
sample dataset. The Telegram bot / order-placement code that consumes this parser
lives elsewhere and is **not** in this repository.

`sg_option_channel_calls.json` is a raw Telegram channel export used as real-world
sample input (~2.7 MB). Each entry under `messages[]` carries the human-typed call
in its `text` field (either a string or an array of formatting fragments).

## Domain vocabulary (needed to read the code)

Messages describe NSE (Indian) index/stock options. The parser turns text like
`BUY PFC 350 CE 15-15.5 / SL 10 / TGT 20 / intra` into a dict.

- `CE` = call, `PE` = put; the number before it is the **strike**.
- `AT` / a price range = **entry** price (rupees). `SL` = stop-loss, `TGT` = target.
- Tags: `INTRA(DAY)`, `BTST` (buy-today-sell-tomorrow), `STBT`, `HOLDING`.
- `bnf` = BANKNIFTY; also NIFTY, FINNIFTY, and individual stock symbols.
- **`isAbove`**: returned alongside the parsed dict. True when the message says
  "only above X", meaning the entry is a *trigger* price, not a limit — downstream
  order logic treats these differently, so preserve this flag.
- Messages containing `BOOK`, `PROFIT`, `ACHIEVED`, `SELL`, `WATCHLIST` are
  status/exit updates, not fresh buy calls, and are intentionally skipped.

## Architecture

The public entry point is `parse_sg_opt_msgs(msg) -> (dict, isAbove)`. It runs a
**three-tier fallback chain**, each tier a self-contained parser, returning the
first that yields `symbol` + `entry` + `stoploss`:

1. `parse_sg_opt_msgs_enhanced` — line-oriented parser. Normalizes the message,
   splits on newlines, and classifies each line (instrument / `AT` / `SL`).
   Uses `expand_range` to repair shorthand ranges like `110-13` → `110-113`.
2. `parse_sg_opt_msgs_enhanced_new` — regex-per-line parser covering compact
   formats (`SYMBOLSTRIKECE`) and `only above` trigger prices.
3. `parse_sg_option_call_claude` — most permissive single-pass regex parser with
   price sanity checks (entry assumed `< 500`).

Symbol strings are normalized via `parse_option_symbol` and entry ranges via
`parse_at_price` before being assembled into the final `ret_dic`
(`symbol`, `strike`, `type`, `entry_min`, `entry_max`, `entry`, `stoploss`).

### Parsing gotchas (verify before relying on them)

- In `parse_sg_opt_msgs`, tier 3 (`parse_sg_option_call_claude`) is **called first
  but its result is immediately overwritten** by tier 1 and never used — it only
  prints. Effective order is tiers 1 → 2 → 3.
- Output schema is inconsistent across parsers: `parse_sg_option_call_claude`
  produces `target`/`stoploss`, but the assembled `ret_dic` carries `stoploss`
  and no `target`.
- The parsers are heuristic and tuned against the message styles in the sample
  JSON. When changing a regex, check it against real lines in that file rather
  than reasoning about the format abstractly — the formats are irregular.

## Commands

No build system, test suite, requirements file, or git repo exists yet.

```bash
# Dependencies (only colorama is actually used; pytz/datetime are imported but dead)
pip install colorama pytz

# Smoke-test the parser against a single message
python -c "from call_parser import parse_sg_opt_msgs; print(parse_sg_opt_msgs('BUY PFC 350 CE 15-15.5\nSL 10\nTGT 20\nintra'))"
```

When adding tests or validating changes, drive `parse_sg_opt_msgs` with `text`
values pulled from `sg_option_channel_calls.json` — it is the source of truth for
the input formats this parser must handle.

---

## Working agreement (preserved from prior CLAUDE.md)

1. Ask, don't assume. If something is unclear, ask before writing a single line. Never make silent assumptions about intent, architecture, or requirements. When running unattended, pick the most reasonable interpretation, proceed, and record the assumption rather than blocking.

2. Implement the simplest solution for simple problems, better solutions for harder problems. Do not over-engineer or add flexibility that isn't needed yet. Before writing code for complex problems, briefly state your approach and what that approach makes harder down the line.

3. Don't touch unrelated code, but please do surface bad code or design smells you discover with me so we can address them as a separate issue.

4. Flag uncertainty explicitly. If you're unsure about something, see point 1 above. If it makes sense to do so, conduct a small, localised and low-risk experiment and bring the hypothesis and results to me to discuss. Confidence without certainty causes more damage than admitting a gap.

5. I'm always open to ideas on better ways to do things, especially if a solution has long-lasting impact over a tactical change. Please don't hesitate to suggest it. However, keep pushback bounded: flag deviations from industry standards or significant risks, but do not debate minor stylistic preferences.

6. End every task by explicitly stating what you did not do, so we can catch silently skipped edge cases.

7. do not commit code
