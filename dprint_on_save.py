import os
import threading
import subprocess
import re
import sublime
import sublime_plugin

ANSI_ESCAPE_RE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

def strip_ansi(text):
    return ANSI_ESCAPE_RE.sub('', text or '')

def on_main_thread(fn, *args, **kwargs):
    sublime.set_timeout(lambda: fn(*args, **kwargs), 0)

def get_output_panel(window):
    panel = window.create_output_panel("dprint")
    panel.set_read_only(False)
    return panel

def write_panel(window, text):
    def _append():
        panel = get_output_panel(window)
        panel.run_command("append", {"characters": text + "\n"})
        window.run_command("show_panel", {"panel": "output.dprint"})
        panel.set_read_only(True)
    on_main_thread(_append)

def find_dprint_config(start_path):
    cur = start_path
    while True:
        for name in ("dprint.json", "dprint.jsonc"):
            p = os.path.join(cur, name)
            if os.path.isfile(p):
                return p
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent

def which(cmd):
    paths = os.environ.get("PATH", "").split(os.pathsep)
    exts = [""] + os.environ.get("PATHEXT", "").split(os.pathsep)
    for path in paths:
        cand = os.path.join(path, cmd)
        for ext in exts:
            c = cand + ext
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
    return None

_running_lock = threading.Lock()
_running_by_path = {}
_pending_by_path = set()

def _start_or_mark_pending(file_path, runner_factory):
    with _running_lock:
        if file_path in _running_by_path:
            _pending_by_path.add(file_path)
            return None
        ev = threading.Event()
        _running_by_path[file_path] = ev
        return runner_factory(ev)

def _finish_and_maybe_rerun(file_path, view, config_path, runner_cls):
    with _running_lock:
        ev = _running_by_path.pop(file_path, None)
        if ev:
            ev.set()
        rerun = file_path in _pending_by_path
        if rerun:
            _pending_by_path.discard(file_path)
            def _requeue():
                runner = runner_cls(view, file_path, config_path)
                runner.start()
            on_main_thread(_requeue)

class DprintRunner(threading.Thread):
    def __init__(self, view, file_path, config_path, done_event=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.view = view
        self.window = view.window() or sublime.active_window()
        self.file_path = file_path
        self.config_path = config_path
        self._done_event = done_event

    def run(self):
        dprint_bin = which("dprint") or "dprint"
        try:
            cmd = [dprint_bin, "fmt", self.file_path, "--config", self.config_path]
            proc = subprocess.Popen(cmd, cwd=os.path.dirname(self.file_path),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    universal_newlines=True)
            stdout, stderr = proc.communicate()
            stdout = strip_ansi(stdout)
            stderr = strip_ansi(stderr)

            if proc.returncode != 0:
                low = (stdout + "\n" + stderr).lower()
                if "no files" in low or "no matching files" in low:
                    return
                write_panel(self.window, "dprint fmt failed (exit {}):\n\nSTDOUT:\n{}\n\nSTDERR:\n{}".format(
                    proc.returncode, stdout, stderr
                ))
                return

            on_main_thread(self._maybe_revert)
        except OSError:
            write_panel(self.window, "dprint binary not found in PATH. Install from https://dprint.dev/")
        except Exception as e:
            write_panel(self.window, "Unexpected error: {}".format(e))
        finally:
            _finish_and_maybe_rerun(self.file_path, self.view, self.config_path, lambda v, fp, cp: DprintRunner(v, fp, cp))

    def _maybe_revert(self):
        v = self.view
        if not v or v.is_loading() or v.is_dirty():
            return
        try:
            with open(self.file_path, "rb") as fh:
                disk = fh.read()
        except Exception:
            return
        buf = v.substr(sublime.Region(0, v.size())).encode("utf-8", "replace")
        if buf != disk:
            v.run_command("revert")

class DprintOnSave(sublime_plugin.EventListener):
    _local_lock = threading.Lock()
    _busy = set()

    def on_post_save_async(self, view):
        vid = view.id()
        with self._local_lock:
            if vid in self._busy:
                return
            self._busy.add(vid)

        try:
            file_path = view.file_name()
            if not file_path:
                return

            folder = os.path.dirname(file_path)
            config_path = find_dprint_config(folder)
            if not config_path:
                return

            def _start_runner():
                runner = _start_or_mark_pending(file_path,
                    lambda done_ev=None: DprintRunner(view, file_path, config_path, done_ev))
                if runner:
                    runner.start()

            on_main_thread(_start_runner)
        finally:
            with self._local_lock:
                self._busy.discard(vid)

class DprintShowVersionCommand(sublime_plugin.WindowCommand):
    def run(self):
        try:
            proc = subprocess.Popen(["dprint", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            stdout, stderr = proc.communicate()
            out = strip_ansi(stdout or stderr)
            if proc.returncode == 0:
                msg = "dprint " + out.strip()
            else:
                msg = "dprint error:\n" + out.strip()
        except OSError:
            msg = "dprint binary not found in PATH."
        sublime.message_dialog(msg)
