"""Smoke-test entry point — open this file in gedit before pressing F2.

Two rename targets:

  * `compute_total` — imported from lib.py, called twice below. F2 on any
    occurrence (the import, either call) should rename across this file,
    lib.py (closed → opens as dirty tab), and utils.py (closed → opens
    as dirty tab). Expected statusbar: "LSP: renamed 3 file(s)".

  * `Calculator` — imported from lib.py, instantiated once. F2 should
    rename across this file and lib.py only. Expected statusbar:
    "LSP: renamed 2 file(s)".

Negative cases worth trying (pylsp + jedi defaults — `pylsp-rope` not
installed):

  * Cursor on `print` (a stdlib builtin): F2 → popover pre-fills with
    `print` (jedi happily accepts builtins). Press Escape to dismiss.
    Caveat: committing a new name here would rename the in-file
    `print(...)` calls only. With `pylsp-rope` instead of jedi this
    would be refused server-side ("LSP: cannot rename symbol here").
  * Cursor in a string literal or on whitespace (no identifier): F2 →
    statusbar "LSP: cannot rename symbol here", no popover.
  * Press F2, then Escape: popover dismisses, no request fired.
  * Press F2, click outside the popover: popover dismisses (focus-out),
    no request fired.

Multi-file behaviour: jedi DOES walk the project filesystem and
includes closed files in the WorkspaceEdit. If you see "LSP: renamed
1 file(s)" on a re-test, the cause is stale buffer state: the dirty
tabs from the previous rename were closed without saving, so pylsp
reverted to the on-disk content (old name) for those files while
THIS buffer still has the new name. Cure between scenarios:
`git restore tests/fixtures/projects/python_rename/` and File →
Revert in every open tab so disk + buffer + pylsp all agree.
"""
from __future__ import annotations

from lib import Calculator, compute_total
from utils import running_average


def report(items: list[float]) -> None:
    total = compute_total(items)
    average = running_average(items)
    print(f"total={total} average={average}")


def stateful_demo(values: list[float]) -> float:
    calc = Calculator()
    for v in values:
        calc.add(v)
    # Verify compute_total still works alongside the class
    return compute_total(values)


if __name__ == "__main__":
    report([1.0, 2.0, 3.0, 4.0])
    print(stateful_demo([10.0, 20.0, 30.0]))
