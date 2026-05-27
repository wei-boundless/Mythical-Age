from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def suppress_pypdf_warnings() -> Iterator[None]:
    loggers = [
        logging.getLogger("pypdf"),
        logging.getLogger("pypdf._reader"),
    ]
    saved = [(logger, logger.level) for logger in loggers]
    try:
        for logger, _level in saved:
            logger.setLevel(logging.ERROR)
        yield
    finally:
        for logger, level in saved:
            logger.setLevel(level)


