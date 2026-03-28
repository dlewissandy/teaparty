from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)


def _is_wsl() -> bool:
    """Detect Windows Subsystem for Linux."""
    try:
        with open('/proc/version') as f:
            return 'microsoft' in f.read().lower()
    except (OSError, FileNotFoundError):
        return False


def open_terminal(command: list[str], title: str = '') -> None:
    """Open a new terminal window running the given command.

    Portable across macOS, Linux (with common terminal emulators), and WSL.
    """
    try:
        if sys.platform == 'darwin':
            # macOS: use osascript to open Terminal.app
            cmd_str = ' '.join(f"'{c}'" for c in command)
            script = f'tell application "Terminal" to do script "{cmd_str}"'
            subprocess.Popen(['osascript', '-e', script])

        elif sys.platform.startswith('linux'):
            if _is_wsl():
                # WSL: use cmd.exe to open a new window running wsl
                cmd_str = ' '.join(command)
                subprocess.Popen([
                    'cmd.exe', '/c', 'start', 'cmd', '/c',
                    f'wsl -e {cmd_str}',
                ])
            else:
                # Linux: try common terminal emulators in order
                terminals = [
                    ['gnome-terminal', '--title', title or 'TeaParty', '--'],
                    ['xfce4-terminal', '--title', title or 'TeaParty', '-e'],
                    ['konsole', '-e'],
                    ['xterm', '-title', title or 'TeaParty', '-e'],
                ]
                for term_cmd in terminals:
                    try:
                        if term_cmd[0] in ('xfce4-terminal',):
                            # -e takes a single string
                            subprocess.Popen(term_cmd + [' '.join(command)])
                        else:
                            subprocess.Popen(term_cmd + command)
                        return
                    except FileNotFoundError:
                        continue
                logger.warning('open_terminal: no supported terminal emulator found')

        elif sys.platform == 'win32':
            subprocess.Popen(['cmd', '/c', 'start', 'cmd', '/k'] + command)

        else:
            logger.warning('open_terminal: unsupported platform %s', sys.platform)

    except Exception as e:
        logger.warning('open_terminal: failed to open terminal: %s', e)


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
