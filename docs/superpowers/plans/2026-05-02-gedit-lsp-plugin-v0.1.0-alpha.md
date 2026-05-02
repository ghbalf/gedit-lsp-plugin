# gedit LSP Plugin v0.1.0-alpha — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an MIT-licensed Python plugin for gedit ≥ 46 that adds LSP-based diagnostics, hover, go-to-definition, and a document outline, with a single JSON config file, per-(language, project root) server lifecycle, and full-buffer document sync — all gated by automated tests and packaged as a GitHub alpha release tarball.

**Architecture:** A libpeas-1.0 Python plugin loaded into `Gedit.Window` instances. A process-global `ServerRegistry` keyed by `(language, project root)` owns one `Gio.Subprocess` per language server. A `DocumentBridge` per `GeditDocument` owns document-sync state and routes responses to four `FeatureController`s (one per LSP feature). All async I/O runs on the GLib main loop (no asyncio, no threads). All settings live in `~/.config/gedit/lsp-plugin.json`.

**Tech Stack:**
- **Language:** Python 3.10+
- **GTK stack:** PyGObject, GTK 3, GtkSourceView 4, libpeas 1.0, gedit ≥ 46 (host)
- **Test:** pytest, hypothesis, pyfakefs
- **Lint/type:** ruff, mypy
- **i18n:** gettext (xgettext + msgfmt via Makefile)
- **Build:** Makefile (no setuptools/pip — libpeas-1.0 doesn't go through pip)
- **CI:** GitHub Actions (Ubuntu runners; `python3-pylsp` for integration tests)

**Spec:** `docs/superpowers/specs/2026-05-02-gedit-lsp-plugin-design.md`

**Total milestones:** 11 (M0–M10). Each milestone produces software that runs and passes its tests. An alpha release is cut at the end of M10.

---

## File Structure

Locked in by the spec; reproduced here so each task can refer to exact paths.

### Source — `src/gedit_lsp/`

| File | Single responsibility |
|---|---|
| `__init__.py` | Re-export `GeditLspPlugin` so libpeas can find it via `Module=gedit_lsp` |
| `plugin.py` | `GeditLspPlugin` (`Gedit.WindowActivatable`) — wires everything together per window |
| `config.py` | Load + watch `~/.config/gedit/lsp-plugin.json`, merge with `defaults.py` |
| `defaults.py` | `BUILTIN_SERVERS` table, `DEFAULT_ROOT_MARKERS`, `DEFAULT_TUNABLES` |
| `registry.py` | `ServerRegistry` — process-global singleton, dict[(lang, root)] → LanguageServer, idle timer |
| `server.py` | `LanguageServer` state machine + crash recovery |
| `rpc.py` | `RpcClient` — JSON-RPC framing on `Gio.DataInputStream` / `Gio.OutputStream` |
| `bridge.py` | `DocumentBridge` — per-buffer document sync + feature routing |
| `root.py` | `ProjectRootResolver` — walk `g_file_get_parent` looking for marker files |
| `utf16.py` | `utf16_to_text_iter`, `text_iter_to_utf16` — the two pure converter functions |
| `log.py` | Two rotating logger setups (plugin + traffic) |
| `i18n.py` | gettext setup, exports `_()` |
| `features/diagnostics.py` | `DiagnosticsController` — `lsp-diag-*` text tags, gutter marks, bottom panel rows |
| `features/hover.py` | `HoverController` — Ctrl+K action, popover render |
| `features/definition.py` | `DefinitionController` — Ctrl+. action, cursor history, location popover |
| `features/outline.py` | `OutlineController` — side panel, document symbols, cursor tracking |
| `ui/statusbar.py` | Statusbar `Gtk.Label` indicator, restart popover |
| `ui/diagnostics_panel.py` | `Gedit.Window.get_bottom_panel()` `Gtk.TreeView` |
| `ui/crash_notify.py` | `Gtk.InfoBar` rendered into `Gedit.Tab.set_info_bar()` after circuit breaker trips |
| `ui/prefs.py` | Preferences dialog, reads/writes the same JSON config |

### Manifest, build, distribution

| File | Purpose |
|---|---|
| `data/gedit-lsp.plugin` | libpeas-1.0 plugin manifest |
| `Makefile` | install / uninstall / test / pot / mo / dist |
| `install.sh` | one-liner copy-paste install for end users |
| `pyproject.toml` | dev-only: pytest, hypothesis, ruff, mypy, pyfakefs |
| `LICENSE` | MIT text |
| `README.md` | elevator pitch, install one-liner, links |
| `CHANGELOG.md` | versioned release notes |
| `CONTRIBUTING.md` | brief; defers to `docs/contributing.md` |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1 |
| `.gitignore` | already exists from spec commit |
| `.editorconfig` | 4-space Python, LF line endings |
| `.github/workflows/ci.yml` | lint + unit + integration + doc-gate |
| `.github/workflows/release.yml` | tarball + checksum + GitHub Release on `v*` tag |
| `.github/ISSUE_TEMPLATE/bug_report.md` | required-fields template |
| `.github/ISSUE_TEMPLATE/feature_request.md` | feature template |

### Tests — `tests/`

| File | Pins down |
|---|---|
| `tests/unit/test_utf16.py` | UTF-16 ↔ Gtk.TextIter conversion (property-based) |
| `tests/unit/test_config.py` | Defaults load, user override merge, file-monitor reload |
| `tests/unit/test_root_resolver.py` | Marker walk, fallback, symlink resolution |
| `tests/unit/test_rpc_framing.py` | `Content-Length` framing encode/decode, split reads, malformed |
| `tests/unit/test_state_machine.py` | LanguageServer state transitions, backoff schedule |
| `tests/integration/conftest.py` | `lsp_server` pytest fixture — real `pylsp` subprocess |
| `tests/integration/test_diagnostics_e2e.py` | Open Python file with import error → tag spans correct range |
| `tests/integration/test_hover_e2e.py` | Cursor on `os.path.join` → response contains `"join"` |
| `tests/integration/test_definition_e2e.py` | Cursor on local symbol → location matches |
| `tests/integration/test_outline_e2e.py` | Class with two methods → 3-node hierarchy |
| `tests/fixtures/projects/python_basic/` | Sample project for diagnostics e2e |
| `tests/fixtures/projects/python_hover/` | Sample for hover e2e |
| `tests/fixtures/projects/python_definition/` | Sample for definition e2e |
| `tests/fixtures/projects/python_outline/` | Sample for outline e2e |

### Documentation — `docs/`

Already enumerated in spec section 15. All must exist before alpha release.

### i18n — `po/`

| File | Purpose |
|---|---|
| `po/POTFILES.in` | List of source files with translatable strings |
| `po/gedit-lsp.pot` | Generated template (regenerated by `make pot`) |
| `po/LINGUAS` | List of supported locales (empty in v0.1.0-alpha) |

---

## Milestone 0 — Project Skeleton, CI Scaffold, Repo Hygiene

**Goal:** A repository that lints clean, runs an empty test suite, and rejects PRs that fail. No gedit code yet — only scaffolding so subsequent milestones have ground to stand on.

**Exit criteria:** `make test` passes (with zero tests), `ruff check` passes, `mypy src/` passes, GitHub Actions `ci.yml` runs successfully on a no-op PR.

### Task M0.1: Create `pyproject.toml` for dev dependencies

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "gedit-lsp"
version = "0.1.0a0"
description = "Language Server Protocol client plugin for gedit"
authors = [{ name = "Alfred Mickautsch", email = "alfred@mickautsch.de" }]
license = { text = "MIT" }
requires-python = ">=3.10"
readme = "README.md"

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-cov>=4.1",
    "hypothesis>=6.92",
    "pyfakefs>=5.3",
    "ruff>=0.1.6",
    "mypy>=1.7",
    "PyGObject-stubs>=2.10",
]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM"]
ignore = ["E501"]  # line length handled by formatter

[tool.mypy]
python_version = "3.10"
strict = true
warn_unused_configs = true
disallow_untyped_defs = true
ignore_missing_imports = true  # PyGObject stubs are best-effort

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
```

- [ ] **Step 2: Verify it parses**

Run: `python -c "import tomllib; tomllib.loads(open('pyproject.toml').read())"`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pyproject.toml with dev deps and tool config"
```

### Task M0.2: Create `Makefile` with all targets

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Write `Makefile`**

```makefile
PLUGIN_NAME := gedit_lsp
PLUGIN_DIR  := $(HOME)/.local/share/gedit/plugins
VERSION     := $(shell python -c "import tomllib; print(tomllib.loads(open('pyproject.toml').read())['project']['version'])")

.PHONY: help install uninstall test test-integration lint typecheck pot mo dist clean

help:
	@echo "Targets:"
	@echo "  install            Copy plugin into $(PLUGIN_DIR)"
	@echo "  uninstall          Remove plugin and logs"
	@echo "  test               Run unit tests"
	@echo "  test-integration   Run integration tests (requires pylsp)"
	@echo "  lint               Run ruff"
	@echo "  typecheck          Run mypy"
	@echo "  pot                Regenerate po/gedit-lsp.pot"
	@echo "  mo                 Compile po/*.po → installed .mo"
	@echo "  dist               Build dist/gedit-lsp-plugin-$(VERSION).tar.gz"
	@echo "  clean              Remove build artefacts"

install:
	mkdir -p $(PLUGIN_DIR)
	cp -r src/$(PLUGIN_NAME) $(PLUGIN_DIR)/
	cp data/gedit-lsp.plugin $(PLUGIN_DIR)/
	@echo "Installed to $(PLUGIN_DIR). Restart gedit and enable in Preferences → Plugins."

uninstall:
	rm -rf $(PLUGIN_DIR)/$(PLUGIN_NAME)
	rm -f $(PLUGIN_DIR)/gedit-lsp.plugin
	rm -rf $(HOME)/.local/state/gedit-lsp
	@echo "Uninstalled. User config at ~/.config/gedit/lsp-plugin.json was NOT removed."

test:
	python -m pytest tests/unit

test-integration:
	@command -v pylsp >/dev/null 2>&1 || { echo "pylsp not on PATH; install with apt install python3-pylsp or pip install python-lsp-server" >&2; exit 1; }
	python -m pytest tests/integration

lint:
	python -m ruff check src tests

typecheck:
	python -m mypy src

pot:
	xgettext --from-code=UTF-8 --keyword=_ --output=po/gedit-lsp.pot \
	    --files-from=po/POTFILES.in --add-comments=TRANSLATORS --package-name=gedit-lsp

mo:
	@for po in po/*.po; do \
	    [ -e "$$po" ] || continue; \
	    locale=$$(basename "$$po" .po); \
	    mkdir -p "$(PLUGIN_DIR)/locale/$$locale/LC_MESSAGES"; \
	    msgfmt "$$po" -o "$(PLUGIN_DIR)/locale/$$locale/LC_MESSAGES/gedit-lsp.mo"; \
	done

dist:
	mkdir -p dist
	tar --transform 's,^,gedit-lsp-plugin-$(VERSION)/,' \
	    -czf dist/gedit-lsp-plugin-$(VERSION).tar.gz \
	    src/$(PLUGIN_NAME) data/gedit-lsp.plugin Makefile install.sh \
	    README.md LICENSE CHANGELOG.md docs po
	cd dist && sha256sum gedit-lsp-plugin-$(VERSION).tar.gz > gedit-lsp-plugin-$(VERSION).tar.gz.sha256
	@echo "Built dist/gedit-lsp-plugin-$(VERSION).tar.gz"

clean:
	rm -rf dist build *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
```

- [ ] **Step 2: Verify the help target prints**

Run: `make help`
Expected: lists all targets including `install`, `uninstall`, `test`, `dist`.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "build: add Makefile (install/test/lint/dist targets)"
```

### Task M0.3: Create empty source tree skeleton

**Files:**
- Create: `src/gedit_lsp/__init__.py`
- Create: `src/gedit_lsp/features/__init__.py`
- Create: `src/gedit_lsp/ui/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`

- [ ] **Step 1: Create the empty `__init__.py` files**

```bash
mkdir -p src/gedit_lsp/features src/gedit_lsp/ui tests/unit tests/integration tests/fixtures
touch src/gedit_lsp/features/__init__.py src/gedit_lsp/ui/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 2: Write `src/gedit_lsp/__init__.py`**

```python
"""gedit LSP plugin — Language Server Protocol client for gedit."""

__version__ = "0.1.0a0"
```

- [ ] **Step 3: Verify the package imports**

Run: `python -c "import sys; sys.path.insert(0, 'src'); import gedit_lsp; print(gedit_lsp.__version__)"`
Expected: `0.1.0a0`.

- [ ] **Step 4: Commit**

```bash
git add src tests
git commit -m "feat: add source and test package skeleton"
```

### Task M0.4: Add `.editorconfig` and standard repo hygiene files

**Files:**
- Create: `.editorconfig`
- Create: `LICENSE`
- Create: `CODE_OF_CONDUCT.md`
- Create: `CONTRIBUTING.md`
- Create: `CHANGELOG.md`
- Create: `README.md`

- [ ] **Step 1: Write `.editorconfig`**

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.py]
indent_style = space
indent_size = 4

[*.{json,yml,yaml}]
indent_style = space
indent_size = 2

[Makefile]
indent_style = tab
```

- [ ] **Step 2: Write `LICENSE`** (MIT text)

```
MIT License

Copyright (c) 2026 Alfred Mickautsch

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

NOTE ON RUNTIME COMBINATION: The plugin source code is licensed under MIT.
When the plugin is loaded into gedit at runtime via libpeas, the resulting
combined work is governed by GPL-2.0-or-later, which is gedit's licence.
The plugin source may be reused under MIT terms in any project, including
non-GPL projects. See docs/license.md for details.
```

- [ ] **Step 3: Write `CODE_OF_CONDUCT.md`** (Contributor Covenant 2.1, full text)

Use the official text from `https://www.contributor-covenant.org/version/2/1/code_of_conduct/code_of_conduct.md`. The engineer fetches it once and pastes into the file. The contact field at the bottom is `alfred@mickautsch.de`.

- [ ] **Step 4: Write `CONTRIBUTING.md`**

```markdown
# Contributing

Thank you for considering a contribution! See `docs/contributing.md` for
the full guide. The short version:

1. Open an issue describing what you want to change before sending a PR.
2. Run `make lint typecheck test` locally; CI runs the same.
3. Update relevant docs in `docs/` along with code changes — the
   `doc-gate` CI check enforces this for `src/gedit_lsp/features/`.
4. Sign your commits if you can (`git commit -s`).
```

- [ ] **Step 5: Write `CHANGELOG.md`**

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- (entries appear here as features land)

## [0.1.0-alpha] — TBD

Initial alpha release. Will be filled in at release time per docs/release.md.
```

- [ ] **Step 6: Write `README.md`** (placeholder; expanded in M10)

```markdown
# gedit LSP plugin

Language Server Protocol client for gedit ≥ 46. Adds diagnostics, hover,
go-to-definition, and a document outline.

> **Status: pre-alpha — under active development. Not ready for use.**

## Quick start

(installation instructions filled in at v0.1.0-alpha; see `docs/install.md`
once it exists).

## License

