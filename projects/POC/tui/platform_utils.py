from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)


def open_file(path: str) -> None:
    """Open a file or directory using the platform's default handler."""
    abs_path = os.path.abspath(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", abs_path])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", abs_path])
        elif sys.platform == "win32":
            os.startfile(abs_path)
        else:
            logger.warning("open_file: unsupported platform %s", sys.platform)
    except FileNotFoundError as e:
        logger.warning("open_file: command not found for %s: %s", abs_path, e)
    except Exception as e:
        logger.warning("open_file: failed to open %s: %s", abs_path, e)
