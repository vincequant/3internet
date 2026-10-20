"""Local bounded diagnostics; player-facing status never contains tracebacks."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = logging.getLogger('fengye.runtime')


def configure(folder):
    path = Path(folder) / 'runtime-errors.log'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not any(getattr(h, 'baseFilename', None) == str(path.resolve()) for h in LOGGER.handlers):
        handler = RotatingFileHandler(path, maxBytes=512*1024, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.WARNING)
    LOGGER.propagate = False


def report(context, error):
    LOGGER.warning('%s: %s: %s', context, type(error).__name__, error,
                   exc_info=(type(error), error, error.__traceback__))
