"""Unit tests for the preferences dialog — specifically the invariant that
the on/off checkbox list stays in sync with DEFAULT_TUNABLES['enabledFeatures'].

We do NOT construct the dialog widget here (CI is headless; see
project_unit_tests_avoid_gtk_widgets). The checkbox names live in a
module-level constant precisely so this contract can be asserted without
spinning up a GtkWindow.
"""
from __future__ import annotations

from gedit_lsp.defaults import DEFAULT_TUNABLES
from gedit_lsp.ui.prefs import FEATURE_CHECKBOX_NAMES


def test_prefs_checkbox_list_covers_every_default_enabled_feature() -> None:
    """Regression for the historical drift documented in
    project_prefs_ui_missing_features.md. Each PR that added a gated
    feature (#13/#15/#16/#17/#18) updated DEFAULT_TUNABLES but forgot to
    add a checkbox to prefs.py, so users could only toggle 5 of the 11
    features through the UI. The invariant the user enforced
    (feedback_every_feature_in_prefs_and_enabledfeatures): every feature
    must appear in BOTH places. This test fails loudly if the next PR
    drifts again.
    """
    defaults = set(DEFAULT_TUNABLES["enabledFeatures"])
    prefs = set(FEATURE_CHECKBOX_NAMES)
    assert defaults == prefs, (
        f"prefs UI feature checkboxes out of sync with defaults.\n"
        f"  in defaults but not prefs: {defaults - prefs}\n"
        f"  in prefs but not defaults: {prefs - defaults}"
    )


def test_prefs_checkbox_names_are_a_sequence_not_a_set() -> None:
    """The on-screen order of checkboxes is meaningful (it should match
    the order users see in defaults.py), so the constant must be a list/
    tuple, not a set."""
    assert isinstance(FEATURE_CHECKBOX_NAMES, (list, tuple))
    assert list(FEATURE_CHECKBOX_NAMES) == DEFAULT_TUNABLES["enabledFeatures"]
