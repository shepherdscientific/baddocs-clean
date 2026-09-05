"""
Per-run LLM cost ceiling (US-013).

A CI run must never be able to blow the LLM budget. This module bounds the
expensive part of an incremental run -- the per-leaf unit-doc generator (US-007)
and the per-node folder/project synthesizer (US-008) -- with a single USD
ceiling that is checked *before* every call.

The mechanism is deliberately tiny and side-effect free so it composes with the
injected-callable design used everywhere in this package:

* :class:`CostBudget` accumulates spend across both phases of one run and knows
  the projected cost of the next call.
* :func:`budgeted` wraps any generator/synthesizer so that, before it invokes
  the real (LLM) callable, it charges the budget. If charging the next call
  would push the accumulated cost past the ceiling, it raises
  :class:`BudgetExceededError` *instead of* making the call -- so the run stops
  before the offending LLM call and the ceiling is never exceeded.

The driver (:func:`~baddocs.incremental.incremental_run.run_incremental`)
catches that error, keeps whatever docs already completed (they are persisted as
they are produced), declines to advance ``last_run_sha`` (so the unfinished work
is retried next run), and reports the halt so CI can exit with a clear,
non-zero/warning status.

Pricing is injected, not assumed: ``cost_per_call`` is the projected USD cost of
a single LLM call. Production estimates it from the model's token pricing; tests
pass a fixed per-call price and assert the run halts at exactly the ceiling.
"""

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from ..core.exceptions import ProcessingError

__all__ = [
    'DEFAULT_MAX_COST_USD',
    'DEFAULT_COST_PER_CALL',
    'BudgetExceededError',
    'CostBudget',
    'budgeted',
]

#: Conservative default per-run ceiling (USD). A single push rarely needs more
#: than a dollar of regeneration; CI overrides this via the ``max_cost`` action
#: input when a larger build is expected.
DEFAULT_MAX_COST_USD = 1.0

#: Conservative default projected cost of one LLM call (USD), used when a caller
#: enables a budget without supplying its own per-call price.
DEFAULT_COST_PER_CALL = 0.01

F = TypeVar('F', bound=Callable[..., Any])


class BudgetExceededError(ProcessingError):
    """
    Raised before an LLM call when charging it would exceed the cost ceiling.

    Carries the spend *so far* (which never exceeds the ceiling, because the
    charge that would have exceeded it was refused), the configured ceiling, and
    the projected cost of the refused call, so the driver can log a clear
    message.
    """

    def __init__(self, spent: float, ceiling: float, next_call: float) -> None:
        """Record the spend, ceiling, and refused-call cost for reporting."""
        self.spent = spent
        self.ceiling = ceiling
        self.next_call = next_call
        super().__init__(
            f"per-run cost ceiling ${ceiling:.2f} reached: ${spent:.2f} spent, "
            f"next call (${next_call:.2f}) refused before exceeding the budget"
        )


@dataclass
class CostBudget:
    """
    A mutable per-run spend accumulator bounded by a USD ceiling.

    One instance is shared across both work phases of a run so unit regeneration
    and ancestor re-synthesis draw from the same budget. ``spent`` is the
    accumulated cost of calls that were actually made; it is only ever advanced
    by a :meth:`charge` that stays within the ceiling, so it never exceeds
    ``max_cost_usd``.
    """

    max_cost_usd: float
    cost_per_call: float = DEFAULT_COST_PER_CALL
    spent: float = 0.0

    def remaining(self) -> float:
        """USD left before the ceiling (clamped at zero)."""
        return max(0.0, self.max_cost_usd - self.spent)

    def would_exceed(self, amount: float) -> bool:
        """True iff spending ``amount`` more would push past the ceiling."""
        return self.spent + amount > self.max_cost_usd

    def charge(self, amount: float = None) -> None:  # type: ignore[assignment]
        """
        Charge the next call against the budget, refusing it if it would exceed.

        Checked *before* the call is made: if the projected cost would push the
        accumulated spend past the ceiling, raises :class:`BudgetExceededError`
        and leaves ``spent`` unchanged (so the run can stop before the call and
        never exceed the budget). Otherwise advances ``spent`` and returns.

        Args:
            amount: Projected USD cost of this call; defaults to
                ``cost_per_call``.
        """
        cost = self.cost_per_call if amount is None else amount
        if self.would_exceed(cost):
            raise BudgetExceededError(self.spent, self.max_cost_usd, cost)
        self.spent += cost


def budgeted(fn: F, budget: CostBudget) -> F:
    """
    Wrap an LLM callable so each invocation is charged against ``budget`` first.

    The returned callable has the same signature as ``fn`` (it forwards all
    arguments), so it drops in for either the unit-doc ``generator`` or the
    folder/project ``synthesizer``. Before delegating, it calls
    :meth:`CostBudget.charge`; if the budget is exhausted that raises
    :class:`BudgetExceededError` and ``fn`` is never invoked -- the LLM call is
    skipped, not merely discarded.

    Args:
        fn: The generator/synthesizer to bound.
        budget: The shared per-run :class:`CostBudget`.

    Returns:
        A cost-bounded wrapper around ``fn``.
    """

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        budget.charge()
        return fn(*args, **kwargs)

    return wrapped  # type: ignore[return-value]
