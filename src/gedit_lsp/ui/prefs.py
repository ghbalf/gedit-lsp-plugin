"""Preferences dialog — reads/writes ~/.config/gedit/lsp-plugin.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk


def build_preferences_widget(config_path: Path) -> Gtk.Widget:
    user = _load(config_path)
    tunables: dict[str, Any] = user.setdefault("tunables", {})

    grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=16)  # type: ignore[call-arg]
    row = 0

    def add_row(label_text: str, widget: Gtk.Widget) -> None:
        nonlocal row
        lbl = Gtk.Label(label=label_text)
        lbl.set_xalign(0)
        grid.attach(lbl, 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)
        row += 1

    idle_adj = Gtk.Adjustment(
        value=tunables.get("serverIdleTimeoutSeconds", 300),
        lower=60, upper=3600, step_increment=60,
    )
    idle_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=idle_adj)
    idle_scale.set_hexpand(True)
    idle_scale.set_size_request(240, -1)
    idle_scale.set_value_pos(Gtk.PositionType.RIGHT)
    add_row("Idle timeout (seconds)", idle_scale)

    sb_check = Gtk.CheckButton(label="Show LSP statusbar indicator")
    sb_check.set_active(tunables.get("showStatusbarIndicator", True))
    add_row("", sb_check)

    traffic_check = Gtk.CheckButton(label="Log LSP traffic to file")
    traffic_check.set_active(tunables.get("logLspTraffic", False))
    add_row("", traffic_check)

    size_adj = Gtk.Adjustment(
        value=tunables.get("maxFileSizeBytes", 5_242_880),
        lower=10_000, upper=100_000_000, step_increment=100_000,
    )
    size_spin = Gtk.SpinButton(adjustment=size_adj)
    add_row("Max file size (bytes)", size_spin)

    enabled = tunables.get(
        "enabledFeatures", ["diagnostics", "hover", "definition", "outline"]
    )
    feat_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    feat_checks: dict[str, Gtk.CheckButton] = {}
    for feat in ["diagnostics", "hover", "definition", "outline"]:
        c = Gtk.CheckButton(label=feat)
        c.set_active(feat in enabled)
        feat_box.pack_start(c, False, False, 0)  # type: ignore[attr-defined]
        feat_checks[feat] = c
    add_row("Enabled features", feat_box)

    open_button = Gtk.Button(label="Edit user config…")

    def _on_open_clicked(_b: Gtk.Button) -> None:
        if not config_path.exists():
            _save(config_path, user)
        Gio.AppInfo.launch_default_for_uri(f"file://{config_path}", None)

    open_button.connect("clicked", _on_open_clicked)
    add_row("", open_button)

    apply_button = Gtk.Button(label="Save")

    def _on_apply_clicked(_b: Gtk.Button) -> None:
        tunables["serverIdleTimeoutSeconds"] = int(idle_scale.get_value())
        tunables["showStatusbarIndicator"] = sb_check.get_active()
        tunables["logLspTraffic"] = traffic_check.get_active()
        tunables["maxFileSizeBytes"] = int(size_spin.get_value())
        tunables["enabledFeatures"] = [
            k for k, v in feat_checks.items() if v.get_active()
        ]
        user["tunables"] = tunables
        _save(config_path, user)

    apply_button.connect("clicked", _on_apply_clicked)
    add_row("", apply_button)

    grid.show_all()  # type: ignore[attr-defined]
    return grid


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
