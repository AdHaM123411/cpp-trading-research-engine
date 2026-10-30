"""Engine for the trading-loop self-learning cycle.

The loop drives a strategy over successive paper-trade windows. Each window is a
trade log in the trade-journal schema. One run = one cycle:

    measure -> loss-autopsy + pattern -> gate (keep/revert) -> adjust (one var)

Memory lives in a JSON cycle-state file. The hard discipline rule — change ONE
variable at a time — is enforced in `run_cycle`: every cycle applies at most one
config key change, and that change is recorded as an explicit diff so the next
cycle can keep or revert it on the evidence.

License-clean: numpy + Python stdlib only.
"""

from __future__ import annotations

import csv
import copy
import json
import math
from typing import Any, Dict, List, Optional

import numpy as np

# Metrics where a HIGHER value is better. The gate uses this to decide whether a
# change improved the strategy. (max_consecutive_losses is excluded — it is a
# guardrail, not the optimisation target.)
HIGHER_IS_BETTER = {"expectancy_R", "profit_factor", "sharpe", "win_rate"}

# Floating-point slack so a metric must genuinely improve, not just tie.
EPS = 1e-9

# Baseline strategy/risk config. Every key is a single lever the loop may move.
#   risk_per_trade_pct        : account % risked per trade (risk-manager sizing)
#   require_rule_compliance   : only count trades that followed the plan
#   allowed_sessions          : None = all; else a whitelist of sessions
#   allowed_setups            : None = all; else a whitelist of setups
#   max_loss_R                : None = no cap; else cap each loss at -max_loss_R
#                               (models a hard stop / max-loss rule)
DEFAULT_CONFIG: Dict[str, Any] = {
    "risk_per_trade_pct": 1.0,
    "require_rule_compliance": False,
    "allowed_sessions": None,
    "allowed_setups": None,
    "max_loss_R": None,
}

_TRUE = {"1", "true", "t", "yes", "y", "followed", "compliant", "pass"}
_FALSE = {"0", "false", "f", "no", "n", "broke", "violated", "fail", ""}


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #
def _to_bool(v: Any, default: bool = True) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return default


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _r_multiple(t: Dict[str, Any]) -> Optional[float]:
    """R multiple = realised reward / planned risk. Use the supplied value if
    present, else derive it from entry/stop/exit/direction (trade-journal fields).
    """
    r = _to_float(t.get("r_multiple"))
    if r is not None:
        return r
    entry = _to_float(t.get("entry"))
    stop = _to_float(t.get("stop"))
    exit_ = _to_float(t.get("exit"))
    if entry is None or stop is None or exit_ is None:
        return None
    risk = abs(entry - stop)
    if risk == 0:
        return None
    direction = str(t.get("direction", "long")).strip().lower()
    sign = -1.0 if direction in {"short", "sell", "s"} else 1.0
    return ((exit_ - entry) * sign) / risk


