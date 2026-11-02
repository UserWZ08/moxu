"""Local rotating diagnostics; no customer contact fields or document contents."""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(root: Path) -> None:
    directory = root / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "moxu.log", maxBytes=2_000_000, backupCount=4, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)

    def uncaught(error_type, error, trace):
        logging.getLogger("uncaught").critical(
            "Unhandled exception", exc_info=(error_type, error, trace)
        )
        sys.__excepthook__(error_type, error, trace)

    sys.excepthook = uncaught
    threading.excepthook = lambda args: uncaught(
        args.exc_type, args.exc_value, args.exc_traceback
    )