Plugin source code: MIT (see `LICENSE`).
When loaded into gedit at runtime, the combined work is governed by
GPL-2.0-or-later (gedit's licence). See `docs/license.md`.
```

- [ ] **Step 7: Commit**

```bash
git add .editorconfig LICENSE CODE_OF_CONDUCT.md CONTRIBUTING.md CHANGELOG.md README.md
git commit -m "docs: add LICENSE (MIT), CoC, CONTRIBUTING, CHANGELOG, README placeholder"
```

### Task M0.5: Add `data/gedit-lsp.plugin` manifest

**Files:**
- Create: `data/gedit-lsp.plugin`

- [ ] **Step 1: Write the plugin manifest**

```ini
[Plugin]
Module=gedit_lsp
Loader=python3
IAge=3
Name=LSP
Description=Language Server Protocol client for gedit
Authors=Alfred Mickautsch <alfred@mickautsch.de>
Copyright=Copyright © 2026 Alfred Mickautsch (MIT-licensed source; combined work GPL-2.0+)
Website=
Version=0.1.0
```

- [ ] **Step 2: Verify libpeas can parse it (sanity check via `gnome-keyfile`-style read)**

Run:
```bash
python -c "
import configparser
c = configparser.ConfigParser()
c.read('data/gedit-lsp.plugin')
assert c['Plugin']['Module'] == 'gedit_lsp'
assert c['Plugin']['Loader'] == 'python3'
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add data/gedit-lsp.plugin
git commit -m "feat: add libpeas-1.0 plugin manifest"
```

### Task M0.6: Add GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.md`

- [ ] **Step 1: Write `ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dev deps
        run: pip install -e ".[dev]"
      - name: Ruff
        run: ruff check src tests
      - name: Mypy
        run: mypy src

  unit:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install GTK / GObject introspection
        run: |
          sudo apt-get update
          sudo apt-get install -y python3-gi gir1.2-gtk-3.0 gir1.2-gtksource-4
      - name: Install dev deps
        run: pip install -e ".[dev]"
      - name: Run unit tests
        run: pytest tests/unit

  integration:
    runs-on: ubuntu-latest
    needs: [lint, unit]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install system deps
        run: |
          sudo apt-get update
          sudo apt-get install -y python3-gi gir1.2-gtk-3.0 gir1.2-gtksource-4 python3-pylsp
      - name: Install dev deps
        run: pip install -e ".[dev]"
      - name: Run integration tests
        run: pytest tests/integration

  doc-gate:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Check feature changes are accompanied by doc updates
        run: |
          base="${{ github.event.pull_request.base.sha }}"
          head="${{ github.event.pull_request.head.sha }}"
          changed=$(git diff --name-only "$base" "$head")
          if echo "$changed" | grep -q '^src/gedit_lsp/features/'; then
            if ! echo "$changed" | grep -qE '^docs/(configure|protocol-coverage)\.md$'; then
              echo "Feature code changed but no doc update under docs/configure.md or docs/protocol-coverage.md"
              echo "Changed files:"
              echo "$changed"
              exit 1
            fi
          fi
```

- [ ] **Step 2: Write `bug_report.md` issue template**

```markdown
---
name: Bug report
about: Something went wrong
labels: bug
---

## Environment

- gedit version (`gedit --version`): 
- Plugin version (from gedit Preferences → Plugins → LSP): 
- Language server name + version (e.g. `pylsp --version`): 
- OS + distro: 
- Python version (`python3 --version`): 

## What you did

(steps to reproduce)

## What you expected

(expected behaviour)

## What actually happened

(observed behaviour, screenshots if relevant)

## Logs

Plugin log (`~/.local/state/gedit-lsp/plugin.log`):

```
(paste relevant lines)
```

LSP traffic log (only if reproducible — set `"logLspTraffic": true` in your config first):

```
(paste relevant lines)
```
```

- [ ] **Step 3: Write `feature_request.md` issue template**

```markdown
---
name: Feature request
about: Suggest a new feature or enhancement
labels: enhancement
---

## Problem

(what use case is currently missing or awkward)

## Proposed solution

(what you'd like to see)

## Alternatives considered

(other approaches you thought about)

## Roadmap fit

The plan in `docs/roadmap.md` lists v0.2 and v0.3 features. Does your
request fit one of those, or is it new territory?
```

- [ ] **Step 4: Commit**

```bash
git add .github
git commit -m "ci: add GitHub Actions workflow and issue templates"
```

### Task M0.7: Verify the empty test suite runs

**Files:**
- (none — verification only)

- [ ] **Step 1: Install dev deps locally**

Run: `pip install -e ".[dev]"`
Expected: installs pytest, ruff, mypy, etc.

- [ ] **Step 2: Run tests (should be 0 passing, 0 failing — no test files yet)**

Run: `make test`
Expected: pytest reports `no tests ran in 0.0s` (or similar). Exit code 0 or 5 (no tests collected). Either is acceptable for now.

- [ ] **Step 3: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: both pass with no findings (the source tree is empty).

- [ ] **Step 4: No commit needed (verification only)**

---

## Milestone 1 — Core Utilities (utf16, RPC framing, state machine skeleton)

**Goal:** Three pure-Python modules with no GTK/gedit dependencies and exhaustive unit tests. These are the high-risk modules where bugs cause silent corruption later.

**Exit criteria:** `tests/unit/test_utf16.py`, `tests/unit/test_rpc_framing.py`, `tests/unit/test_state_machine.py` all green. Property-based tests on `utf16.py` round-trip cleanly. No `Gio.Subprocess` yet — `LanguageServer` state machine is exercised through method calls, not real I/O.

### Task M1.1: Write `utf16.py` failing tests

**Files:**
- Create: `tests/unit/test_utf16.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the LSP UTF-16 ↔ Gtk.TextIter converter.

These functions are the single highest-risk module in the plugin. A one-off
bug here turns into "go-to-definition jumps to the wrong line on files with
emoji or CJK" much later.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from hypothesis import given, settings, strategies as st
import pytest

from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter


def _buffer(text: str) -> Gtk.TextBuffer:
    buf = Gtk.TextBuffer()
    buf.set_text(text)
    return buf


@pytest.mark.parametrize(
    "text, line, char_utf16, expected_offset",
    [
        # Plain ASCII
        ("hello world", 0, 0, 0),
        ("hello world", 0, 5, 5),
        ("hello world", 0, 11, 11),
        # BMP characters (each = 1 UTF-16 code unit, but >1 byte in UTF-8)
        ("héllo", 0, 1, 1),
        ("héllo", 0, 2, 2),
        # Surrogate pair characters (1 codepoint = 2 UTF-16 code units)
        ("a🐍b", 0, 0, 0),
        ("a🐍b", 0, 1, 1),  # before snake
        ("a🐍b", 0, 3, 2),  # after snake (snake = 2 UTF-16 units)
        ("a🐍b", 0, 4, 3),  # after b
        # Multi-line
        ("line0\nline1\nline2", 1, 3, 3),
        ("line0\nline1\nline2", 2, 5, 5),
    ],
)
def test_utf16_to_text_iter_known_positions(
    text: str, line: int, char_utf16: int, expected_offset: int
) -> None:
    buf = _buffer(text)
    it = utf16_to_text_iter(buf, line, char_utf16)
    assert it.get_line() == line
    assert it.get_line_offset() == expected_offset


@pytest.mark.parametrize(
    "text, line, line_offset, expected_utf16",
    [
        ("hello", 0, 5, 5),
        ("héllo", 0, 5, 5),
        ("a🐍b", 0, 0, 0),
        ("a🐍b", 0, 1, 1),
        ("a🐍b", 0, 2, 3),  # after snake
        ("a🐍b", 0, 3, 4),
        ("line0\nline1", 1, 5, 5),
    ],
)
def test_text_iter_to_utf16_known_positions(
    text: str, line: int, line_offset: int, expected_utf16: int
) -> None:
    buf = _buffer(text)
    it = buf.get_iter_at_line_offset(line, line_offset)
    got_line, got_char = text_iter_to_utf16(it)
    assert got_line == line
    assert got_char == expected_utf16


def test_empty_buffer_position_zero() -> None:
    buf = _buffer("")
    it = utf16_to_text_iter(buf, 0, 0)
    assert it.get_line() == 0
    assert it.get_line_offset() == 0


def test_end_of_line_position() -> None:
    buf = _buffer("hello\nworld")
    it = utf16_to_text_iter(buf, 0, 5)
    assert it.get_line() == 0
    assert it.get_line_offset() == 5


@given(
    text=st.text(
        alphabet=st.characters(
            blacklist_categories=("Cs",),  # exclude lone surrogates
            blacklist_characters="\n\r",
        ),
        min_size=0,
        max_size=200,
    ),
    pos=st.integers(min_value=0, max_value=200),
)
@settings(max_examples=500, deadline=None)
def test_round_trip_iter_to_utf16_and_back(text: str, pos: int) -> None:
    """For any single-line text and any valid offset, round-tripping is identity."""
    buf = _buffer(text)
    pos = min(pos, len(text))
    original_iter = buf.get_iter_at_line_offset(0, pos)
    line, char_utf16 = text_iter_to_utf16(original_iter)
    round_tripped = utf16_to_text_iter(buf, line, char_utf16)
    assert round_tripped.get_line() == original_iter.get_line()
    assert round_tripped.get_line_offset() == original_iter.get_line_offset()


def test_surrogate_pair_alone_on_line() -> None:
    """A line containing only a surrogate-pair char must convert correctly at both ends."""
    buf = _buffer("🐍")
    start = utf16_to_text_iter(buf, 0, 0)
    end = utf16_to_text_iter(buf, 0, 2)  # snake = 2 UTF-16 units
    assert start.get_line_offset() == 0
    assert end.get_line_offset() == 1  # 1 codepoint
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_utf16.py -v`
Expected: ImportError (`gedit_lsp.utf16` does not exist yet) — or, if the module is importable but empty, AttributeError.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_utf16.py
git commit -m "test: add failing tests for utf16 converter"
```

### Task M1.2: Implement `utf16.py` to pass the tests

**Files:**
- Create: `src/gedit_lsp/utf16.py`

- [ ] **Step 1: Write the implementation**

```python
"""LSP UTF-16 position ↔ Gtk.TextIter conversion.

LSP `Position` is `(line, character)` where `character` is a UTF-16 code-unit
offset within the line. `Gtk.TextIter` works in codepoints (Python `str`
indexing), so a converter is needed at every protocol boundary.

This module is pure: no GTK widgets, no signals, no side effects. It is
exercised by property-based tests and is the highest-risk module in the
plugin — every controller goes through these two functions, never anything
else.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


def _line_end_iter(start_of_line: Gtk.TextIter) -> Gtk.TextIter:
    """Return an iter at the end of the line that `start_of_line` belongs to."""
    end = start_of_line.copy()
    if not end.ends_line():
        end.forward_to_line_end()
    return end


def utf16_to_text_iter(
    buffer: Gtk.TextBuffer, line: int, char_utf16: int
) -> Gtk.TextIter:
    """Convert an LSP `(line, character)` to a `Gtk.TextIter`.

    `character` is interpreted as a UTF-16 code-unit offset.
    """
    line_iter = buffer.get_iter_at_line(line)
    line_text = buffer.get_text(line_iter, _line_end_iter(line_iter), False)

    units = 0
    cp_offset = 0
    for ch in line_text:
        if units >= char_utf16:
            break
        units += 1 if ord(ch) < 0x10000 else 2
        cp_offset += 1

    return buffer.get_iter_at_line_offset(line, cp_offset)


def text_iter_to_utf16(it: Gtk.TextIter) -> tuple[int, int]:
    """Convert a `Gtk.TextIter` to LSP `(line, character_utf16)`."""
    line = it.get_line()
    line_start = it.get_buffer().get_iter_at_line(line)
    line_text = it.get_buffer().get_text(line_start, it, False)
    units = sum(1 if ord(ch) < 0x10000 else 2 for ch in line_text)
    return line, units
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/unit/test_utf16.py -v`
Expected: all parametrized cases pass; the property-based test runs 500 examples and passes.

- [ ] **Step 3: Run mypy**

Run: `mypy src/gedit_lsp/utf16.py`
Expected: `Success: no issues found`.

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/utf16.py
git commit -m "feat: implement utf16 converter (LSP positions ↔ Gtk.TextIter)"
```

### Task M1.3: Write `rpc.py` framing failing tests

**Files:**
- Create: `tests/unit/test_rpc_framing.py`

- [ ] **Step 1: Write failing tests for the framing helpers**

```python
"""Tests for the JSON-RPC framing helpers.

The transport itself (real GIO async I/O) is exercised in integration tests.
This file pins down the pure framing helpers: encode/decode of
`Content-Length: N\\r\\n\\r\\n<body>` messages.
"""
import pytest

from gedit_lsp.rpc import (
    FrameDecoder,
    MalformedFrameError,
    encode_frame,
)


def test_encode_simple_message() -> None:
    body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
    framed = encode_frame(body)
    assert framed == b"Content-Length: 40\r\n\r\n" + body


def test_encode_utf8_multibyte_body() -> None:
    body = '{"v":"héllo"}'.encode("utf-8")
    framed = encode_frame(body)
    # Header counts BYTES, not chars
    expected_header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    assert framed == expected_header + body


def test_decode_one_message() -> None:
    body = b'{"jsonrpc":"2.0","id":1}'
    blob = b"Content-Length: 24\r\n\r\n" + body
    dec = FrameDecoder()
    msgs = dec.feed(blob)
    assert msgs == [body]


def test_decode_multiple_messages_in_one_chunk() -> None:
    b1 = b'{"a":1}'
    b2 = b'{"b":2}'
    blob = (
        b"Content-Length: 7\r\n\r\n" + b1 +
        b"Content-Length: 7\r\n\r\n" + b2
    )
    dec = FrameDecoder()
    assert dec.feed(blob) == [b1, b2]


def test_decode_split_header() -> None:
    body = b'{"a":1}'
    dec = FrameDecoder()
    assert dec.feed(b"Content-Length: ") == []
    assert dec.feed(b"7\r\n\r\n") == []
    assert dec.feed(body) == [body]


def test_decode_split_body() -> None:
    body = b'{"a":1}'
    dec = FrameDecoder()
    assert dec.feed(b"Content-Length: 7\r\n\r\n" + body[:3]) == []
    assert dec.feed(body[3:]) == [body]


def test_decode_extra_headers_are_ignored() -> None:
    body = b'{"a":1}'
    blob = b"Content-Length: 7\r\nContent-Type: application/vscode-jsonrpc; charset=utf-8\r\n\r\n" + body
    dec = FrameDecoder()
    assert dec.feed(blob) == [body]


def test_decode_rejects_lf_only_line_endings() -> None:
    blob = b"Content-Length: 7\n\n" + b'{"a":1}'
    dec = FrameDecoder()
    with pytest.raises(MalformedFrameError):
        dec.feed(blob)


def test_decode_rejects_missing_content_length() -> None:
    blob = b"Content-Type: text/plain\r\n\r\nhello"
    dec = FrameDecoder()
    with pytest.raises(MalformedFrameError):
        dec.feed(blob)


def test_decode_rejects_non_integer_content_length() -> None:
    blob = b"Content-Length: abc\r\n\r\n"
    dec = FrameDecoder()
    with pytest.raises(MalformedFrameError):
        dec.feed(blob)
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest tests/unit/test_rpc_framing.py -v`
Expected: ImportError on `gedit_lsp.rpc`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_rpc_framing.py
git commit -m "test: add failing tests for JSON-RPC framing"
```

### Task M1.4: Implement framing in `rpc.py` (helpers only — async I/O comes later)

**Files:**
- Create: `src/gedit_lsp/rpc.py`

- [ ] **Step 1: Implement the framing helpers**

```python
"""JSON-RPC framing for LSP.

Frame format (mandated by the LSP spec):

    Content-Length: <N>\\r\\n
    [other headers]\\r\\n
    \\r\\n
    <N bytes of UTF-8 JSON body>

Headers other than `Content-Length` are ignored. Line endings must be CRLF;
LF-only is rejected as malformed.

This module exposes:
    - encode_frame(body) -> bytes
    - FrameDecoder().feed(chunk) -> list[bytes]
    - MalformedFrameError

The async transport (`RpcClient`) layers on top of these in a later task.
"""
from __future__ import annotations


class MalformedFrameError(Exception):
    """The byte stream is not a valid JSON-RPC LSP frame."""


def encode_frame(body: bytes) -> bytes:
    """Wrap a raw JSON body in the `Content-Length` framed envelope."""
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class FrameDecoder:
    """Stateful decoder that turns a byte stream into discrete JSON bodies.

    Feed any sized chunk; receive a list (possibly empty) of complete bodies.
    Partial frames are buffered internally until enough bytes arrive.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._expected_length: int | None = None

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buffer.extend(chunk)
        out: list[bytes] = []
        while True:
            if self._expected_length is None:
                # Looking for the header block.
                sep = self._buffer.find(b"\r\n\r\n")
                if sep < 0:
                    if b"\n\n" in self._buffer and b"\r\n\r\n" not in self._buffer:
                        # LF-only sequences are illegal in LSP framing.
                        raise MalformedFrameError("LF-only line endings in headers")
                    return out
                header_block = bytes(self._buffer[:sep])
                del self._buffer[: sep + 4]
                self._expected_length = self._parse_content_length(header_block)
            if self._expected_length is not None:
                if len(self._buffer) < self._expected_length:
                    return out
                body = bytes(self._buffer[: self._expected_length])
                del self._buffer[: self._expected_length]
                self._expected_length = None
                out.append(body)

    @staticmethod
    def _parse_content_length(header_block: bytes) -> int:
        for raw_line in header_block.split(b"\r\n"):
            if not raw_line:
                continue
            try:
                name, _, value = raw_line.partition(b":")
            except ValueError as exc:
                raise MalformedFrameError(f"bad header line: {raw_line!r}") from exc
            if name.strip().lower() == b"content-length":
                try:
                    return int(value.strip())
                except ValueError as exc:
                    raise MalformedFrameError(
                        f"non-integer Content-Length: {value!r}"
                    ) from exc
        raise MalformedFrameError("missing Content-Length header")
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/unit/test_rpc_framing.py -v`
Expected: all 9 tests pass.

- [ ] **Step 3: Run mypy**

Run: `mypy src/gedit_lsp/rpc.py`
Expected: `Success: no issues found`.

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/rpc.py
git commit -m "feat: implement JSON-RPC frame encoder/decoder"
```

### Task M1.5: Write `LanguageServer` state-machine failing tests

**Files:**
- Create: `tests/unit/test_state_machine.py`

These tests exercise the state machine *without* spawning a real subprocess. The implementation in M1.6 takes a `transport` callable as a constructor argument so the test can inject a fake.

- [ ] **Step 1: Write failing tests**

```python
"""Tests for LanguageServer state transitions.

The tests here use a fake transport that records outgoing messages and lets
the test push fake responses synchronously. Real subprocess and async I/O
are exercised by integration tests later.
"""
from __future__ import annotations

from typing import Any

import pytest

from gedit_lsp.server import (
    LanguageServer,
    ServerState,
)


class FakeTransport:
    """In-memory transport for state-machine tests."""

    def __init__(self) -> None:
        self.outgoing: list[dict[str, Any]] = []
        self.started = False
        self.killed = False
        self._on_response: dict[int, Any] = {}
        self._on_notification: dict[str, Any] = {}

    def start(self) -> None:
        self.started = True

    def kill(self) -> None:
        self.killed = True

    def send(self, msg: dict[str, Any]) -> None:
        self.outgoing.append(msg)

    def on_response(self, request_id: int, callback: Any) -> None:
        self._on_response[request_id] = callback

    def on_notification(self, method: str, callback: Any) -> None:
        self._on_notification[method] = callback

    def fake_response(self, request_id: int, result: Any = None, error: Any = None) -> None:
        cb = self._on_response.pop(request_id)
        cb({"id": request_id, "result": result, "error": error})

    def fake_notification(self, method: str, params: Any) -> None:
        cb = self._on_notification.get(method)
        if cb:
            cb({"method": method, "params": params})

    def fake_exit(self, code: int = 0) -> None:
        pass  # set by the test via callback wiring


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def server(transport: FakeTransport) -> LanguageServer:
    return LanguageServer(
        language_id="python",
        root_path="/tmp/proj",
        command=["pylsp"],
        initialization_options=None,
        transport_factory=lambda *a, **kw: transport,
        backoff_schedule=[1, 2, 4],
        max_restart_attempts=3,
    )


def test_initial_state_is_not_running(server: LanguageServer) -> None:
    assert server.state == ServerState.NOT_RUNNING


def test_attach_first_buffer_transitions_to_starting(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    assert server.state == ServerState.STARTING
    assert transport.started is True
    assert transport.outgoing[0]["method"] == "initialize"


def test_initialize_response_transitions_to_ready(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    init_id = transport.outgoing[0]["id"]
    transport.fake_response(init_id, result={"capabilities": {}})
    assert server.state == ServerState.READY


def test_last_buffer_detach_transitions_to_idle(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    transport.fake_response(transport.outgoing[0]["id"], result={"capabilities": {}})
    server.detach_buffer("file:///tmp/proj/a.py")
    assert server.state == ServerState.IDLE


def test_attach_during_idle_returns_to_ready(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    transport.fake_response(transport.outgoing[0]["id"], result={"capabilities": {}})
    server.detach_buffer("file:///tmp/proj/a.py")
    assert server.state == ServerState.IDLE
    server.attach_buffer("file:///tmp/proj/b.py")
    assert server.state == ServerState.READY


def test_idle_timer_expires_to_stopping(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    transport.fake_response(transport.outgoing[0]["id"], result={"capabilities": {}})
    server.detach_buffer("file:///tmp/proj/a.py")
    server._fire_idle_timer_for_test()  # synchronous test hook
    assert server.state == ServerState.STOPPING
    # Verify shutdown then exit were sent
    methods = [m.get("method") for m in transport.outgoing]
    assert "shutdown" in methods
    assert "exit" in methods


def test_subprocess_crash_from_ready_clears_state(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    transport.fake_response(transport.outgoing[0]["id"], result={"capabilities": {}})
    server._handle_subprocess_exit_for_test(exit_code=139)
    assert server.state == ServerState.NOT_RUNNING


def test_backoff_schedule_is_advanced_on_each_failure(
    server: LanguageServer, transport: FakeTransport
) -> None:
    # Force three failed starts
    for expected_backoff in [1, 2, 4]:
        server.attach_buffer("file:///tmp/proj/a.py")
        # crash before initialize completes
        server._handle_subprocess_exit_for_test(exit_code=1)
        assert server.state == ServerState.NOT_RUNNING
        assert server.next_restart_delay == expected_backoff


def test_circuit_breaker_trips_after_max_attempts(
    server: LanguageServer, transport: FakeTransport
) -> None:
    for _ in range(3):  # max_restart_attempts=3
        server.attach_buffer("file:///tmp/proj/a.py")
        server._handle_subprocess_exit_for_test(exit_code=1)
    server.attach_buffer("file:///tmp/proj/a.py")
    # Further attempts are refused until reset_circuit_breaker() is called
    assert server.state == ServerState.CIRCUIT_OPEN


def test_reset_circuit_breaker_allows_restart(
    server: LanguageServer, transport: FakeTransport
) -> None:
    for _ in range(3):
        server.attach_buffer("file:///tmp/proj/a.py")
        server._handle_subprocess_exit_for_test(exit_code=1)
    assert server.state in (ServerState.NOT_RUNNING, ServerState.CIRCUIT_OPEN)
    server.reset_circuit_breaker()
    server.attach_buffer("file:///tmp/proj/a.py")
    assert server.state == ServerState.STARTING
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest tests/unit/test_state_machine.py -v`
Expected: ImportError on `gedit_lsp.server`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_state_machine.py
git commit -m "test: add failing tests for LanguageServer state machine"
```

### Task M1.6: Implement `server.py` state machine

**Files:**
- Create: `src/gedit_lsp/server.py`

- [ ] **Step 1: Implement `ServerState` enum and `LanguageServer`**

```python
"""LanguageServer — one (lang, root) pair, one subprocess, one state machine.

This module is transport-agnostic. The constructor takes a `transport_factory`
callable which is invoked to construct the actual I/O layer. In production this
is the GLib-async `RpcClient` (Milestone 3); in tests it is a synchronous
fake.
"""
from __future__ import annotations

import enum
import itertools
from typing import Any, Callable, Protocol


class ServerState(enum.Enum):
    NOT_RUNNING = "not_running"
    STARTING = "starting"
    READY = "ready"
    IDLE = "idle"
    STOPPING = "stopping"
    CIRCUIT_OPEN = "circuit_open"


class Transport(Protocol):
    def start(self) -> None: ...
    def kill(self) -> None: ...
    def send(self, msg: dict[str, Any]) -> None: ...
    def on_response(
        self, request_id: int, callback: Callable[[dict[str, Any]], None]
    ) -> None: ...
    def on_notification(
        self, method: str, callback: Callable[[dict[str, Any]], None]
    ) -> None: ...


class LanguageServer:
    def __init__(
        self,
        language_id: str,
        root_path: str,
        command: list[str],
        initialization_options: Any,
        transport_factory: Callable[..., Transport],
        backoff_schedule: list[int],
        max_restart_attempts: int,
    ) -> None:
        self.language_id = language_id
        self.root_path = root_path
        self.command = command
        self.initialization_options = initialization_options
        self._transport_factory = transport_factory
        self._backoff_schedule = backoff_schedule
        self._max_restart_attempts = max_restart_attempts

        self.state: ServerState = ServerState.NOT_RUNNING
        self._transport: Transport | None = None
        self._attached_uris: set[str] = set()
        self._req_ids = itertools.count(1)
        self._failed_starts = 0

    @property
    def next_restart_delay(self) -> int:
        idx = min(self._failed_starts, len(self._backoff_schedule) - 1)
        return self._backoff_schedule[idx]

    def attach_buffer(self, uri: str) -> None:
        if self.state == ServerState.CIRCUIT_OPEN:
            return
        self._attached_uris.add(uri)
        if self.state in (ServerState.NOT_RUNNING,):
            self._spawn_and_initialize()
        elif self.state == ServerState.IDLE:
            self.state = ServerState.READY
            # (real impl cancels idle timer here)

    def detach_buffer(self, uri: str) -> None:
        self._attached_uris.discard(uri)
        if not self._attached_uris and self.state == ServerState.READY:
            self.state = ServerState.IDLE
            # (real impl starts idle timer here)

    def reset_circuit_breaker(self) -> None:
        self._failed_starts = 0
        if self.state == ServerState.CIRCUIT_OPEN:
            self.state = ServerState.NOT_RUNNING

    # --- internal ---

    def _spawn_and_initialize(self) -> None:
        self.state = ServerState.STARTING
        self._transport = self._transport_factory()
        self._transport.start()
        req_id = next(self._req_ids)
        self._transport.on_response(req_id, self._on_initialize_response)
        self._transport.on_notification(
            "textDocument/publishDiagnostics", self._on_diagnostics
        )
        self._transport.send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "initialize",
                "params": self._initialize_params(),
            }
        )

    def _initialize_params(self) -> dict[str, Any]:
        return {
            "processId": None,
            "rootUri": f"file://{self.root_path}",
            "capabilities": {},
            "initializationOptions": self.initialization_options,
        }

    def _on_initialize_response(self, msg: dict[str, Any]) -> None:
        if msg.get("error"):
            self._handle_failed_start()
            return
        # Send `initialized` notification per LSP spec.
        assert self._transport is not None
        self._transport.send(
            {"jsonrpc": "2.0", "method": "initialized", "params": {}}
        )
        self._failed_starts = 0
        self.state = ServerState.READY

    def _on_diagnostics(self, msg: dict[str, Any]) -> None:
        # Routed to controllers via signal in real impl; no-op in state machine
        pass

    def _handle_failed_start(self) -> None:
        self._failed_starts += 1
        if self._failed_starts >= self._max_restart_attempts:
            self.state = ServerState.CIRCUIT_OPEN
        else:
            self.state = ServerState.NOT_RUNNING

    # --- test hooks (named with `_for_test` to make their purpose obvious) ---

    def _fire_idle_timer_for_test(self) -> None:
        assert self.state == ServerState.IDLE
        self._begin_shutdown()

    def _handle_subprocess_exit_for_test(self, exit_code: int) -> None:
        if self.state == ServerState.STARTING and exit_code != 0:
            self._handle_failed_start()
            return
        # Crash from READY/IDLE
        self._failed_starts += 1
        if self._failed_starts >= self._max_restart_attempts:
            self.state = ServerState.CIRCUIT_OPEN
        else:
            self.state = ServerState.NOT_RUNNING

    def _begin_shutdown(self) -> None:
        self.state = ServerState.STOPPING
        assert self._transport is not None
        req_id = next(self._req_ids)
        self._transport.on_response(req_id, lambda _msg: None)
        self._transport.send(
            {"jsonrpc": "2.0", "id": req_id, "method": "shutdown", "params": None}
        )
        self._transport.send({"jsonrpc": "2.0", "method": "exit", "params": None})
        self._transport.kill()
        self.state = ServerState.NOT_RUNNING
```

- [ ] **Step 2: Run state-machine tests**

Run: `pytest tests/unit/test_state_machine.py -v`
Expected: all tests pass.

- [ ] **Step 3: Run mypy on the whole module**

Run: `mypy src/gedit_lsp/server.py`
Expected: `Success: no issues found`.

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/server.py
git commit -m "feat: implement LanguageServer state machine (transport-agnostic)"
```

### Task M1.7: Run the full M1 suite + lint + typecheck

- [ ] **Step 1: Verify everything still passes**

Run: `make test && make lint && make typecheck`
Expected: all green. Test count ≥ 30 (utf16 parametrized + property + framing + state machine).

- [ ] **Step 2: No commit needed**

---

## Milestone 2 — Configuration and Project Root Resolver

**Goal:** Two more pure modules: `defaults.py` (the built-in tables), `config.py` (loader + file monitor + merge), and `root.py` (project-root walk). All exercised by unit tests on tmp directories.

**Exit criteria:** `tests/unit/test_config.py` and `tests/unit/test_root_resolver.py` green.

### Task M2.1: Write `defaults.py`

**Files:**
- Create: `src/gedit_lsp/defaults.py`

- [ ] **Step 1: Write the defaults**

```python
"""Built-in defaults for the gedit LSP plugin.

Users override any subset via ~/.config/gedit/lsp-plugin.json. See
docs/configure.md for the merge policy.
"""
from __future__ import annotations

from typing import Any

BUILTIN_SERVERS: dict[str, dict[str, Any]] = {
    "python":     {"command": ["pylsp"]},
    "c":          {"command": ["clangd", "--background-index"]},
    "cpp":        {"command": ["clangd", "--background-index"]},
    "rust":       {"command": ["rust-analyzer"]},
    "go":         {"command": ["gopls"]},
    "typescript": {"command": ["typescript-language-server", "--stdio"]},
    "js":         {"command": ["typescript-language-server", "--stdio"]},
    "sh":         {"command": ["bash-language-server", "start"]},
}

DEFAULT_ROOT_MARKERS: list[str] = [
    ".git", ".hg", ".svn",
    "pyproject.toml", "setup.py", "Pipfile",
    "Cargo.toml",
    "go.mod",
    "package.json",
    "compile_commands.json", "CMakeLists.txt",
    "Makefile",
]

DEFAULT_TUNABLES: dict[str, Any] = {
    "serverIdleTimeoutSeconds": 300,
    "changeDebounceMs": 150,
    "outlineRefreshDebounceMs": 2000,
    "outlineInitialDelayMs": 1000,
    "hoverSpinnerThresholdMs": 300,
    "requestTimeoutMs": 10000,
    "gotoHistoryMaxEntries": 50,
    "restartBackoffSchedule": [1, 2, 4, 8, 16, 30],
    "restartMaxAttempts": 5,
    "logLevel": "info",
    "logRotationMaxBytes": 5_242_880,
    "logRotationKeepFiles": 3,
    "logLspTraffic": False,
    "maxFileSizeBytes": 5_242_880,
    "showStatusbarIndicator": True,
    "enabledFeatures": ["diagnostics", "hover", "definition", "outline"],
    "severityIcons": {
        "error":   "dialog-error-symbolic",
        "warning": "dialog-warning-symbolic",
        "info":    "dialog-information-symbolic",
        "hint":    "dialog-information-symbolic",
    },
    "severityUnderlineStyle": {
        "error":   "error",
        "warning": "error",
        "info":    "single",
        "hint":    "single",
    },
    "disabledForPaths": [
        "**/.venv/**",
        "**/node_modules/**",
        "**/.tox/**",
        "**/dist/**",
        "**/build/**",
    ],
    "serverCapabilityOverrides": {},
}
```

