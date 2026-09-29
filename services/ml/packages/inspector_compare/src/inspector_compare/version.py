"""Versions of the comparison engine and its rule set (recorded in findings, the protocol and the sidecar)."""

from __future__ import annotations

COMPARE_VERSION = "0.3.0"
# Bump on any change that can change a finding, a status or an exported value (rules, templates, precedence).
RULES_VERSION = "compare-rules-m1.3"
# Protocol renderer (texts, section layout, DOCX/PDF look).
PROTOCOL_VERSION = "protocol-app2-m1.2"