def normalise_trade(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce one raw trade dict into the internal schema."""
    r = _r_multiple(raw)
    return {
        "date": raw.get("date"),
        "asset": raw.get("asset"),
        "direction": raw.get("direction"),
        "session": (
            str(raw.get("session")).strip()
            if raw.get("session") not in (None, "")
            else None
        ),
        "setup": (
            str(raw.get("setup")).strip()
            if raw.get("setup") not in (None, "")
            else None
        ),
        "emotional_state": raw.get("emotional_state"),
        # Default UNKNOWN compliance to True so we don't silently delete trades
        # that simply didn't record the field.
        "rule_compliance": _to_bool(raw.get("rule_compliance"), default=True),
        "r_multiple": r,
    }


def load_trades(path: str) -> List[Dict[str, Any]]:
    """Load a trade log CSV into normalised trade dicts. Rows with no derivable
    R multiple are skipped (they can't be measured)."""
    out: List[Dict[str, Any]] = []
    with open(path, newline="") as fh:
        for raw in csv.DictReader(fh):
            t = normalise_trade(raw)
            if t["r_multiple"] is not None:
                out.append(t)
    return out


# --------------------------------------------------------------------------- #
# Apply config -> effective trades
# --------------------------------------------------------------------------- #
def apply_config(
    trades: List[Dict[str, Any]], config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Project a raw window of trades through the active config to get the trades
    the strategy would actually have TAKEN, with risk scaling and loss caps
    applied. Filters model 'don't take this kind of trade'; max_loss_R models a
    tighter hard stop.
    """
    risk = float(config.get("risk_per_trade_pct", 1.0))
    require_rc = bool(config.get("require_rule_compliance", False))
    sessions = config.get("allowed_sessions")
    setups = config.get("allowed_setups")
    cap = config.get("max_loss_R")

    eff: List[Dict[str, Any]] = []
    for t in trades:
        if require_rc and not t["rule_compliance"]:
            continue
        if sessions is not None and t["session"] not in sessions:
            continue
        if setups is not None and t["setup"] not in setups:
            continue
        r = float(t["r_multiple"])
        if cap is not None and r < -abs(cap):
            r = -abs(cap)
        e = dict(t)
        e["r_multiple"] = r
        e["risk_pct"] = risk
        e["pnl_pct"] = r * risk
        eff.append(e)
    return eff


# --------------------------------------------------------------------------- #
# Measure
# --------------------------------------------------------------------------- #
def _max_consecutive_losses(rs: List[float]) -> int:
    run = best = 0
    for r in rs:
        if r < 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def compute_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Period tear-sheet from the journal: win rate, expectancy (avg R),
    profit factor, max consecutive losses, per-trade Sharpe."""
    rs = [float(t["r_multiple"]) for t in trades]
    n = len(rs)
    if n == 0:
        return {
            "n_trades": 0,
            "win_rate": 0.0,
            "expectancy_R": 0.0,
            "avg_win_R": 0.0,
            "avg_loss_R": 0.0,
            "profit_factor": 0.0,
            "max_consecutive_losses": 0,
            "sharpe": 0.0,
            "total_R": 0.0,
        }
    arr = np.asarray(rs, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    sharpe = float(arr.mean() / sd) if sd > 0 else 0.0
    return {
        "n_trades": n,
        "win_rate": float(len(wins) / n),
        "expectancy_R": float(arr.mean()),
        "avg_win_R": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_R": float(losses.mean()) if len(losses) else 0.0,
        # profit factor: inf-safe (no losses -> large but finite sentinel)
        "profit_factor": (
            float(gross_win / gross_loss)
            if gross_loss > 0
            else (999.0 if gross_win > 0 else 0.0)
        ),
        "max_consecutive_losses": _max_consecutive_losses(rs),
        "sharpe": round(sharpe, 4),
        "total_R": float(arr.sum()),
    }


# --------------------------------------------------------------------------- #
# Loss autopsy + pattern analyser  (mirrors trade-journal categories)
# --------------------------------------------------------------------------- #
def _group_expectancy(
    trades: List[Dict[str, Any]], key: str
) -> Dict[Any, Dict[str, float]]:
    groups: Dict[Any, List[float]] = {}
    for t in trades:
        g = t.get(key)
        if g is None:
            continue
        groups.setdefault(g, []).append(float(t["r_multiple"]))
    out = {}
    for g, rs in groups.items():
        arr = np.asarray(rs, dtype=float)
        out[g] = {
            "n": len(rs),
            "expectancy_R": float(arr.mean()),
            "total_R": float(arr.sum()),
        }
    return out


def loss_autopsy(
    trades: List[Dict[str, Any]], config: Dict[str, Any]
) -> Dict[str, Any]:
    """Find the biggest cause of lost R and emit specific, single-variable rule
    changes. Categories follow the trade-journal Loss Autopsy: psychology,
    timing, setup quality, risk management, market context.

    Returns {findings, patterns, pattern_note}. Findings are ranked by lost_R
    (the R the change would have recovered) so the loop fixes the worst leak.
    """
    findings: List[Dict[str, Any]] = []
    losers = [t for t in trades if float(t["r_multiple"]) < 0]

    # 1. Psychology / discipline — losses on trades that broke the plan.
    if not config.get("require_rule_compliance", False):
        broke = [t for t in losers if not t["rule_compliance"]]
        lost = sum(-float(t["r_multiple"]) for t in broke)
        if broke and lost > 0:
            findings.append(
                {
                    "category": "psychology",
                    "observation": f"{len(broke)} losing trades broke the plan, costing {lost:.2f}R",
                    "lost_R": lost,
                    "variable": "require_rule_compliance",
                    "to": True,
                    "rule_change": "Only take trades that pass the pre-trade checklist (rule_compliance=True).",
                }
            )

    # 2. Timing — worst session by expectancy. Restrict to non-negative sessions.
    sess = _group_expectancy(trades, "session")
    if len(sess) >= 2:
        worst = min(sess, key=lambda g: sess[g]["expectancy_R"])
        if sess[worst]["expectancy_R"] < 0:
            keep = sorted([g for g, s in sess.items() if s["expectancy_R"] >= 0])
            if keep and keep != sorted(config.get("allowed_sessions") or sess.keys()):
                findings.append(
                    {
                        "category": "timing",
                        "observation": f"'{worst}' session has negative expectancy "
                        f"({sess[worst]['expectancy_R']:.2f}R over {sess[worst]['n']} trades)",
                        "lost_R": -sess[worst]["total_R"],
                        "variable": "allowed_sessions",
                        "to": keep,
                        "rule_change": f"Stop trading the '{worst}' session; restrict to {keep}.",
                    }
                )

    # 3. Setup quality — worst setup by expectancy.
    setp = _group_expectancy(trades, "setup")
    if len(setp) >= 2:
        worst = min(setp, key=lambda g: setp[g]["expectancy_R"])
        if setp[worst]["expectancy_R"] < 0:
            keep = sorted([g for g, s in setp.items() if s["expectancy_R"] >= 0])
            if keep and keep != sorted(config.get("allowed_setups") or setp.keys()):
                findings.append(
                    {
                        "category": "setup_quality",
                        "observation": f"'{worst}' setup has negative expectancy "
                        f"({setp[worst]['expectancy_R']:.2f}R over {setp[worst]['n']} trades)",
                        "lost_R": -setp[worst]["total_R"],
                        "variable": "allowed_setups",
                        "to": keep,
                        "rule_change": f"Stop trading the '{worst}' setup; restrict to {keep}.",
                    }
                )

    # 4. Risk management — losses that ran past the planned 1R stop.
    if config.get("max_loss_R") is None:
        excess = sum(max(0.0, -float(t["r_multiple"]) - 1.0) for t in losers)
        if excess > 0:
            findings.append(
                {
                    "category": "risk_management",
                    "observation": f"Losses ran past -1R, bleeding {excess:.2f}R of avoidable damage",
                    "lost_R": excess,
                    "variable": "max_loss_R",
                    "to": 1.0,
                    "rule_change": "Hard-cap every loss at -1R (honour the stop).",
                }
            )

    # 5. Market context — defensive fallback when consecutive losses spike.
    rs = [float(t["r_multiple"]) for t in trades]
    if (
        _max_consecutive_losses(rs) >= 5
        and float(config.get("risk_per_trade_pct", 1.0)) > 0.5
    ):
        findings.append(
            {
                "category": "market_context",
                "observation": f"{_max_consecutive_losses(rs)} losses in a row — drawdown / ruin risk",
                "lost_R": 0.5,  # low priority: protects capital, not expectancy
                "variable": "risk_per_trade_pct",
                "to": round(float(config.get("risk_per_trade_pct", 1.0)) / 2.0, 4),
                "rule_change": "Halve risk-per-trade until the streak breaks (circuit breaker).",
            }
        )

    findings.sort(key=lambda f: f["lost_R"], reverse=True)

    patterns = {
        "by_session": sess,
        "by_setup": setp,
    }
    pattern_note = (
        "Pattern Analyser needs 20+ trades for stable read (trade-journal rule); "
        f"this window has {len(trades)}."
    )
    return {"findings": findings, "patterns": patterns, "pattern_note": pattern_note}


# --------------------------------------------------------------------------- #
# Adjust — pick ONE variable to change
# --------------------------------------------------------------------------- #
def propose_change(
    autopsy: Dict[str, Any], config: Dict[str, Any], reverted_locks: List[str]
) -> Optional[Dict[str, Any]]:
    """Pick the single highest-impact change that (a) actually changes the
    config and (b) isn't a variable we already tried and reverted. Returns one
    change dict or None when the strategy is clean / out of safe moves."""
    for f in autopsy["findings"]:
        var = f["variable"]
        if var in reverted_locks:
            continue
        current = config.get(var)
        target = f["to"]
        # skip no-ops (already at target, incl. list equality)
        if isinstance(target, list) and isinstance(current, list):
            if sorted(current) == sorted(target):
                continue
        elif current == target:
            continue
        return {
            "variable": var,
            "from": current,
            "to": target,
            "category": f["category"],
            "rationale": f["observation"],
            "rule_change": f["rule_change"],
        }
    return None


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def new_state(
    hypothesis: str,
    primary_metric: str = "expectancy_R",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if primary_metric not in HIGHER_IS_BETTER:
        raise ValueError(
            f"primary_metric must be one of {sorted(HIGHER_IS_BETTER)} (higher-is-better)."
        )
    cfg = copy.deepcopy(config) if config else copy.deepcopy(DEFAULT_CONFIG)
    return {
        "schema": "trading-loop/1",
        "hypothesis": hypothesis,
        "primary_metric": primary_metric,
        "accepted_config": copy.deepcopy(cfg),  # currently-trusted config
        "active_config": copy.deepcopy(cfg),  # accepted + pending change (this window)
        "pending_change": None,  # the change being tested this window
        "benchmark": None,  # {metric, value} of accepted config
        "reverted_locks": [],  # variables tried and rejected
        "cycles": [],
    }


def load_state(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        return json.load(fh)


def save_state(state: Dict[str, Any], path: str) -> None:
    with open(path, "w") as fh:
        json.dump(state, fh, indent=2, default=_json_default)
        fh.write("\n")


def _json_default(o: Any):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    raise TypeError(f"not serialisable: {type(o)}")


# --------------------------------------------------------------------------- #
# Run one cycle  (the closed loop, with the keep/revert gate)
# --------------------------------------------------------------------------- #
def run_cycle(state: Dict[str, Any], trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run one full cycle on one paper-trade window and append it to state.

    Gate logic:
      * cycle 1 has no pending change -> decision 'baseline', sets the benchmark.
      * later cycles test the pending change against the benchmark:
          improved -> 'keep'  (change folds into accepted_config, benchmark moves)
          else     -> 'revert'(accepted_config unchanged, variable locked out)
      * then ONE new change is proposed on top of the accepted config.
    """
    primary = state["primary_metric"]
    cfg_tested = copy.deepcopy(state["active_config"])

    eff = apply_config(trades, cfg_tested)
    metrics = compute_metrics(eff)
    autopsy = loss_autopsy(eff, cfg_tested)
    pending = state.get("pending_change")

    # ---- gate ----
    if pending is None:
        decision = "baseline"
        compared = None
        state["accepted_config"] = copy.deepcopy(cfg_tested)
        state["benchmark"] = {"metric": primary, "value": metrics[primary]}
    else:
        prev_val = state["benchmark"]["value"]
        this_val = metrics[primary]
        improved = this_val > prev_val + EPS  # higher-is-better metrics only
        compared = {
            "metric": primary,
            "this": this_val,
            "prev": prev_val,
            "improved": improved,
        }
        if improved:
            decision = "keep"
            state["accepted_config"] = copy.deepcopy(cfg_tested)  # includes the change
            state["benchmark"] = {"metric": primary, "value": this_val}
        else:
            decision = "revert"
            state.setdefault("reverted_locks", [])
            if pending["variable"] not in state["reverted_locks"]:
                state["reverted_locks"].append(pending["variable"])
            # accepted_config and benchmark stay as they were

    # ---- adjust: propose ONE new variable change on the accepted config ----
    change = propose_change(
        autopsy, state["accepted_config"], state.get("reverted_locks", [])
    )
    new_active = copy.deepcopy(state["accepted_config"])
    if change is not None:
        new_active[change["variable"]] = change["to"]
    state["pending_change"] = change
    state["active_config"] = new_active

    record = {
        "cycle": len(state["cycles"]) + 1,
        "hypothesis": state["hypothesis"],
        "window_trades": len(trades),
        "taken_trades": metrics["n_trades"],
        "config_tested": cfg_tested,
        "metrics": metrics,
        "gate": {"decision": decision, "compared": compared},
        "autopsy": {
            "top_findings": autopsy["findings"][:3],
            "pattern_note": autopsy["pattern_note"],
        },
        "change_proposed": change,  # applied to NEXT window (one variable)
        "accepted_config_after": copy.deepcopy(state["accepted_config"]),
    }
    state["cycles"].append(record)
    return record