- [ ] **Step 2: Smoke-import**

Run: `python -c "from gedit_lsp.defaults import BUILTIN_SERVERS, DEFAULT_TUNABLES; print(len(BUILTIN_SERVERS), len(DEFAULT_TUNABLES))"`
Expected: `8 19` (or whatever the current counts are — just verifies no syntax error).

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/defaults.py
git commit -m "feat: add built-in defaults table"
```

### Task M2.2: Write `config.py` failing tests

**Files:**
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the Config loader and merge policy."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gedit_lsp.config import Config, ConfigError


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj))


def test_no_user_file_uses_defaults_only(tmp_path: Path) -> None:
    cfg = Config(user_path=tmp_path / "missing.json")
    cfg.load()
    assert cfg.server_for("python")["command"] == ["pylsp"]


def test_user_override_replaces_server_command(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"servers": {"python": {"command": ["pyright-langserver", "--stdio"]}}})
    cfg = Config(user_path=user)
    cfg.load()
    assert cfg.server_for("python")["command"] == ["pyright-langserver", "--stdio"]


def test_user_override_does_not_affect_other_languages(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"servers": {"python": {"command": ["pyright-langserver"]}}})
    cfg = Config(user_path=user)
    cfg.load()
    # Rust still uses default
    assert cfg.server_for("rust")["command"] == ["rust-analyzer"]


def test_unknown_language_returns_none(tmp_path: Path) -> None:
    cfg = Config(user_path=tmp_path / "missing.json")
    cfg.load()
    assert cfg.server_for("brainfuck") is None


def test_user_can_add_new_language(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"servers": {"haskell": {"command": ["haskell-language-server-wrapper", "--lsp"]}}})
    cfg = Config(user_path=user)
    cfg.load()
    assert cfg.server_for("haskell")["command"] == [
        "haskell-language-server-wrapper", "--lsp"
    ]


def test_malformed_json_raises_with_path(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    user.write_text("{not valid json")
    cfg = Config(user_path=user)
    with pytest.raises(ConfigError) as exc:
        cfg.load()
    assert str(user) in str(exc.value)


def test_root_markers_per_language_override_default(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"rootMarkers": {"python": ["only-pyproject.toml"]}})
    cfg = Config(user_path=user)
    cfg.load()
    assert cfg.root_markers_for("python") == ["only-pyproject.toml"]
    # Other languages still use the default merged list
    assert ".git" in cfg.root_markers_for("rust")


def test_tunables_user_override_replaces_value(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"tunables": {"changeDebounceMs": 500}})
    cfg = Config(user_path=user)
    cfg.load()
    assert cfg.tunable("changeDebounceMs") == 500
    # Untouched tunable retains default
    assert cfg.tunable("serverIdleTimeoutSeconds") == 300


def test_capability_overrides_deep_merged(tmp_path: Path) -> None:
    """serverCapabilityOverrides is per-key replacement at every depth."""
    user = tmp_path / "lsp-plugin.json"
    write_json(
        user,
        {"tunables": {"serverCapabilityOverrides": {"python": {"hoverProvider": False}}}},
    )
    cfg = Config(user_path=user)
    cfg.load()
    overrides = cfg.tunable("serverCapabilityOverrides")
    assert overrides["python"]["hoverProvider"] is False


def test_initialization_options_user_override(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(
        user,
        {"initializationOptions": {"python": {"plugins": {"pycodestyle": {"enabled": False}}}}},
    )
    cfg = Config(user_path=user)
    cfg.load()
    init_opts = cfg.initialization_options_for("python")
    assert init_opts["plugins"]["pycodestyle"]["enabled"] is False


def test_initialization_options_none_for_missing_language(tmp_path: Path) -> None:
    cfg = Config(user_path=tmp_path / "missing.json")
    cfg.load()
    assert cfg.initialization_options_for("python") is None
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest tests/unit/test_config.py -v`
Expected: ImportError on `gedit_lsp.config`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_config.py
git commit -m "test: add failing tests for Config loader"
```

### Task M2.3: Implement `config.py`

**Files:**
- Create: `src/gedit_lsp/config.py`

- [ ] **Step 1: Implement `Config`**

```python
"""Config loader and accessors.

Loads ~/.config/gedit/lsp-plugin.json and merges it with the built-in
defaults. The merge policy is intentionally simple:

    servers          — full replacement at language-key level (no per-key merge)
    rootMarkers      — full replacement at language-key level
    initializationOptions — full replacement at language-key level
    tunables         — per-key replacement (top level only)
    serverCapabilityOverrides — preserved verbatim; deep-merge into the
                       server's claimed capabilities is performed by the
                       LanguageServer at initialize time.

Reload-on-change wiring (Gio.FileMonitor) is added in Task M2.4.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from gedit_lsp.defaults import BUILTIN_SERVERS, DEFAULT_ROOT_MARKERS, DEFAULT_TUNABLES


class ConfigError(Exception):
    """Could not load the user config file."""


class Config:
    def __init__(self, user_path: Path) -> None:
        self._user_path = user_path
        self._servers: dict[str, dict[str, Any]] = {}
        self._root_markers: dict[str, list[str]] = {}
        self._initialization_options: dict[str, Any] = {}
        self._tunables: dict[str, Any] = {}

    def load(self) -> None:
        self._servers = copy.deepcopy(BUILTIN_SERVERS)
        self._root_markers = {}
        self._initialization_options = {}
        self._tunables = copy.deepcopy(DEFAULT_TUNABLES)

        if not self._user_path.exists():
            return

        try:
            user = json.loads(self._user_path.read_text())
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"failed to parse {self._user_path}: {exc.msg} at line {exc.lineno}"
            ) from exc

        for lang, entry in (user.get("servers") or {}).items():
            self._servers[lang] = entry  # full replacement

        for lang, markers in (user.get("rootMarkers") or {}).items():
            self._root_markers[lang] = list(markers)

        for lang, opts in (user.get("initializationOptions") or {}).items():
            self._initialization_options[lang] = opts

        for k, v in (user.get("tunables") or {}).items():
            self._tunables[k] = v

    def server_for(self, language_id: str) -> dict[str, Any] | None:
        return self._servers.get(language_id)

    def root_markers_for(self, language_id: str) -> list[str]:
        return self._root_markers.get(language_id, list(DEFAULT_ROOT_MARKERS))

    def initialization_options_for(self, language_id: str) -> Any:
        return self._initialization_options.get(language_id)

    def tunable(self, key: str) -> Any:
        return self._tunables[key]
```

- [ ] **Step 2: Run config tests**

Run: `pytest tests/unit/test_config.py -v`
Expected: all 11 tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/config.py
git commit -m "feat: implement Config loader (defaults + user JSON merge)"
```

### Task M2.4: Add file-monitor reload to `Config`

**Files:**
- Modify: `src/gedit_lsp/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Add a failing reload test**

Append to `tests/unit/test_config.py`:

```python
def test_reload_picks_up_changes(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"servers": {"python": {"command": ["a"]}}})
    cfg = Config(user_path=user)
    cfg.load()
    assert cfg.server_for("python")["command"] == ["a"]

    write_json(user, {"servers": {"python": {"command": ["b"]}}})
    cfg.load()  # explicit reload
    assert cfg.server_for("python")["command"] == ["b"]


def test_observer_called_on_reload(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {})
    cfg = Config(user_path=user)
    cfg.load()
    calls: list[str] = []
    cfg.add_observer(lambda: calls.append("reload"))
    write_json(user, {"servers": {"python": {"command": ["x"]}}})
    cfg.load()
    assert calls == ["reload"]
```

- [ ] **Step 2: Verify the new tests fail**

Run: `pytest tests/unit/test_config.py::test_observer_called_on_reload -v`
Expected: AttributeError on `add_observer`.

- [ ] **Step 3: Add observer support to `Config`**

In `src/gedit_lsp/config.py`, modify the class:

```python
class Config:
    def __init__(self, user_path: Path) -> None:
        self._user_path = user_path
        self._servers: dict[str, dict[str, Any]] = {}
        self._root_markers: dict[str, list[str]] = {}
        self._initialization_options: dict[str, Any] = {}
        self._tunables: dict[str, Any] = {}
        self._observers: list[Any] = []

    def add_observer(self, callback: Any) -> None:
        self._observers.append(callback)

    def load(self) -> None:
        # ... existing body ...
        for cb in self._observers:
            cb()
```

(The actual `Gio.FileMonitor` wiring is added in M3 when we have a real GLib main loop running. For unit tests, explicit `cfg.load()` is sufficient.)

- [ ] **Step 4: Run the new tests**

Run: `pytest tests/unit/test_config.py -v`
Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/gedit_lsp/config.py tests/unit/test_config.py
git commit -m "feat(config): add observer pattern for reloads"
```

### Task M2.5: Write `root.py` failing tests

**Files:**
- Create: `tests/unit/test_root_resolver.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for project-root resolution.

Walks the directory tree upward from a buffer's file looking for marker
files, falling back to the file's own parent directory if nothing is
found.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gedit_lsp.root import ProjectRootResolver


@pytest.fixture
def resolver() -> ProjectRootResolver:
    return ProjectRootResolver(markers=[".git", "pyproject.toml", "Cargo.toml"])


def test_marker_in_immediate_parent(tmp_path: Path, resolver: ProjectRootResolver) -> None:
    (tmp_path / ".git").mkdir()
    fn = tmp_path / "src" / "a.py"
    fn.parent.mkdir(parents=True)
    fn.write_text("")
    assert resolver.resolve(fn) == tmp_path


def test_no_marker_falls_back_to_file_parent(
    tmp_path: Path, resolver: ProjectRootResolver
) -> None:
    fn = tmp_path / "loose.py"
    fn.write_text("")
    assert resolver.resolve(fn) == tmp_path


def test_inner_marker_wins_over_outer(
    tmp_path: Path, resolver: ProjectRootResolver
) -> None:
    (tmp_path / ".git").mkdir()
    inner = tmp_path / "subproj"
    (inner / "pyproject.toml").parent.mkdir()
    (inner / "pyproject.toml").write_text("")
    fn = inner / "src" / "a.py"
    fn.parent.mkdir(parents=True)
    fn.write_text("")
    assert resolver.resolve(fn) == inner


def test_walk_stops_at_filesystem_root_or_home(
    tmp_path: Path, resolver: ProjectRootResolver
) -> None:
    fn = tmp_path / "deep" / "deep" / "deep" / "a.py"
    fn.parent.mkdir(parents=True)
    fn.write_text("")
    # No markers anywhere — falls back to file's parent
    assert resolver.resolve(fn) == fn.parent


def test_symlinked_dir_resolved_to_real_path(
    tmp_path: Path, resolver: ProjectRootResolver
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / ".git").mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    fn = link / "a.py"
    fn.write_text("")
    assert resolver.resolve(fn) == real.resolve()


def test_first_marker_in_list_wins_at_same_level(tmp_path: Path) -> None:
    """If a directory has multiple markers, the resolver still returns that
    directory — order in the markers list doesn't change the answer for a
    single level."""
    resolver = ProjectRootResolver(markers=[".git", "pyproject.toml"])
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("")
    fn = tmp_path / "a.py"
    fn.write_text("")
    assert resolver.resolve(fn) == tmp_path
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest tests/unit/test_root_resolver.py -v`
Expected: ImportError on `gedit_lsp.root`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_root_resolver.py
git commit -m "test: add failing tests for project root resolver"
```

### Task M2.6: Implement `root.py`

**Files:**
- Create: `src/gedit_lsp/root.py`

- [ ] **Step 1: Implement the resolver**

```python
"""Project-root resolution.

Walks upward from a buffer's file looking for any of the configured marker
files. Stops at the user's home directory or the filesystem root and
falls back to the file's own parent directory if no marker is found.

Symlinks are resolved before walking so the same physical file always
maps to the same root, regardless of which symlink path the user opened.
"""
from __future__ import annotations

import os
from pathlib import Path


class ProjectRootResolver:
    def __init__(self, markers: list[str]) -> None:
        self._markers = list(markers)

    def resolve(self, file_path: Path) -> Path:
        path = file_path.resolve()
        if path.is_file():
            current = path.parent
        else:
            current = path
        home = Path.home().resolve()
        fs_root = Path(path.anchor).resolve()
        while True:
            for marker in self._markers:
                if (current / marker).exists():
                    return current
            if current == home or current == fs_root:
                return path.parent
            parent = current.parent
            if parent == current:
                return path.parent
            current = parent
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/unit/test_root_resolver.py -v`
Expected: all 6 tests pass.

- [ ] **Step 3: Run mypy**

Run: `mypy src/gedit_lsp/root.py`
Expected: `Success: no issues found`.

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/root.py
git commit -m "feat: implement ProjectRootResolver"
```

### Task M2.7: M2 sweep

- [ ] **Step 1: Run everything**

Run: `make lint typecheck test`
Expected: all green. Test count ≥ 50.

---

## Milestone 3 — LanguageServer Real I/O + ServerRegistry + Logging

**Goal:** Wire real `Gio.Subprocess` + `Gio.DataInputStream` async I/O to `LanguageServer`, build the process-global `ServerRegistry`, and stand up the two log streams (`plugin.log`, `lsp-traffic.log`).

**Exit criteria:** A smoke script in `tests/smoke/spawn_pylsp.py` spawns `pylsp`, completes `initialize`, prints the server's reported capabilities, then shuts it down cleanly via `shutdown` + `exit`. New `tests/unit/test_registry.py` asserts `(lang, root)` keying. `tests/unit/test_log.py` asserts both log streams are created with rotation.

### Task M3.1: Implement `log.py` and tests

**Files:**
- Create: `src/gedit_lsp/log.py`
- Create: `tests/unit/test_log.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for the log setup."""
from __future__ import annotations

from pathlib import Path

from gedit_lsp.log import setup_logging


