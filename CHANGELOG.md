# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Hover feature: Ctrl+K sends `textDocument/hover` and renders the response in a popover.
- Go-to-definition: Ctrl+. sends `textDocument/definition` and navigates to the result. Alt+Left returns to the previous cursor position via a per-window history stack.
- Document outline: a side panel "LSP Outline" displays the symbol tree for the active document and jumps the cursor on row activation.

## [0.1.0-alpha] — TBD

Initial alpha release. Will be filled in at release time per docs/release.md.
