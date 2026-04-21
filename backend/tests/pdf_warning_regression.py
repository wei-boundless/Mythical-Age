from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pdf_runtime import suppress_pypdf_warnings


def test_suppress_pypdf_warnings_mutes_reader_warning_temporarily() -> None:
    logger = logging.getLogger("pypdf._reader")
    original_level = logger.level
    original_propagate = logger.propagate
    original_handlers = list(logger.handlers)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.handlers = [handler]
    logger.setLevel(logging.WARNING)
    logger.propagate = False

    try:
        logger.warning("before")
        assert "before" in stream.getvalue()

        stream.seek(0)
        stream.truncate(0)
        with suppress_pypdf_warnings():
            logger.warning("EOF marker not found")
        assert stream.getvalue() == ""

        logger.warning("after")
        assert "after" in stream.getvalue()
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate


def main() -> None:
    test_suppress_pypdf_warnings_mutes_reader_warning_temporarily()
    print("ALL PASSED (pdf warning regression)")


if __name__ == "__main__":
    main()
