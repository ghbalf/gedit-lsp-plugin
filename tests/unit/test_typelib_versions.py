"""Static check that every ``gi.require_version()`` call in ``src/`` uses
the typelib version gedit actually loads at runtime.

GObject-Introspection namespace versions are an ABI version, decoupled
from package versions. On Ubuntu 24.04 + gedit 46.x:

* ``Gedit-3.0.typelib`` — gedit's namespace has been frozen at 3.0 for
  a decade; there is no ``Gedit-46.typelib``.
* ``GtkSource-300.typelib`` — gedit links against the
  ``libgedit-gtksourceview`` fork (kept GTK3-compatible), which exposes
  namespace ``GtkSource-300`` rather than upstream ``GtkSource-4``.

A mismatch is invisible to the existing test suite (which never imports
``gedit_lsp.plugin``) but causes libpeas to silently fail to activate
the plugin in gedit. This test exists to make that class of bug visible.
"""
from __future__ import annotations

import re
from pathlib import Path

EXPECTED: dict[str, str] = {
    "Gedit": "3.0",
    "GtkSource": "300",
    "Gtk": "3.0",
    "Peas": "1.0",
    "PeasGtk": "1.0",
    "Tepl": "6",
    "Gio": "2.0",
    "GLib": "2.0",
    "Pango": "1.0",
}

_PATTERN = re.compile(
    r'gi\.require_version\(\s*["\'](?P<ns>[A-Za-z]+)["\']\s*,'
    r'\s*["\'](?P<ver>[\w.]+)["\']\s*\)'
)


def test_require_version_strings_match_gedit_46_runtime() -> None:
    src_root = Path(__file__).resolve().parents[2] / "src"
    bad: list[str] = []
    for py in sorted(src_root.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            m = _PATTERN.search(line)
            if not m:
                continue
            ns, ver = m.group("ns"), m.group("ver")
            assert ns in EXPECTED, (
                f"{py}:{line_no}: unknown namespace {ns!r}; add it to "
                f"EXPECTED in this test if it's intentional."
            )
            if ver != EXPECTED[ns]:
                bad.append(
                    f"  {py.relative_to(src_root.parent)}:{line_no}: "
                    f'require_version({ns!r}, {ver!r}) — expected {EXPECTED[ns]!r}'
                )
    assert not bad, (
        "gi.require_version() versions disagree with the gedit 46 runtime:\n"
        + "\n".join(bad)
    )
