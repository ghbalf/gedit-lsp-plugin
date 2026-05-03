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
