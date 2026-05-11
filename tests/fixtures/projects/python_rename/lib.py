"""Library module: target of the rename smoke test.

The function `compute_total` and the class `Calculator` are referenced
from `app.py` and `utils.py`, neither of which the smoke-tester opens
manually. After F2-renaming `compute_total` from inside `app.py`, this
file should auto-open as a dirty tab with the new name applied.
"""
from __future__ import annotations


def compute_total(items: list[float]) -> float:
    """Sum a list of numbers. Smoke-test target #1 — referenced from
    both app.py (twice) and utils.py (once).
    """
    return sum(items)


class Calculator:
    """Simple stateful adder. Smoke-test target #2 — referenced from
    app.py only. Use to verify the popover pre-fills with the class
    name and the rename touches both the definition and the import.
    """

    def __init__(self) -> None:
        self._running = 0.0

    def add(self, value: float) -> float:
        self._running += value
        return self._running

    def reset(self) -> None:
        self._running = 0.0
