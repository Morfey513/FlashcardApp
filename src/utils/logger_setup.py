# src/utils/logger_setup.py

import logging
import sys

from src.config import LOG_FILE, LOG_DIR


def setup_logging():
    # 1. Ensure the directory exists (Safety first)
    LOG_DIR.mkdir(exist_ok=True)

    # 2. Define the format
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 3. Create Handlers
    # File Handler
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a')
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.DEBUG)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.INFO)

    # 4. Configure the Root Logger
    root_logger = logging.getLogger()
    # If handlers already exist (e.g. from a previous call), remove them to avoid duplicates
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.info("Logging initialized. File: %s", LOG_FILE)
