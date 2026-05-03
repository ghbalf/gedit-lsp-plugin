"""gedit LSP plugin — Language Server Protocol client for gedit."""

__version__ = "0.1.0a0"

# libpeas discovers GeditLspPlugin via the package namespace, but the import
# requires the Gedit typelib (only available inside a running gedit process).
# In test/dev environments without the typelib, skip the re-export silently.
import contextlib

with contextlib.suppress(ValueError, ImportError):
    from gedit_lsp.plugin import GeditLspPlugin  # noqa: F401
