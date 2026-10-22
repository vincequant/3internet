"""Rotating service logs. Never write passwords."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logs(data_dir):
    path = Path(data_dir) / 'logs' / 'monitor.log'
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('sgi_room_monitor')
    if logger.handlers:
        return logger
    handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=4, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger
