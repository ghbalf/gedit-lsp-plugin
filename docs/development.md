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

The short version is `git tag v0.1.0-alpha && git push --tags`; CI does
the rest via `.github/workflows/release.yml`.
