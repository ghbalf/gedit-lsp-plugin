"""Pure helpers for `textDocument/codeAction` responses.

GTK-free; importable from both controller and popover model so neither
needs polymorphic Command/CodeAction dispatch. The LSP spec lets a
codeAction response be a mixed array of `Command` and `CodeAction`
shapes; `normalize_action` coerces both into one TypedDict.
"""
from __future__ import annotations

from typing import Any, TypedDict


class NormalizedAction(TypedDict):
    title: str
    kind: str
    edit: dict[str, Any] | None
    command: dict[str, Any] | None
    data: Any
    is_preferred: bool
    disabled_reason: str | None


def normalize_action(item: Any) -> NormalizedAction | None:
    """Coerce a raw codeAction response item into a NormalizedAction,
    or return None if it's malformed (no title, or neither edit nor
    command nor data — the LSP signal that the server expects resolve).

    Accepts both the legacy `Command` shape (`{title, command,
    arguments}`) and the modern `CodeAction` shape (`{title, kind,
    edit, command, data, isPreferred, disabled}`).
    """
    if not isinstance(item, dict):
        return None
    title = item.get("title")
    if not isinstance(title, str):
        return None

    # Command shape: has a `command` field that is a *string* (the
    # command name). In CodeAction shape, `command` is a *dict*
    # (`{title, command, arguments}`) — distinguish by type.
    if isinstance(item.get("command"), str):
        return NormalizedAction(
            title=title,
            kind="",
            edit=None,
            command={
                "title": title,
                "command": item["command"],
                "arguments": item.get("arguments", []),
            },
            data=None,
            is_preferred=False,
            disabled_reason=None,
        )

    # CodeAction shape.
    cmd = item.get("command")
    if cmd is not None and not isinstance(cmd, dict):
        cmd = None

    disabled = item.get("disabled")
    disabled_reason: str | None = None
    if isinstance(disabled, dict) and isinstance(disabled.get("reason"), str):
        disabled_reason = disabled["reason"]

    edit = item.get("edit")
    if edit is not None and not isinstance(edit, dict):
        edit = None

    data = item.get("data")

    # An action with no edit, no command, and no data is unactionable
    # (per spec, server must provide at least one of these to be
    # meaningful). Treat as malformed.
    if edit is None and cmd is None and data is None:
        return None

    return NormalizedAction(
        title=title,
        kind=str(item.get("kind", "")),
        edit=edit,
        command=cmd,
        data=data,
        is_preferred=bool(item.get("isPreferred", False)),
        disabled_reason=disabled_reason,
    )


_KIND_ORDER = ("quickfix", "refactor", "source")


def group_by_kind(
    actions: list[NormalizedAction],
) -> list[tuple[str, list[NormalizedAction]]]:
    """Group actions by top-level CodeActionKind prefix.

    Groups: `quickfix` → `refactor.*` → `source.*` → `unknown` (any
    other or empty kind). Server-supplied order is preserved within
    each group.
    """
    buckets: dict[str, list[NormalizedAction]] = {
        name: [] for name in _KIND_ORDER
    }
    buckets["unknown"] = []
    for action in actions:
        kind = action["kind"]
        # Top-level prefix: "refactor.extract" → "refactor"
        top = kind.split(".", 1)[0] if kind else ""
        if top in buckets and top != "unknown":
            buckets[top].append(action)
        else:
            buckets["unknown"].append(action)
    return [(name, buckets[name]) for name in (*_KIND_ORDER, "unknown") if buckets[name]]


def needs_resolve(action: NormalizedAction) -> bool:
    """True if the action has neither `edit` nor `command` — server
    expects a codeAction/resolve round-trip before execution.

    `data` alone doesn't make the action executable, but its presence
    (or absence) is irrelevant to whether resolve is needed: the LSP
    spec keys resolve-required on missing edit AND missing command,
    not on the data field.
    """
    return action["edit"] is None and action["command"] is None


def extract_diag_context(
    diagnostics: list[dict[str, Any]],
    cursor_line: int,
    cursor_char: int,
) -> list[dict[str, Any]]:
    """Filter diagnostics whose range contains the cursor position.

    Used to populate `codeAction` request's `context.diagnostics`. A
    diagnostic at position D covers the cursor iff:
        (D.start ≤ cursor) AND (cursor ≤ D.end)
    where positions compare lexicographically by (line, character).

    Boundary semantics: the cursor on `start` is *included* (matches
    LSP server behavior for "diagnostics at this point"); the cursor
    on `end` is also included (zero-width selections still cover).
    """
    cursor = (cursor_line, cursor_char)
    result: list[dict[str, Any]] = []
    for diag in diagnostics:
        rng = diag.get("range")
        if not isinstance(rng, dict):
            continue
        start = rng.get("start")
        end = rng.get("end")
        if not isinstance(start, dict) or not isinstance(end, dict):
            continue
        start_pos = (start.get("line", 0), start.get("character", 0))
        end_pos = (end.get("line", 0), end.get("character", 0))
        if start_pos <= cursor <= end_pos:
            result.append(diag)
    return result
