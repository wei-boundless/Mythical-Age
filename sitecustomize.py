from __future__ import annotations

try:
    from backend.runtime_encoding import configure_process_utf8
except Exception:
    configure_process_utf8 = None

if configure_process_utf8 is not None:
    configure_process_utf8()
