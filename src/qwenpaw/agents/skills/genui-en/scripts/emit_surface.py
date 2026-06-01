"""Validate + push an A2UI surface onto the live run stream.

Usage:
    python scripts/emit_surface.py <<'EOF'
    [ {"version":"v0.10","createSurface":{...}}, {"version":"v0.10","updateComponents":{...}} ]
    EOF

Reads a JSON array of A2UI envelopes from stdin (a single envelope object is
also accepted). Validates each against the vendored catalog; on success pushes
them to ``/genui/emit`` so the in-app renderer draws the surface. On a
validation error, prints ``VALIDATION_FAILED at <path>: <message>`` to stderr
and exits 1 — fix the reported field and re-emit.
"""
from __future__ import annotations

import sys

from common import push, read_envelopes_from_stdin, validate_envelopes


def main() -> int:
    try:
        envelopes = read_envelopes_from_stdin()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    errors = validate_envelopes(envelopes)
    if errors:
        for msg in errors:
            print(msg, file=sys.stderr)
        return 1

    ok, detail = push(envelopes)
    if not ok:
        print(f"ERROR: {detail}", file=sys.stderr)
        return 1

    print(f"OK: surface emitted ({len(envelopes)} envelope(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
