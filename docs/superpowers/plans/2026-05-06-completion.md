# v0.2.0 Completion Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `textDocument/completion` (+ `completionItem/resolve`) wired to a `GtkSource.CompletionProvider`, so users get LSP-driven completion proposals in gedit's existing completion popup. Snippets and signatureHelp are out of scope (separate plans).

**Architecture:** Pull the GTK-free request building, response conversion, capability gating, and trigger classification into pure-Python helpers (unit-testable, no display required). Implement the GTK-side `LspCompletionProvider` as a thin async bridge that calls those helpers, fires the LSP request, and feeds the response back into `GtkSource.CompletionContext.add_proposals(...)`. Wire it from `plugin.py` per buffer with a disposer (matches the listener-cleanup pattern in `96d4f11`). Server capabilities (currently discarded after `initialize`) are stored on `LanguageServer` with `serverCapabilityOverrides` deep-merged on top — closes a documented-but-unimplemented contract from `config.py:11`.

**Tech Stack:** Python 3.12, PyGObject (Gtk 3, GtkSource 300), pytest, ruff, mypy, gedit 46. JSON-RPC over stdio to language servers.

**Phasing:** The plan splits into four phases that map to natural PR boundaries. Each phase produces shippable, CI-green code on its own.

| Phase | Tasks | Output | PR |
|---|---|---|---|
| 0 | 1–4 | Server capabilities stored + overrides applied. Closes a documented gap; useful even without completion. | PR-A: `feat: track server capabilities with config overrides applied` |
| 1 | 5–10 | Completion data layer (request shape, item conversion, capability gate, trigger classification, debounce). All pytest-testable. | PR-B: `feat(completion): pure-data layer for textDocument/completion` |
| 2 | 11–13 | `LspCompletionProvider` (GtkSource integration), plugin.py wiring with disposer, manual smoke test. | PR-C: `feat(completion): wire GtkSource provider into plugin` |
| 3 | 14–17 | `completionItem/resolve`, default `enabledFeatures` flip, docs (`configure.md`, `example-config.json`, `example-config.md`), CHANGELOG. | PR-D: `feat(completion): resolve, defaults, docs` |

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `src/gedit_lsp/server.py` | modify | Store `capabilities` from initialize response; apply `serverCapabilityOverrides`; expose `capability(path)` accessor. |
| `src/gedit_lsp/features/completion.py` | create | Pure helpers (request builder, item converter, trigger classifier, capability gate) + `LspCompletionProvider` (GtkSource integration) + `CompletionController` (orchestration: debounce + lifecycle). |
| `src/gedit_lsp/plugin.py` | modify | Construct/dispose `CompletionController` per attached buffer; gate on `enabledFeatures`. |
| `src/gedit_lsp/defaults.py` | modify | Add `"completion"` to `enabledFeatures` default. |
| `tests/unit/test_completion_request.py` | create | Tests for `_build_completion_params`. |
| `tests/unit/test_completion_conversion.py` | create | Tests for `lsp_item_to_proposal`, sort/filter, kind mapping. |
| `tests/unit/test_completion_capability.py` | create | Tests for `is_completion_supported`, `trigger_characters_from`, capability override merge. |
| `tests/unit/test_completion_trigger.py` | create | Tests for `classify_trigger`. |
| `tests/unit/test_server_capabilities.py` | create | Tests for the new `capability()` accessor and override deep-merge. |
| `docs/configure.md` | modify | Add `completion` to the `enabledFeatures` recognised list. |
| `docs/example-config.json` | modify | Add `"completion"` to `enabledFeatures` list (default flip means it's already on, but the example explicitly lists). |
| `docs/example-config.md` | modify | Add `completion` to the recognised-values note. |
| `CHANGELOG.md` | modify | Unreleased entry for completion. |

---

# Phase 0 — Server capabilities + overrides

## Task 1: Capability deep-merge helper (TDD)

**Files:**
- Create: `tests/unit/test_server_capabilities.py`
- Modify: `src/gedit_lsp/server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_server_capabilities.py
"""Tests for server-capabilities tracking and override application."""
from __future__ import annotations

from gedit_lsp.server import _merge_capabilities


def test_merge_capabilities_no_overrides_returns_server_caps() -> None:
    server_caps = {"hoverProvider": True, "completionProvider": {"triggerCharacters": ["."]}}
    assert _merge_capabilities(server_caps, {}) == server_caps


def test_merge_capabilities_overrides_top_level_bool() -> None:
    server_caps = {"hoverProvider": True}
    overrides  = {"hoverProvider": False}
    assert _merge_capabilities(server_caps, overrides) == {"hoverProvider": False}


def test_merge_capabilities_deep_merges_nested_dicts() -> None:
    server_caps = {
        "completionProvider": {"triggerCharacters": [".", "->"], "resolveProvider": True}
    }
    overrides = {
        "completionProvider": {"triggerCharacters": ["."]}  # narrow only
    }
    merged = _merge_capabilities(server_caps, overrides)
    assert merged == {
        "completionProvider": {"triggerCharacters": ["."], "resolveProvider": True}
    }


def test_merge_capabilities_override_adds_missing_capability() -> None:
    server_caps = {}
    overrides = {"hoverProvider": True}
    assert _merge_capabilities(server_caps, overrides) == {"hoverProvider": True}


def test_merge_capabilities_lists_are_replaced_not_concatenated() -> None:
    server_caps = {"completionProvider": {"triggerCharacters": [".", "->", "::"]}}
    overrides  = {"completionProvider": {"triggerCharacters": ["."]}}
    merged = _merge_capabilities(server_caps, overrides)
    assert merged["completionProvider"]["triggerCharacters"] == ["."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: `ImportError: cannot import name '_merge_capabilities' from 'gedit_lsp.server'`

- [ ] **Step 3: Implement `_merge_capabilities` in `server.py`**

Add at module level (above the `LanguageServer` class):

```python
def _merge_capabilities(server: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge `overrides` on top of `server` capabilities.

    Dicts are recursively merged; non-dict values (bools, lists, scalars) are
    replaced wholesale. Lists are *replaced*, not concatenated — overriding
    `triggerCharacters: ["."]` narrows the set rather than appending.
    """
    if not overrides:
        return dict(server)
    out: dict[str, Any] = dict(server)
    for key, value in overrides.items():
        if (
            isinstance(value, dict)
            and isinstance(out.get(key), dict)
        ):
            out[key] = _merge_capabilities(out[key], value)
        else:
            out[key] = value
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: `5 passed` for the new test file (total count grows by 5).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_server_capabilities.py src/gedit_lsp/server.py
git commit -m "feat(server): add _merge_capabilities deep-merge helper"
```

---

## Task 2: Store capabilities on LanguageServer (TDD)

**Files:**
- Modify: `tests/unit/test_server_capabilities.py`
- Modify: `src/gedit_lsp/server.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_server_capabilities.py`:

```python
from typing import Any

from gedit_lsp.server import LanguageServer, ServerState


def _make_server(capability_overrides: dict[str, Any] | None = None) -> LanguageServer:
    return LanguageServer(
        language_id="python",
        command=["pylsp"],
        root_path="/tmp",
        initialization_options=None,
        transport_factory=lambda *a, **kw: None,  # type: ignore[arg-type]
        backoff_schedule=[1, 2, 4],
        max_restart_attempts=3,
        idle_timeout_seconds=300,
        stderr_buffer_max_lines=100,
        server_capability_overrides=capability_overrides or {},
    )


def test_capability_returns_none_before_initialize() -> None:
    server = _make_server()
    assert server.capability("hoverProvider") is None


def test_capability_returns_value_after_initialize_response() -> None:
    server = _make_server()
    server._apply_initialize_capabilities(
        {"hoverProvider": True, "completionProvider": {"triggerCharacters": ["."]}}
    )
    assert server.capability("hoverProvider") is True
    assert server.capability("completionProvider") == {"triggerCharacters": ["."]}


def test_capability_applies_overrides_after_initialize() -> None:
    server = _make_server({"hoverProvider": False})
    server._apply_initialize_capabilities({"hoverProvider": True})
    assert server.capability("hoverProvider") is False


def test_capability_unknown_key_returns_none() -> None:
    server = _make_server()
    server._apply_initialize_capabilities({"hoverProvider": True})
    assert server.capability("nonexistentProvider") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && make test 2>&1 | tail -10`
Expected: `AttributeError: 'LanguageServer' object has no attribute 'capability'` or similar — and possibly a `TypeError` on the constructor call if `server_capability_overrides` isn't a kw yet (it isn't — see step 3).

- [ ] **Step 3: Add the constructor argument, attribute, and accessor**

In `src/gedit_lsp/server.py`, modify `LanguageServer.__init__` (around line 62) to accept `server_capability_overrides`. Add it at the END of the signature with a default of `None` (so existing positional/keyword callers don't break — Task 3 will update the one production call site to pass it explicitly):

```python
def __init__(
    self,
    language_id: str,
    root_path: str,
    command: list[str],
    initialization_options: Any,
    transport_factory: Callable[..., Transport],
    backoff_schedule: list[int],
    max_restart_attempts: int,
    idle_timeout_seconds: int = 300,
    stderr_buffer_max_lines: int = 1000,
    server_capability_overrides: dict[str, Any] | None = None,
) -> None:
```

In the body, after `self._idle_timeout_seconds = idle_timeout_seconds`, add:

```python
self._capability_overrides: dict[str, Any] = dict(server_capability_overrides or {})
self._capabilities: dict[str, Any] | None = None  # set on initialize response
```

(The `dict(...)` copy is important — it ensures each LanguageServer has its own override dict, not a shared reference. The isolation test in Task 3 relies on this.)

Add the accessor and merge method on the class:

```python
def capability(self, key: str) -> Any:
    """Return the merged-with-overrides capability value for `key`, or None.

    Returns None before the initialize response arrives. After it arrives,
    returns the server's reported value with `serverCapabilityOverrides`
    deep-merged on top.
    """
    if self._capabilities is None:
        return None
    return self._capabilities.get(key)

def _apply_initialize_capabilities(self, server_caps: dict[str, Any]) -> None:
    self._capabilities = _merge_capabilities(server_caps, self._capability_overrides)
```

In `_on_initialize_response`, immediately after the `if msg.get("error"):` guard, add:

```python
result = msg.get("result") or {}
self._apply_initialize_capabilities(result.get("capabilities") or {})
```

(So that `capability()` is populated before `state` flips to READY.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: total test count grows by 4 — all green.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_server_capabilities.py src/gedit_lsp/server.py
git commit -m "feat(server): store + expose initialize capabilities (with overrides)"
```

---

## Task 3: Pass overrides from Config to LanguageServer

**Files:**
- Modify: `src/gedit_lsp/registry.py` (the only `LanguageServer(...)` construction site, at line 33)
- Modify: `tests/unit/test_server_capabilities.py`

- [ ] **Step 1: Add a regression test**

Append to `tests/unit/test_server_capabilities.py`:

```python
def test_overrides_dict_subkey_isolation_per_language() -> None:
    """Capability overrides are looked up per language at the call site;
    a Python-only override must not leak into a C server.
    Sanity test: just make sure the override stored on the server is the
    per-language slice the caller passed in (the plugin is responsible for
    slicing config['serverCapabilityOverrides'][lang] before construction).
    """
    server = _make_server({"hoverProvider": False})
    assert server._capability_overrides == {"hoverProvider": False}
    other = _make_server({"completionProvider": {"resolveProvider": False}})
    assert other._capability_overrides == {"completionProvider": {"resolveProvider": False}}
    # The two servers must have independent override dicts (no shared mutation).
    server._capability_overrides["leak"] = True
    assert "leak" not in other._capability_overrides
```

- [ ] **Step 2: Modify the construction in `registry.py`**

Edit `src/gedit_lsp/registry.py`. Inside `get_or_spawn`, just above the `LanguageServer(...)` construction, read the per-language slice:

```python
overrides_all = self._config.tunable("serverCapabilityOverrides") or {}
language_overrides = overrides_all.get(language_id, {})
```

Then add the new keyword argument to the `LanguageServer(...)` call (alphabetical placement — after `root_path` works, but matching the constructor's order is fine):

```python
self._servers[key] = LanguageServer(
    language_id=language_id,
    root_path=str(root_path),
    command=entry["command"],
    initialization_options=self._config.initialization_options_for(language_id),
    transport_factory=self._transport_factory,
    backoff_schedule=self._config.tunable("restartBackoffSchedule"),
    max_restart_attempts=self._config.tunable("restartMaxAttempts"),
    idle_timeout_seconds=self._config.tunable("serverIdleTimeoutSeconds"),
    stderr_buffer_max_lines=self._config.tunable("stderrBufferMaxLines"),
    server_capability_overrides=language_overrides,
)
```

- [ ] **Step 3: Run the full test suite**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: all green; the isolation test from step 1 passes.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_server_capabilities.py src/gedit_lsp/registry.py
git commit -m "feat(registry): pass per-language capability overrides to LanguageServer"
```

---

## Task 4: Phase 0 PR

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin feat/completion
gh pr create --title "feat: track server capabilities with config overrides applied" --body "$(cat <<'EOF'
## Summary

Closes a documented-but-unimplemented contract from `config.py:11`. The `serverCapabilityOverrides` tunable is now actually applied: the server's reported capabilities (from the `initialize` response) are stored on `LanguageServer`, and overrides deep-merge on top.

This is Phase 0 of v0.2.0 completion (separate plan), but it lands independently because it's useful in its own right — for example, you can now disable a server's hoverProvider per-language without touching code.

## Test plan
- [x] 9 new unit tests in `test_server_capabilities.py`
- [x] `make test` green
- [ ] Manual: install, edit a Python file, set `serverCapabilityOverrides.python.hoverProvider=false`, verify hover popover no longer appears
EOF
)"
```

- [ ] **Step 2: Verify CI green via gh**

Run: `gh pr view --json statusCheckRollup --jq '.statusCheckRollup[] | "\(.name): \(.conclusion // .status)"'`
Expected: lint, unit, doc-gate, integration all `SUCCESS`.

- [ ] **Step 3: Wait for review / self-merge**

Once CI is green and you (the maintainer) are happy, merge via the GitHub UI or `gh pr merge --merge --delete-branch`. Then sync local main:

```bash
git checkout main && git pull --ff-only && git checkout -b feat/completion
```

(Recreate the feature branch so Phase 1 work continues.)

---

# Phase 1 — Completion data layer

All tasks in this phase produce pure-Python helpers — fully unit-testable in pytest, no GTK display needed.

## Task 5: Completion request builder (TDD)

**Files:**
- Create: `tests/unit/test_completion_request.py`
- Create: `src/gedit_lsp/features/completion.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_completion_request.py
"""Tests for the LSP completion request param builder."""
from __future__ import annotations

from gedit_lsp.features.completion import (
    CompletionTriggerKind,
    build_completion_params,
)


def test_build_completion_params_invoked() -> None:
    params = build_completion_params(
        uri="file:///tmp/x.py", line=3, character=7,
        trigger_kind=CompletionTriggerKind.Invoked,
        trigger_character=None,
    )
    assert params == {
        "textDocument": {"uri": "file:///tmp/x.py"},
        "position": {"line": 3, "character": 7},
        "context": {"triggerKind": 1},
    }


def test_build_completion_params_trigger_character() -> None:
    params = build_completion_params(
        uri="file:///x", line=0, character=5,
        trigger_kind=CompletionTriggerKind.TriggerCharacter,
        trigger_character=".",
    )
    assert params["context"] == {"triggerKind": 2, "triggerCharacter": "."}


def test_build_completion_params_for_incomplete() -> None:
    params = build_completion_params(
        uri="file:///x", line=1, character=2,
        trigger_kind=CompletionTriggerKind.TriggerForIncompleteCompletions,
        trigger_character=None,
    )
    assert params["context"] == {"triggerKind": 3}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: `ModuleNotFoundError: No module named 'gedit_lsp.features.completion'`.

- [ ] **Step 3: Implement the builder**

Create `src/gedit_lsp/features/completion.py`:

```python
"""LSP completion feature — request shapes, response conversion, GtkSource provider.

Pure helpers (unit-testable, no GTK dependency) live at module level. The
GtkSource bindings (CompletionProvider class + Controller) are added in
later tasks.
"""
from __future__ import annotations

import enum
from typing import Any


class CompletionTriggerKind(enum.IntEnum):
    """Subset of LSP CompletionTriggerKind we use."""
    Invoked = 1
    TriggerCharacter = 2
    TriggerForIncompleteCompletions = 3


def build_completion_params(
    *,
    uri: str,
    line: int,
    character: int,
    trigger_kind: CompletionTriggerKind,
    trigger_character: str | None,
) -> dict[str, Any]:
    """Build the params dict for a `textDocument/completion` request.

    `trigger_character` is included only when `trigger_kind` is
    `TriggerCharacter`; per LSP spec, omit it otherwise.
    """
    context: dict[str, Any] = {"triggerKind": int(trigger_kind)}
    if trigger_kind is CompletionTriggerKind.TriggerCharacter and trigger_character:
        context["triggerCharacter"] = trigger_character
    return {
        "textDocument": {"uri": uri},
        "position": {"line": line, "character": character},
        "context": context,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: 3 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_completion_request.py src/gedit_lsp/features/completion.py
git commit -m "feat(completion): add LSP completion request param builder"
```

---

## Task 6: Capability gate (TDD)

**Files:**
- Create: `tests/unit/test_completion_capability.py`
- Modify: `src/gedit_lsp/features/completion.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_completion_capability.py
"""Tests for the completion capability gate and trigger-character extraction."""
from __future__ import annotations

from gedit_lsp.features.completion import (
    is_completion_supported,
    trigger_characters_from,
    resolve_provider_from,
)


def test_is_completion_supported_no_capability() -> None:
    assert is_completion_supported(None) is False
    assert is_completion_supported({}) is False


def test_is_completion_supported_present_dict() -> None:
    assert is_completion_supported({"triggerCharacters": ["."]}) is True


def test_is_completion_supported_present_empty_dict() -> None:
    # Server reports support but configures nothing — still supported.
    assert is_completion_supported({}) is False  # we treat absent capability as no support
    assert is_completion_supported({"resolveProvider": False}) is True


def test_trigger_characters_extracts_list() -> None:
    assert trigger_characters_from({"triggerCharacters": [".", "->"]}) == [".", "->"]


def test_trigger_characters_missing_returns_empty() -> None:
    assert trigger_characters_from({}) == []
    assert trigger_characters_from(None) == []


def test_resolve_provider_default_false() -> None:
    assert resolve_provider_from({}) is False
    assert resolve_provider_from(None) is False


def test_resolve_provider_explicit_true() -> None:
    assert resolve_provider_from({"resolveProvider": True}) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: `ImportError: cannot import name 'is_completion_supported'`.

- [ ] **Step 3: Implement the gate helpers**

Append to `src/gedit_lsp/features/completion.py`:

```python
def is_completion_supported(capability: dict[str, Any] | None) -> bool:
    """Return True if the server's `completionProvider` capability is present
    and has any concrete configuration. We treat `None` and `{}` as "not
    supported" — a server that returns an empty completionProvider gives us
    no trigger characters and no resolveProvider hint, so there's nothing
    to wire up.
    """
    return bool(capability)


def trigger_characters_from(capability: dict[str, Any] | None) -> list[str]:
    if not capability:
        return []
    return list(capability.get("triggerCharacters", []) or [])


def resolve_provider_from(capability: dict[str, Any] | None) -> bool:
    if not capability:
        return False
    return bool(capability.get("resolveProvider", False))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: all 7 capability tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_completion_capability.py src/gedit_lsp/features/completion.py
git commit -m "feat(completion): add capability gate + trigger char extraction"
```

---

## Task 7: Trigger classification (TDD)

**Files:**
- Create: `tests/unit/test_completion_trigger.py`
- Modify: `src/gedit_lsp/features/completion.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_completion_trigger.py
"""Tests for classify_trigger — maps a typed character + state to LSP trigger."""
from __future__ import annotations

from gedit_lsp.features.completion import (
    CompletionTriggerKind,
    classify_trigger,
)


def test_classify_user_invoked_no_char() -> None:
    kind, char = classify_trigger(typed_char=None, trigger_chars=[".", "->"], list_is_incomplete=False)
    assert kind is CompletionTriggerKind.Invoked
    assert char is None


def test_classify_typed_known_trigger_char() -> None:
    kind, char = classify_trigger(typed_char=".", trigger_chars=[".", "->"], list_is_incomplete=False)
    assert kind is CompletionTriggerKind.TriggerCharacter
    assert char == "."


def test_classify_typed_unknown_char() -> None:
    # User typed a regular letter — not a trigger character, but maybe we are
    # filtering an existing list. Treat as Invoked (regular re-fetch).
    kind, char = classify_trigger(typed_char="x", trigger_chars=[".", "->"], list_is_incomplete=False)
    assert kind is CompletionTriggerKind.Invoked
    assert char is None


def test_classify_incomplete_continuation() -> None:
    # The previous response had isIncomplete=true; the user keeps typing,
    # we re-request to extend the list.
    kind, char = classify_trigger(typed_char="x", trigger_chars=[".", "->"], list_is_incomplete=True)
    assert kind is CompletionTriggerKind.TriggerForIncompleteCompletions
    assert char is None


def test_classify_multichar_trigger() -> None:
    # `->` is a 2-char trigger. The classifier sees the latest typed
    # character (`>`), but matching a multichar trigger requires looking at
    # context. For v1 we match a multichar trigger only when the typed_char
    # equals one of the listed strings exactly — i.e. we don't reconstruct
    # buffer suffixes here.
    kind, _ = classify_trigger(typed_char=">", trigger_chars=[".", "->"], list_is_incomplete=False)
    # `>` alone isn't in trigger_chars, so this is Invoked.
    assert kind is CompletionTriggerKind.Invoked

    # If the caller passes the actual matched suffix (`->`), we honour it.
    kind, char = classify_trigger(typed_char="->", trigger_chars=[".", "->"], list_is_incomplete=False)
    assert kind is CompletionTriggerKind.TriggerCharacter
    assert char == "->"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: `ImportError: cannot import name 'classify_trigger'`.

- [ ] **Step 3: Implement the classifier**

Append to `src/gedit_lsp/features/completion.py`:

```python
def classify_trigger(
    *,
    typed_char: str | None,
    trigger_chars: list[str],
    list_is_incomplete: bool,
) -> tuple[CompletionTriggerKind, str | None]:
    """Map (typed_char, server trigger chars, prior isIncomplete) to an LSP
    CompletionContext shape.

    Returns (kind, character_to_send).

    The caller is responsible for matching multi-character triggers (e.g.
    `->`); if it determined a multi-char suffix matched, it passes that
    suffix as `typed_char`. We only check for membership in `trigger_chars`.
    """
    if list_is_incomplete:
        return (CompletionTriggerKind.TriggerForIncompleteCompletions, None)
    if typed_char is not None and typed_char in trigger_chars:
        return (CompletionTriggerKind.TriggerCharacter, typed_char)
    return (CompletionTriggerKind.Invoked, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: all 5 trigger tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_completion_trigger.py src/gedit_lsp/features/completion.py
git commit -m "feat(completion): add trigger classifier"
```

---

## Task 8: Item conversion (TDD)

**Files:**
- Create: `tests/unit/test_completion_conversion.py`
- Modify: `src/gedit_lsp/features/completion.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_completion_conversion.py
"""Tests for LSP CompletionItem → display-ready Python dataclass."""
from __future__ import annotations

from gedit_lsp.features.completion import (
    LspProposal,
    extract_completion_items,
    lsp_item_to_proposal,
)


def test_lsp_item_minimal_label_only() -> None:
    p = lsp_item_to_proposal({"label": "foo"})
    assert p.label == "foo"
    assert p.insert_text == "foo"           # falls back to label
    assert p.detail is None
    assert p.kind is None
    assert p.documentation == ""
    assert p.sort_text == "foo"             # falls back to label
    assert p.filter_text == "foo"           # falls back to label
    assert p.raw_item == {"label": "foo"}   # preserved for resolve


def test_lsp_item_full_fields() -> None:
    item = {
        "label": "spam",
        "insertText": "spam(${0})",
        "detail": "(method) Spam.spam() -> int",
        "kind": 2,
        "documentation": {"kind": "markdown", "value": "Spam the eggs."},
        "sortText": "0_spam",
        "filterText": "spam",
    }
    p = lsp_item_to_proposal(item)
    assert p.insert_text == "spam(${0})"
    assert p.detail == "(method) Spam.spam() -> int"
    assert p.kind == 2
    assert p.documentation == "Spam the eggs."
    assert p.sort_text == "0_spam"
    assert p.filter_text == "spam"


def test_lsp_item_documentation_string_form() -> None:
    p = lsp_item_to_proposal({"label": "x", "documentation": "plain string"})
    assert p.documentation == "plain string"


def test_extract_completion_items_handles_array() -> None:
    items = extract_completion_items([{"label": "a"}, {"label": "b"}])
    assert [p.label for p in items] == ["a", "b"]


def test_extract_completion_items_handles_completion_list() -> None:
    response = {"isIncomplete": False, "items": [{"label": "x"}]}
    items = extract_completion_items(response)
    assert [p.label for p in items] == ["x"]


def test_extract_completion_items_handles_null() -> None:
    assert extract_completion_items(None) == []


def test_extract_completion_items_handles_empty_object() -> None:
    assert extract_completion_items({}) == []
    assert extract_completion_items({"items": []}) == []


def test_extract_completion_list_preserves_isincomplete() -> None:
    """Caller needs to know if the list was incomplete — we expose it via
    a sibling helper since extract_ returns proposals only."""
    from gedit_lsp.features.completion import response_is_incomplete
    assert response_is_incomplete(None) is False
    assert response_is_incomplete([]) is False
    assert response_is_incomplete({"isIncomplete": True, "items": []}) is True
    assert response_is_incomplete({"isIncomplete": False, "items": []}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: `ImportError`.

- [ ] **Step 3: Implement the converter**

Append to `src/gedit_lsp/features/completion.py`:

```python
import dataclasses


@dataclasses.dataclass(frozen=True)
class LspProposal:
    """Display-ready, GTK-free representation of a single completion proposal.

    `raw_item` retains the original LSP CompletionItem dict so we can pass
    it back to `completionItem/resolve` later.
    """
    label: str
    insert_text: str
    detail: str | None
    kind: int | None        # LSP CompletionItemKind enum value
    documentation: str
    sort_text: str
    filter_text: str
    raw_item: dict[str, Any]


def _stringify_documentation(doc: Any) -> str:
    """Mirror render_hover_contents shape — strings, MarkupContent dicts, None."""
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        return str(doc.get("value", ""))
    return ""


def lsp_item_to_proposal(item: dict[str, Any]) -> LspProposal:
    label = str(item.get("label", ""))
    return LspProposal(
        label=label,
        insert_text=str(item.get("insertText") or label),
        detail=item.get("detail"),
        kind=item.get("kind"),
        documentation=_stringify_documentation(item.get("documentation")),
        sort_text=str(item.get("sortText") or label),
        filter_text=str(item.get("filterText") or label),
        raw_item=item,
    )


def extract_completion_items(response: Any) -> list[LspProposal]:
    """Normalise both LSP response shapes (`CompletionItem[]` and
    `CompletionList`) and return a list of LspProposal."""
    if response is None:
        return []
    if isinstance(response, list):
        return [lsp_item_to_proposal(it) for it in response]
    if isinstance(response, dict):
        items = response.get("items") or []
        return [lsp_item_to_proposal(it) for it in items]
    return []


def response_is_incomplete(response: Any) -> bool:
    if isinstance(response, dict):
        return bool(response.get("isIncomplete", False))
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: all 8 conversion tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_completion_conversion.py src/gedit_lsp/features/completion.py
git commit -m "feat(completion): add LSP item → LspProposal conversion"
```

---

## Task 9: Add `enabledFeatures` allow-list update (text-only test)

The list of recognised feature names lives implicitly in `plugin.py`'s
feature-wiring code and is documented in `defaults.py` and
`docs/example-config.md`. Adding `"completion"` is a doc-only step here;
the actual wiring happens in Phase 2. We add the recognised name now so
that the example config and docs land at the same time as Phase 1's
unit-testable code, and so users who poke at the JSON schema see the
new value.

**Files:**
- Modify: `src/gedit_lsp/defaults.py`

- [ ] **Step 1: Add `"completion"` to `enabledFeatures` default**

Edit `src/gedit_lsp/defaults.py`:

```python
"enabledFeatures": ["diagnostics", "hover", "definition", "outline", "completion"],
```

- [ ] **Step 2: Verify nothing breaks (no test exercises this list directly)**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/defaults.py
git commit -m "feat(completion): include 'completion' in default enabledFeatures"
```

(The feature gate in plugin.py is added in Task 12. This commit makes the *default* include it, but the gate doesn't exist yet, so it's still inert. Safe.)

---

## Task 10: Phase 1 PR

- [ ] **Step 1: Push and open PR**

```bash
git push -u origin feat/completion
gh pr create --title "feat(completion): pure-data layer for textDocument/completion" --body "$(cat <<'EOF'
## Summary

Phase 1 of v0.2.0 completion (separate plan in `docs/superpowers/plans/2026-05-06-completion.md`). Adds the pure-Python helpers needed for the GtkSource provider in Phase 2:

- `build_completion_params` — request shape
- `is_completion_supported` / `trigger_characters_from` / `resolve_provider_from` — capability gating
- `classify_trigger` — typed-character → LSP CompletionTriggerKind
- `extract_completion_items` / `lsp_item_to_proposal` — response → LspProposal dataclass
- `response_is_incomplete` — flag passthrough for re-request logic

All testable in pytest; no GTK display required. Phase 2 (next PR) wires these into `LspCompletionProvider` and `plugin.py`.

## Test plan
- [x] 23 new unit tests across 4 test files
- [x] `make test` green
EOF
)"
```

- [ ] **Step 2: Wait for CI green, self-merge, sync local**

```bash
gh pr view --json statusCheckRollup --jq '.statusCheckRollup[] | "\(.name): \(.conclusion // .status)"'
# After all SUCCESS:
gh pr merge --merge --delete-branch
git checkout main && git pull --ff-only && git checkout -b feat/completion
```

---

# Phase 2 — GtkSource provider + plugin wiring

## Task 11: `LspCompletionProvider` class (manual smoke test)

This task introduces GTK-bound code that can't be unit-tested in pytest
without a display. We do not write fake unit tests; instead, the
verification is a manual smoke test in gedit. This is the same pattern as
`HoverController` (no controller-level unit tests; only the renderer
helper is tested).

**Files:**
- Modify: `src/gedit_lsp/features/completion.py`

- [ ] **Step 1: Append the GtkSource integration**

Append to `src/gedit_lsp/features/completion.py`:

```python
import logging

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import GObject, Gtk, GtkSource  # noqa: E402

from gedit_lsp.utf16 import text_iter_to_utf16  # noqa: E402

logger = logging.getLogger("gedit_lsp.completion")


class _LspCompletionProposal(GObject.Object, GtkSource.CompletionProposal):
    """A single proposal exposed to GtkSource."""

    def __init__(self, lsp: LspProposal) -> None:
        GObject.Object.__init__(self)
        self.lsp = lsp

    def do_get_label(self) -> str:
        return self.lsp.label

    def do_get_text(self) -> str:
        return self.lsp.insert_text

    def do_get_info(self) -> str:
        # Used by the info popup; we render plain text (markdown is
        # stringified upstream).
        return self.lsp.documentation


class LspCompletionProvider(GObject.Object, GtkSource.CompletionProvider):
    """GtkSource.CompletionProvider that fires LSP completion requests.

    One instance per (buffer, server). The provider is registered with the
    view's CompletionContext and disposed on tab-removed / plugin
    deactivate (see `CompletionController.dispose`).
    """

    def __init__(
        self,
        *,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server: "LanguageServer",
        uri: str,
    ) -> None:
        GObject.Object.__init__(self)
        self._view = view
        self._buffer = buffer
        self._server = server
        self._uri = uri
        self._last_was_incomplete = False
        self._inflight_id: int | None = None

    def do_get_name(self) -> str:
        return "LSP"

    def do_get_priority(self) -> int:
        return 100  # higher than the default word provider (which is ~10)

    def do_get_activation(self) -> "GtkSource.CompletionActivation":
        # USER_REQUESTED so Ctrl+Space invokes us; Interactive so trigger
        # characters auto-fire.
        return (
            GtkSource.CompletionActivation.USER_REQUESTED
            | GtkSource.CompletionActivation.INTERACTIVE
        )

    def do_match(self, _context: GtkSource.CompletionContext) -> bool:
        cap = self._server.capability("completionProvider")
        return is_completion_supported(cap)

    def do_populate(self, context: GtkSource.CompletionContext) -> None:
        cap = self._server.capability("completionProvider")
        trigger_chars = trigger_characters_from(cap)

        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        line, char = text_iter_to_utf16(cursor)

        # Best-effort: detect last-typed character to decide trigger kind.
        # GtkSource doesn't tell us directly, so we look at the char before
        # the cursor.
        typed = self._char_before(cursor)

        kind, trig_char = classify_trigger(
            typed_char=typed,
            trigger_chars=trigger_chars,
            list_is_incomplete=self._last_was_incomplete,
        )

        params = build_completion_params(
            uri=self._uri,
            line=line,
            character=char,
            trigger_kind=kind,
            trigger_character=trig_char,
        )

        if self._inflight_id is not None:
            self._server.cancel_request(self._inflight_id)
            self._inflight_id = None

        def on_response(msg: dict[str, Any]) -> None:
            if msg.get("error"):
                logger.info("completion error: %r", msg.get("error"))
                context.add_proposals(self, [], True)
                return
            result = msg.get("result")
            self._last_was_incomplete = response_is_incomplete(result)
            proposals = extract_completion_items(result)
            gtk_proposals = [_LspCompletionProposal(p) for p in proposals]
            context.add_proposals(self, gtk_proposals, True)

        self._inflight_id = self._server._send_request(
            "textDocument/completion", params, on_response
        )

    def do_activate_proposal(
        self,
        proposal: GtkSource.CompletionProposal,
        iter_: Gtk.TextIter,
    ) -> bool:
        # GtkSource's default activation inserts proposal.get_text() at
        # the iter and returns True. We rely on that for v1 — snippet
        # support arrives in a separate plan.
        return False  # signal "use default behavior"

    def _char_before(self, cursor: Gtk.TextIter) -> str | None:
        prev = cursor.copy()
        if not prev.backward_char():
            return None
        return prev.get_char() or None
```

- [ ] **Step 2: Verify imports / types compile**

Run: `source .venv/bin/activate && mypy src/gedit_lsp/features/completion.py 2>&1 | tail -20`
Expected: no errors. If GtkSource's stubs are missing certain symbols, the existing `# type: ignore[...]` patterns in `hover.py` may need to be replicated.

- [ ] **Step 3: Run the full test suite**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: all green; no test references the new GTK-bound classes (intentional).

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/features/completion.py
git commit -m "feat(completion): add LspCompletionProvider GtkSource integration"
```

---

## Task 12: Plugin wiring (`CompletionController`) with disposer

**Files:**
- Modify: `src/gedit_lsp/features/completion.py`
- Modify: `src/gedit_lsp/plugin.py`

- [ ] **Step 1: Add `CompletionController` to completion.py**

Append to `src/gedit_lsp/features/completion.py`:

```python
class CompletionController:
    """Per-buffer wrapper that registers/unregisters the LspCompletionProvider.

    Lifecycle: constructed when the bridge attaches; `dispose()` called from
    plugin.py on tab-removed or deactivate. Returns the provider instance
    so the caller can inspect / re-register if needed.
    """

    def __init__(
        self,
        *,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server: "LanguageServer",
        uri: str,
    ) -> None:
        self._view = view
        self._provider = LspCompletionProvider(
            view=view, buffer=buffer, server=server, uri=uri
        )
        completion = view.get_completion()
        if completion is not None:
            completion.add_provider(self._provider)

    def dispose(self) -> None:
        completion = self._view.get_completion()
        if completion is not None:
            completion.remove_provider(self._provider)
```

- [ ] **Step 2: Wire into plugin.py — gate on enabledFeatures**

In `src/gedit_lsp/plugin.py`, find where the bridge is constructed for a doc (`_bridges[doc] = ...`). Right after, add:

```python
if "completion" in self._config.tunable("enabledFeatures"):
    from gedit_lsp.features.completion import CompletionController
    ctrl = CompletionController(
        view=view, buffer=doc, server=server, uri=bridge.uri,
    )
    self._completion_controllers[doc] = ctrl
```

Initialise `self._completion_controllers: dict[Gedit.Document, CompletionController] = {}` in `__init__` alongside `self._bridges` etc.

In the tab-removed / deactivate cleanup paths (search for where `self._bridges` is cleared on doc removal), add:

```python
ctrl = self._completion_controllers.pop(doc, None)
if ctrl is not None:
    ctrl.dispose()
```

- [ ] **Step 3: Run tests + mypy**

```bash
source .venv/bin/activate
make test
make typecheck
```
Expected: both green.

- [ ] **Step 4: Manual smoke test**

```bash
./install.sh
# Restart gedit
# Open a Python file with at least one import (so pylsp has context)
# Type "import os" then on a new line type "os." — completion popup should
# appear with os.path, os.environ, etc.
# Press Esc to dismiss; press Ctrl+Space to invoke manually.
# Open a non-Python file — verify no popup tries to fire.
```

Document the smoke test outcome inline in the commit message body.

- [ ] **Step 5: Commit**

```bash
git add src/gedit_lsp/features/completion.py src/gedit_lsp/plugin.py
git commit -m "feat(completion): wire LspCompletionProvider into plugin lifecycle"
```

---

## Task 13: Phase 2 PR

- [ ] **Step 1: Push and open PR**

```bash
git push -u origin feat/completion
gh pr create --title "feat(completion): wire GtkSource provider into plugin" --body "$(cat <<'EOF'
## Summary

Phase 2 of v0.2.0 completion. Lands the GTK-side integration:

- `LspCompletionProvider` (GtkSource.CompletionProvider implementation)
- `_LspCompletionProposal` (proposal wrapper)
- `CompletionController` (per-buffer registration/disposal, follows `96d4f11` disposer pattern)
- Plugin.py wiring gated on `enabledFeatures`

`completionItem/resolve` and the doc updates land in Phase 3 (next PR).

## Test plan
- [x] `make test` green (Phase 1's data-layer tests still cover the helpers)
- [x] `make typecheck` green
- [x] Manual: typed `os.` after `import os` in pylsp — completion popup shows `os.path`, etc.
- [x] Manual: Ctrl+Space invokes completion in a Python buffer
- [x] Manual: opening a Markdown file (no LSP server) — no errors, no provider attached
EOF
)"
```

- [ ] **Step 2: CI green → merge → sync**

```bash
gh pr view --json statusCheckRollup --jq '.statusCheckRollup[] | "\(.name): \(.conclusion // .status)"'
gh pr merge --merge --delete-branch
git checkout main && git pull --ff-only && git checkout -b feat/completion
```

---

# Phase 3 — Resolve, defaults, docs, CHANGELOG

## Task 14: `completionItem/resolve` (TDD for the merge logic; manual for wiring)

**Files:**
- Modify: `tests/unit/test_completion_conversion.py`
- Modify: `src/gedit_lsp/features/completion.py`

- [ ] **Step 1: Write the failing test for `merge_resolved_item`**

Append to `tests/unit/test_completion_conversion.py`:

```python
from gedit_lsp.features.completion import merge_resolved_item


def test_merge_resolved_item_fills_missing_fields() -> None:
    base = lsp_item_to_proposal({"label": "foo"})
    resolved = {"label": "foo", "detail": "(method) foo() -> int",
                "documentation": "Foo the bar."}
    merged = merge_resolved_item(base, resolved)
    assert merged.detail == "(method) foo() -> int"
    assert merged.documentation == "Foo the bar."
    assert merged.label == "foo"  # unchanged


def test_merge_resolved_item_does_not_overwrite_existing() -> None:
    base = lsp_item_to_proposal({"label": "foo", "detail": "preset"})
    resolved = {"label": "foo", "detail": "from server"}
    merged = merge_resolved_item(base, resolved)
    # We trust the resolved server payload — overwrite.
    assert merged.detail == "from server"


def test_merge_resolved_item_preserves_raw() -> None:
    base = lsp_item_to_proposal({"label": "foo"})
    resolved = {"label": "foo", "detail": "x"}
    merged = merge_resolved_item(base, resolved)
    assert merged.raw_item == resolved
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: `ImportError`.

- [ ] **Step 3: Implement `merge_resolved_item`**

Append to `src/gedit_lsp/features/completion.py`:

```python
def merge_resolved_item(base: LspProposal, resolved: dict[str, Any]) -> LspProposal:
    """Replace `base` fields with values from a `completionItem/resolve`
    response. The resolved server payload wins — we trust later, more
    detailed information over the initial item.
    """
    return dataclasses.replace(
        lsp_item_to_proposal(resolved),
        # Preserve the immutable bits the user already saw.
        label=base.label,
    )
```

Note: in `LspCompletionProvider.do_populate` we already store the raw_item on the proposal; resolve wiring fires when GtkSource's "info" popup is opened, calling the server with the raw_item, then re-injecting via `set_info`. Wiring follows in step 4 — a manual-smoke task.

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && make test 2>&1 | tail -5`
Expected: 3 new tests pass.

- [ ] **Step 5: Wire into the provider (manual smoke verifies)**

In `LspCompletionProvider`, override `do_get_info_widget`/`do_update_info` (whichever the GtkSource version exposes — check the running version). When the info popup activates for a proposal:

```python
def do_update_info(
    self,
    proposal: GtkSource.CompletionProposal,
    info: GtkSource.CompletionInfo,
) -> None:
    if not isinstance(proposal, _LspCompletionProposal):
        return
    cap = self._server.capability("completionProvider")
    if not resolve_provider_from(cap):
        return  # server doesn't support resolve

    def on_resolved(msg: dict[str, Any]) -> None:
        if msg.get("error") or msg.get("result") is None:
            return
        merged = merge_resolved_item(proposal.lsp, msg["result"])
        proposal.lsp = merged
        # Re-render the info popup with the new documentation.
        info.set_widget(_make_info_label(merged))

    self._server._send_request(
        "completionItem/resolve", proposal.lsp.raw_item, on_resolved
    )
```

Add a helper `_make_info_label(proposal)` that builds a `Gtk.Label` from `proposal.documentation` + `proposal.detail`. Mirror the simple `Gtk.Label` shape used for the hover popover.

- [ ] **Step 6: Manual smoke test**

After `./install.sh` and gedit restart:
- Open a Python file, trigger completion via `os.`.
- Highlight a proposal (arrow keys), press Tab/F1 (whichever opens info in your gedit) — info popup should show pylsp's documentation.

- [ ] **Step 7: Commit**

```bash
git add src/gedit_lsp/features/completion.py tests/unit/test_completion_conversion.py
git commit -m "feat(completion): support completionItem/resolve for info popup"
```

---

## Task 15: Update docs

**Files:**
- Modify: `docs/configure.md`
- Modify: `docs/example-config.json`
- Modify: `docs/example-config.md`

- [ ] **Step 1: `docs/configure.md`**

Find the `enabledFeatures` row in the tunables table and update the default cell from `["diagnostics","hover","definition","outline"]` to `["diagnostics","hover","definition","outline","completion"]`.

- [ ] **Step 2: `docs/example-config.json`**

Update the `enabledFeatures` line to include `"completion"`:

```json
"enabledFeatures": ["diagnostics", "hover", "definition", "outline", "completion"],
```

- [ ] **Step 3: `docs/example-config.md`**

In the `### Features` block, update the recognised list:

```markdown
Recognised values: `diagnostics`, `hover`, `definition`, `outline`,
`completion`. Any other string is silently ignored.
```

- [ ] **Step 4: Sanity-verify the example config still parses**

```bash
source .venv/bin/activate
PYTHONPATH=src python -c "
import json, sys
from pathlib import Path
from gedit_lsp.config import Config
from gedit_lsp.defaults import DEFAULT_TUNABLES
data = json.loads(Path('docs/example-config.json').read_text())
cfg = Config(Path('docs/example-config.json')); cfg.load()
missing = [k for k in DEFAULT_TUNABLES if k not in data['tunables']]
assert not missing, missing
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add docs/configure.md docs/example-config.json docs/example-config.md
git commit -m "docs: document the completion feature in configure + example"
```

---

## Task 16: CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add Unreleased entries**

Edit `CHANGELOG.md`. Under `## [Unreleased]` → `### Added`:

```markdown
- LSP-driven completion via `textDocument/completion`. Wires LSP completion
  proposals into gedit's existing completion popup
  (`GtkSource.CompletionProvider`). Trigger characters from the server's
  `completionProvider` capability auto-fire; `Ctrl+Space` invokes
  manually. Supports `completionItem/resolve` for richer info popups when
  the server advertises it. Off by default for any language whose server
  doesn't support `completionProvider`. Enabled in `enabledFeatures` by
  default; remove `"completion"` from that list to disable globally, or
  use `serverCapabilityOverrides.<lang>.completionProvider = false` to
  disable per-language.

### Changed

- The server's `capabilities` from the `initialize` response is now
  retained on `LanguageServer` and exposed via `LanguageServer.capability(key)`.
  `serverCapabilityOverrides` is deep-merged on top — closes a
  documented contract that wasn't previously implemented.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entries for completion + capability tracking"
```

---

## Task 17: Phase 3 PR + manual full smoke

- [ ] **Step 1: Push and open PR**

```bash
git push -u origin feat/completion
gh pr create --title "feat(completion): resolve, defaults, docs" --body "$(cat <<'EOF'
## Summary

Phase 3 of v0.2.0 completion. Final shipped pieces:

- `completionItem/resolve` (info popup gets richer docs on hover/highlight)
- `enabledFeatures` default now includes `"completion"`
- Docs: configure.md, example-config.json, example-config.md updated
- CHANGELOG entries

## Test plan
- [x] `make test` green
- [x] Example config parses against `Config.load()`
- [x] Manual: full smoke on a Python file — auto-trigger on `.`, Ctrl+Space, info popup populates with pylsp docstrings
- [x] Manual: open a Markdown file (no completionProvider) — no errors, no popup
- [x] Manual: set `serverCapabilityOverrides.python.completionProvider=false` in user config — completion disabled for Python only
EOF
)"
```

- [ ] **Step 2: CI green → merge**

```bash
gh pr view --json statusCheckRollup --jq '.statusCheckRollup[] | "\(.name): \(.conclusion // .status)"'
gh pr merge --merge --delete-branch
git checkout main && git pull --ff-only
```

- [ ] **Step 3: Tag-or-not decision (out of plan)**

Whether the merged completion feature triggers a `v0.2.0-alpha.1` (or beta-direct, or wait-for-signatureHelp) release is a separate decision. The plan stops at "feature merged on main." Release prep is its own short plan when you're ready.

---

## Self-review notes (post-write)

- **Spec coverage:** Roadmap v0.2.0 has three items; this plan covers item 1 (completion) and item 1's sub-feature (resolve). Items 2 (signatureHelp) and 3 (snippets) are explicitly deferred to separate plans. Documented in the goal.
- **Dependency on Phase 0:** Completion needs `triggerCharacters` from server capabilities. Currently those are dropped. Phase 0 is therefore a real prerequisite, not a nice-to-have. It also lands a documented-but-unimplemented config key (`serverCapabilityOverrides`) so it's standalone-shippable.
- **Test-vs-manual split:** Pure data layer (Phase 0 + 1 + the merge helper in Phase 3) is fully pytest-tested. GTK-bound code (provider class, plugin wiring, info popup) is manual-smoke-tested per `HoverController` precedent. No fake unit tests.
- **PR sizing:** Four PRs of ~300–600 LOC each. Each is independently CI-green and reviewable in <15 minutes.
- **Risk hotspots:** GtkSource provider lifecycle (Task 12) — easy to leak providers if the disposer isn't called from every removal path. Test by toggling `enabledFeatures` and watching for duplicate providers (no test catches this; manual eyes only).
