"""Tests for LightbulbGutter — diagnostic-driven gutter indicator."""
from __future__ import annotations

from unittest.mock import MagicMock

from gedit_lsp.ui.lightbulb_gutter import LightbulbGutter


def _make_server() -> MagicMock:
    """Create a mock LanguageServer with diagnostic-listener tracking."""
    server = MagicMock()
    listeners: list = []

    def add_listener(cb):  # type: ignore[no-untyped-def]
        listeners.append(cb)
        def dispose() -> None:
            if cb in listeners:
                listeners.remove(cb)
        return dispose

    server.add_diagnostics_listener.side_effect = add_listener
    server._test_listeners = listeners
    return server


def test_listener_registered_on_construct() -> None:
    server = _make_server()
    activations: list[int] = []
    gutter = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=activations.append,
    )
    assert len(server._test_listeners) == 1
    # Avoid teardown warning
    gutter.dispose()


def test_diagnostics_populate_lit_lines() -> None:
    server = _make_server()
    gutter = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    # Simulate publishDiagnostics
    server._test_listeners[0]({
        "uri": "file:///a.py",
        "diagnostics": [
            {"range": {"start": {"line": 3, "character": 0}, "end": {"line": 3, "character": 4}}},
            {"range": {"start": {"line": 7, "character": 0}, "end": {"line": 7, "character": 4}}},
            {"range": {"start": {"line": 3, "character": 5}, "end": {"line": 3, "character": 9}}},
        ],
    })
    assert gutter.lit_lines() == {3, 7}
    gutter.dispose()


def test_diagnostics_for_other_uri_ignored() -> None:
    server = _make_server()
    gutter = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    server._test_listeners[0]({
        "uri": "file:///OTHER.py",
        "diagnostics": [
            {"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 4}}},
        ],
    })
    assert gutter.lit_lines() == set()
    gutter.dispose()


def test_empty_diagnostics_clears_lit_lines() -> None:
    server = _make_server()
    gutter = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    # First, lit lines
    server._test_listeners[0]({
        "uri": "file:///a.py",
        "diagnostics": [
            {"range": {"start": {"line": 3, "character": 0}, "end": {"line": 3, "character": 4}}},
        ],
    })
    assert gutter.lit_lines() == {3}
    # Then, server reports empty
    server._test_listeners[0]({"uri": "file:///a.py", "diagnostics": []})
    assert gutter.lit_lines() == set()
    gutter.dispose()


def test_dispose_removes_listener_and_renderer() -> None:
    server = _make_server()
    view = MagicMock()
    gutter_obj = MagicMock()
    view.get_gutter.return_value = gutter_obj
    g = LightbulbGutter(
        view=view, server=server, uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    assert len(server._test_listeners) == 1
    g.dispose()
    assert len(server._test_listeners) == 0
    gutter_obj.remove.assert_called_once()


def test_double_dispose_is_safe() -> None:
    server = _make_server()
    view = MagicMock()
    view.get_gutter.return_value = MagicMock()
    g = LightbulbGutter(
        view=view, server=server, uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    g.dispose()
    g.dispose()  # must not raise


def test_activate_line_calls_callback() -> None:
    server = _make_server()
    activations: list[int] = []
    g = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=activations.append,
    )
    g._fire_activate_for_test(line=5)
    assert activations == [5]
    g.dispose()
