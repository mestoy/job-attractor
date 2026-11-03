"""Delete the temp directories a test process made, so they never pile up in /tmp (which is RAM on this machine).

Importing this module (the harnesses and tests/__init__.py do) does four things, once per process:
  1. wraps tempfile.mkdtemp so every directory the process makes is remembered and listed in a registry file, /tmp/.ja-test-dirs-<pid>;
  2. removes those directories when the process exits: normally, after an unhandled exception, or on SIGTERM (what `timeout` sends);
  3. sweeps the registry files of processes that are DEAD (a SIGKILL or an out-of-memory kill cannot be caught) and removes what they listed;
  4. never removes a directory of a live process, and never a path outside the temp root.
One file, identical in the workspace (tests/) and the kit (partner-starter/tests/); tests/test_tmp_cleanup.py holds both to that."""
import atexit
import os
import shutil
import signal
import sys
import tempfile
import threading

_MARK = "_ja_tmp_cleanup_installed"
_PREFIX = ".ja-test-dirs-"
_made = []


def _tmp_root():
    return os.path.realpath(tempfile.gettempdir())


def _registry(pid):
    return os.path.join(_tmp_root(), _PREFIX + str(pid))


def _inside_tmp(path):
    p = os.path.realpath(path)
    root = _tmp_root()
    return p.startswith(root + os.sep) and p != root


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove(path):
    if _inside_tmp(path):
        shutil.rmtree(path, ignore_errors=True)


def sweep_dead():
    """Remove what dead processes left, by their registry files. A file that cannot be read or parsed is skipped, never fatal."""
    try:
        names = os.listdir(_tmp_root())
    except OSError:
        return
    for name in names:
        if not name.startswith(_PREFIX):
            continue
        try:
            pid = int(name[len(_PREFIX):])
        except ValueError:
            continue
        path = os.path.join(_tmp_root(), name)
        try:
            if pid == os.getpid() or _alive(pid) or os.stat(path).st_uid != os.getuid():
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh.read().splitlines():
                    if line.strip():
                        _remove(line.strip())
            os.remove(path)
        except OSError:
            continue


def remove_mine():
    for d in reversed(_made):
        _remove(d)
    try:
        os.remove(_registry(os.getpid()))
    except OSError:
        pass


def install():
    if getattr(tempfile, _MARK, False):
        return
    real = tempfile.mkdtemp

    def mkdtemp(*args, **kwargs):
        d = os.path.abspath(real(*args, **kwargs))
        _made.append(d)
        try:
            with open(_registry(os.getpid()), "a", encoding="utf-8") as fh:
                fh.write(d + "\n")
        except OSError:
            pass
        return d

    tempfile.mkdtemp = mkdtemp
    setattr(tempfile, _MARK, True)
    atexit.register(remove_mine)
    if threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM) == signal.SIG_DFL:
        signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(143))
    sweep_dead()


install()
