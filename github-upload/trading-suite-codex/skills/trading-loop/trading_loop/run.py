"""CLI for the trading-loop self-learning cycle.

Examples
--------
# 1. Initialise the loop with a falsifiable hypothesis + the metric that proves it
python3 -m trading_loop.run init \
    --state cycle_state.json \
    --hypothesis "London-session breakout has positive expectancy after a discipline filter" \
    --metric expectancy_R

# 2. Run one cycle over a paper-trade window (a trade log CSV)
python3 -m trading_loop.run run --state cycle_state.json --trades window1.csv

# 3. Inspect the history
python3 -m trading_loop.run show --state cycle_state.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .engine import (
    new_state,
    load_state,
    save_state,
    load_trades,
    run_cycle,
    HIGHER_IS_BETTER,
)


def _fmt_config(cfg: dict) -> str:
    parts = []
    for k, v in cfg.items():
        parts.append(f"{k}={v}")
    return ", ".join(parts)


def cmd_init(args: argparse.Namespace) -> int:
    if os.path.exists(args.state) and not args.force:
        print(f"refusing to overwrite existing state: {args.state} (use --force)")
        return 1
    state = new_state(args.hypothesis, primary_metric=args.metric)
    save_state(state, args.state)
    print(f"initialised loop -> {args.state}")
    print(f"  hypothesis     : {state['hypothesis']}")
    print(f"  primary metric : {state['primary_metric']} (higher is better)")
    print(f"  baseline config: {_fmt_config(state['accepted_config'])}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not os.path.exists(args.state):
        print(f"no state file at {args.state}; run `init` first.")
        return 1
    state = load_state(args.state)
    trades = load_trades(args.trades)
    if not trades:
        print(f"no measurable trades in {args.trades}")
        return 1

    rec = run_cycle(state, trades)
    save_state(state, args.state)

    m = rec["metrics"]
    g = rec["gate"]
    print(f"=== cycle {rec['cycle']} ===")
    print(f"hypothesis : {rec['hypothesis']}")
    print(
        f"window     : {rec['window_trades']} logged / {rec['taken_trades']} taken under tested config"
    )
    print(f"config     : {_fmt_config(rec['config_tested'])}")
    print("metrics    :")
    print(
        f"  expectancy {m['expectancy_R']:+.3f}R | win {m['win_rate']*100:.1f}% | "
        f"PF {m['profit_factor']:.2f} | maxConsecLoss {m['max_consecutive_losses']} | "
        f"Sharpe {m['sharpe']:.2f} | total {m['total_R']:+.2f}R"
    )
    print(f"GATE       : {g['decision'].upper()}", end="")
    if g["compared"]:
        c = g["compared"]
        print(
            f"  ({c['metric']} {c['this']:+.3f} vs {c['prev']:+.3f} -> "
            f"{'improved' if c['improved'] else 'no improvement'})"
        )
    else:
        print("  (baseline — sets the benchmark)")
    if rec["autopsy"]["top_findings"]:
        print("autopsy    :")
        for f in rec["autopsy"]["top_findings"]:
            print(
                f"  [{f['category']}] {f['observation']} (recoverable {f['lost_R']:.2f}R)"
            )
    ch = rec["change_proposed"]
    if ch:
        print(f"NEXT CHANGE: {ch['variable']}: {ch['from']} -> {ch['to']}")
        print(f"  rule      : {ch['rule_change']}")
        print("  (one variable only — re-run next window to keep or revert)")
    else:
        print(
            "NEXT CHANGE: none — strategy is clean or out of safe single-variable moves"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    if not os.path.exists(args.state):
        print(f"no state file at {args.state}")
        return 1
    state = load_state(args.state)
    if args.json:
        print(json.dumps(state, indent=2))
        return 0
    print(f"loop: {state['hypothesis']}")
    print(f"primary metric: {state['primary_metric']}")
    print(f"reverted (locked) variables: {state.get('reverted_locks') or 'none'}")
    print(f"current accepted config: {_fmt_config(state['accepted_config'])}")
    print("-" * 72)
    for rec in state["cycles"]:
        g = rec["gate"]["decision"]
        m = rec["metrics"]
        ch = rec["change_proposed"]
        line = (
            f"cycle {rec['cycle']:>2} | {g:<8} | "
            f"{state['primary_metric']}={m[state['primary_metric']]:+.3f} | "
            f"PF {m['profit_factor']:.2f} | taken {rec['taken_trades']}"
        )
        print(line)
        if ch:
            print(
                f"           -> tried next: {ch['variable']}: {ch['from']} -> {ch['to']}"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trading_loop", description="Self-learning paper-trading loop."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="create a new cycle-state file")
    pi.add_argument("--state", default="cycle_state.json")
    pi.add_argument("--hypothesis", required=True, help="falsifiable edge to test")
    pi.add_argument(
        "--metric", default="expectancy_R", choices=sorted(HIGHER_IS_BETTER)
    )
    pi.add_argument("--force", action="store_true", help="overwrite existing state")
    pi.set_defaults(func=cmd_init)

    pr = sub.add_parser("run", help="run one cycle over a trade-log window")
    pr.add_argument("--state", default="cycle_state.json")
    pr.add_argument("--trades", required=True, help="CSV trade log for this window")
    pr.set_defaults(func=cmd_run)

    ps = sub.add_parser("show", help="print cycle history")
    ps.add_argument("--state", default="cycle_state.json")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_show)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
