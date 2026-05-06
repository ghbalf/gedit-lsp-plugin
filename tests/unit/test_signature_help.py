"""Tests for the pure helpers in features/signature_help.py.

The GTK-bound `SignatureHelpController` is exercised in the smoke checklist
on the PR; only the protocol-mapping helpers are covered here.
"""
from __future__ import annotations

from gedit_lsp.features.signature_help import (
    ParsedSignatureHelp,
    SignatureSegments,
    build_signature_help_params,
    is_signature_help_supported,
    parse_signature_help,
    signature_retrigger_chars,
    signature_trigger_chars,
    split_signature_by_active_param,
)


# --- is_signature_help_supported ---------------------------------------------


def test_is_signature_help_supported_none_or_empty_is_false() -> None:
    assert is_signature_help_supported(None) is False
    assert is_signature_help_supported({}) is False


def test_is_signature_help_supported_non_empty_is_true() -> None:
    assert is_signature_help_supported({"triggerCharacters": ["("]}) is True
    assert is_signature_help_supported({"retriggerCharacters": [","]}) is True
    # A non-empty capability dict, even with empty trigger list, still counts as
    # "advertised" — the server promises the method exists; trigger absence just
    # means the user must invoke manually.
    assert is_signature_help_supported({"triggerCharacters": []}) is True


# --- signature_trigger_chars / signature_retrigger_chars ---------------------


def test_signature_trigger_chars_extracts_list() -> None:
    assert signature_trigger_chars({"triggerCharacters": ["(", ","]}) == ["(", ","]


def test_signature_trigger_chars_missing_returns_empty() -> None:
    assert signature_trigger_chars({}) == []
    assert signature_trigger_chars(None) == []


def test_signature_retrigger_chars_falls_back_to_trigger() -> None:
    cap = {"triggerCharacters": ["(", ","]}
    assert signature_retrigger_chars(cap) == ["(", ","]


def test_signature_retrigger_chars_explicit_empty_overrides_fallback() -> None:
    # Server explicitly sends [] — that's "no retriggers", not "use triggers".
    cap = {"triggerCharacters": ["(", ","], "retriggerCharacters": []}
    assert signature_retrigger_chars(cap) == []


def test_signature_retrigger_chars_explicit_distinct_set() -> None:
    cap = {"triggerCharacters": ["("], "retriggerCharacters": [",", ")"]}
    assert signature_retrigger_chars(cap) == [",", ")"]


def test_signature_retrigger_chars_no_capability() -> None:
    assert signature_retrigger_chars(None) == []
    assert signature_retrigger_chars({}) == []


# --- build_signature_help_params ---------------------------------------------


def test_build_params_kind2_with_trigger_character() -> None:
    p = build_signature_help_params(
        uri="file:///x.py", line=3, character=10,
        trigger_character="(", is_retrigger=False,
    )
    assert p["textDocument"] == {"uri": "file:///x.py"}
    assert p["position"] == {"line": 3, "character": 10}
    assert p["context"] == {
        "triggerKind": 2,
        "isRetrigger": False,
        "triggerCharacter": "(",
    }


def test_build_params_kind3_when_retrigger_only() -> None:
    p = build_signature_help_params(
        uri="file:///x.py", line=0, character=0,
        trigger_character=None, is_retrigger=True,
    )
    assert p["context"] == {"triggerKind": 3, "isRetrigger": True}
    assert "triggerCharacter" not in p["context"]


def test_build_params_kind1_when_invoked() -> None:
    p = build_signature_help_params(
        uri="file:///x.py", line=0, character=0,
        trigger_character=None, is_retrigger=False,
    )
    assert p["context"] == {"triggerKind": 1, "isRetrigger": False}
    assert "triggerCharacter" not in p["context"]


# --- split_signature_by_active_param -----------------------------------------


def test_split_offset_pair_shape() -> None:
    sig = {
        "label": "def foo(a: int, b: str) -> None",
        "parameters": [
            {"label": [8, 14]},   # "a: int"
            {"label": [16, 22]},  # "b: str"
        ],
    }
    seg = split_signature_by_active_param(sig, 1)
    assert seg == SignatureSegments(
        prefix="def foo(a: int, ",
        active="b: str",
        suffix=") -> None",
    )


def test_split_substring_shape() -> None:
    sig = {
        "label": "def foo(a: int, b: str) -> None",
        "parameters": [{"label": "a: int"}, {"label": "b: str"}],
    }
    seg = split_signature_by_active_param(sig, 0)
    assert seg.prefix == "def foo("
    assert seg.active == "a: int"
    assert seg.suffix == ", b: str) -> None"


def test_split_active_index_out_of_range_returns_label_only() -> None:
    sig = {"label": "f(a)", "parameters": [{"label": "a"}]}
    seg = split_signature_by_active_param(sig, 5)
    assert seg == SignatureSegments("f(a)", "", "")


def test_split_negative_active_index_returns_label_only() -> None:
    sig = {"label": "f(a)", "parameters": [{"label": "a"}]}
    seg = split_signature_by_active_param(sig, -1)
    assert seg == SignatureSegments("f(a)", "", "")


