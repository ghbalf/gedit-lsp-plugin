# `$/progress` work-done progress indicator — design

Date: 2026-05-29
Status: approved, pre-implementation
Target: v0.4.0 bundle

## Goal

Surface server-**initiated** work-done progress (notably background
indexing — clangd, rust-analyzer, gopls) in the gedit statusbar, so the
user can see *why* features are briefly unavailable right after a server
starts.

## Scope

In scope:

- Advertise `window.workDoneProgress: true` in the `initialize` client
  capabilities.
- Acknowledge the server→client `window/workDoneProgress/create` request
  (reply `result: null`).
- Handle `$/progress` notifications (`begin` / `report` / `end`) for
  server-initiated work-done tokens.
- Display active progress in the statusbar, **appended** to the existing
  server-state glyph: `LSP: clangd ⚡ · indexing… 45%`.
- Gate display behind a new `enabledFeatures` entry, `"progress"`.

Out of scope (YAGNI for this cut):

- Attaching a `workDoneToken` to our own outbound requests (references,
  workspace/symbol). Those are usually fast; marginal value, broad wiring.
- A cancel affordance for `cancellable: true` progress. The append-mode
  statusbar has no room for a cancel button.
- Partial-result progress (`partialResultToken`).

## Background — current architecture

- `RpcClient._dispatch` (`rpc.py`) already classifies inbound messages
  into three kinds: response (`id`, no `method`), notification (`method`,
  no `id`), and server→client request (`method` **and** `id`), routing the
  last to an `on_request` callback. **That callback is never wired** —
  `real_transport_factory` / `LanguageServer` don't pass one — so
  server→client requests are currently dropped silently.
- `LanguageServer` (`server.py`) is the per-`(lang, root)` state machine.
  It already exposes two listener registries that return disposers:
  `add_diagnostics_listener` and `add_state_listener`. `$/progress`
  follows the same shape with `add_progress_listener`.
- Servers are process-global and shared across windows
  (`registry.py`, keyed by `(language_id, root_path)`). The statusbar is
  per-window. Each window subscribes its own progress listener, so a
  shared server's progress fans out to every window showing it — exactly
  like the existing state listener.
- The statusbar (`ui/statusbar.py`) is a single dumb `Gtk.Label`;
  `plugin._refresh_statusbar` composes the displayed string.

## Design

### 1. Transport — wire the dropped `on_request` path

- Add an `on_request` parameter to `real_transport_factory` and pass it to
  `RpcClient`.
- In `LanguageServer._spawn_and_initialize`, register
  `on_request=self._on_server_request`.
- `_on_server_request(msg)`:
  - `window/workDoneProgress/create` → reply `result: null`.
  - any other server→client request → reply JSON-RPC error `-32601`
    ("method not found"). We advertise nothing else that invites a
    server→client request, so this branch is defensive; it prevents a
    spec-strict server from stalling on an unanswered request.
- New helper `_send_response(request_id, result)` and
  `_send_error_response(request_id, code, message)`.

### 2. Capability advertisement

`LanguageServer._initialize_params` changes the `capabilities` field from
`{}` to `{"window": {"workDoneProgress": True}}`. Without it, strict
servers will not emit progress at all.

### 3. Progress state machine

- `LanguageServer` gains:
  - `_progress: dict[ProgressToken, ProgressEntry]` where
    `ProgressEntry = {title: str, message: str | None, percentage: int | None}`
    and `ProgressToken = str | int`.
  - `_progress_order: list[ProgressToken]` (or equivalent) to track
    most-recently-updated for display selection.
  - `_progress_listeners` + `add_progress_listener(cb) -> disposer`
    (identical disposer semantics to diagnostics/state listeners).
- Register `on_notification("$/progress", self._on_progress)` alongside the
  existing `publishDiagnostics` registration.
- `_on_progress(msg)` parses `params = {token, value}`:
  - `value.kind == "begin"` → create/replace the entry. `title` is
    required by spec; if absent, fall back to an empty title rather than
    raising.
  - `value.kind == "report"` → update `message` / `percentage` when
    present, **keep the existing title**. Unknown token → ignore.
  - `value.kind == "end"` → remove the entry. Unknown token → ignore.
  - Then fire `_progress_listeners`.
- Pure helper `format_progress_fragment(entry) -> str`:
  `title` + (` {percentage}%` if percentage is not None,
  else ` {message}` if message, else nothing).
- `active_progress_fragment() -> str | None`: returns the fragment for the
  most-recently-updated active token, or `None` when no progress is
  active.

### 4. UI wiring

- In `plugin._attach`, append a progress-listener disposer to the existing
  per-document disposer list:
  `disposers.append(server.add_progress_listener(lambda *_: self._refresh_statusbar()))`.
  Cleaned up on tab-removed / deactivate exactly like the state listener.
- `plugin._refresh_statusbar`: after computing the base state string, if
  `"progress" in enabledFeatures` **and**
  `server.active_progress_fragment()` is non-None, append
  ` · {fragment}`.
- `ui/statusbar.py` is unchanged.

**Separation of concerns:** `server.py` stays config-agnostic — it always
acks `create` and always tracks `$/progress` (cheap and correct). The
`enabledFeatures` toggle gates only the plugin-side *display*, keeping
feature-flag knowledge out of the transport/state layer.

### 5. Config + toggle

Add `"progress"` to the `enabledFeatures` default list in `defaults.py`.
The prefs UI checkbox is mechanically derived from `DEFAULT_TUNABLES` by
the existing sync test in `tests/unit/test_prefs.py` — no manual prefs
edit; the sync test is run to confirm no drift.

## Display decisions

- **Multiple concurrent tokens:** show the most-recently-updated token's
  fragment (no merged "(+1 more)"). Indexing is typically a single token.
- **`cancellable: true`:** ignored; no cancel UI in append mode.
- **Missing percentage:** show `title` + ` message`; if neither extra is
  present, just the `title`.

## Error handling

- Malformed `$/progress` params (missing `token` / `value`, non-dict
  `value`) → ignored, no listener fired.
- `report` / `end` for an unknown token → ignored.
- Other server→client requests → JSON-RPC `-32601` error response.

## Testing

- **Unit (pure):** `format_progress_fragment` and the begin/report/end
  state machine — multiple concurrent tokens, unknown-token report/end,
  missing percentage, end clears the entry, most-recently-updated
  selection.
- **server.py:** `_on_progress` updates state and fires listeners;
  `window/workDoneProgress/create` request → `result: null` response sent;
  unknown server→client request → error response sent;
  `add_progress_listener` disposer removes the listener.
- **Mutation test:** break a state-machine production line, watch a test
  fail, restore (per project convention).
- **Gates per task:** `.venv/bin/python -m pytest tests/` (full tree),
  `ruff`, and `mypy` — all three, every task.

## Manual smoke

Add a step to `docs/manual-smoke-test.md`: open a C/C++ project with
`clangd` configured; on server start, the statusbar shows
`LSP: clangd ⚡ · <indexing fragment>` during indexing, reverting to the
plain state glyph when indexing finishes.

## Docs (doc-gate)

- `protocol-coverage.md`: add rows for `$/progress` and
  `window/workDoneProgress/create`.
- `configure.md`: document the `progress` toggle.

## Delivery

Feature branch `feat/progress` → PR targeting `main` (direct push to main
is blocked). Holds the v0.4.0 tag; the bundle is released only once
`$/progress`, `workspace/didChangeWatchedFiles`, and snippets opt-in have
all landed.
