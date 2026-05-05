"""Built-in defaults for the gedit LSP plugin.

Users override any subset via ~/.config/gedit/lsp-plugin.json. See
docs/configure.md for the merge policy.
"""
from __future__ import annotations

from typing import Any

BUILTIN_SERVERS: dict[str, dict[str, Any]] = {
    "python":     {"command": ["pylsp"]},
    "python3":    {"command": ["pylsp"]},
    "c":          {"command": ["clangd", "--background-index"]},
    "cpp":        {"command": ["clangd", "--background-index"]},
    "rust":       {"command": ["rust-analyzer"]},
    "go":         {"command": ["gopls"]},
    "typescript": {"command": ["typescript-language-server", "--stdio"]},
    "js":         {"command": ["typescript-language-server", "--stdio"]},
    "sh":         {"command": ["bash-language-server", "start"]},
}

DEFAULT_ROOT_MARKERS: list[str] = [
    ".git", ".hg", ".svn",
    "pyproject.toml", "setup.py", "Pipfile",
    "Cargo.toml",
    "go.mod",
    "package.json",
    "compile_commands.json", "CMakeLists.txt",
    "Makefile",
]

DEFAULT_KEYBINDINGS: dict[str, list[str]] = {
    "hover":            ["<Primary>k"],
    "goto-definition":  ["F12"],
    "go-back":          ["<Shift>F12"],
    "show-server-logs": [],
}

DEFAULT_TUNABLES: dict[str, Any] = {
    "serverIdleTimeoutSeconds": 300,
    "changeDebounceMs": 150,
    "outlineRefreshDebounceMs": 2000,
    "outlineInitialDelayMs": 1000,
    "hoverSpinnerThresholdMs": 300,
    "requestTimeoutMs": 10000,
    "gotoHistoryMaxEntries": 50,
    "restartBackoffSchedule": [1, 2, 4, 8, 16, 30],
    "restartMaxAttempts": 5,
    "logLevel": "info",
    "logRotationMaxBytes": 5_242_880,
    "logRotationKeepFiles": 3,
    "logLspTraffic": False,
    "maxFileSizeBytes": 5_242_880,
    "showStatusbarIndicator": True,
    "stderrBufferMaxLines": 1000,
    "enabledFeatures": ["diagnostics", "hover", "definition", "outline", "completion"],
    "severityIcons": {
        "error":   "dialog-error-symbolic",
        "warning": "dialog-warning-symbolic",
        "info":    "dialog-information-symbolic",
        "hint":    "dialog-information-symbolic",
    },
    "severityUnderlineStyle": {
        "error":   "error",
        "warning": "error",
        "info":    "error",
        "hint":    "error",
    },
    "severityUnderlineColor": {
        "error":   "#e01b24",
        "warning": "#e5a50a",
        "info":    "#62a0ea",
        "hint":    "#9a9996",
    },
    "disabledForPaths": [
        "**/.venv/**",
        "**/node_modules/**",
        "**/.tox/**",
        "**/dist/**",
        "**/build/**",
    ],
    "serverCapabilityOverrides": {},
}
