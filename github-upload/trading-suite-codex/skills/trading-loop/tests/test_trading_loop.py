"""Verification suite for the trading-loop cycle.

Asserts the closed-loop *invariants*, not magic performance numbers:
  1. One full cycle on a synthetic window writes a cycle-state file.
  2. Cycle 1 is a 'baseline' that sets the benchmark and proposes exactly one
     single-variable change (the autopsy's biggest leak).
  3. A second window runs that change and the gate emits a keep/revert decision,
     persisted to disk.
  4. The one-variable-at-a-time discipline holds: at most one config key differs
     between the tested config and the accepted config each cycle.
"""

import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_loop.engine import (  # noqa: E402
    new_state,
    run_cycle,
    save_state,
    load_state,
    apply_config,
    compute_metrics,
    loss_autopsy,
    propose_change,
    DEFAULT_CONFIG,
)


def _trade(r, session="london", setup="breakout", rc=True):
    return {"session": session, "setup": setup, "rule_compliance": rc, "r_multiple": r}


def _window_with_discipline_leak():
    """Disciplined trades win; rule-breakers lose hard. The autopsy's biggest
    leak is therefore the discipline filter (require_rule_compliance)."""
    trades = []
    # 14 disciplined winners/small losers — net positive
    for _ in range(10):
        trades.append(_trade(+1.5, rc=True))
    for _ in range(4):
        trades.append(_trade(-1.0, rc=True))
    # 8 undisciplined blow-ups — net very negative
    for _ in range(8):
        trades.append(_trade(-2.5, rc=False))
    return trades


def _diff_keys(a, b):
    return [k for k in a if a[k] != b[k]]


def test_one_cycle_writes_state_with_decision(tmp_path):
    state = new_state(
        "Disciplined London breakouts have positive expectancy",
        primary_metric="expectancy_R",
    )
    statefile = tmp_path / "cycle_state.json"

    # --- cycle 1: baseline ---
    w1 = _window_with_discipline_leak()
    rec1 = run_cycle(state, w1)
    save_state(state, str(statefile))

    assert statefile.exists()
    assert rec1["gate"]["decision"] == "baseline"
    assert rec1["change_proposed"] is not None
    # autopsy should target the discipline leak first
    assert rec1["change_proposed"]["variable"] == "require_rule_compliance"
    assert rec1["change_proposed"]["to"] is True

    # one-variable discipline: tested vs accepted-after differ by <=1 key
    assert len(_diff_keys(rec1["config_tested"], rec1["accepted_config_after"])) <= 1

    # --- cycle 2: run the proposed change on a fresh window, gate fires ---
    reloaded = load_state(str(statefile))
    w2 = _window_with_discipline_leak()  # same edge -> filter should help -> keep
    rec2 = run_cycle(reloaded, w2)
    save_state(reloaded, str(statefile))

    assert rec2["gate"]["decision"] in {"keep", "revert"}
    assert rec2["gate"]["compared"] is not None
    # the tested config in cycle 2 must carry the one change from cycle 1
    assert rec2["config_tested"]["require_rule_compliance"] is True

    # persisted file round-trips and records both cycles + the decision
    on_disk = json.loads(statefile.read_text())
    assert len(on_disk["cycles"]) == 2
    assert on_disk["cycles"][1]["gate"]["decision"] in {"keep", "revert"}


def test_keep_when_filter_improves_expectancy(tmp_path):
    """With a clear discipline leak, applying the filter must improve expectancy
    -> the gate KEEPS it and folds it into the accepted config."""
    state = new_state("edge", primary_metric="expectancy_R")
    w = _window_with_discipline_leak()
    run_cycle(state, w)  # baseline, proposes require_rule_compliance=True
    rec2 = run_cycle(state, _window_with_discipline_leak())

    assert rec2["gate"]["decision"] == "keep"
    assert rec2["gate"]["compared"]["improved"] is True
    assert state["accepted_config"]["require_rule_compliance"] is True


def test_revert_locks_the_variable(tmp_path):
    """If the tested change does NOT beat the benchmark, the gate reverts and
    locks that variable out of future proposals."""
    # window where rule-breakers actually do FINE -> filtering them won't help
    good = [_trade(+1.0, rc=True) for _ in range(6)] + [
        _trade(+1.0, rc=False) for _ in range(6)
    ]
    state = new_state("edge", primary_metric="expectancy_R")
    run_cycle(
        state, good
    )  # baseline. all positive; autopsy may still propose something

    # Force a pending change that cannot help, then run a non-improving window.
    state["pending_change"] = {
        "variable": "require_rule_compliance",
        "from": False,
        "to": True,
        "category": "psychology",
        "rationale": "test",
        "rule_change": "test",
    }
    state["active_config"] = copy.deepcopy(state["accepted_config"])
    state["active_config"]["require_rule_compliance"] = True
    state["benchmark"] = {"metric": "expectancy_R", "value": 5.0}  # impossible to beat

    rec = run_cycle(state, good)
    assert rec["gate"]["decision"] == "revert"
    assert "require_rule_compliance" in state["reverted_locks"]
    # accepted config was NOT mutated by the failed change
    assert state["accepted_config"]["require_rule_compliance"] is False


def test_metrics_sanity():
    eff = apply_config(
        [_trade(+2.0), _trade(-1.0), _trade(+1.0), _trade(-1.0), _trade(-1.0)],
        DEFAULT_CONFIG,
    )
    m = compute_metrics(eff)
    assert m["n_trades"] == 5
    assert m["win_rate"] == pytest.approx(0.4)
    assert m["expectancy_R"] == pytest.approx(0.0)
    assert m["max_consecutive_losses"] == 2
    assert m["profit_factor"] == pytest.approx(1.0)


def test_one_variable_rule_holds_every_cycle():
    """Across several cycles, no cycle ever changes more than one config key."""
    state = new_state("edge", primary_metric="expectancy_R")
    for _ in range(5):
        rec = run_cycle(state, _window_with_discipline_leak())
        before = rec["config_tested"]
        after = rec["accepted_config_after"]
        assert len(_diff_keys(before, after)) <= 1