def test_creates_state_dir_and_plugin_log(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    setup_logging(state_dir, level="info", traffic_enabled=False, max_bytes=1024, keep=2)
    assert (state_dir / "plugin.log").exists()


def test_traffic_log_only_when_enabled(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    setup_logging(state_dir, level="info", traffic_enabled=False, max_bytes=1024, keep=2)
    assert not (state_dir / "lsp-traffic.log").exists()
    setup_logging(state_dir, level="info", traffic_enabled=True, max_bytes=1024, keep=2)
    assert (state_dir / "lsp-traffic.log").exists()


def test_plugin_log_records_have_levels(tmp_path: Path) -> None:
    import logging
    state_dir = tmp_path / "state"
    setup_logging(state_dir, level="debug", traffic_enabled=False, max_bytes=1024, keep=2)
    logging.getLogger("gedit_lsp").info("hello")
    logging.shutdown()
    text = (state_dir / "plugin.log").read_text()
    assert "INFO" in text
    assert "hello" in text
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/unit/test_log.py -v`
Expected: ImportError on `gedit_lsp.log`.

- [ ] **Step 3: Implement `log.py`**

```python
"""Two log streams: plugin diagnostic + LSP traffic.

The plugin log uses standard Python `logging` with a `RotatingFileHandler`.
The traffic log is line-streamed (one wire message per line) and uses a
small custom rotator so we don't pay record-formatting overhead.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO


_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


_traffic_file: IO[str] | None = None
_traffic_path: Path | None = None
_traffic_max_bytes: int = 5_242_880
_traffic_keep: int = 3


def setup_logging(
    state_dir: Path,
    level: str,
    traffic_enabled: bool,
    max_bytes: int,
    keep: int,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    plugin_log = state_dir / "plugin.log"

    logger = logging.getLogger("gedit_lsp")
    logger.setLevel(_LEVELS.get(level, logging.INFO))
    # Remove any prior handlers (idempotent)
    for h in list(logger.handlers):
        logger.removeHandler(h)
    handler = RotatingFileHandler(
        plugin_log, maxBytes=max_bytes, backupCount=keep, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)

    global _traffic_file, _traffic_path, _traffic_max_bytes, _traffic_keep
    _traffic_max_bytes = max_bytes
    _traffic_keep = keep
    if _traffic_file is not None:
        _traffic_file.close()
        _traffic_file = None
    if traffic_enabled:
        _traffic_path = state_dir / "lsp-traffic.log"
        _traffic_file = open(_traffic_path, "a", encoding="utf-8")


def write_traffic(direction: str, prefix: str, ts_ms: float, body: bytes) -> None:
    """Append one wire message to the traffic log.

    `direction` is `>>>` (client → server) or `<<<` (server → client).
    `prefix` is `[<lang>:<root-basename>]`.
    """
    global _traffic_file, _traffic_path
    if _traffic_file is None or _traffic_path is None:
        return
    line = f"{direction} {ts_ms:013.3f} {prefix} {body.decode('utf-8', 'replace')}\n"
    _traffic_file.write(line)
    _traffic_file.flush()
    if _traffic_path.stat().st_size >= _traffic_max_bytes:
        _rotate_traffic()


def _rotate_traffic() -> None:
    global _traffic_file, _traffic_path
    assert _traffic_path is not None
    _traffic_file.close() if _traffic_file else None
    for i in range(_traffic_keep, 0, -1):
        src = _traffic_path.with_suffix(_traffic_path.suffix + f".{i - 1}") if i > 1 else _traffic_path
        dst = _traffic_path.with_suffix(_traffic_path.suffix + f".{i}")
        if src.exists():
            src.replace(dst)
    _traffic_file = open(_traffic_path, "a", encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_log.py -v`
Expected: all 3 pass.

- [ ] **Step 5: Commit**

```bash
git add src/gedit_lsp/log.py tests/unit/test_log.py
git commit -m "feat: implement plugin and traffic log streams with rotation"
```

### Task M3.2: Implement `RpcClient` (real GIO transport)

**Files:**
- Modify: `src/gedit_lsp/rpc.py`

The framing helpers from M1.4 stay; we add the `RpcClient` class on top.

- [ ] **Step 1: Append `RpcClient` to `src/gedit_lsp/rpc.py`**

Add to the bottom of the existing file:

```python
import json
import time
from typing import Any, Callable

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gio

from gedit_lsp.log import write_traffic


class RpcClient:
    """Async JSON-RPC 2.0 client over a GIO subprocess.

    Reads via `Gio.DataInputStream.read_line_async` for headers,
    `Gio.InputStream.read_bytes_async` for bodies. Writes are FIFO-
    serialized through a single `write_bytes_async` chain.
    """

    def __init__(
        self,
        command: list[str],
        log_prefix: str,
        on_request: Callable[[dict[str, Any]], None] | None = None,
        on_notification_default: Callable[[dict[str, Any]], None] | None = None,
        on_exit: Callable[[int], None] | None = None,
    ) -> None:
        self._command = command
        self._log_prefix = log_prefix
        self._on_request = on_request
        self._on_notification_default = on_notification_default
        self._on_exit = on_exit

        self._proc: Gio.Subprocess | None = None
        self._stdout: Gio.DataInputStream | None = None
        self._stdin: Gio.OutputStream | None = None
        self._decoder = FrameDecoder()
        self._response_callbacks: dict[int, Callable[[dict[str, Any]], None]] = {}
        self._notification_callbacks: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._write_queue: list[bytes] = []
        self._writing = False

    def start(self) -> None:
        flags = (
            Gio.SubprocessFlags.STDIN_PIPE
            | Gio.SubprocessFlags.STDOUT_PIPE
            | Gio.SubprocessFlags.STDERR_PIPE
        )
        self._proc = Gio.Subprocess.new(self._command, flags)
        self._stdin = self._proc.get_stdin_pipe()
        self._stdout = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        self._stdout.set_newline_type(Gio.DataStreamNewlineType.CR_LF)
        self._proc.wait_check_async(None, self._on_subprocess_exit)
        self._read_header_line()

    def kill(self) -> None:
        if self._proc is not None:
            self._proc.force_exit()

    def send(self, msg: dict[str, Any]) -> None:
        body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        write_traffic(">>>", self._log_prefix, time.monotonic() * 1000.0, body)
        framed = encode_frame(body)
        self._write_queue.append(framed)
        self._pump_writes()

    def on_response(
        self, request_id: int, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        self._response_callbacks[request_id] = callback

    def on_notification(
        self, method: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        self._notification_callbacks[method] = callback

    # --- internals ---

    def _pump_writes(self) -> None:
        if self._writing or not self._write_queue or self._stdin is None:
            return
        self._writing = True
        chunk = self._write_queue.pop(0)
        self._stdin.write_bytes_async(
            GLib.Bytes.new(chunk), GLib.PRIORITY_DEFAULT, None, self._on_write_done
        )

    def _on_write_done(self, source: Any, res: Any) -> None:
        try:
            source.write_bytes_finish(res)
        except GLib.Error as exc:
            logging.getLogger("gedit_lsp").warning("write failed: %s", exc.message)
        self._writing = False
        self._pump_writes()

    def _read_header_line(self) -> None:
        assert self._stdout is not None
        self._stdout.read_line_async(
            GLib.PRIORITY_DEFAULT, None, self._on_header_line
        )

    def _on_header_line(self, source: Any, res: Any) -> None:
        try:
            line, _length = source.read_line_finish_utf8(res)
        except GLib.Error:
            return
        if line is None:
            return
        chunk = (line + "\r\n").encode("ascii")
        msgs = self._decoder.feed(chunk)
        if msgs:
            for body in msgs:
                self._dispatch(body)
        # Read body if header block completed
        if self._decoder._expected_length is not None:  # type: ignore[attr-defined]
            self._read_body(self._decoder._expected_length - len(self._decoder._buffer))  # type: ignore[attr-defined]
        else:
            self._read_header_line()

    def _read_body(self, remaining: int) -> None:
        assert self._stdout is not None
        self._stdout.read_bytes_async(
            remaining, GLib.PRIORITY_DEFAULT, None, self._on_body
        )

    def _on_body(self, source: Any, res: Any) -> None:
        try:
            chunk = source.read_bytes_finish(res).get_data() or b""
        except GLib.Error:
            return
        msgs = self._decoder.feed(chunk)
        for body in msgs:
            self._dispatch(body)
        self._read_header_line()

    def _dispatch(self, body: bytes) -> None:
        write_traffic("<<<", self._log_prefix, time.monotonic() * 1000.0, body)
        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            logging.getLogger("gedit_lsp").warning("malformed JSON from server")
            return
        if "id" in msg and "method" not in msg:
            cb = self._response_callbacks.pop(msg["id"], None)
            if cb is not None:
                cb(msg)
        elif "method" in msg and "id" not in msg:
            cb_n = self._notification_callbacks.get(msg["method"])
            if cb_n is not None:
                cb_n(msg)
            elif self._on_notification_default is not None:
                self._on_notification_default(msg)
        elif "method" in msg and "id" in msg:
            if self._on_request is not None:
                self._on_request(msg)

    def _on_subprocess_exit(self, source: Any, res: Any) -> None:
        try:
            self._proc.wait_check_finish(res) if self._proc else None
            code = 0
        except GLib.Error as exc:
            code = exc.code or 1
        if self._on_exit is not None:
            self._on_exit(code)
```

Note: This implementation uses GLib `read_line_async`, which strips the CR/LF on read. We re-feed `line + "\r\n"` into the decoder so its CRLF handling stays the same; this is the simplest way to keep the framing module CRLF-strict without writing a separate non-line-aware reader.

- [ ] **Step 2: Verify framing tests still pass**

Run: `pytest tests/unit/test_rpc_framing.py -v`
Expected: all framing tests still green (we only added a class, didn't change the existing helpers).

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/rpc.py
git commit -m "feat(rpc): add RpcClient async transport over GIO subprocess"
```

### Task M3.3: Wire real transport into `LanguageServer`

**Files:**
- Modify: `src/gedit_lsp/server.py`

- [ ] **Step 1: Add a real-transport factory and idle timer**

Modify `src/gedit_lsp/server.py`. Replace the existing class body to add:

1. A real-transport factory that constructs an `RpcClient`.
2. A GLib `Timeout` for the idle timer.
3. A `_handle_subprocess_exit` slot that the `RpcClient.on_exit` callback calls.

Add at the top of the file:

```python
import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gedit_lsp.rpc import RpcClient
```

Add a factory helper:

```python
def real_transport_factory(
    command: list[str],
    log_prefix: str,
    on_exit: Callable[[int], None],
) -> RpcClient:
    return RpcClient(command=command, log_prefix=log_prefix, on_exit=on_exit)
```

Add an idle-timer field and wire it. Modify `detach_buffer`:

```python
    def detach_buffer(self, uri: str) -> None:
        self._attached_uris.discard(uri)
        if not self._attached_uris and self.state == ServerState.READY:
            self.state = ServerState.IDLE
            self._idle_source_id = GLib.timeout_add_seconds(
                self._idle_timeout_seconds, self._on_idle_timer
            )
```

Add `_idle_timeout_seconds` to `__init__` (with a sensible default; passed in by registry):

```python
        self._idle_timeout_seconds = idle_timeout_seconds
        self._idle_source_id: int | None = None

    def _on_idle_timer(self) -> bool:
        if self.state == ServerState.IDLE:
            self._begin_shutdown()
        self._idle_source_id = None
        return False  # don't repeat
```

Modify `attach_buffer` to cancel the idle timer when re-attaching:

```python
        elif self.state == ServerState.IDLE:
            if self._idle_source_id is not None:
                GLib.source_remove(self._idle_source_id)
                self._idle_source_id = None
            self.state = ServerState.READY
```

- [ ] **Step 2: Run state-machine tests**

Run: `pytest tests/unit/test_state_machine.py -v`
Expected: still pass (the test fake `transport_factory` ignores the new constructor arg via `**kw`).

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/server.py
git commit -m "feat(server): wire real RpcClient transport and idle timer"
```

### Task M3.4: Implement `ServerRegistry` and tests

**Files:**
- Create: `src/gedit_lsp/registry.py`
- Create: `tests/unit/test_registry.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for ServerRegistry — the (lang, root) → LanguageServer map."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gedit_lsp.config import Config
from gedit_lsp.registry import ServerRegistry


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config(user_path=tmp_path / "missing.json")
    c.load()
    return c


def test_same_lang_same_root_returns_same_server(cfg: Config) -> None:
    reg = ServerRegistry(config=cfg, transport_factory=MagicMock())
    s1 = reg.get_or_spawn("python", Path("/tmp/proj"))
    s2 = reg.get_or_spawn("python", Path("/tmp/proj"))
    assert s1 is s2


def test_same_lang_different_root_returns_different_server(cfg: Config) -> None:
    reg = ServerRegistry(config=cfg, transport_factory=MagicMock())
    s1 = reg.get_or_spawn("python", Path("/tmp/projA"))
    s2 = reg.get_or_spawn("python", Path("/tmp/projB"))
    assert s1 is not s2


def test_different_lang_same_root_returns_different_server(cfg: Config) -> None:
    reg = ServerRegistry(config=cfg, transport_factory=MagicMock())
    s1 = reg.get_or_spawn("python", Path("/tmp/proj"))
    s2 = reg.get_or_spawn("c", Path("/tmp/proj"))
    assert s1 is not s2


def test_no_server_configured_returns_none(cfg: Config) -> None:
    reg = ServerRegistry(config=cfg, transport_factory=MagicMock())
    assert reg.get_or_spawn("brainfuck", Path("/tmp/proj")) is None
```

- [ ] **Step 2: Implement `registry.py`**

```python
"""Process-global ServerRegistry.

Maps `(language_id, root_path)` → `LanguageServer`. Constructs servers
lazily; once a server exists for a key, future requests reuse it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from gedit_lsp.config import Config
from gedit_lsp.server import LanguageServer, Transport


class ServerRegistry:
    def __init__(
        self,
        config: Config,
        transport_factory: Callable[..., Transport],
    ) -> None:
        self._config = config
        self._transport_factory = transport_factory
        self._servers: dict[tuple[str, str], LanguageServer] = {}

    def get_or_spawn(
        self, language_id: str, root_path: Path
    ) -> LanguageServer | None:
        entry = self._config.server_for(language_id)
        if entry is None:
            return None
        key = (language_id, str(root_path))
        if key not in self._servers:
            self._servers[key] = LanguageServer(
                language_id=language_id,
                root_path=str(root_path),
                command=entry["command"],
                initialization_options=self._config.initialization_options_for(language_id),
                transport_factory=self._transport_factory,
                backoff_schedule=self._config.tunable("restartBackoffSchedule"),
                max_restart_attempts=self._config.tunable("restartMaxAttempts"),
                idle_timeout_seconds=self._config.tunable("serverIdleTimeoutSeconds"),
            )
        return self._servers[key]

    def all_servers(self) -> list[LanguageServer]:
        return list(self._servers.values())

    def shutdown_all(self) -> None:
        for server in self._servers.values():
            server.kill_now()
        self._servers.clear()
```

(Add a `kill_now()` method on `LanguageServer` that does `_begin_shutdown()` immediately, regardless of state — needed for plugin-deactivate cleanup.)

In `src/gedit_lsp/server.py`, add:

```python
    def kill_now(self) -> None:
        """Immediate shutdown — used on plugin deactivate / window close."""
        if self.state in (ServerState.READY, ServerState.IDLE):
            self._begin_shutdown()
        elif self._transport is not None:
            self._transport.kill()
            self.state = ServerState.NOT_RUNNING
```

- [ ] **Step 3: Run all unit tests**

Run: `make test`
Expected: all green. Test count ≥ 60.

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/registry.py tests/unit/test_registry.py src/gedit_lsp/server.py
git commit -m "feat: implement ServerRegistry with (lang, root) keying"
```

### Task M3.5: Smoke test — spawn `pylsp`, complete `initialize`, shut it down

**Files:**
- Create: `tests/smoke/__init__.py`
- Create: `tests/smoke/spawn_pylsp.py`

(Smoke tests are scripts that run a real GLib main loop. They are NOT part of `pytest` collection — they run via `python tests/smoke/spawn_pylsp.py` and serve as living documentation.)

- [ ] **Step 1: Write the smoke script**

```python
#!/usr/bin/env python3
"""Spawn pylsp, complete initialize, print capabilities, shut down.

Usage:
    python tests/smoke/spawn_pylsp.py

Requires:
    - pylsp on $PATH
    - python3-gi (PyGObject), GLib

Exit codes:
    0 — success (initialize completed, shutdown sent, subprocess exited)
    1 — failure
"""
from __future__ import annotations

import json
import sys

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

# Make the source tree importable without installing.
sys.path.insert(0, "src")

from gedit_lsp.rpc import RpcClient


def main() -> int:
    loop = GLib.MainLoop()
    client = RpcClient(
        command=["pylsp"],
        log_prefix="[python:smoke]",
        on_exit=lambda code: (print(f"pylsp exited (code={code})"), loop.quit()),
    )
    client.start()

    def on_init(msg: dict) -> None:
        if msg.get("error"):
            print("initialize failed:", msg["error"])
            sys.exit(1)
        caps = msg["result"]["capabilities"]
        print("Server capabilities:", json.dumps(caps, indent=2)[:500])
        client.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        # Now send shutdown + exit
        client.on_response(2, lambda _: client.send(
            {"jsonrpc": "2.0", "method": "exit", "params": None}
        ))
        client.send({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None})

    client.on_response(1, on_init)
    client.send(
        {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "processId": None, "rootUri": None, "capabilities": {},
            },
        }
    )

    GLib.timeout_add_seconds(15, lambda: (print("TIMEOUT"), loop.quit())[1])
    loop.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the smoke script**

Run: `python tests/smoke/spawn_pylsp.py`
Expected:
- Prints "Server capabilities: ..." with non-empty JSON
- Prints "pylsp exited (code=0)"
- Exits 0

If `pylsp` is not on the path, the test fails with a clear error. Install on Debian/Ubuntu: `apt install python3-pylsp`.

- [ ] **Step 3: Commit**

```bash
git add tests/smoke
git commit -m "test: add smoke script that exercises full pylsp init/shutdown round-trip"
```

### Task M3.6: M3 sweep

- [ ] **Step 1: Run all unit tests + the smoke**

Run: `make test && python tests/smoke/spawn_pylsp.py`
Expected: all unit tests green; smoke completes successfully.

---

## Milestone 4 — DocumentBridge + Plugin Entry Point

**Goal:** First runnable plugin that loads in gedit, observes document open/change/save/close, and sends the corresponding `textDocument/*` messages to the right server. No features yet — but the plumbing through which features will deliver responses is fully in place.

**Exit criteria:**
- `make install` and restart gedit successfully loads the plugin (no errors in `~/.local/state/gedit-lsp/plugin.log`).
- Open a `.py` file → `lsp-traffic.log` (with `logLspTraffic: true`) shows `>>> ... initialize` followed by `>>> ... textDocument/didOpen`.
- Type a character → after 150 ms, `>>> ... textDocument/didChange` appears (debounced).
- Save → `>>> ... textDocument/didSave`.
- Close tab → `>>> ... textDocument/didClose`.
- New unit: `tests/unit/test_bridge.py` exercises debouncing logic without a real GLib timeout.

### Task M4.1: Write `DocumentBridge` failing tests (debounce + version monotonicity)

**Files:**
- Create: `tests/unit/test_bridge.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for DocumentBridge — per-buffer document sync logic.

The bridge depends on a `LanguageServer` (we use a fake) and on a clock
(we use a manual clock so debouncing is deterministic).
"""
from __future__ import annotations

from typing import Any

from gedit_lsp.bridge import DocumentBridge


class FakeServer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.state = "READY"

    def send_notification(self, method: str, params: dict[str, Any]) -> None:
        self.sent.append({"method": method, "params": params})


class ManualClock:
    def __init__(self) -> None:
        self.now_ms = 0
        self.scheduled: list[tuple[int, Any]] = []

    def schedule_after_ms(self, delay_ms: int, callback: Any) -> Any:
        self.scheduled.append((self.now_ms + delay_ms, callback))
        return len(self.scheduled) - 1

    def cancel(self, handle: Any) -> None:
        self.scheduled = [s for i, s in enumerate(self.scheduled) if i != handle]

    def advance(self, ms: int) -> None:
        self.now_ms += ms
        due = [(t, cb) for (t, cb) in self.scheduled if t <= self.now_ms]
        self.scheduled = [(t, cb) for (t, cb) in self.scheduled if t > self.now_ms]
        for _, cb in due:
            cb()


def test_did_open_sent_on_attach() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py",
        language_id="python",
        text="print(1)",
        server=server,
        clock=clock,
        debounce_ms=150,
    )
    bridge.attach()
    assert server.sent[-1]["method"] == "textDocument/didOpen"
    p = server.sent[-1]["params"]
    assert p["textDocument"]["uri"] == "file:///x.py"
    assert p["textDocument"]["text"] == "print(1)"
    assert p["textDocument"]["version"] == 1


def test_did_change_debounced() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py",
        language_id="python",
        text="print(1)",
        server=server,
        clock=clock,
        debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_changed("print(2)")
    bridge.on_changed("print(3)")
    bridge.on_changed("print(4)")
    # No didChange yet — still inside debounce window
    assert server.sent == []
    clock.advance(150)
    # One didChange sent with the latest text
    assert len(server.sent) == 1
    assert server.sent[0]["method"] == "textDocument/didChange"
    assert server.sent[0]["params"]["contentChanges"][0]["text"] == "print(4)"


def test_did_change_version_monotonic() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="a",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    for new in ["b", "c", "d"]:
        bridge.on_changed(new)
        clock.advance(150)
    versions = [s["params"]["textDocument"]["version"] for s in server.sent]
    assert versions == [2, 3, 4]


def test_did_save_sent_immediately() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="a",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_saved()
    assert server.sent[0]["method"] == "textDocument/didSave"


def test_did_close_sent_on_detach() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="a",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    bridge.detach()
    assert server.sent[0]["method"] == "textDocument/didClose"


def test_pending_change_flushed_on_save() -> None:
    """Saving while a debounced change is pending must flush the change first."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="a",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_changed("ab")
    bridge.on_saved()
    methods = [s["method"] for s in server.sent]
    assert methods == ["textDocument/didChange", "textDocument/didSave"]
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/unit/test_bridge.py -v`
Expected: ImportError on `gedit_lsp.bridge`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_bridge.py
git commit -m "test: add failing tests for DocumentBridge debounce/version logic"
```

### Task M4.2: Implement `DocumentBridge`

**Files:**
- Create: `src/gedit_lsp/bridge.py`

- [ ] **Step 1: Implement `DocumentBridge`**

```python
"""DocumentBridge — one per gedit buffer.

Owns the version counter, the debounce timer, and the wire-message
formatting for the four `textDocument/*` notifications. Holds a reference
to its `LanguageServer` (passed in at construction) and a `Clock`
abstraction so unit tests can drive time deterministically.
"""
from __future__ import annotations

from typing import Any, Protocol


class Server(Protocol):
    def send_notification(self, method: str, params: dict[str, Any]) -> None: ...


class Clock(Protocol):
    def schedule_after_ms(self, delay_ms: int, callback: Any) -> Any: ...
    def cancel(self, handle: Any) -> None: ...


class DocumentBridge:
    def __init__(
        self,
        uri: str,
        language_id: str,
        text: str,
        server: Server,
        clock: Clock,
        debounce_ms: int,
    ) -> None:
        self.uri = uri
        self.language_id = language_id
        self._text = text
        self._server = server
        self._clock = clock
        self._debounce_ms = debounce_ms
        self._version = 0
        self._pending_handle: Any = None

    def attach(self) -> None:
        self._version = 1
        self._server.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": self.uri,
                    "languageId": self.language_id,
                    "version": self._version,
                    "text": self._text,
                }
            },
        )

    def on_changed(self, new_text: str) -> None:
        self._text = new_text
        if self._pending_handle is not None:
            self._clock.cancel(self._pending_handle)
        self._pending_handle = self._clock.schedule_after_ms(
            self._debounce_ms, self._flush_change
        )

    def on_saved(self) -> None:
        self._flush_change_if_pending()
        self._server.send_notification(
            "textDocument/didSave",
            {"textDocument": {"uri": self.uri}, "text": self._text},
        )

    def detach(self) -> None:
        if self._pending_handle is not None:
            self._clock.cancel(self._pending_handle)
            self._pending_handle = None
        self._server.send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": self.uri}},
        )

    def _flush_change(self) -> None:
        self._pending_handle = None
        self._version += 1
        self._server.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": self.uri, "version": self._version},
                "contentChanges": [{"text": self._text}],
            },
        )

    def _flush_change_if_pending(self) -> None:
        if self._pending_handle is not None:
            self._clock.cancel(self._pending_handle)
            self._flush_change()
```

A `send_notification` shim is needed on `LanguageServer` (the bridge speaks at the notification level, not raw JSON-RPC). Add to `src/gedit_lsp/server.py`:

```python
    def send_notification(self, method: str, params: Any) -> None:
        if self._transport is None:
            return
        self._transport.send(
            {"jsonrpc": "2.0", "method": method, "params": params}
        )
```

- [ ] **Step 2: Run bridge tests**

Run: `pytest tests/unit/test_bridge.py -v`
Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/bridge.py src/gedit_lsp/server.py
git commit -m "feat: implement DocumentBridge (didOpen/didChange/didSave/didClose)"
```

### Task M4.3: Add a real GLib `Clock` adapter

**Files:**
- Modify: `src/gedit_lsp/bridge.py`

- [ ] **Step 1: Append the adapter to `bridge.py`**

```python
class GLibClock:
    """Real Clock backed by GLib.timeout_add."""

    def __init__(self) -> None:
        import gi  # local import to keep test imports light

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib

        self._GLib = GLib

    def schedule_after_ms(self, delay_ms: int, callback: Any) -> int:
        def _wrapper() -> bool:
            callback()
            return False

        return int(self._GLib.timeout_add(delay_ms, _wrapper))

    def cancel(self, handle: int) -> None:
        self._GLib.source_remove(handle)
```

- [ ] **Step 2: Verify mypy**

Run: `mypy src/gedit_lsp/bridge.py`
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/bridge.py
git commit -m "feat(bridge): add GLibClock adapter for production use"
```

### Task M4.4: Implement plugin entry point `plugin.py`

**Files:**
- Create: `src/gedit_lsp/plugin.py`
- Modify: `src/gedit_lsp/__init__.py`

- [ ] **Step 1: Implement `GeditLspPlugin`**

```python
"""GeditLspPlugin — libpeas entry point, Gedit.WindowActivatable.

Lifecycle:
    do_activate()    — wire signals on Gedit.Window, attach DocumentBridges
                       to currently-open documents, set up logging.
    do_deactivate()  — disconnect signals, detach all bridges, shut down
                       all servers via the registry.
    do_update_state() — reserved (used for menu-action sensitivity in
                       feature milestones).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gedit", "46")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, GObject, Gedit, Gtk

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.config import Config
from gedit_lsp.log import setup_logging
from gedit_lsp.registry import ServerRegistry
from gedit_lsp.root import ProjectRootResolver
from gedit_lsp.rpc import RpcClient


def _config_path() -> Path:
    base = Path(
        os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    )
    return base / "gedit" / "lsp-plugin.json"


def _state_dir() -> Path:
    base = Path(
        os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    )
    return base / "gedit-lsp"


# Module-global singletons (one per gedit process)
_config: Config | None = None
_registry: ServerRegistry | None = None


def _ensure_globals() -> tuple[Config, ServerRegistry]:
    global _config, _registry
    if _config is None:
        _config = Config(user_path=_config_path())
        _config.load()
        setup_logging(
            state_dir=_state_dir(),
            level=_config.tunable("logLevel"),
            traffic_enabled=_config.tunable("logLspTraffic"),
            max_bytes=_config.tunable("logRotationMaxBytes"),
            keep=_config.tunable("logRotationKeepFiles"),
        )

        def factory(command: list[str], log_prefix: str, on_exit: Any) -> RpcClient:
            return RpcClient(command=command, log_prefix=log_prefix, on_exit=on_exit)

        _registry = ServerRegistry(config=_config, transport_factory=factory)
    assert _config is not None and _registry is not None
    return _config, _registry


class GeditLspPlugin(GObject.Object, Gedit.WindowActivatable):
    __gtype_name__ = "GeditLspPlugin"

    window = GObject.Property(type=Gedit.Window)

    def do_activate(self) -> None:
        cfg, registry = _ensure_globals()
        self._config = cfg
        self._registry = registry
        self._resolver = ProjectRootResolver(markers=cfg.tunable("rootMarkers") if False else [])  # placeholder; root markers used per-language
        self._clock = GLibClock()
        self._bridges: dict[Gedit.Document, DocumentBridge] = {}
        self._handlers: list[tuple[GObject.Object, int]] = []

        win = self.window
        for doc in win.get_documents():
            self._attach_document(doc)
        self._handlers.append((win, win.connect("tab-added", self._on_tab_added)))
        self._handlers.append((win, win.connect("tab-removed", self._on_tab_removed)))

    def do_deactivate(self) -> None:
        for obj, hid in self._handlers:
            obj.disconnect(hid)
        self._handlers.clear()
        for bridge in list(self._bridges.values()):
            bridge.detach()
        self._bridges.clear()

    def do_update_state(self) -> None:
        pass

    def _on_tab_added(self, _win: Gedit.Window, tab: Gedit.Tab) -> None:
        doc = tab.get_document()
        # Document may not be loaded yet; defer to `loaded` signal
        loaded_handler = doc.connect("loaded", lambda d: self._attach_document(d))
        self._handlers.append((doc, loaded_handler))

    def _on_tab_removed(self, _win: Gedit.Window, tab: Gedit.Tab) -> None:
        doc = tab.get_document()
        bridge = self._bridges.pop(doc, None)
        if bridge is not None:
            bridge.detach()

    def _attach_document(self, doc: Gedit.Document) -> None:
        if doc in self._bridges:
            return
        gfile = doc.get_file().get_location()
        if gfile is None:
            return  # untitled buffer
        path = Path(gfile.get_path())
        lang = doc.get_language()
        if lang is None:
            return
        lang_id = lang.get_id()
        if self._config.server_for(lang_id) is None:
            return
        markers = self._config.root_markers_for(lang_id)
        resolver = ProjectRootResolver(markers=markers)
        root = resolver.resolve(path)
        server = self._registry.get_or_spawn(lang_id, root)
        if server is None:
            return
        # Trigger a buffer attach so server transitions to STARTING/READY
        uri = gfile.get_uri()
        server.attach_buffer(uri)
        text = doc.get_text(doc.get_start_iter(), doc.get_end_iter(), False)
        bridge = DocumentBridge(
            uri=uri,
            language_id=lang_id,
            text=text,
            server=server,
            clock=self._clock,
            debounce_ms=self._config.tunable("changeDebounceMs"),
        )
        bridge.attach()
        self._bridges[doc] = bridge
        self._handlers.append(
            (doc, doc.connect("changed", lambda d: self._on_doc_changed(d)))
        )
        self._handlers.append(
            (doc, doc.connect("saved", lambda d: self._on_doc_saved(d)))
        )

    def _on_doc_changed(self, doc: Gedit.Document) -> None:
        bridge = self._bridges.get(doc)
        if bridge is None:
            return
        text = doc.get_text(doc.get_start_iter(), doc.get_end_iter(), False)
        bridge.on_changed(text)

    def _on_doc_saved(self, doc: Gedit.Document) -> None:
        bridge = self._bridges.get(doc)
        if bridge is not None:
            bridge.on_saved()
```

- [ ] **Step 2: Re-export from `__init__.py`**

```python
"""gedit LSP plugin — Language Server Protocol client for gedit."""

__version__ = "0.1.0a0"

from gedit_lsp.plugin import GeditLspPlugin  # noqa: F401  (libpeas discovery)
```

- [ ] **Step 3: Install and smoke-test in real gedit**

```bash
make install
# In a separate shell:
gedit -s ~/scratch/test.py &
# In gedit: Preferences → Plugins → enable "LSP"
# Type something, save, close the tab
tail -f ~/.local/state/gedit-lsp/lsp-traffic.log
```

Expected lines (approximate):

```
>>> ...... [python:scratch] {"jsonrpc":"2.0","id":1,"method":"initialize",...}
<<< ...... [python:scratch] {"jsonrpc":"2.0","id":1,"result":{"capabilities":...}}
>>> ...... [python:scratch] {"jsonrpc":"2.0","method":"initialized","params":{}}
>>> ...... [python:scratch] {"jsonrpc":"2.0","method":"textDocument/didOpen",...}
>>> ...... [python:scratch] {"jsonrpc":"2.0","method":"textDocument/didChange",...}  (after typing)
>>> ...... [python:scratch] {"jsonrpc":"2.0","method":"textDocument/didSave",...}    (on save)
>>> ...... [python:scratch] {"jsonrpc":"2.0","method":"textDocument/didClose",...}   (on close)
```

To enable traffic logging, first edit `~/.config/gedit/lsp-plugin.json`:

```json
{ "tunables": { "logLspTraffic": true } }
```

…and restart gedit.

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/plugin.py src/gedit_lsp/__init__.py
git commit -m "feat: implement plugin entry point with document sync wiring"
```

### Task M4.5: M4 sweep

- [ ] **Step 1: Run full unit suite**

Run: `make test && make lint && make typecheck`
Expected: all green.

- [ ] **Step 2: Manual smoke test as above**

The plugin should load without errors in `plugin.log` and produce the expected wire traffic.

---

## Milestone 5 — Diagnostics Feature

**Goal:** When the server publishes `textDocument/publishDiagnostics`, the plugin renders squiggles in the buffer (via `Gtk.TextTag`), gutter marks (`GtkSourceMark`), and rows in a bottom panel.

**Exit criteria:**
- `tests/integration/test_diagnostics_e2e.py` passes against real `pylsp` — open a Python file with `import nonexistent`, expect one error tag spanning the right characters.
- Manual: open `~/scratch/test.py` containing `import nonexistent`, see a red squiggle.

### Task M5.1: Write integration-test fixture infrastructure

**Files:**
- Create: `tests/integration/conftest.py`
- Create: `tests/fixtures/projects/python_basic/broken.py`
- Create: `tests/fixtures/projects/python_basic/.gitignore`

- [ ] **Step 1: Write the conftest with `lsp_server` fixture**

```python
"""Integration-test fixtures.

Fixtures construct real LanguageServer instances driving real pylsp
subprocesses. Each test gets a tmp directory it can populate; pylsp is
rooted there.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterator

import gi
import pytest

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gedit_lsp.config import Config
from gedit_lsp.registry import ServerRegistry
from gedit_lsp.rpc import RpcClient


@pytest.fixture
def pylsp_available() -> None:
    if shutil.which("pylsp") is None:
        pytest.skip("pylsp not on PATH; install python3-pylsp or python-lsp-server")


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config(user_path=tmp_path / "missing.json")
    c.load()
    return c


@pytest.fixture
def registry(cfg: Config) -> ServerRegistry:
    def factory(command, log_prefix, on_exit):
        return RpcClient(command=command, log_prefix=log_prefix, on_exit=on_exit)
    return ServerRegistry(config=cfg, transport_factory=factory)


@pytest.fixture
def main_loop() -> Iterator[GLib.MainLoop]:
    """Provide a runnable MainLoop the test owns."""
    loop = GLib.MainLoop()
    yield loop


def run_until(loop: GLib.MainLoop, predicate, timeout_s: float = 10.0) -> None:
    """Pump the GLib loop until predicate() returns truthy or timeout."""
    expired = [False]

    def _check() -> bool:
        if predicate():
            loop.quit()
            return False
        return True

    GLib.idle_add(_check)
    GLib.timeout_add(50, _check)
    GLib.timeout_add_seconds(int(timeout_s), lambda: (loop.quit(), expired.__setitem__(0, True))[1])
    loop.run()
    if expired[0]:
        raise TimeoutError("integration test timed out")
```

- [ ] **Step 2: Write the broken-import fixture**

`tests/fixtures/projects/python_basic/broken.py`:

```python
import nonexistent_module_xyz  # noqa
print("hello")
```

`tests/fixtures/projects/python_basic/.gitignore`:

```
*.pyc
__pycache__/
```

- [ ] **Step 3: Commit**

```bash
git add tests/integration/conftest.py tests/fixtures/projects/python_basic
git commit -m "test: add integration-test fixtures (conftest + python_basic project)"
```

### Task M5.2: Write `DiagnosticsController` failing tests (unit + e2e)

**Files:**
- Create: `tests/unit/test_diagnostics_controller.py`
- Create: `tests/integration/test_diagnostics_e2e.py`

- [ ] **Step 1: Write unit-level tests**

Unit test exercises tag application without a server:

```python
"""Unit tests for DiagnosticsController.

Tests construct a Gtk.TextBuffer manually, build the controller, then
call `apply_diagnostics` with synthetic LSP `Diagnostic` dicts.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import GtkSource

from gedit_lsp.features.diagnostics import DiagnosticsController


def _buffer(text: str) -> GtkSource.Buffer:
    buf = GtkSource.Buffer()
    buf.set_text(text)
    return buf


def test_clears_then_applies_tags() -> None:
    buf = _buffer("line0\nline1\n")
    ctrl = DiagnosticsController(buffer=buf, severity_underlines={"error": "error"})
    ctrl.apply_diagnostics(
        [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 4},
                },
                "severity": 1,
                "message": "boom",
                "source": "pylsp",
            }
        ]
    )
    # Re-apply with no diagnostics — old tag must be cleared
    ctrl.apply_diagnostics([])
    # Look for the error tag — should not be applied anywhere now
    tag = buf.get_tag_table().lookup("lsp-diag-error")
    if tag is None:
        return  # never created — fine
    start = buf.get_start_iter()
    end = buf.get_end_iter()
    assert not start.starts_tag(tag) and not start.has_tag(tag)


def test_applies_correct_range_for_emoji() -> None:
    buf = _buffer("a🐍def")
    ctrl = DiagnosticsController(buffer=buf, severity_underlines={"warning": "error"})
    # Mark "def" — UTF-16 chars 3..6 (after `a` and the surrogate pair)
    ctrl.apply_diagnostics(
        [
            {
                "range": {
                    "start": {"line": 0, "character": 3},
                    "end": {"line": 0, "character": 6},
                },
                "severity": 2,
                "message": "warn",
            }
        ]
    )
    tag = buf.get_tag_table().lookup("lsp-diag-warning")
    assert tag is not None
    # Find the tagged range
    it = buf.get_start_iter()
    it.forward_to_tag_toggle(tag)
    assert it.get_line_offset() == 2  # codepoint offset for "def" (after a + 🐍)
```

- [ ] **Step 2: Write the integration test**

```python
"""End-to-end test: pylsp publishes diagnostics for a broken Python file."""
from __future__ import annotations

from pathlib import Path

import gi
import pytest

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.features.diagnostics import DiagnosticsController
from gedit_lsp.registry import ServerRegistry


def test_diagnostics_arrive_for_broken_import(
    pylsp_available, project_dir: Path, registry: ServerRegistry, main_loop, monkeypatch
):
    src = project_dir / "broken.py"
    src.write_text("import nonexistent_module_xyz_42\nprint('ok')\n")

    server = registry.get_or_spawn("python", project_dir)
    assert server is not None

    buf = GtkSource.Buffer()
    buf.set_text(src.read_text())
    ctrl = DiagnosticsController(
        buffer=buf, severity_underlines={"error": "error", "warning": "error"}
    )

    # Wire diagnostics callback
    received: list[list[dict]] = []
    def on_diag(msg: dict) -> None:
        if msg["params"]["uri"] != src.as_uri():
            return
        received.append(msg["params"]["diagnostics"])
        ctrl.apply_diagnostics(msg["params"]["diagnostics"])

    # Patch server's diagnostics handler (real wiring would go via signals)
    server._on_diagnostics = lambda m: on_diag(m)  # type: ignore[attr-defined]

    server.attach_buffer(src.as_uri())
    bridge = DocumentBridge(
        uri=src.as_uri(),
        language_id="python",
        text=src.read_text(),
        server=server,
        clock=GLibClock(),
        debounce_ms=150,
    )
    bridge.attach()

    def predicate() -> bool:
        return len(received) > 0 and len(received[-1]) > 0

    GLib.timeout_add(50, lambda: (predicate() and main_loop.quit(), True)[1])
    GLib.timeout_add_seconds(15, lambda: (main_loop.quit(),)[0])
    main_loop.run()
    assert received, "no diagnostics arrived within 15 s"
    assert any(
        "nonexistent_module_xyz_42" in d.get("message", "")
        or d.get("severity") == 1
        for d in received[-1]
    )
```

- [ ] **Step 3: Verify both fail**

Run: `pytest tests/unit/test_diagnostics_controller.py tests/integration/test_diagnostics_e2e.py -v`
Expected: ImportError on `gedit_lsp.features.diagnostics` for both.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_diagnostics_controller.py tests/integration/test_diagnostics_e2e.py
git commit -m "test: add failing diagnostics tests (unit + e2e)"
```

### Task M5.3: Implement `DiagnosticsController`

**Files:**
- Create: `src/gedit_lsp/features/diagnostics.py`

- [ ] **Step 1: Implement the controller**

```python
"""DiagnosticsController — render LSP diagnostics into a GtkSource buffer.

For each `publishDiagnostics` notification:
    1. Remove all `lsp-diag-*` tags from the buffer.
    2. For each diagnostic, convert UTF-16 range → Gtk.TextIter via utf16.py.
    3. Apply the severity-keyed tag.

Gutter marks and the bottom panel are added in M9.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
gi.require_version("Pango", "1.0")
from gi.repository import GtkSource, Pango

from gedit_lsp.utf16 import utf16_to_text_iter


_SEVERITY_TO_KEY = {1: "error", 2: "warning", 3: "info", 4: "hint"}
_UNDERLINE = {
    "error": Pango.Underline.ERROR,
    "single": Pango.Underline.SINGLE,
    "none": Pango.Underline.NONE,
}


class DiagnosticsController:
    def __init__(
        self,
        buffer: GtkSource.Buffer,
        severity_underlines: dict[str, str],
    ) -> None:
        self._buffer = buffer
        self._severity_underlines = severity_underlines
        self._ensure_tags()

    def _ensure_tags(self) -> None:
        table = self._buffer.get_tag_table()
        for sev, style in self._severity_underlines.items():
            name = f"lsp-diag-{sev}"
            if table.lookup(name) is None:
                tag = self._buffer.create_tag(name)
                tag.set_property("underline", _UNDERLINE.get(style, Pango.Underline.ERROR))

    def apply_diagnostics(self, diagnostics: list[dict]) -> None:
        self._clear_all_tags()
        for d in diagnostics:
            sev = _SEVERITY_TO_KEY.get(d.get("severity", 1), "error")
            tag = self._buffer.get_tag_table().lookup(f"lsp-diag-{sev}")
            if tag is None:
                continue
            r = d["range"]
            start = utf16_to_text_iter(self._buffer, r["start"]["line"], r["start"]["character"])
            end = utf16_to_text_iter(self._buffer, r["end"]["line"], r["end"]["character"])
            self._buffer.apply_tag(tag, start, end)

    def _clear_all_tags(self) -> None:
        table = self._buffer.get_tag_table()
        start = self._buffer.get_start_iter()
        end = self._buffer.get_end_iter()
        for sev in self._severity_underlines:
            tag = table.lookup(f"lsp-diag-{sev}")
            if tag is not None:
                self._buffer.remove_tag(tag, start, end)
```

- [ ] **Step 2: Run unit tests**

Run: `pytest tests/unit/test_diagnostics_controller.py -v`
Expected: pass.

- [ ] **Step 3: Wire `DiagnosticsController` into the plugin**

Modify `src/gedit_lsp/plugin.py`. In `_attach_document`, after constructing the bridge, also build the controller and connect the server's diagnostics signal to it:

```python
        from gedit_lsp.features.diagnostics import DiagnosticsController
        ctrl = DiagnosticsController(
            buffer=doc,
            severity_underlines=self._config.tunable("severityUnderlineStyle"),
        )
        # Hold a strong reference (gedit doesn't track these)
        self._bridges[doc] = bridge
        self._diagnostics_ctrls[doc] = ctrl

        def _on_diag(params: dict) -> None:
            if params["uri"] != uri:
                return
            ctrl.apply_diagnostics(params["diagnostics"])

        server.add_diagnostics_listener(_on_diag)
```

Add the listener-registration helper to `LanguageServer`:

```python
    def add_diagnostics_listener(self, callback: Callable[[dict], None]) -> None:
        self._diagnostics_listeners.append(callback)

    def _on_diagnostics(self, msg: dict[str, Any]) -> None:
        for cb in self._diagnostics_listeners:
            cb(msg["params"])
```

(In `__init__`, add `self._diagnostics_listeners: list[Callable[[dict], None]] = []`.)

In `plugin.py`, add `self._diagnostics_ctrls: dict[Gedit.Document, DiagnosticsController] = {}` in `do_activate`.

- [ ] **Step 4: Run the integration test**

Run: `pytest tests/integration/test_diagnostics_e2e.py -v`
Expected: passes (diagnostics arrive within timeout).

- [ ] **Step 5: Commit**

```bash
git add src/gedit_lsp/features/diagnostics.py src/gedit_lsp/plugin.py src/gedit_lsp/server.py
git commit -m "feat: implement diagnostics rendering (squiggles via TextTag)"
```

### Task M5.4: Manual smoke test

- [ ] **Step 1: Reinstall and exercise in real gedit**

```bash
make install
gedit ~/scratch/broken.py
# (scratch/broken.py contains: import nonexistent_xyz)
```

Expected: a red error squiggle under `nonexistent_xyz` within 2–5 seconds.

- [ ] **Step 2: Update CHANGELOG**

Add to `CHANGELOG.md` under `[Unreleased]`:

```markdown
- Diagnostics rendering: squiggles applied via Gtk.TextTag with severity-keyed underline styles.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: log diagnostics feature in CHANGELOG"
```

---

## Milestone 6 — Hover Feature (Ctrl+K)

**Goal:** A `win.lsp-hover` action bound to **Ctrl+K** that sends `textDocument/hover` and renders the response as a `Gtk.Popover`.

**Exit criteria:** `tests/integration/test_hover_e2e.py` passes — pylsp returns a non-empty hover response for `os.path.join` and the rendered text contains `"join"`.

### Task M6.1: Write `HoverController` failing tests

**Files:**
- Create: `tests/unit/test_hover_controller.py`
- Create: `tests/integration/test_hover_e2e.py`
- Create: `tests/fixtures/projects/python_hover/main.py`

- [ ] **Step 1: Create the fixture**

`tests/fixtures/projects/python_hover/main.py`:

```python
import os
result = os.path.join("a", "b")
print(result)
```

- [ ] **Step 2: Write unit test for hover request construction**

```python
"""Unit tests for HoverController — verifies request format and response rendering."""
from __future__ import annotations

from gedit_lsp.features.hover import HoverController, render_hover_contents


def test_render_string_contents() -> None:
    text = render_hover_contents("hello")
    assert text == "hello"


def test_render_markup_contents_extracts_value() -> None:
    text = render_hover_contents({"kind": "markdown", "value": "# Title\n\nbody"})
    assert "Title" in text and "body" in text


def test_render_markedstring_array() -> None:
    text = render_hover_contents([{"language": "python", "value": "def f(): ..."}, "docstring"])
    assert "def f()" in text and "docstring" in text


def test_render_none_returns_empty() -> None:
    assert render_hover_contents(None) == ""
```

- [ ] **Step 3: Write integration test**

```python
"""End-to-end hover test against pylsp."""
from __future__ import annotations

from pathlib import Path
import shutil

import gi
import pytest

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.registry import ServerRegistry
from gedit_lsp.utf16 import text_iter_to_utf16


def test_hover_returns_join_for_os_path_join(
    pylsp_available, tmp_path: Path, registry: ServerRegistry, main_loop
) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "import os\nresult = os.path.join(\"a\", \"b\")\nprint(result)\n"
    )
    (tmp_path / ".git").mkdir()

    server = registry.get_or_spawn("python", tmp_path)
    assert server is not None
    server.attach_buffer(src.as_uri())

    import gi as _gi
    _gi.require_version("GtkSource", "4")
    from gi.repository import GtkSource
    buf = GtkSource.Buffer()
    buf.set_text(src.read_text())
    bridge = DocumentBridge(
        uri=src.as_uri(), language_id="python", text=src.read_text(),
        server=server, clock=GLibClock(), debounce_ms=150,
    )
    bridge.attach()

    # Wait for server to be READY before sending hover
    GLib.timeout_add_seconds(2, lambda: main_loop.quit())
    main_loop.run()

    # Cursor on the `j` in `join` (line 1, col ~17 in UTF-16)
    line_text = src.read_text().splitlines()[1]
    char = line_text.find("join")
    response: dict | None = None
    def on_resp(msg):
        nonlocal response
        response = msg
        main_loop.quit()
    server._send_request(
        "textDocument/hover",
        {
            "textDocument": {"uri": src.as_uri()},
            "position": {"line": 1, "character": char},
        },
        on_resp,
    )
    GLib.timeout_add_seconds(10, lambda: main_loop.quit())
    main_loop.run()
    assert response is not None and response.get("result") is not None
    contents = response["result"].get("contents")
    from gedit_lsp.features.hover import render_hover_contents
    rendered = render_hover_contents(contents)
    assert "join" in rendered.lower()
```

- [ ] **Step 4: Verify failure**

Run: `pytest tests/unit/test_hover_controller.py tests/integration/test_hover_e2e.py -v`
Expected: ImportError on `gedit_lsp.features.hover`.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_hover_controller.py tests/integration/test_hover_e2e.py tests/fixtures/projects/python_hover
git commit -m "test: add failing hover tests"
```

### Task M6.2: Add `_send_request` helper to `LanguageServer`

**Files:**
- Modify: `src/gedit_lsp/server.py`

- [ ] **Step 1: Add the helper**

```python
    def _send_request(
        self,
        method: str,
        params: Any,
        callback: Callable[[dict[str, Any]], None],
    ) -> int:
        """Send a request, register the callback, return the request id."""
        if self._transport is None:
            return -1
        req_id = next(self._req_ids)
        self._transport.on_response(req_id, callback)
        self._transport.send(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        return req_id

    def cancel_request(self, request_id: int) -> None:
        if self._transport is None:
            return
        self._transport.send(
            {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": request_id}}
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/gedit_lsp/server.py
git commit -m "feat(server): add _send_request and cancel_request helpers"
```

### Task M6.3: Implement `HoverController`

**Files:**
- Create: `src/gedit_lsp/features/hover.py`

- [ ] **Step 1: Implement the renderer + controller**

```python
"""HoverController — Ctrl+K shows a popover with the server's hover content.

Markdown is rendered as plain text with triple-backtick code blocks
detected and given a monospace styling. We don't pull in a markdown
renderer for v1.
"""
from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, Gtk, GtkSource

from gedit_lsp.utf16 import text_iter_to_utf16


def render_hover_contents(contents: Any) -> str:
    """Render LSP `Hover.contents` to plain text.

    Accepts:
        - str
        - {"kind": "markdown" | "plaintext", "value": str}    (MarkupContent)
        - {"language": str, "value": str}                     (MarkedString — old)
        - list of MarkedString | str                          (MarkedString[])
        - None
    """
    if contents is None:
        return ""
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return contents.get("value", "")
    if isinstance(contents, list):
        return "\n\n".join(render_hover_contents(c) for c in contents).strip()
    return ""


class HoverController:
    def __init__(
        self,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server,  # LanguageServer
        uri: str,
        spinner_threshold_ms: int,
    ) -> None:
        self._view = view
        self._buffer = buffer
        self._server = server
        self._uri = uri
        self._spinner_threshold_ms = spinner_threshold_ms
        self._popover: Gtk.Popover | None = None

    def trigger(self) -> None:
        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        line, char = text_iter_to_utf16(cursor)
        request_started = [False]

        def on_response(msg: dict) -> None:
            if msg.get("error") or msg.get("result") is None:
                return
            text = render_hover_contents(msg["result"].get("contents"))
            if not text.strip():
                return
            self._show_popover(cursor, text)

        self._server._send_request(
            "textDocument/hover",
            {"textDocument": {"uri": self._uri}, "position": {"line": line, "character": char}},
            on_response,
        )

    def _show_popover(self, anchor_iter, text: str) -> None:
        if self._popover is not None:
            self._popover.popdown()
        rect = self._view.get_iter_location(anchor_iter)
        bx, by = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y + rect.height
        )
        rect.x = bx
        rect.y = by
        rect.width = 1
        rect.height = 1

        self._popover = Gtk.Popover.new(self._view)
        self._popover.set_pointing_to(rect)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(120)
        scrolled.set_min_content_width(400)
        inner_buf = GtkSource.Buffer()
        inner_buf.set_text(text)
        inner_view = GtkSource.View.new_with_buffer(inner_buf)
        inner_view.set_editable(False)
        inner_view.set_cursor_visible(False)
        inner_view.set_wrap_mode(Gtk.WrapMode.WORD)
        inner_view.set_monospace(True)
        scrolled.add(inner_view)
        self._popover.add(scrolled)
        self._popover.show_all()
        self._popover.popup()
```

- [ ] **Step 2: Wire the action in the plugin**

In `plugin.py`, in `do_activate`, after constructing the registry/etc., add:

```python
        action = Gio.SimpleAction.new("lsp-hover", None)
        action.connect("activate", self._on_hover_activate)
        win.add_action(action)
        # Application object holds the accelerator
        app = win.get_application()
        if app is not None:
            app.set_accels_for_action("win.lsp-hover", ["<Primary>k"])
        self._actions = [action]
```

(Add `from gi.repository import Gio` at the top.)

Implement `_on_hover_activate`:

```python
    def _on_hover_activate(self, action, param):
        view = self.window.get_active_view()
        if view is None:
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        if bridge is None:
            return
        from gedit_lsp.features.hover import HoverController
        # Re-construct controller per invocation (cheap; popover state is per-trigger)
        ctrl = HoverController(
            view=view,
            buffer=doc,
            server=self._registry.get_or_spawn(bridge.language_id, Path(bridge.uri.replace("file://", "")).parent),
            uri=bridge.uri,
            spinner_threshold_ms=self._config.tunable("hoverSpinnerThresholdMs"),
        )
        ctrl.trigger()
```

- [ ] **Step 3: Run unit and integration tests**

Run: `pytest tests/unit/test_hover_controller.py tests/integration/test_hover_e2e.py -v`
Expected: both pass.

- [ ] **Step 4: Manual smoke test**

```bash
make install
gedit tests/fixtures/projects/python_hover/main.py
# Position cursor on `join`, press Ctrl+K
```

Expected: a popover appears below the cursor with the docstring of `os.path.join`.

- [ ] **Step 5: Commit**

```bash
git add src/gedit_lsp/features/hover.py src/gedit_lsp/plugin.py
git commit -m "feat: implement hover (Ctrl+K) with popover render"
```

### Task M6.4: Update CHANGELOG and protocol-coverage doc

- [ ] **Step 1: Update `CHANGELOG.md`**

Append under `[Unreleased]`:

```markdown
- Hover feature: Ctrl+K sends `textDocument/hover` and renders the response in a popover.
```

- [ ] **Step 2: Update `docs/protocol-coverage.md`** (create if not exists; keep matching Appendix B of the spec)

```markdown
# LSP Protocol Coverage

| Method | v0.1.0-alpha |
|---|---|
| `initialize` / `initialized` / `shutdown` / `exit` | ✓ |
| `textDocument/didOpen` / `didChange` (Full) / `didSave` / `didClose` | ✓ |
| `textDocument/publishDiagnostics` | ✓ |
| `textDocument/hover` | ✓ |
| `textDocument/definition` | (M7) |
| `textDocument/documentSymbol` | (M8) |
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md docs/protocol-coverage.md
git commit -m "docs: update changelog and protocol-coverage for hover"
```

---

## Milestone 7 — Go-to-Definition + Cursor History

**Goal:** `win.lsp-goto-definition` (Ctrl+.) sends `textDocument/definition`, opens the target file (or moves the cursor in-buffer if same file), pushes the previous position onto a per-window history stack. `win.lsp-go-back` (Alt+Left) pops it.

**Exit criteria:** `tests/integration/test_definition_e2e.py` passes; manual: jumping with Ctrl+. opens the right file at the right line, Alt+Left returns.

### Task M7.1: Write `DefinitionController` failing tests

**Files:**
- Create: `tests/unit/test_definition_controller.py`
- Create: `tests/integration/test_definition_e2e.py`
- Create: `tests/fixtures/projects/python_definition/main.py`

- [ ] **Step 1: Create the fixture**

`tests/fixtures/projects/python_definition/main.py`:

```python
def helper(x):
    return x + 1


def main():
    return helper(42)
```

- [ ] **Step 2: Write unit tests**

```python
"""Unit tests for DefinitionController — handles 0/1/N location responses."""
from __future__ import annotations

from gedit_lsp.features.definition import (
    CursorHistory,
    DefinitionController,
    classify_locations,
)


def test_classify_no_locations() -> None:
    assert classify_locations(None) == ("none", [])
    assert classify_locations([]) == ("none", [])


def test_classify_single_location() -> None:
    loc = {"uri": "file:///x.py", "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}}
    kind, locs = classify_locations(loc)
    assert kind == "single"
    assert locs == [loc]


def test_classify_array_with_one() -> None:
    loc = {"uri": "file:///x.py", "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}}
    kind, locs = classify_locations([loc])
    assert kind == "single"


def test_classify_array_with_many() -> None:
    locs = [
        {"uri": "file:///x.py", "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}},
        {"uri": "file:///y.py", "range": {"start": {"line": 5, "character": 0}, "end": {"line": 5, "character": 3}}},
    ]
    kind, got = classify_locations(locs)
    assert kind == "many"
    assert got == locs


def test_cursor_history_push_pop() -> None:
    h = CursorHistory(max_entries=3)
    h.push(("file:///a", 1, 1))
    h.push(("file:///b", 2, 2))
    assert h.pop() == ("file:///b", 2, 2)
    assert h.pop() == ("file:///a", 1, 1)
    assert h.pop() is None


def test_cursor_history_drops_oldest_when_full() -> None:
    h = CursorHistory(max_entries=2)
    h.push(("file:///a", 1, 1))
    h.push(("file:///b", 2, 2))
    h.push(("file:///c", 3, 3))
    assert h.pop() == ("file:///c", 3, 3)
    assert h.pop() == ("file:///b", 2, 2)
    assert h.pop() is None  # 'a' was dropped
```

- [ ] **Step 3: Write integration test**

```python
"""End-to-end go-to-definition test against pylsp."""
from __future__ import annotations

from pathlib import Path

import gi
import pytest

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.registry import ServerRegistry


def test_definition_jumps_to_helper(
    pylsp_available, tmp_path: Path, registry: ServerRegistry, main_loop
) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "def helper(x):\n    return x + 1\n\n\ndef main():\n    return helper(42)\n"
    )
    (tmp_path / ".git").mkdir()

    server = registry.get_or_spawn("python", tmp_path)
    server.attach_buffer(src.as_uri())
    bridge = DocumentBridge(
        uri=src.as_uri(), language_id="python", text=src.read_text(),
        server=server, clock=GLibClock(), debounce_ms=150,
    )
    bridge.attach()

    GLib.timeout_add_seconds(2, lambda: main_loop.quit())
    main_loop.run()

    # Cursor on `helper` at line 5, char 11 (after "    return ")
    response: dict | None = None
    def on_resp(msg):
        nonlocal response
        response = msg
        main_loop.quit()
    server._send_request(
        "textDocument/definition",
        {"textDocument": {"uri": src.as_uri()},
         "position": {"line": 5, "character": 11}},
        on_resp,
    )
    GLib.timeout_add_seconds(10, lambda: main_loop.quit())
    main_loop.run()
    assert response is not None
    res = response.get("result")
    assert res, f"no definition: {response}"
    # Could be Location or list[Location]
    if isinstance(res, list):
        loc = res[0]
    else:
        loc = res
    assert loc["range"]["start"]["line"] == 0  # helper is defined on line 0
```

- [ ] **Step 4: Verify failure**

Run: `pytest tests/unit/test_definition_controller.py tests/integration/test_definition_e2e.py -v`
Expected: ImportError on `gedit_lsp.features.definition`.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_definition_controller.py tests/integration/test_definition_e2e.py tests/fixtures/projects/python_definition
git commit -m "test: add failing definition tests"
```

### Task M7.2: Implement `DefinitionController` and `CursorHistory`

**Files:**
- Create: `src/gedit_lsp/features/definition.py`

- [ ] **Step 1: Implement classification + history + controller**

```python
"""DefinitionController + CursorHistory.

The controller sends `textDocument/definition`, classifies the response
as 0/1/N locations, and dispatches:
    none   → status-bar message
    single → Gedit.Window.create_tab_from_location() (or in-buffer move)
    many   → small Gtk.Popover listing each location

The history stack is per-window. Goto pushes the *current* cursor location
before jumping; Alt+Left pops and restores it.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gedit", "46")
from gi.repository import Gedit, Gio, Gtk

from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter


def classify_locations(result: Any) -> tuple[str, list[dict]]:
    if result is None:
        return ("none", [])
    if isinstance(result, dict):
        return ("single", [result])
    if isinstance(result, list):
        if not result:
            return ("none", [])
        if len(result) == 1:
            return ("single", result)
        return ("many", result)
    return ("none", [])


class CursorHistory:
    def __init__(self, max_entries: int) -> None:
        self._stack: deque[tuple[str, int, int]] = deque(maxlen=max_entries)

    def push(self, entry: tuple[str, int, int]) -> None:
        self._stack.append(entry)

    def pop(self) -> Optional[tuple[str, int, int]]:
        if not self._stack:
            return None
        return self._stack.pop()


class DefinitionController:
    def __init__(self, window: Gedit.Window, history: CursorHistory) -> None:
        self._window = window
        self._history = history

    def trigger(self, server, uri: str) -> None:
        view = self._window.get_active_view()
        buf = view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        line, char = text_iter_to_utf16(cursor)

        # Capture current position for the history stack
        current_uri = buf.get_file().get_location().get_uri()
        self._history.push(
            (current_uri, cursor.get_line(), cursor.get_line_offset())
        )

        def on_response(msg: dict) -> None:
            kind, locs = classify_locations(msg.get("result"))
            if kind == "none":
                self._window.get_statusbar().push(0, "LSP: no definition found")
                # Pop the history entry we pushed — we didn't actually navigate
                self._history.pop()
                return
            if kind == "single":
                self._navigate_to(locs[0])
                return
            self._show_locations_popover(locs)

        server._send_request(
            "textDocument/definition",
            {"textDocument": {"uri": uri},
             "position": {"line": line, "character": char}},
            on_response,
        )

    def go_back(self) -> None:
        entry = self._history.pop()
        if entry is None:
            return
        uri, line, col = entry
        self._navigate_to_uri_line_col(uri, line, col)

    def _navigate_to(self, location: dict) -> None:
        uri = location["uri"]
        line = location["range"]["start"]["line"]
        char_utf16 = location["range"]["start"]["character"]
        self._navigate_to_uri_line_utf16(uri, line, char_utf16)

    def _navigate_to_uri_line_utf16(self, uri: str, line: int, char_utf16: int) -> None:
        active_view = self._window.get_active_view()
        active_doc = active_view.get_buffer() if active_view else None
        if active_doc and active_doc.get_file().get_location().get_uri() == uri:
            it = utf16_to_text_iter(active_doc, line, char_utf16)
            active_doc.place_cursor(it)
            active_view.scroll_to_iter(it, 0.1, False, 0.0, 0.5)
            return
        gfile = Gio.File.new_for_uri(uri)
        tab = self._window.create_tab_from_location(gfile, None, line + 1, char_utf16, False, True)
        # gedit handles scrolling for us when we pass line/col

    def _navigate_to_uri_line_col(self, uri: str, line: int, col: int) -> None:
        active_view = self._window.get_active_view()
        active_doc = active_view.get_buffer() if active_view else None
        if active_doc and active_doc.get_file().get_location().get_uri() == uri:
            it = active_doc.get_iter_at_line_offset(line, col)
            active_doc.place_cursor(it)
            active_view.scroll_to_iter(it, 0.1, False, 0.0, 0.5)
            return
        gfile = Gio.File.new_for_uri(uri)
        self._window.create_tab_from_location(gfile, None, line + 1, col, False, True)

    def _show_locations_popover(self, locs: list[dict]) -> None:
        # Minimal implementation for v0.1.0-alpha: show a simple chooser.
        active_view = self._window.get_active_view()
        if active_view is None:
            return
        popover = Gtk.Popover.new(active_view)
        listbox = Gtk.ListBox()
        for loc in locs:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=f"{loc['uri']}:{loc['range']['start']['line'] + 1}")
            label.set_xalign(0)
            row.add(label)
            listbox.add(row)
        listbox.connect(
            "row-activated",
            lambda _box, row: (
                self._navigate_to(locs[row.get_index()]),
                popover.popdown(),
            ),
        )
        popover.add(listbox)
        popover.show_all()
        popover.popup()
```

- [ ] **Step 2: Wire into the plugin**

In `plugin.py`, in `do_activate`, after the hover action, add:

```python
        from gedit_lsp.features.definition import CursorHistory, DefinitionController
        self._history = CursorHistory(
            max_entries=self._config.tunable("gotoHistoryMaxEntries")
        )
        self._definition_ctrl = DefinitionController(window=win, history=self._history)
        for name, accel, handler in [
            ("lsp-goto-definition", "<Primary>period", self._on_definition_activate),
            ("lsp-go-back", "<Alt>Left", self._on_go_back_activate),
        ]:
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", handler)
            win.add_action(a)
            app = win.get_application()
            if app:
                app.set_accels_for_action(f"win.{name}", [accel])
            self._actions.append(a)
```

Implement the handlers:

```python
    def _on_definition_activate(self, action, param):
        view = self.window.get_active_view()
        if view is None:
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        if bridge is None:
            return
        server = self._registry.get_or_spawn(
            bridge.language_id,
            Path(bridge.uri.replace("file://", "")).parent,
        )
        if server is not None:
            self._definition_ctrl.trigger(server, bridge.uri)

    def _on_go_back_activate(self, action, param):
        self._definition_ctrl.go_back()
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/unit/test_definition_controller.py tests/integration/test_definition_e2e.py -v`
Expected: both pass.

- [ ] **Step 4: Manual smoke test**

Open a Python file, place cursor on a name, press Ctrl+. → it jumps. Press Alt+Left → returns.

- [ ] **Step 5: Commit + CHANGELOG**

```bash
git add src/gedit_lsp/features/definition.py src/gedit_lsp/plugin.py
git commit -m "feat: implement go-to-definition + cursor history"
# Update CHANGELOG.md, docs/protocol-coverage.md
git commit -am "docs: log definition feature"
```

---

## Milestone 8 — Outline (Document Symbols) Side Panel

**Goal:** A side panel ("LSP Outline") displaying the symbol tree returned by `textDocument/documentSymbol`. Click a row → cursor jumps. Cursor in the buffer tracks the closest enclosing symbol.

**Exit criteria:** `tests/integration/test_outline_e2e.py` passes (3-node tree for a class with two methods); manual: open a Python file with classes and functions, side panel shows the tree.

### Task M8.1: Write `OutlineController` failing tests + fixture

**Files:**
- Create: `tests/unit/test_outline_controller.py`
- Create: `tests/integration/test_outline_e2e.py`
- Create: `tests/fixtures/projects/python_outline/sample.py`

- [ ] **Step 1: Create the fixture**

`tests/fixtures/projects/python_outline/sample.py`:

```python
class Greeter:
    def hello(self):
        return "hi"

    def goodbye(self):
        return "bye"
```

- [ ] **Step 2: Write unit tests**

```python
"""Unit tests for outline tree-building.

These pin down the conversion from LSP `DocumentSymbol[]` (or the legacy
`SymbolInformation[]`) to a flat tree-row structure suitable for
Gtk.TreeStore.
"""
from __future__ import annotations

from gedit_lsp.features.outline import (
    SymbolNode,
    build_tree,
    detect_response_format,
)


def test_detect_hierarchical() -> None:
    assert detect_response_format([{"name": "x", "kind": 12, "range": {}, "selectionRange": {}}]) == "hierarchical"


def test_detect_flat_via_location_field() -> None:
    assert detect_response_format([{"name": "x", "kind": 12, "location": {"uri": "...", "range": {}}}]) == "flat"


def test_detect_empty() -> None:
    assert detect_response_format([]) == "hierarchical"  # default


def test_build_tree_hierarchical() -> None:
    items = [
        {
            "name": "Greeter", "kind": 5,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 5, "character": 0}},
            "selectionRange": {"start": {"line": 0, "character": 6}, "end": {"line": 0, "character": 13}},
            "children": [
                {
                    "name": "hello", "kind": 6,
                    "range": {"start": {"line": 1, "character": 4}, "end": {"line": 2, "character": 16}},
                    "selectionRange": {"start": {"line": 1, "character": 8}, "end": {"line": 1, "character": 13}},
                },
                {
                    "name": "goodbye", "kind": 6,
                    "range": {"start": {"line": 4, "character": 4}, "end": {"line": 5, "character": 16}},
                    "selectionRange": {"start": {"line": 4, "character": 8}, "end": {"line": 4, "character": 15}},
                },
            ],
        }
    ]
    tree = build_tree(items, "hierarchical")
    assert len(tree) == 1
    assert tree[0].name == "Greeter"
    assert [c.name for c in tree[0].children] == ["hello", "goodbye"]


def test_build_tree_flat() -> None:
    items = [
        {"name": "Greeter", "kind": 5, "location": {"uri": "x", "range": {"start": {"line": 0, "character": 0}, "end": {"line": 5, "character": 0}}}, "containerName": None},
        {"name": "hello", "kind": 6, "location": {"uri": "x", "range": {"start": {"line": 1, "character": 8}, "end": {"line": 1, "character": 13}}}, "containerName": "Greeter"},
        {"name": "goodbye", "kind": 6, "location": {"uri": "x", "range": {"start": {"line": 4, "character": 8}, "end": {"line": 4, "character": 15}}}, "containerName": "Greeter"},
    ]
    tree = build_tree(items, "flat")
    assert len(tree) == 1
    assert tree[0].name == "Greeter"
    assert {c.name for c in tree[0].children} == {"hello", "goodbye"}
```

- [ ] **Step 3: Write integration test**

```python
"""End-to-end outline test."""
from __future__ import annotations

from pathlib import Path

import gi
import pytest

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.features.outline import build_tree, detect_response_format
from gedit_lsp.registry import ServerRegistry


def test_outline_returns_class_with_two_methods(
    pylsp_available, tmp_path: Path, registry: ServerRegistry, main_loop
) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        "class Greeter:\n    def hello(self):\n        return 'hi'\n\n    def goodbye(self):\n        return 'bye'\n"
    )
    (tmp_path / ".git").mkdir()

    server = registry.get_or_spawn("python", tmp_path)
    server.attach_buffer(src.as_uri())
    bridge = DocumentBridge(
        uri=src.as_uri(), language_id="python", text=src.read_text(),
        server=server, clock=GLibClock(), debounce_ms=150,
    )
    bridge.attach()

    GLib.timeout_add_seconds(2, lambda: main_loop.quit())
    main_loop.run()

    response = None
    def on_resp(msg):
        nonlocal response
        response = msg
        main_loop.quit()
    server._send_request(
        "textDocument/documentSymbol",
        {"textDocument": {"uri": src.as_uri()}},
        on_resp,
    )
    GLib.timeout_add_seconds(10, lambda: main_loop.quit())
    main_loop.run()
    assert response is not None
    items = response.get("result") or []
    fmt = detect_response_format(items)
    tree = build_tree(items, fmt)
    assert any(node.name == "Greeter" for node in tree)
    greeter = next(n for n in tree if n.name == "Greeter")
    assert {c.name for c in greeter.children} == {"hello", "goodbye"}
```

- [ ] **Step 4: Verify failure**

Run: `pytest tests/unit/test_outline_controller.py tests/integration/test_outline_e2e.py -v`
Expected: ImportError on `gedit_lsp.features.outline`.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_outline_controller.py tests/integration/test_outline_e2e.py tests/fixtures/projects/python_outline
git commit -m "test: add failing outline tests"
```

### Task M8.2: Implement outline tree-builder + controller

**Files:**
- Create: `src/gedit_lsp/features/outline.py`

- [ ] **Step 1: Implement tree-building logic + controller**

```python
"""OutlineController + tree-building.

Hierarchical responses (DocumentSymbol[]) are converted directly. Flat
responses (SymbolInformation[]) are nested by `containerName` matching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gedit", "46")
from gi.repository import Gedit, GLib, Gtk


@dataclass
class SymbolNode:
    name: str
    kind: int
    range_start_line: int
    range_start_char: int
    selection_start_line: int
    selection_start_char: int
    children: list["SymbolNode"] = field(default_factory=list)


def detect_response_format(items: list[dict[str, Any]]) -> str:
    """Return 'hierarchical' (DocumentSymbol[]) or 'flat' (SymbolInformation[])."""
    if not items:
        return "hierarchical"
    first = items[0]
    if "location" in first and "selectionRange" not in first:
        return "flat"
    return "hierarchical"


def build_tree(items: list[dict[str, Any]], fmt: str) -> list[SymbolNode]:
    if fmt == "hierarchical":
        return [_build_hier(it) for it in items]
    return _build_flat(items)


def _build_hier(it: dict[str, Any]) -> SymbolNode:
    r = it["range"]["start"]
    s = it.get("selectionRange", it["range"])["start"]
    node = SymbolNode(
        name=it["name"],
        kind=it.get("kind", 0),
        range_start_line=r["line"],
        range_start_char=r["character"],
        selection_start_line=s["line"],
        selection_start_char=s["character"],
        children=[_build_hier(c) for c in it.get("children", [])],
    )
    return node


def _build_flat(items: list[dict[str, Any]]) -> list[SymbolNode]:
    by_name: dict[str, SymbolNode] = {}
    roots: list[SymbolNode] = []
    for it in items:
        r = it["location"]["range"]["start"]
        node = SymbolNode(
            name=it["name"],
            kind=it.get("kind", 0),
            range_start_line=r["line"],
            range_start_char=r["character"],
            selection_start_line=r["line"],
            selection_start_char=r["character"],
        )
        by_name[it["name"]] = node
        container = it.get("containerName")
        if container and container in by_name:
            by_name[container].children.append(node)
        else:
            roots.append(node)
    return roots


class OutlineController:
    """Side-panel TreeView populated from documentSymbol responses."""

    def __init__(
        self,
        window: Gedit.Window,
        refresh_debounce_ms: int,
        initial_delay_ms: int,
    ) -> None:
        self._window = window
        self._refresh_debounce_ms = refresh_debounce_ms
        self._initial_delay_ms = initial_delay_ms
        self._store = Gtk.TreeStore(str, int, int)  # name, line, col
        self._tree = Gtk.TreeView(model=self._store)
        col = Gtk.TreeViewColumn("Symbol")
        renderer = Gtk.CellRendererText()
        col.pack_start(renderer, True)
        col.add_attribute(renderer, "text", 0)
        self._tree.append_column(col)
        self._tree.connect("row-activated", self._on_row_activated)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self._tree)
        scrolled.show_all()
        panel = window.get_side_panel()
        panel.add_titled(scrolled, "lsp-outline", "LSP Outline")
        self._scrolled = scrolled

    def populate(self, items: list[dict[str, Any]]) -> None:
        fmt = detect_response_format(items)
        tree = build_tree(items, fmt)
        self._store.clear()
        for node in tree:
            self._insert(None, node)
        self._tree.expand_all()

    def _insert(self, parent_iter, node: SymbolNode) -> None:
        it = self._store.append(
            parent_iter, [node.name, node.selection_start_line, node.selection_start_char]
        )
        for child in node.children:
            self._insert(it, child)

    def _on_row_activated(self, view, path, _column) -> None:
        it = self._store.get_iter(path)
        line, col = self._store.get(it, 1, 2)
        active_view = self._window.get_active_view()
        if active_view is None:
            return
        buf = active_view.get_buffer()
        from gedit_lsp.utf16 import utf16_to_text_iter
        target = utf16_to_text_iter(buf, line, col)
        buf.place_cursor(target)
        active_view.scroll_to_iter(target, 0.1, False, 0.0, 0.5)
```

- [ ] **Step 2: Wire OutlineController into plugin**

In `plugin.py`, in `do_activate`:

```python
        from gedit_lsp.features.outline import OutlineController
        self._outline_ctrl = OutlineController(
            window=win,
            refresh_debounce_ms=self._config.tunable("outlineRefreshDebounceMs"),
            initial_delay_ms=self._config.tunable("outlineInitialDelayMs"),
        )
```

In `_attach_document`, after the bridge is built, schedule the initial outline request:

```python
        def request_outline():
            def on_resp(msg):
                items = msg.get("result") or []
                self._outline_ctrl.populate(items)
            server._send_request(
                "textDocument/documentSymbol",
                {"textDocument": {"uri": uri}},
                on_resp,
            )
            return False  # one-shot
        GLib.timeout_add(self._config.tunable("outlineInitialDelayMs"), request_outline)
```

(`from gi.repository import GLib` already imported.)

- [ ] **Step 3: Run all tests**

Run: `pytest tests/unit/test_outline_controller.py tests/integration/test_outline_e2e.py -v`
Expected: both pass.

- [ ] **Step 4: Manual smoke test**

Open a Python file with classes and functions; the right-side panel "LSP Outline" should populate within 1–2 seconds.

- [ ] **Step 5: Commit + CHANGELOG**

```bash
git add src/gedit_lsp/features/outline.py src/gedit_lsp/plugin.py
git commit -m "feat: implement document outline side panel"
git commit -am "docs: log outline feature"  # after editing CHANGELOG and protocol-coverage
```

---

## Milestone 9 — UI Polish: Statusbar, Crash-loop Notification, Bottom Panel, Prefs Dialog

**Goal:** All non-feature UI pieces from spec section 6: statusbar indicator, info-bar on circuit-breaker trip, bottom panel listing all diagnostics in the window, preferences dialog reading/writing the same JSON file.

**Exit criteria:** Manual smoke-test checklist (`docs/manual-smoke-test.md`) passes 100%. No new integration tests required — these are visual UI components and are best verified by hand.

### Task M9.1: Implement statusbar indicator

**Files:**
- Create: `src/gedit_lsp/ui/statusbar.py`
- Modify: `src/gedit_lsp/plugin.py`

- [ ] **Step 1: Implement the widget**

```python
"""Statusbar indicator showing LSP state for the active buffer."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gedit", "46")
from gi.repository import Gedit, Gtk


class StatusbarIndicator:
    def __init__(self, window: Gedit.Window) -> None:
        self._window = window
        self._label = Gtk.Label(label="")
        self._label.set_margin_start(8)
        self._label.set_margin_end(8)
        statusbar = window.get_statusbar()
        statusbar.pack_end(self._label, False, False, 0)
        self._label.show()

    def set_state(self, text: str) -> None:
        self._label.set_text(text)

    def hide(self) -> None:
        self._label.hide()

    def show(self) -> None:
        self._label.show()

    def destroy(self) -> None:
        self._label.destroy()
```

- [ ] **Step 2: Wire it into the plugin**

In `plugin.py`, `do_activate`:

```python
        from gedit_lsp.ui.statusbar import StatusbarIndicator
        self._statusbar = StatusbarIndicator(win)
        if not self._config.tunable("showStatusbarIndicator"):
            self._statusbar.hide()
```

When state changes (server transition, attach, detach, large-file skip), call `self._statusbar.set_state(...)`. Hook these in:

```python
    def _refresh_statusbar(self):
        view = self.window.get_active_view()
        if view is None:
            self._statusbar.set_state("")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        if bridge is None:
            self._statusbar.set_state("")
            return
        from gedit_lsp.server import ServerState
        from pathlib import Path as _P
        server = self._registry.get_or_spawn(
            bridge.language_id,
            _P(bridge.uri.replace("file://", "")).parent,
        )
        if server is None:
            self._statusbar.set_state("")
            return
        cmd = server.command[0] if server.command else "?"
        states = {
            ServerState.NOT_RUNNING: f"LSP: {cmd} ⏵",
            ServerState.STARTING:    f"LSP: {cmd} …",
            ServerState.READY:       f"LSP: {cmd} ⚡",
            ServerState.IDLE:        f"LSP: {cmd} ⚡",
            ServerState.STOPPING:    f"LSP: {cmd} ⏹",
            ServerState.CIRCUIT_OPEN: f"LSP: {cmd} ✗ disabled",
        }
        self._statusbar.set_state(states.get(server.state, ""))
```

Connect a `notify::state` mechanism on `LanguageServer` (a small list of state-change callbacks). In `server.py`, add:

```python
    def add_state_listener(self, callback: Callable[[ServerState], None]) -> None:
        self._state_listeners.append(callback)
```

…and call it whenever `self.state = X` happens. Add `self._state_listeners: list[Callable[[ServerState], None]] = []` in `__init__`. Use a property setter:

```python
    @property
    def state(self) -> ServerState:
        return self._state

    @state.setter
    def state(self, value: ServerState) -> None:
        self._state = value
        for cb in self._state_listeners:
            cb(value)
```

(Replace direct `self.state = X` with `self._state = X` in `__init__`.)

In `plugin.py`, after `get_or_spawn`:

```python
        server.add_state_listener(lambda _s: self._refresh_statusbar())
```

Also call `self._refresh_statusbar()` whenever the active tab changes (`window` `active-tab-changed` signal).

- [ ] **Step 3: Manual smoke**

Verify the statusbar updates as the server transitions states.

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/ui/statusbar.py src/gedit_lsp/plugin.py src/gedit_lsp/server.py
git commit -m "feat: add statusbar indicator with server-state tracking"
```

### Task M9.2: Implement bottom panel diagnostics list

**Files:**
- Create: `src/gedit_lsp/ui/diagnostics_panel.py`
- Modify: `src/gedit_lsp/plugin.py`

- [ ] **Step 1: Implement the panel**

```python
"""Bottom panel listing all diagnostics across all open buffers in the window."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gedit", "46")
from gi.repository import Gedit, Gio, Gtk


class DiagnosticsPanel:
    def __init__(self, window: Gedit.Window) -> None:
        self._window = window
        # cols: severity, line, message, source, uri (hidden)
        self._store = Gtk.ListStore(str, int, str, str, str)
        self._view = Gtk.TreeView(model=self._store)
        for i, title in enumerate(["Severity", "Line", "Message", "Source"]):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            self._view.append_column(col)
        self._view.connect("row-activated", self._on_row_activated)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self._view)
        scrolled.show_all()
        panel = window.get_bottom_panel()
        panel.add_titled(scrolled, "lsp-diagnostics", "LSP Diagnostics")

    def update_for_uri(self, uri: str, diagnostics: list[dict]) -> None:
        # Remove existing rows for this URI
        rows_to_remove = []
        it = self._store.get_iter_first()
        while it:
            if self._store.get_value(it, 4) == uri:
                rows_to_remove.append(self._store.get_path(it))
            it = self._store.iter_next(it)
        for path in reversed(rows_to_remove):
            self._store.remove(self._store.get_iter(path))
        for d in diagnostics:
            sev = {1: "Error", 2: "Warning", 3: "Info", 4: "Hint"}.get(
                d.get("severity", 1), "Error"
            )
            line = d["range"]["start"]["line"] + 1
            self._store.append(
                [sev, line, d.get("message", ""), d.get("source", ""), uri]
            )

    def _on_row_activated(self, view, path, _column) -> None:
        it = self._store.get_iter(path)
        line = self._store.get_value(it, 1) - 1
        uri = self._store.get_value(it, 4)
        gfile = Gio.File.new_for_uri(uri)
        self._window.create_tab_from_location(gfile, None, line + 1, 0, False, True)
```

- [ ] **Step 2: Wire it**

In `plugin.py`, `do_activate`:

```python
        from gedit_lsp.ui.diagnostics_panel import DiagnosticsPanel
        self._diag_panel = DiagnosticsPanel(win)
```

In the diagnostics callback (`_on_diag` in `_attach_document`), after `ctrl.apply_diagnostics(...)`, also call:

```python
            self._diag_panel.update_for_uri(uri, params["diagnostics"])
```

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/ui/diagnostics_panel.py src/gedit_lsp/plugin.py
git commit -m "feat: add bottom-panel diagnostics list"
```

### Task M9.3: Implement crash-loop info-bar

**Files:**
- Create: `src/gedit_lsp/ui/crash_notify.py`
- Modify: `src/gedit_lsp/plugin.py`

- [ ] **Step 1: Implement**

```python
"""Crash-loop notification — Gtk.InfoBar on Gedit.Tab.set_info_bar()."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gedit", "46")
from gi.repository import Gedit, Gtk


class CrashNotifier:
    def __init__(self, window: Gedit.Window) -> None:
        self._window = window
        self._active: dict[Gedit.Tab, Gtk.InfoBar] = {}

    def show_for_tab(
        self,
        tab: Gedit.Tab,
        message: str,
        on_restart,
        on_open_log,
        on_disable,
    ) -> None:
        if tab in self._active:
            return
        bar = Gtk.InfoBar()
        bar.set_message_type(Gtk.MessageType.WARNING)
        content = bar.get_content_area()
        content.add(Gtk.Label(label=message))
        bar.add_button("Restart", 1)
        bar.add_button("Open log", 2)
        bar.add_button("Disable for session", 3)
        bar.connect("response", lambda _b, rid: self._dispatch(tab, rid, on_restart, on_open_log, on_disable))
        bar.show_all()
        tab.set_info_bar(bar)
        self._active[tab] = bar

    def _dispatch(self, tab, response_id, on_restart, on_open_log, on_disable) -> None:
        bar = self._active.pop(tab, None)
        if bar is not None:
            tab.set_info_bar(None)
        if response_id == 1:
            on_restart()
        elif response_id == 2:
            on_open_log()
        elif response_id == 3:
            on_disable()
```

- [ ] **Step 2: Wire to circuit-breaker state**

In `plugin.py`'s state-listener callback, when state transitions to `CIRCUIT_OPEN`, find the tab(s) that bind to this `(lang, root)` and call `self._crash_notifier.show_for_tab(...)`.

```python
        from gedit_lsp.ui.crash_notify import CrashNotifier
        self._crash_notifier = CrashNotifier(win)
```

```python
    def _on_server_state(self, server, new_state):
        from gedit_lsp.server import ServerState
        if new_state != ServerState.CIRCUIT_OPEN:
            return
        # Find tabs whose document is bridged to this server
        for doc, bridge in self._bridges.items():
            if bridge.language_id != server.language_id:
                continue
            tab = self.window.get_tab_from_location(doc.get_file().get_location())
            if tab is None:
                continue
            self._crash_notifier.show_for_tab(
                tab,
                f"LSP for {server.language_id} ({server.root_path}) failed {self._config.tunable('restartMaxAttempts')} times.",
                on_restart=lambda s=server: (s.reset_circuit_breaker(), s.attach_buffer(bridge.uri)),
                on_open_log=self._open_log,
                on_disable=lambda s=server: None,  # no-op for now
            )

    def _open_log(self) -> None:
        path = (Path.home() / ".local/state/gedit-lsp/plugin.log")
        gfile = Gio.File.new_for_path(str(path))
        self.window.create_tab_from_location(gfile, None, 1, 0, False, True)
```

(In `_ensure_globals` or per-server wiring, attach the listener: `server.add_state_listener(lambda s: self._on_server_state(server, s))`.)

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/ui/crash_notify.py src/gedit_lsp/plugin.py
git commit -m "feat: surface crash-loop circuit-breaker as info-bar"
```

### Task M9.4: Implement Preferences dialog (reads/writes JSON config)

**Files:**
- Create: `src/gedit_lsp/ui/prefs.py`
- Modify: `src/gedit_lsp/plugin.py` to expose `do_create_configure_widget`

- [ ] **Step 1: Implement the widget**

```python
"""Preferences dialog — reads/writes ~/.config/gedit/lsp-plugin.json."""
from __future__ import annotations

import json
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk


def build_preferences_widget(config_path: Path) -> Gtk.Widget:
    user = _load(config_path)
    tunables = user.setdefault("tunables", {})

    grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=16)
    row = 0

    def add_row(label_text: str, widget: Gtk.Widget) -> None:
        nonlocal row
        lbl = Gtk.Label(label=label_text)
        lbl.set_xalign(0)
        grid.attach(lbl, 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)
        row += 1

    # Idle timeout (slider 60..3600)
    idle_adj = Gtk.Adjustment(
        value=tunables.get("serverIdleTimeoutSeconds", 300),
        lower=60, upper=3600, step_increment=60,
    )
    idle_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=idle_adj)
    idle_scale.set_hexpand(True)
    idle_scale.set_size_request(240, -1)
    idle_scale.set_value_pos(Gtk.PositionType.RIGHT)
    add_row("Idle timeout (seconds)", idle_scale)

    # Show statusbar indicator
    sb_check = Gtk.CheckButton(label="Show LSP statusbar indicator")
    sb_check.set_active(tunables.get("showStatusbarIndicator", True))
    add_row("", sb_check)

    # Log LSP traffic
    traffic_check = Gtk.CheckButton(label="Log LSP traffic to file")
    traffic_check.set_active(tunables.get("logLspTraffic", False))
    add_row("", traffic_check)

    # Max file size
    size_adj = Gtk.Adjustment(
        value=tunables.get("maxFileSizeBytes", 5_242_880),
        lower=10_000, upper=100_000_000, step_increment=100_000,
    )
    size_spin = Gtk.SpinButton(adjustment=size_adj)
    add_row("Max file size (bytes)", size_spin)

    # Enabled features
    enabled = tunables.get(
        "enabledFeatures", ["diagnostics", "hover", "definition", "outline"]
    )
    feat_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    feat_checks: dict[str, Gtk.CheckButton] = {}
    for feat in ["diagnostics", "hover", "definition", "outline"]:
        c = Gtk.CheckButton(label=feat)
        c.set_active(feat in enabled)
        feat_box.pack_start(c, False, False, 0)
        feat_checks[feat] = c
    add_row("Enabled features", feat_box)

    # Open config file button
    open_button = Gtk.Button(label="Edit user config…")
    open_button.connect(
        "clicked",
        lambda _b: Gio.AppInfo.launch_default_for_uri(
            f"file://{config_path}", None
        ),
    )
    add_row("", open_button)

    # Apply button
    apply = Gtk.Button(label="Save")
    def on_apply(_b):
        tunables["serverIdleTimeoutSeconds"] = int(idle_scale.get_value())
        tunables["showStatusbarIndicator"] = sb_check.get_active()
        tunables["logLspTraffic"] = traffic_check.get_active()
        tunables["maxFileSizeBytes"] = int(size_spin.get_value())
        tunables["enabledFeatures"] = [k for k, v in feat_checks.items() if v.get_active()]
        user["tunables"] = tunables
        _save(config_path, user)
    apply.connect("clicked", on_apply)
    add_row("", apply)

    grid.show_all()
    return grid


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
```

- [ ] **Step 2: Expose the configure widget**

The `Gedit.WindowActivatable` interface doesn't have `do_create_configure_widget`; that's `PeasGtk.Configurable`. Add it to the plugin class:

In `plugin.py`, change the imports and class:

```python
gi.require_version("PeasGtk", "1.0")
from gi.repository import PeasGtk

class GeditLspPlugin(GObject.Object, Gedit.WindowActivatable, PeasGtk.Configurable):
    __gtype_name__ = "GeditLspPlugin"
    window = GObject.Property(type=Gedit.Window)

    def do_create_configure_widget(self):
        from gedit_lsp.ui.prefs import build_preferences_widget
        return build_preferences_widget(_config_path())
```

- [ ] **Step 3: Manual smoke**

Open Preferences → Plugins → LSP → Configure. Verify:
- All controls reflect current config values.
- Saving updates `~/.config/gedit/lsp-plugin.json`.
- Reopening the dialog shows the saved values.

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/ui/prefs.py src/gedit_lsp/plugin.py
git commit -m "feat: add preferences dialog backed by JSON config"
```

### Task M9.5: Persistent ignore-list + file-size cap enforcement

**Files:**
- Modify: `src/gedit_lsp/plugin.py`

- [ ] **Step 1: Add the size + glob check**

Modify `_attach_document`. Before constructing the bridge:

```python
        from fnmatch import fnmatch
        size_limit = self._config.tunable("maxFileSizeBytes")
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size > size_limit:
            self._statusbar.set_state(f"LSP: skipped (large file)")
            return
        path_abs = str(path.resolve())
        for pattern in self._config.tunable("disabledForPaths"):
            if fnmatch(path_abs, pattern):
                self._statusbar.set_state(f"LSP: skipped (path excluded)")
                return
```

- [ ] **Step 2: Manual smoke**

Touch a 6 MB Python file in `/tmp`, open in gedit → statusbar reports "skipped (large file)". Open something inside `~/proj/.venv/` → "skipped (path excluded)".

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/plugin.py
git commit -m "feat: enforce file-size cap and disabledForPaths ignore-list"
```

### Task M9.6: i18n stub

**Files:**
- Create: `src/gedit_lsp/i18n.py`
- Create: `po/POTFILES.in`
- Create: `po/LINGUAS`
- Modify: source files to wrap user-visible strings in `_()`

- [ ] **Step 1: Implement `i18n.py`**

```python
"""gettext setup. v0.1.0-alpha ships English only; the infrastructure lets
translations land later without code changes.
"""
from __future__ import annotations

import gettext
from pathlib import Path

_DOMAIN = "gedit-lsp"
_LOCALE_DIR = Path.home() / ".local/share/gedit/plugins/locale"

if _LOCALE_DIR.exists():
    gettext.bindtextdomain(_DOMAIN, str(_LOCALE_DIR))
    gettext.textdomain(_DOMAIN)


def _(s: str) -> str:
    return gettext.dgettext(_DOMAIN, s)
```

- [ ] **Step 2: Create `po/LINGUAS`** (empty file with a comment)

```
# Add language codes here as translations are contributed
```

- [ ] **Step 3: Create `po/POTFILES.in`**

```
src/gedit_lsp/plugin.py
src/gedit_lsp/ui/statusbar.py
src/gedit_lsp/ui/diagnostics_panel.py
src/gedit_lsp/ui/crash_notify.py
src/gedit_lsp/ui/prefs.py
src/gedit_lsp/features/diagnostics.py
src/gedit_lsp/features/hover.py
src/gedit_lsp/features/definition.py
src/gedit_lsp/features/outline.py
```

- [ ] **Step 4: Wrap user-visible strings**

In each of the source files listed above, add `from gedit_lsp.i18n import _` and wrap all strings that appear in UI labels, popovers, statusbar messages, etc. Example diff for `statusbar.py`:

```python
        states = {
            ServerState.NOT_RUNNING: _("LSP: {} ⏵").format(cmd),
            ServerState.STARTING:    _("LSP: {} …").format(cmd),
            ...
        }
```

- [ ] **Step 5: Generate the .pot template**

Run: `make pot`
Expected: `po/gedit-lsp.pot` is created with all wrapped strings.

- [ ] **Step 6: Commit**

```bash
git add src/gedit_lsp/i18n.py po
git commit -m "feat: add gettext infrastructure (English-only at alpha)"
```

### Task M9.7: M9 sweep + manual smoke-test checklist

- [ ] **Step 1: Run all unit + integration tests**

Run: `make lint typecheck test test-integration`
Expected: all green.

- [ ] **Step 2: Run manual smoke-test (defined in M10.5 — `docs/manual-smoke-test.md`)**

This is the formal pre-release gate.

---

## Milestone 10 — Documentation, Release Pipeline, Alpha Cut

**Goal:** Every documentation file required for v0.1.0-alpha (spec section 15) exists and is complete; the release workflow is in place; a `v0.1.0-alpha` tag triggers a GitHub Release with the tarball + checksum.

**Exit criteria:** A `v0.1.0-alpha` tag pushed to GitHub produces a published pre-release with `gedit-lsp-plugin-0.1.0a0.tar.gz` and `.sha256` attached.

### Task M10.1: Write `docs/install.md`

**Files:**
- Create: `docs/install.md`

- [ ] **Step 1: Write the file**

```markdown
# Installing the gedit LSP plugin

## Requirements

- gedit ≥ 46
- libpeas-1.0
- GtkSourceView-4
- Python ≥ 3.10
- GObject introspection bindings: `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-gtksource-4`

### Per-distro install commands

**Debian / Ubuntu (24.04+):**

```bash
sudo apt install gedit python3-gi gir1.2-gtk-3.0 gir1.2-gtksource-4
```

**Fedora (39+):**

```bash
sudo dnf install gedit python3-gobject gtksourceview4
```

**Arch / Manjaro:**

```bash
sudo pacman -S gedit python-gobject gtksourceview4
```

**openSUSE Tumbleweed:**

```bash
sudo zypper install gedit python3-gobject typelib-1_0-GtkSource-4
```

### Flatpak gedit caveat

The Flatpak build of gedit runs in a sandbox that cannot spawn host
binaries like `pylsp` or `clangd`. **The plugin will not function under
Flatpak gedit.** Install the distro-package version of gedit instead.

## Install the plugin

### From a release tarball (recommended for users)

```bash
curl -LO https://github.com/<your-account>/gedit-lsp-plugin/releases/download/v0.1.0-alpha/gedit-lsp-plugin-0.1.0a0.tar.gz
curl -LO https://github.com/<your-account>/gedit-lsp-plugin/releases/download/v0.1.0-alpha/gedit-lsp-plugin-0.1.0a0.tar.gz.sha256
sha256sum -c gedit-lsp-plugin-0.1.0a0.tar.gz.sha256
tar xzf gedit-lsp-plugin-0.1.0a0.tar.gz
cd gedit-lsp-plugin-0.1.0a0
make install
```

### From source (recommended for developers)

```bash
git clone https://github.com/<your-account>/gedit-lsp-plugin
cd gedit-lsp-plugin
make install
```

Both paths copy:

- `src/gedit_lsp/` → `~/.local/share/gedit/plugins/gedit_lsp/`
- `data/gedit-lsp.plugin` → `~/.local/share/gedit/plugins/gedit-lsp.plugin`

## Install language servers

Install the servers for the languages you use. Examples:

| Language | Server | Install command |
|---|---|---|
| Python | pylsp | `sudo apt install python3-pylsp` or `pip install --user python-lsp-server` |
| C / C++ | clangd | `sudo apt install clangd` |
| Rust | rust-analyzer | `rustup component add rust-analyzer` |
| Go | gopls | `go install golang.org/x/tools/gopls@latest` |
| TypeScript / JavaScript | typescript-language-server | `npm install -g typescript typescript-language-server` |
| Bash | bash-language-server | `npm install -g bash-language-server` |

The plugin auto-detects whichever servers are on `$PATH` at startup.

## Enable the plugin

1. Restart gedit.
2. **Edit → Preferences → Plugins**.
3. Tick **LSP**.

## Verify it works

```bash
echo "import nonexistent_module_xyz" > /tmp/test.py
gedit /tmp/test.py
```

Within a few seconds, a red squiggle should appear under
`nonexistent_module_xyz` and the row should appear in the *LSP
Diagnostics* bottom panel.

If it doesn't work, see `docs/troubleshooting.md`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/install.md
git commit -m "docs: add install.md"
```

### Task M10.2: Write `docs/configure.md`

**Files:**
- Create: `docs/configure.md`

- [ ] **Step 1: Write the file**

```markdown
# Configuring the gedit LSP plugin

The plugin reads a single JSON config file:

```
~/.config/gedit/lsp-plugin.json
```

Missing keys fall through to built-in defaults.

## Top-level structure

```json
{
  "servers": {            "<lang-id>": { "command": ["..."] } },
  "rootMarkers": {        "<lang-id>": ["...", "..."] },
  "initializationOptions": { "<lang-id>": { ... } },
  "tunables": { /* see below */ }
}
```

`<lang-id>` matches the GtkSourceView language ID (`python`, `c`, `cpp`,
`rust`, `go`, `typescript`, `js`, `sh`, `haskell`, …).

## `servers` — replace built-in command for a language

User entries fully replace the built-in entry for the same language.

```json
{ "servers": { "python": { "command": ["pyright-langserver", "--stdio"] } } }
```

To add a new language not in the built-ins:

```json
{ "servers": { "haskell": { "command": ["haskell-language-server-wrapper", "--lsp"] } } }
```

## `rootMarkers` — override the project-root walk

```json
{ "rootMarkers": { "python": ["pyproject.toml", ".git"] } }
```

Order in the list does not matter — the first marker found while walking
upward wins.

## `initializationOptions` — server-specific init parameters

Forwarded verbatim to the server's `initialize` request.

```json
{ "initializationOptions": {
    "python": { "pylsp": { "plugins": { "pycodestyle": { "enabled": false } } } }
  } }
