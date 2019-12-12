import os
from datetime import datetime
from argparse import ArgumentParser
from typing import Dict

import logging
from logging.handlers import TimedRotatingFileHandler
from config import LOG_NAME, MONITORING_PATH


def get_url() -> str:
    parser = ArgumentParser()

    parser.add_argument('--url',
                        type=str,
                        help='Url to download log file')

    args = parser.parse_args()
    url = args.url
    return url


def initialize_monitoring(monitor_name: str = LOG_NAME,
                          logging_level=logging.INFO) -> logging.Logger:

    root_dir = os.path.abspath(os.path.dirname(__file__))
    date_postfix = datetime.today().strftime('%Y-%m-%d')
    file_name = f"{root_dir}/{MONITORING_PATH}/{monitor_name}_{date_postfix}.log"

    stream_handler = logging.StreamHandler()

    file_handler = logging.FileHandler(filename=file_name, mode='w+')

    logging.basicConfig(format="%(asctime)s %(message)s",
                        datefmt="%m/%d/%Y %I:%M:%S %p",
                        level=logging_level,
                        handlers=[stream_handler, file_handler])

    monitor = logging.getLogger(name=monitor_name)
    return monitor





