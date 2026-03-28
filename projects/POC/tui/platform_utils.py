from __future__ import annotations

import logging
import os
import shutil
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


def _shell_escape(args: list[str]) -> str:
    """Join args into a shell-safe string."""
    import shlex
    return ' '.join(shlex.quote(a) for a in args)


def open_terminal(command: list[str], title: str = '') -> None:
    """Open a NEW terminal window running the given command.

    Detects the user's terminal emulator via $TERM_PROGRAM (macOS) or
    probing common emulators (Linux). Works on macOS, Linux, and WSL.
    """
    title = title or 'TeaParty'
    cmd_str = _shell_escape(command)

    try:
        if sys.platform == 'darwin':
            _open_terminal_macos(cmd_str, title)
        elif sys.platform.startswith('linux'):
            if _is_wsl():
                _open_terminal_wsl(command)
            else:
                _open_terminal_linux(command, title)
        elif sys.platform == 'win32':
            subprocess.Popen(['cmd', '/c', 'start', title, 'cmd', '/k'] + command)
        else:
            logger.warning('open_terminal: unsupported platform %s', sys.platform)
    except Exception as e:
        logger.warning('open_terminal: failed: %s', e)


def _open_terminal_macos(cmd_str: str, title: str) -> None:
    """Open a new terminal window on macOS using the active terminal app."""
    term_program = os.environ.get('TERM_PROGRAM', '')

    if 'iTerm' in term_program:
        script = (
            'tell application "iTerm"\n'
            f'  create window with default profile command "{cmd_str}"\n'
            'end tell'
        )
    else:
        # Terminal.app or unknown — "do script ... in (make new window)" forces a new window
        script = (
            'tell application "Terminal"\n'
            '  activate\n'
            f'  do script "{cmd_str}" in (make new window)\n'
            'end tell'
        )

    subprocess.Popen(['osascript', '-e', script])


def _open_terminal_linux(command: list[str], title: str) -> None:
    """Open a new terminal window on Linux by probing available emulators."""
    # Try xdg-terminal-exec first (new XDG standard, Ubuntu 25.04+)
    if shutil.which('xdg-terminal-exec'):
        subprocess.Popen(['xdg-terminal-exec'] + command)
        return

    # Try x-terminal-emulator (Debian/Ubuntu alternatives system)
    if shutil.which('x-terminal-emulator'):
        subprocess.Popen(['x-terminal-emulator', '-e'] + command)
        return

    # Probe common emulators
    probes = [
        ('gnome-terminal', ['gnome-terminal', '--title', title, '--']),
        ('konsole', ['konsole', '--new-tab', '-e']),
        ('xfce4-terminal', ['xfce4-terminal', '--title', title, '-e']),
        ('alacritty', ['alacritty', '--title', title, '-e']),
        ('kitty', ['kitty', '--title', title]),
        ('xterm', ['xterm', '-title', title, '-e']),
    ]
    for binary, prefix in probes:
        if shutil.which(binary):
            if binary == 'xfce4-terminal':
                # -e takes a single string
                subprocess.Popen(prefix + [_shell_escape(command)])
            else:
                subprocess.Popen(prefix + command)
            return

    logger.warning('open_terminal: no terminal emulator found on this system')


def _open_terminal_wsl(command: list[str]) -> None:
    """Open a new Windows Terminal window from WSL."""
    if shutil.which('wt.exe'):
        # Windows Terminal: -w new forces a new window
        subprocess.Popen(['wt.exe', '-w', 'new', 'new-tab', '--', 'wsl.exe', '-e'] + command)
    else:
        # Fallback to cmd.exe
        cmd_str = _shell_escape(command)
        subprocess.Popen(['cmd.exe', '/c', 'start', 'cmd', '/c', f'wsl -e {cmd_str}'])


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