```

## `tunables` — runtime knobs

Per-key replacement; missing keys keep their default.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `serverIdleTimeoutSeconds` | int | 300 | Seconds of buffer-detached idleness before the server is shut down |
| `changeDebounceMs` | int | 150 | Debounce window for `textDocument/didChange` |
| `outlineRefreshDebounceMs` | int | 2000 | Debounce window for outline refresh after edits |
| `outlineInitialDelayMs` | int | 1000 | Delay before first outline request after document open |
| `hoverSpinnerThresholdMs` | int | 300 | Show spinner if hover hasn't returned by this time |
| `requestTimeoutMs` | int | 10000 | Per-request timeout |
| `gotoHistoryMaxEntries` | int | 50 | Max entries in the cursor history (Alt+Left) |
| `restartBackoffSchedule` | int[] | `[1,2,4,8,16,30]` | Backoff delays (seconds) on consecutive crashes |
| `restartMaxAttempts` | int | 5 | After this many crashes, the circuit breaker trips |
| `logLevel` | str | `"info"` | One of `debug`, `info`, `warning`, `error` |
| `logRotationMaxBytes` | int | 5_242_880 | Max bytes per log file before rotation |
| `logRotationKeepFiles` | int | 3 | Number of historical log files retained |
| `logLspTraffic` | bool | `false` | Whether to write all wire messages to a separate traffic log |
| `maxFileSizeBytes` | int | 5_242_880 | Buffers larger than this are skipped |
| `showStatusbarIndicator` | bool | `true` | Show the LSP state indicator in the statusbar |
| `enabledFeatures` | str[] | `["diagnostics","hover","definition","outline"]` | Which features run |
| `severityIcons` | obj | (see defaults) | Per-severity gutter icon names |
| `severityUnderlineStyle` | obj | (see defaults) | Per-severity Pango underline style: `error`, `single`, `none` |
| `disabledForPaths` | str[] | (see defaults) | Glob patterns; matching buffers are skipped |
| `serverCapabilityOverrides` | obj | `{}` | Deep-merged on top of server's `initialize` response capabilities |

## Recipes

### Switch Python from pylsp to pyright

```json
{
  "servers": { "python": { "command": ["pyright-langserver", "--stdio"] } }
}
```

### Disable diagnostics globally, keep hover and definition

```json
{ "tunables": { "enabledFeatures": ["hover", "definition", "outline"] } }
```

### Disable hover for Python only (server-side)

```json
{
  "tunables": {
    "serverCapabilityOverrides": {
      "python": { "hoverProvider": false }
    }
  }
}
```

### Add additional ignore globs

```json
{
  "tunables": {
    "disabledForPaths": [
      "**/.venv/**", "**/node_modules/**", "**/vendor/**", "**/generated/**"
    ]
  }
}
```

### Enable the LSP traffic log temporarily for bug reports

```json
{ "tunables": { "logLspTraffic": true } }
```

The log appears at `~/.local/state/gedit-lsp/lsp-traffic.log`. Disable it
after debugging — the file rotates but grows fast under heavy use.
```

