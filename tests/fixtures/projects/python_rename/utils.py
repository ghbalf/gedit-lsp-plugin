"""Auxiliary module — second cross-file usage of compute_total.

This file is closed when the smoke-tester triggers F2 on `compute_total`
in app.py. After the rename, this file should auto-open as a dirty tab
with the new name applied to both the import and the function body
reference.
"""
from __future__ import annotations

from lib import compute_total


def running_average(items: list[float]) -> float:
    """Mean of `items`, or 0 for an empty list. Uses compute_total to
    sum so the rename touches both the import line and this body.
    """
    if not items:
        return 0.0
    return compute_total(items) / len(items)
