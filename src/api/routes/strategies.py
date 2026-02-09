"""Strategy management API endpoints.

Provides REST access to strategy lifecycle (enable/disable), executor
summary, and recent signal history.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_strategy_executor
from src.api.schemas import ExecutorSummaryResponse, SignalResponse
from src.execution.strategy_executor import StrategyExecutor

router = APIRouter(tags=["Strategies"])

# In-memory recent signal store (ring buffer, max 200 entries).
_recent_signals: deque[Dict[str, Any]] = deque(maxlen=200)


def record_signal(signal_dict: Dict[str, Any]) -> None:
    """Append a signal dict to the in-memory store.

    Intended to be called from the strategy executor processing loop
    or any component that produces signals.

    Args:
        signal_dict: Serialized signal with at minimum keys matching
            SignalResponse fields.
    """
    _recent_signals.append(signal_dict)


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/strategies", response_model=ExecutorSummaryResponse)
def get_strategies(
    executor: StrategyExecutor = Depends(get_strategy_executor),
) -> ExecutorSummaryResponse:
    """Get executor summary including all registered strategy states."""
    summary = executor.get_summary()
    return ExecutorSummaryResponse(**summary)


@router.post("/strategies/{name}/enable")
def enable_strategy(
    name: str,
    executor: StrategyExecutor = Depends(get_strategy_executor),
) -> Dict[str, str]:
    """Enable a registered strategy by name.

    Args:
        name: Strategy name as registered in the executor.

    Returns:
        Confirmation message.

    Raises:
        HTTPException: If the strategy is not found.
    """
    states = executor.get_strategy_states()
    if name not in states:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{name}' not found.",
        )
    executor.enable_strategy(name)
    return {"message": f"Strategy '{name}' enabled."}


@router.post("/strategies/{name}/disable")
def disable_strategy(
    name: str,
    executor: StrategyExecutor = Depends(get_strategy_executor),
) -> Dict[str, str]:
    """Disable a registered strategy by name.

    Args:
        name: Strategy name as registered in the executor.

    Returns:
        Confirmation message.

    Raises:
        HTTPException: If the strategy is not found.
    """
    states = executor.get_strategy_states()
    if name not in states:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{name}' not found.",
        )
    executor.disable_strategy(name)
    return {"message": f"Strategy '{name}' disabled."}


@router.get("/signals", response_model=List[SignalResponse])
def get_signals(
    limit: int = Query(default=50, ge=1, le=200, description="Max signals to return"),
    strategy: Optional[str] = Query(
        default=None, description="Filter by strategy name"
    ),
) -> List[SignalResponse]:
    """Get recent trading signals.

    Signals are stored in-memory (max 200). Optionally filter by
    strategy name.

    Args:
        limit: Maximum number of signals to return.
        strategy: Optional strategy name filter.

    Returns:
        List of recent signals, newest first.
    """
    signals = list(_recent_signals)

    if strategy is not None:
        signals = [s for s in signals if s.get("strategy_name") == strategy]

    # Return newest first, limited
    signals = signals[-limit:]
    signals.reverse()

    result: List[SignalResponse] = []
    for s in signals:
        try:
            result.append(SignalResponse(**s))
        except Exception:
            # Skip malformed entries
            continue

    return result
