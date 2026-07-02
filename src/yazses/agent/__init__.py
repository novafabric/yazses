"""Voice-to-Tool / offline Spoken MCP (ADR-v2-006).

Speak an intent → a local SLM emits a GBNF-constrained tool call → it runs via MCP
against an allowlist, with confirmation for state-mutating tools. This package's
``plan`` module is the pure planner/guard (no model, no network); the offline SLM
and the MCP client are heavy and opt-in behind the ``agent`` extra, lazy-imported
only when ``[agent] enabled``. OFF by default.
"""