- [ ] **Step 2: Commit**

```bash
git add docs/configure.md
git commit -m "docs: add configure.md (full schema and recipes)"
```

### Task M10.3: Write `docs/uninstall.md` and `docs/troubleshooting.md`

**Files:**
- Create: `docs/uninstall.md`
- Create: `docs/troubleshooting.md`

- [ ] **Step 1: Write `docs/uninstall.md`**

```markdown
# Uninstalling the gedit LSP plugin

## Files installed

| Path | Created when |
|---|---|
| `~/.local/share/gedit/plugins/gedit_lsp/` | `make install` |
| `~/.local/share/gedit/plugins/gedit-lsp.plugin` | `make install` |
| `~/.local/share/gedit/plugins/locale/<lang>/LC_MESSAGES/gedit-lsp.mo` | `make mo` |
| `~/.local/state/gedit-lsp/plugin.log[.1..N]` | first plugin run |
| `~/.local/state/gedit-lsp/lsp-traffic.log[.1..N]` | only if `logLspTraffic: true` |
| `~/.config/gedit/lsp-plugin.json` | only if you created it |

## Quick uninstall (Makefile target)

```bash
cd /path/to/gedit-lsp-plugin   # or extracted release tarball
make uninstall
```

`make uninstall` removes:

- the plugin source dir
- the manifest
- the entire log directory (`~/.local/state/gedit-lsp/`)

It does **not** touch your user config (`~/.config/gedit/lsp-plugin.json`)
because that's your data.

## Manual uninstall

```bash
rm -rf ~/.local/share/gedit/plugins/gedit_lsp
rm -f ~/.local/share/gedit/plugins/gedit-lsp.plugin
rm -rf ~/.local/state/gedit-lsp
# Optional — only if you want to wipe your settings too:
rm -f ~/.config/gedit/lsp-plugin.json
```

## Verify clean uninstall

```bash
ls ~/.local/share/gedit/plugins/      # should not contain gedit_lsp
ls ~/.local/state/                    # should not contain gedit-lsp
```

Restart gedit; the plugin should no longer appear in **Edit → Preferences
→ Plugins**.
```

