"""trading-loop: the self-learning loop for a paper-trading strategy.

Orchestrates the trade-journal, autoresearch and risk-manager skills into one
closed monthly cadence: hypothesis -> paper-trade -> measure -> autopsy ->
adjust (one variable) -> gate (keep/revert) -> re-run. Cycle state persists to
a JSON file so the loop has memory across runs.
"""

from .engine import (
    DEFAULT_CONFIG,
    apply_config,
    compute_metrics,
    loss_autopsy,
    propose_change,
    run_cycle,
    new_state,
    load_state,
    save_state,
    load_trades,
)

__all__ = [
    "DEFAULT_CONFIG",
    "apply_config",
    "compute_metrics",
    "loss_autopsy",
    "propose_change",
    "run_cycle",
    "new_state",
    "load_state",
    "save_state",
    "load_trades",
]
