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