- [ ] **Step 2: Write `docs/troubleshooting.md`**

```markdown
# Troubleshooting

## Decision tree

### Plugin doesn't appear in Edit → Preferences → Plugins

- Check `~/.local/share/gedit/plugins/` contains both `gedit_lsp/` and `gedit-lsp.plugin`.
- Check the manifest's `Loader=python3` line is present (`cat ~/.local/share/gedit/plugins/gedit-lsp.plugin`).
- Check the log: `tail ~/.local/state/gedit-lsp/plugin.log` — Python import errors land here.
- Are you running gedit from Flatpak? It can't run host binaries; use the distro package.

### Plugin loads but no diagnostics appear

1. Check the language server is installed: `which pylsp` (or whichever).
2. Check `~/.local/state/gedit-lsp/plugin.log` for "spawn failed" messages.
3. Enable the traffic log: edit `~/.config/gedit/lsp-plugin.json`:
   ```json
   { "tunables": { "logLspTraffic": true } }
   ```
   Restart gedit, reopen the file. `~/.local/state/gedit-lsp/lsp-traffic.log` should now show:
   - `>>> ... initialize`
   - `<<< ... result for initialize`
   - `>>> ... textDocument/didOpen`
   - `<<< ... textDocument/publishDiagnostics`
4. If `publishDiagnostics` never arrives, the issue is server-side. Run the server manually to see its stderr:
   ```bash
   pylsp --check-parent-process < /dev/null
   ```

### Statusbar shows "⚠ exited" or "✗ disabled"

The server crashed N times in a row and the circuit breaker tripped.
Click the statusbar label → **Restart**, or check `plugin.log` for the
exit reason.

### Hover popover never appears

- Cursor must be on a symbol the server recognizes.
- Some servers (e.g. clangd) need a `compile_commands.json` for hover to work.
- Check the traffic log for `<<<` response to `textDocument/hover`.

### Diagnostics line numbers are wrong

This indicates a UTF-16 conversion bug — the highest-risk module in the
plugin. Please file a bug report with:
- The exact file content (or a minimal reproduction)
- The exact diagnostic that's misplaced
- The plugin and traffic logs

### "skipped (large file)" in statusbar

The buffer is over `maxFileSizeBytes` (default 5 MB). Increase it in your
config:
```json
{ "tunables": { "maxFileSizeBytes": 20000000 } }
```

### "skipped (path excluded)" in statusbar

The buffer's path matches a `disabledForPaths` glob (default excludes
`.venv`, `node_modules`, etc.). Edit the list in your config.
```