def test_split_missing_parameters_list_returns_label_only() -> None:
    sig = {"label": "f()"}
    seg = split_signature_by_active_param(sig, 0)
    assert seg == SignatureSegments("f()", "", "")


def test_split_malformed_offset_pair_returns_label_only() -> None:
    # Reversed offsets — 5 > 2 fails the start <= end check.
    sig = {"label": "f(arg)", "parameters": [{"label": [5, 2]}]}
    seg = split_signature_by_active_param(sig, 0)
    assert seg == SignatureSegments("f(arg)", "", "")


def test_split_offset_pair_out_of_label_bounds_returns_label_only() -> None:
    sig = {"label": "f(a)", "parameters": [{"label": [0, 99]}]}
    seg = split_signature_by_active_param(sig, 0)
    assert seg == SignatureSegments("f(a)", "", "")


def test_split_non_dict_parameter_returns_label_only() -> None:
    sig = {"label": "f(a)", "parameters": ["not a dict"]}
    seg = split_signature_by_active_param(sig, 0)
    assert seg == SignatureSegments("f(a)", "", "")


def test_split_substring_not_found_returns_label_only() -> None:
    sig = {"label": "f(a)", "parameters": [{"label": "z"}]}
    seg = split_signature_by_active_param(sig, 0)
    assert seg == SignatureSegments("f(a)", "", "")


def test_split_offset_pair_non_int_returns_label_only() -> None:
    sig = {"label": "f(a)", "parameters": [{"label": ["x", "y"]}]}
    seg = split_signature_by_active_param(sig, 0)
    assert seg == SignatureSegments("f(a)", "", "")


# --- parse_signature_help ----------------------------------------------------


def test_parse_signature_help_null_response() -> None:
    assert parse_signature_help(None) is None


def test_parse_signature_help_non_dict_response() -> None:
    assert parse_signature_help([]) is None
    assert parse_signature_help("foo") is None


def test_parse_signature_help_empty_signatures() -> None:
    assert parse_signature_help({"signatures": []}) is None
    assert parse_signature_help({}) is None


def test_parse_signature_help_active_signature_out_of_range_clamps_to_zero() -> None:
    response = {
        "signatures": [
            {"label": "f(a)", "parameters": [{"label": "a"}]},
        ],
        "activeSignature": 99,
        "activeParameter": 0,
    }
    parsed = parse_signature_help(response)
    assert parsed is not None
    assert parsed.active_signature_index == 0
    assert parsed.segments.active == "a"


def test_parse_signature_help_signature_active_param_overrides_top_level() -> None:
    # LSP 3.16+: signature.activeParameter takes precedence.
    response = {
        "signatures": [
            {
                "label": "f(a, b)",
                "parameters": [{"label": "a"}, {"label": "b"}],
                "activeParameter": 1,
            },
        ],
        "activeParameter": 0,
    }
    parsed = parse_signature_help(response)
    assert parsed is not None
    assert parsed.segments.active == "b"


def test_parse_signature_help_param_doc_preferred_over_signature_doc() -> None:
    response = {
        "signatures": [
            {
                "label": "f(a)",
                "parameters": [{"label": "a", "documentation": "param doc"}],
                "documentation": "signature doc",
            },
        ],
        "activeParameter": 0,
    }
    parsed = parse_signature_help(response)
    assert parsed is not None
    assert parsed.documentation == "param doc"


def test_parse_signature_help_falls_back_to_signature_doc_when_param_empty() -> None:
    response = {
        "signatures": [
            {
                "label": "f(a)",
                "parameters": [{"label": "a"}],  # no documentation
                "documentation": "signature doc",
            },
        ],
        "activeParameter": 0,
    }
    parsed = parse_signature_help(response)
    assert parsed is not None
    assert parsed.documentation == "signature doc"


def test_parse_signature_help_markup_content_documentation() -> None:
    response = {
        "signatures": [
            {
                "label": "f(a)",
                "parameters": [{"label": "a"}],
                "documentation": {"kind": "markdown", "value": "**bold doc**"},
            },
        ],
        "activeParameter": 0,
    }
    parsed = parse_signature_help(response)
    assert parsed is not None
    assert parsed.documentation == "**bold doc**"


def test_parse_signature_help_count_and_index_reported() -> None:
    response = {
        "signatures": [
            {"label": "f()", "parameters": []},
            {"label": "f(a)", "parameters": [{"label": "a"}]},
        ],
        "activeSignature": 1,
        "activeParameter": 0,
    }
    parsed = parse_signature_help(response)
    assert parsed is not None
    assert parsed.signature_count == 2
    assert parsed.active_signature_index == 1
    assert parsed.segments.active == "a"


def test_parse_signature_help_returns_dataclass() -> None:
    response = {"signatures": [{"label": "f()", "parameters": []}]}
    parsed = parse_signature_help(response)
    assert isinstance(parsed, ParsedSignatureHelp)
