"""Fixture for textDocument/codeAction integration test.

The `import os` line is intentionally unused: pylsp-ruff (rule F401)
should publish a diagnostic for it and offer a "Remove unused import"
quickfix. The test drives the full pipeline:

  open (didOpen) -> diagnostic arrives -> codeAction request ->
  resolve (if needed) -> apply edit -> assert `import os` is gone.

`sys` is used by `main()` so pylsp-ruff doesn't ALSO flag it as
unused (which could land another quickfix that confuses the test's
"pick the F401-os action" matching).
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    print(sys.version)


if __name__ == "__main__":
    main()