- [ ] **Step 3: Commit**

```bash
git add docs/uninstall.md docs/troubleshooting.md
git commit -m "docs: add uninstall.md and troubleshooting.md"
```

### Task M10.4: Write supporting docs (`security.md`, `license.md`, `architecture.md`, `development.md`, `contributing.md`, `roadmap.md`)

**Files:**
- Create: `docs/security.md`
- Create: `docs/license.md`
- Create: `docs/architecture.md`
- Create: `docs/development.md`
- Create: `docs/contributing.md`
- Create: `docs/roadmap.md`

- [ ] **Step 1: `docs/security.md`** (mirrors spec section 10)

```markdown
# Security & Privacy

## Single config file

The plugin reads exactly one config file:
`$XDG_CONFIG_HOME/gedit/lsp-plugin.json` (typically
`~/.config/gedit/lsp-plugin.json`).

It **does not** read per-project config files (e.g. a hypothetical
`.gedit-lsp.json` placed in a project directory). This is deliberate: a
malicious project could otherwise execute arbitrary commands by dropping
such a file in its tree.

If you want per-project servers, edit your global config to add the
project's specific server entry, or change the project root via
`rootMarkers` so each project gets its own server instance.

## No telemetry, no network

The plugin makes no network calls. It only spawns user-configured
language servers; what those servers do is entirely the server's
responsibility.

## Servers run with user privileges

Spawned servers run as the user, with no sandboxing. Trust your servers.

## License obligations

The plugin source is MIT (`LICENSE`). Loaded into gedit at runtime, the
combined work is governed by GPL-2.0-or-later (gedit's license). The
plugin source may be reused under MIT terms in any project, including
non-GPL projects. See `docs/license.md`.
```

- [ ] **Step 2: `docs/license.md`**

```markdown
# License

## Plugin source code

The plugin source code in this repository is licensed under the MIT
License (see `LICENSE` in the repository root).

## Combined runtime work

When the plugin is loaded into gedit at runtime via libpeas, the
resulting combined work — your gedit process containing this plugin's
code — is governed by GPL-2.0-or-later, which is gedit's license.

## What this means in practice

- **You can use the plugin source under MIT terms** in any project,
  including non-GPL projects, as long as you respect the MIT notice.
- **Distributing a binary tarball that bundles gedit + this plugin**
  must comply with GPL-2.0-or-later.
- **Distributing the plugin source alone** (this repository's contents)
  is governed by MIT only.

## Compatibility

MIT is GPL-compatible (it adds no restrictions over GPL). This means
GPL software can absorb this code; permissive software can also use it
freely.

## I am not your lawyer

This is a description of the licensing arrangement, not legal advice. If
you intend to redistribute this code in a commercial or otherwise
sensitive context, consult a lawyer who specialises in open-source
licensing.
```

- [ ] **Step 3: `docs/architecture.md`** (a permanent counterpart to spec section 3)

Write a high-level architecture overview using the same diagram and component descriptions from the spec, intended to be kept in sync as architecture evolves. Roughly 200–400 words. Engineers should refer to the spec for design rationale and to this for current architecture.

```markdown
# Architecture

This document describes the current architecture of the gedit LSP
plugin. For the *design rationale*, see
`docs/superpowers/specs/2026-05-02-gedit-lsp-plugin-design.md`. For new
component additions or significant changes, update both this file and
the spec; this file remains authoritative for what the code looks like
now.

## Component map

```
GeditLspPlugin (per gedit window)
    ├── Config          (process global, watches user JSON)
    ├── ServerRegistry  (process global, dict[(lang, root)] → LanguageServer)
    │       └── LanguageServer
    │               └── RpcClient → Gio.Subprocess (one per language server)
    ├── DocumentBridge  (one per Gedit.Document)
    └── FeatureControllers (one of each per Gedit.Document)
            ├── DiagnosticsController
            ├── HoverController
            ├── DefinitionController
            └── OutlineController
```

(Continue with one paragraph per component summarising its responsibility
— see spec section 3 for fuller descriptions.)

## Data flow

```
gedit signals → DocumentBridge → LanguageServer → RpcClient → subprocess
                                                ← RpcClient ←
                ← FeatureControllers ←
```

## Threading model

Single-threaded GLib main loop. All async I/O via `Gio.DataInputStream` /
`Gio.OutputStream` async methods. No `asyncio`, no Python threads.
```

- [ ] **Step 4: `docs/development.md`**

```markdown
# Development guide

## Setup

```bash
git clone https://github.com/<your-account>/gedit-lsp-plugin
cd gedit-lsp-plugin
pip install -e ".[dev]"
```

## Run tests

```bash
make test                  # unit only
make test-integration      # requires pylsp on PATH
make lint typecheck        # ruff + mypy
```

## Run gedit against the source tree without installing

```bash
cp -r src/gedit_lsp data/gedit-lsp.plugin ~/.local/share/gedit/plugins/
# or symlink for live edits:
ln -s "$(pwd)/src/gedit_lsp" ~/.local/share/gedit/plugins/gedit_lsp
ln -s "$(pwd)/data/gedit-lsp.plugin" ~/.local/share/gedit/plugins/gedit-lsp.plugin
```

After source changes, restart gedit (libpeas does not hot-reload).

## Logs while developing

```bash
tail -F ~/.local/state/gedit-lsp/plugin.log
# in another terminal:
echo '{"tunables":{"logLspTraffic":true,"logLevel":"debug"}}' \
     > ~/.config/gedit/lsp-plugin.json
tail -F ~/.local/state/gedit-lsp/lsp-traffic.log
```

## Code style

`ruff check` is the source of truth. Formatting deltas with
`ruff format` are accepted in PRs without bikeshedding.

## Test discipline

- **Unit tests are TDD-style**: write the failing test first, see it
  fail, implement minimally, see it pass.
- **Integration tests require pylsp.** They live in
  `tests/integration/` and are excluded from default `pytest` runs by
  the Makefile target split.
- **Smoke scripts** in `tests/smoke/` are not collected by pytest. They
  serve as living documentation and run via `python ...`.

## Cutting an alpha release

See `docs/release.md` (coming in v0.1.0-alpha) — the short version is
`git tag v0.1.0-alpha && git push --tags`; CI does the rest.
```

- [ ] **Step 5: `docs/contributing.md`**

```markdown
# Contributing

Thanks for your interest! A few things to know before sending a PR.

## Process

1. **Open an issue first** describing what you want to change. Big
   changes should be agreed on before coding starts.
2. **Branch naming:** `feature/<short-name>` or `fix/<short-name>`.
3. **Commit style:** Conventional Commits (`feat:`, `fix:`, `docs:`,
   `test:`, `build:`, `ci:`, `refactor:`, `chore:`).
4. **Test discipline:** new code lands with tests. CI rejects PRs whose
   feature code touches `src/gedit_lsp/features/` without a
   corresponding update to `docs/configure.md` or
   `docs/protocol-coverage.md` (the `doc-gate` check).
5. **Sign your commits** if you can (`git commit -s`).

## What needs help

See the GitHub issue tracker; issues labelled `good first issue` are
deliberately scoped to be self-contained.

## Translations

`po/LINGUAS` lists supported locales (currently empty). To add one:

```bash
cd po
msginit -i gedit-lsp.pot -l de   # creates de.po
# translate strings in de.po
echo "de" >> LINGUAS
```

Send a PR with the `.po` file. The Makefile compiles all `po/*.po` to
installed `.mo` files via `make mo`.

## Code of Conduct

By participating, you agree to abide by the
[Contributor Covenant 2.1](../CODE_OF_CONDUCT.md).
```

- [ ] **Step 6: `docs/roadmap.md`**

```markdown
# Roadmap

## v0.1.0-beta (post-alpha polish)

- Surface server stderr via a menu action (currently log-only).
- Evaluation/screenshot script (`tests/eval/screenshots.py`) for README + visual regression.
- Codify v1.0.0 readiness criteria.

## v0.2.0 — Editing intelligence

- `textDocument/completion` (+ `completionItem/resolve`) wired to
  `GtkSourceCompletionProvider`.
- `textDocument/signatureHelp`.
- Snippet support behind a per-language opt-in.

## v0.3.0 — Sync & infrastructure improvements

- Incremental document sync (`TextDocumentSyncKind.Incremental`).
- Mouse-hover trigger.
- `$/progress` server-reported indexing.
- `workspace/didChangeWatchedFiles`.

## v0.4.0 — Editing operations

- `textDocument/rename` + `prepareRename`.
- `textDocument/codeAction`.
- `textDocument/formatting`, `rangeFormatting`.
- `textDocument/references`.
- `workspace/symbol`.

## v1.0.0 — Stable

Criteria:

- Scope C (completion) shipped.
- ≥ 6 months on stable releases without regression-class bugs reported.
- At least one translation other than English shipped.

Beyond v1: Flatpak gedit support (requires sandbox handshake), system
install, GPG-signed releases.
```

- [ ] **Step 7: Commit**

```bash
git add docs/security.md docs/license.md docs/architecture.md docs/development.md docs/contributing.md docs/roadmap.md
git commit -m "docs: add security, license, architecture, development, contributing, roadmap"
```

### Task M10.5: Write `docs/manual-smoke-test.md`

**Files:**
- Create: `docs/manual-smoke-test.md`

- [ ] **Step 1: Write the checklist**

```markdown
# Manual smoke-test checklist

Required to pass 100% before cutting a release. Tester reads each line,
performs the action, ticks the box.

## Setup

- [ ] On Ubuntu 24.04 + gedit 46.x.
- [ ] Plugin installed via `make install`.
- [ ] gedit restarted; plugin shows in Preferences → Plugins.
- [ ] Plugin enabled.
- [ ] `~/.config/gedit/lsp-plugin.json` does not exist (test the default path).
- [ ] `pylsp` is on `$PATH`.

## Diagnostics

- [ ] Open `/tmp/test.py` containing `import nonexistent_xyz`. Within 5 s,
      a red squiggle appears under the import target.
- [ ] *LSP Diagnostics* bottom panel lists the same error.
- [ ] Edit the file to fix the import. Within 5 s, the squiggle disappears.

## Hover

- [ ] Open a Python file using `os.path.join`. Place cursor on `join`.
      Press **Ctrl+K** → popover appears with `os.path.join` documentation.
- [ ] Press **Esc** → popover closes.
- [ ] Move cursor → if popover was still open, it closes.

## Definition

- [ ] Open `tests/fixtures/projects/python_definition/main.py`. Cursor
      on the call to `helper(42)` in `main`. Press **Ctrl+.** → cursor
      jumps to the `def helper(x):` line.
- [ ] Press **Alt+Left** → cursor returns to the `helper(42)` call.

## Outline

- [ ] Open `tests/fixtures/projects/python_outline/sample.py`. Within
      2 s, the *LSP Outline* side panel shows `Greeter > hello, goodbye`.
- [ ] Click `goodbye` in the panel → cursor jumps to the method.

## Multi-window / multi-buffer

- [ ] Open the same file in two gedit windows. Check
      `pgrep -c pylsp` shows **1** (single shared process).
- [ ] Close the first window. Check `pgrep -c pylsp` still shows **1**
      (other window keeps it alive).
- [ ] Close all gedit windows. Check `pgrep -c pylsp` shows **0** within
      `serverIdleTimeoutSeconds` + a few seconds.

## Crash-loop circuit breaker

- [ ] Edit config to set `"servers": {"python": {"command": ["nonexistent_binary_xyz"]}}`.
- [ ] Restart gedit, open a Python file. After backoff exhausted, an
      info-bar appears on the tab with [Restart] [Open log] [Disable].
- [ ] Click **Open log** → opens `~/.local/state/gedit-lsp/plugin.log` in a new tab.

## Statusbar states

- [ ] Active tab is a Python file with running pylsp → `LSP: pylsp ⚡`.
- [ ] Active tab has no language server configured → blank.
- [ ] Open a 6 MB+ file → `LSP: skipped (large file)`.
- [ ] Open a file under `~/x/.venv/lib/...` → `LSP: skipped (path excluded)`.

## Toggling

- [ ] Toggle plugin off (Preferences → Plugins). All squiggles, marks,
      panels disappear. gedit doesn't crash.
- [ ] Toggle on → state restored.

## Final

- [ ] All boxes ticked.
- [ ] No errors in `~/.local/state/gedit-lsp/plugin.log`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-smoke-test.md
git commit -m "docs: add manual smoke-test checklist"
```

### Task M10.6: Add `install.sh` (one-line installer)

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
set -euxo pipefail

# Idempotent install of the gedit LSP plugin into ~/.local/share/gedit/plugins/
# Re-running is safe; existing files are overwritten.

PLUGIN_DIR="${HOME}/.local/share/gedit/plugins"
SRC="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "${PLUGIN_DIR}"
cp -r "${SRC}/src/gedit_lsp" "${PLUGIN_DIR}/"
cp "${SRC}/data/gedit-lsp.plugin" "${PLUGIN_DIR}/"

echo
echo "Installed gedit LSP plugin to ${PLUGIN_DIR}"
echo "Restart gedit and enable the plugin in Edit → Preferences → Plugins."
```

- [ ] **Step 2: Make executable + commit**

```bash
chmod +x install.sh
git add install.sh
git commit -m "build: add one-line install.sh"
```

### Task M10.7: GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install system deps
        run: |
          sudo apt-get update
          sudo apt-get install -y python3-gi gir1.2-gtk-3.0 gir1.2-gtksource-4 python3-pylsp gettext

      - name: Install dev deps
        run: pip install -e ".[dev]"

      - name: Run full test suite
        run: |
          ruff check src tests
          mypy src
          pytest tests/unit
          pytest tests/integration

      - name: Generate .pot template
        run: make pot

      - name: Build distribution tarball
        run: make dist

      - name: Extract changelog section for this version
        id: changelog
        run: |
          tag="${GITHUB_REF#refs/tags/}"
          # Extract section from CHANGELOG.md between "## [<version>]" and the next "## "
          version="${tag#v}"
          awk -v v="$version" '
            $0 ~ "^## \\[" v "\\]" { capture=1; print; next }
            capture && /^## \[/ { exit }
            capture { print }
          ' CHANGELOG.md > release-notes.md
          echo "Notes:"; cat release-notes.md

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          prerelease: true
          body_path: release-notes.md
          files: |
            dist/*.tar.gz
            dist/*.tar.gz.sha256
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add release workflow (tag → tarball + GitHub Release)"
```

### Task M10.8: Final pre-release sweep

- [ ] **Step 1: Run the manual smoke-test from M10.5**

Walk through `docs/manual-smoke-test.md` checking every box. Fix any
defects found and commit them.

- [ ] **Step 2: Run the full automated suite**

```bash
make lint typecheck test test-integration
```

Expected: all green.

- [ ] **Step 3: Update `CHANGELOG.md`** with the v0.1.0-alpha section

```markdown
## [0.1.0-alpha] — 2026-MM-DD

### Added

- Initial alpha release of the gedit LSP plugin.
- Diagnostics: squiggles via `Gtk.TextTag`, gutter marks, bottom panel listing.
- Hover: Ctrl+K shows a popover with `textDocument/hover` content.
- Go-to-Definition: Ctrl+. with cursor history (Alt+Left to return).
- Document outline: side panel populated from `textDocument/documentSymbol`.
- Single JSON config file at `~/.config/gedit/lsp-plugin.json`, with hot-reload.
- Built-in defaults for Python (pylsp), C/C++ (clangd), Rust, Go, TS/JS, Bash.
- Per-(language, project root) server lifecycle with idle-kill timer.
- Crash-loop circuit breaker with info-bar UI.
- Statusbar indicator with 8 distinct states.
- File-size cap and persistent ignore-list (`disabledForPaths`).
- Two log streams (plugin + opt-in LSP traffic) with rotation.
- Internationalisation infrastructure (English-only at alpha).
- MIT-licensed source with documented MIT/GPL runtime distinction.

### Tooling

- Unit + integration test suites in CI.
- `doc-gate` CI check requiring documentation updates with feature changes.
- Tag-triggered GitHub Release workflow with SHA-256 checksums.
```

- [ ] **Step 4: Commit and tag**

```bash
git add CHANGELOG.md
git commit -m "release: prepare v0.1.0-alpha"
git tag -a v0.1.0-alpha -m "v0.1.0-alpha — first usable release"
git push
git push --tags
```

The `release.yml` workflow runs on the tag push and creates the GitHub
Release.

- [ ] **Step 5: Verify the release on GitHub**

Visit `https://github.com/<your-account>/gedit-lsp-plugin/releases`.
Expected:

- A pre-release named `v0.1.0-alpha`.
- Body matches the `[0.1.0-alpha]` section from CHANGELOG.md.
- `gedit-lsp-plugin-0.1.0a0.tar.gz` and `.sha256` are attached.

Verify the tarball:

```bash
mkdir /tmp/release-check && cd /tmp/release-check
curl -LO https://github.com/<your-account>/gedit-lsp-plugin/releases/download/v0.1.0-alpha/gedit-lsp-plugin-0.1.0a0.tar.gz
curl -LO https://github.com/<your-account>/gedit-lsp-plugin/releases/download/v0.1.0-alpha/gedit-lsp-plugin-0.1.0a0.tar.gz.sha256
sha256sum -c *.sha256
tar xzf gedit-lsp-plugin-0.1.0a0.tar.gz
cd gedit-lsp-plugin-0.1.0a0
make install
```

Restart gedit and run the manual smoke test. If anything fails, the
release is broken — yank it and cut a `v0.1.0-alpha.1` after the fix.

---

## Self-Review Checklist (Plan Author)

Before handing this plan to an executor, verify:

- [ ] **Spec coverage:** Every section of `docs/superpowers/specs/2026-05-02-gedit-lsp-plugin-design.md` maps to one or more milestones (M0–M10). Sections 4 (config) and Appendix A → M2 + M9.4. Section 5 (lifecycle) → M3.3 + M3.4 + M9.3. Section 6 (UI) → M5–M9. Section 7 (sync + UTF-16) → M1.1–M1.4 + M3.2 + M4. Section 8 (logging) → M3.1 + M9 spot-checks. Section 9 (i18n) → M9.6. Section 10 (security/privacy) → M10.4. Section 11 (testing) → unit + integration tests in every milestone. Section 12 (layout) → M0.3. Sections 13–14 (build/CI) → M0.2, M0.6. Section 15 (docs matrix) → M10.1–M10.5. Section 16 (license) → M0.4 + M10.4. Section 17 (release) → M10.7–M10.8. Section 18 (roadmap) → M10.4 (`docs/roadmap.md`).
- [ ] **No placeholders:** No "TBD", "TODO", "implement later", or vague hand-waves. Where the plan says "(see fixture)" or "(see CHANGELOG section)", the referenced content exists in another task in the plan.
- [ ] **Type consistency:** `LanguageServer.send_notification`, `_send_request`, `add_diagnostics_listener`, `add_state_listener`, `kill_now`, `cancel_request` are all defined and used consistently. `Config.server_for`, `root_markers_for`, `initialization_options_for`, `tunable`, `add_observer` are consistent. `ServerRegistry.get_or_spawn`, `all_servers`, `shutdown_all` are consistent.
- [ ] **Frequent commits:** Every task ends with a commit step. No task batches multiple unrelated changes.
- [ ] **TDD discipline:** Every implementation task is preceded by a failing test task — exception: pure UI components (statusbar, info-bar, prefs dialog) which the spec explicitly notes are best verified by hand. Those skip TDD by design.
- [ ] **DRY:** `_send_request` is defined once (M6.2), used everywhere. Configuration loading is in one place. `utf16` is used by every controller via the same module — no inline conversions.
- [ ] **YAGNI:** No completion (v0.2). No incremental sync (v0.3). No mouse-hover (v0.2). No rename/code-actions (v0.4). The plan does not include features that aren't in scope B.

---

## Execution Handoff

Plan complete and saved to
`docs/superpowers/plans/2026-05-02-gedit-lsp-plugin-v0.1.0-alpha.md`.

**Two execution options:**

1. **Subagent-Driven (recommended).** A fresh subagent per task, review
   between tasks, fast iteration. Best for a project of this size (~80
   tasks across 11 milestones) — keeps the main context window clean
   and lets failures be diagnosed in isolation.

2. **Inline Execution.** Execute tasks in this session using
   `superpowers:executing-plans`, batch execution with checkpoints for
   review.

**Which approach?**
