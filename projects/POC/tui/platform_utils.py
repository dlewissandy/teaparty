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


def open_terminal(command: list[str], title: str = '', cwd: str = '') -> None:
    """Open a NEW terminal window running the given command.

    Detects the user's terminal emulator via $TERM_PROGRAM (macOS) or
    probing common emulators (Linux). Works on macOS, Linux, and WSL.
    """
    title = title or 'TeaParty'
    # Prepend cd if cwd is specified
    if cwd:
        shell_cmd = f'cd {_shell_escape([cwd])} && {_shell_escape(command)}'
    else:
        shell_cmd = _shell_escape(command)

    try:
        if sys.platform == 'darwin':
            _open_terminal_macos(shell_cmd, title)
        elif sys.platform.startswith('linux'):
            if _is_wsl():
                _open_terminal_wsl(shell_cmd)
            else:
                _open_terminal_linux(shell_cmd, title)
        elif sys.platform == 'win32':
            subprocess.Popen(['cmd', '/c', 'start', title, 'cmd', '/k', shell_cmd])
        else:
            logger.warning('open_terminal: unsupported platform %s', sys.platform)
    except Exception as e:
        logger.warning('open_terminal: failed: %s', e)


def _open_terminal_macos(cmd_str: str, title: str) -> None:
    """Open a new terminal window on macOS using the active terminal app."""
    term_program = os.environ.get('TERM_PROGRAM', '')

    if 'iTerm' in term_program:
        # Create a new window with a login shell, then type the command into it.
        # Using 'write text' instead of 'command' so the shell has full PATH.
        script = (
            'tell application "iTerm2"\n'
            '  set newWindow to (create window with default profile)\n'
            '  tell current session of newWindow\n'
            f'    write text "{cmd_str}"\n'
            '  end tell\n'
            'end tell'
        )
    else:
        # Terminal.app — do script runs in a login shell with full PATH
        script = (
            'tell application "Terminal"\n'
            '  activate\n'
            f'  do script "{cmd_str}" in (make new window)\n'
            'end tell'
        )

    subprocess.Popen(['osascript', '-e', script])


def _open_terminal_linux(shell_cmd: str, title: str) -> None:
    """Open a new terminal window on Linux by probing available emulators."""
    # Wrap in sh -c so cd && ... works
    wrapped = ['sh', '-c', shell_cmd]

    # Try xdg-terminal-exec first (new XDG standard, Ubuntu 25.04+)
    if shutil.which('xdg-terminal-exec'):
        subprocess.Popen(['xdg-terminal-exec'] + wrapped)
        return

    # Try x-terminal-emulator (Debian/Ubuntu alternatives system)
    if shutil.which('x-terminal-emulator'):
        subprocess.Popen(['x-terminal-emulator', '-e'] + wrapped)
        return

    # Probe common emulators
    probes = [
        ('gnome-terminal', ['gnome-terminal', '--title', title, '--']),
        ('konsole', ['konsole', '-e']),
        ('xfce4-terminal', ['xfce4-terminal', '--title', title, '-e']),
        ('alacritty', ['alacritty', '--title', title, '-e']),
        ('kitty', ['kitty', '--title', title]),
        ('xterm', ['xterm', '-title', title, '-e']),
    ]
    for binary, prefix in probes:
        if shutil.which(binary):
            if binary == 'xfce4-terminal':
                subprocess.Popen(prefix + [shell_cmd])
            else:
                subprocess.Popen(prefix + wrapped)
            return

    logger.warning('open_terminal: no terminal emulator found on this system')


def _open_terminal_wsl(shell_cmd: str) -> None:
    """Open a new Windows Terminal window from WSL."""
    if shutil.which('wt.exe'):
        subprocess.Popen(['wt.exe', '-w', 'new', 'new-tab', '--',
                          'wsl.exe', '-e', 'sh', '-c', shell_cmd])
    else:
        subprocess.Popen(['cmd.exe', '/c', 'start', 'cmd', '/c',
                          f'wsl -e sh -c "{shell_cmd}"'])


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
