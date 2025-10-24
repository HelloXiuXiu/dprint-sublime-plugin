import os
import threading
import subprocess
import re
import sublime
import sublime_plugin

# === Utilities ===

ANSI_ESCAPE_RE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

def strip_ansi(text: str) -> str:
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

def find_dprint_config(start_path: str):
    """Walk up from start_path to find nearest dprint.json / dprint.jsonc. Return absolute path or None."""
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

def which(cmd: str):
    """Cross-platform 'which' suitable for Sublime envs (Windows/macOS/Linux)."""
    paths = os.environ.get("PATH", "").split(os.pathsep)
    exts = [""] + os.environ.get("PATHEXT", "").split(os.pathsep)
    for path in paths:
        cand = os.path.join(path, cmd)
        for ext in exts:
            c = cand + ext
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
    return None

def handled_by_dprint(file_path: str, config_path: str) -> bool:
    """
    Ask dprint whether this file is covered by user's config/plugins.
    Prefer 'dprint output-file-paths <file> --config <config>'.
    Fallback: allow 'fmt' to decide and we will quietly skip if it says 'no files'.
    """
    dprint_bin = which("dprint") or "dprint"
    try:
        proc = subprocess.run(
            [dprint_bin, "output-file-paths", file_path, "--config", config_path],
            cwd=os.path.dirname(file_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        if proc.returncode == 0:
            out = strip_ansi(proc.stdout).strip()
            if not out:
                return False
            fname = os.path.basename(file_path)
            return any(os.path.basename(line.strip()) == fname for line in out.splitlines())
        # If command is unsupported or returns non-zero, fall back to letting 'fmt' decide.
        return True
    except Exception:
        # If probing fails (older dprint, env), fall back to 'fmt' path.
        return True

# === Per-file serialization (no debounce) ===
_running_lock = threading.Lock()
_running_by_path = {}     # file_path -> threading.Event
_pending_by_path = set()  # file paths with a pending rerun request

def _start_or_mark_pending(file_path: str, runner_factory):
    with _running_lock:
        if file_path in _running_by_path:
            _pending_by_path.add(file_path)
            return None
        ev = threading.Event()
        _running_by_path[file_path] = ev
        return runner_factory(ev)

def _finish_and_maybe_rerun(file_path: str, view, config_path, runner_cls):
    with _running_lock:
        ev = _running_by_path.pop(file_path, None)
        if ev:
            ev.set()
        rerun = file_path in _pending_by_path
        if rerun:
            _pending_by_path.discard(file_path)
            # Re-queue one more run on the next tick (no fixed delay)
            def _requeue():
                runner = runner_cls(view, file_path, config_path)
                runner.start()
            on_main_thread(_requeue)

# === Runner & EventListener ===

class DprintRunner(threading.Thread):
    def __init__(self, view: sublime.View, file_path: str, config_path: str, done_event: threading.Event = None):
        super().__init__(daemon=True)
        self.view = view
        self.window = view.window() or sublime.active_window()
        self.file_path = file_path
        self.config_path = config_path
        self._done_event = done_event

    def run(self):
        dprint_bin = which("dprint") or "dprint"
        try:
            cmd = [dprint_bin, "fmt", self.file_path, "--config", self.config_path]
            proc = subprocess.run(
                cmd,
                cwd=os.path.dirname(self.file_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            stdout = strip_ansi(proc.stdout)
            stderr = strip_ansi(proc.stderr)

            if proc.returncode != 0:
                low = (stdout + "\n" + stderr).lower()
                # If this file isn't matched by config, dprint may say "no files" / "no matching files" — skip quietly.
                if "no files" in low or "no matching files" in low:
                    return
                write_panel(self.window, "dprint fmt failed (exit {}):\n\nSTDOUT:\n{}\n\nSTDERR:\n{}".format(
                    proc.returncode, stdout, stderr
                ))
                return

            # Pick up on-disk changes, if any.
            on_main_thread(self._maybe_revert)
        except FileNotFoundError:
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
        buf = v.substr(sublime.Region(0, v.size())).encode("utf-8", errors="replace")
        if buf != disk:
            v.run_command("revert")

class DprintOnSave(sublime_plugin.EventListener):
    _local_lock = threading.Lock()
    _busy = set()  # simple per-view recursion guard

    def on_post_save_async(self, view: sublime.View):
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
                return  # no dprint config in project => exit immediately (fast path)

            # Ask dprint if this file is covered by user's config/plugins
            if not handled_by_dprint(file_path, config_path):
                return  # not handled => silent skip

            # Start on next tick and serialize per file (no fixed delays)
            def _start_runner():
                runner = _start_or_mark_pending(
                    file_path,
                    lambda done_ev=None: DprintRunner(view, file_path, config_path, done_ev)
                )
                if runner:
                    runner.start()

            on_main_thread(_start_runner)
        finally:
            with self._local_lock:
                self._busy.discard(vid)

# Optional command to quickly check availability
class DprintShowVersionCommand(sublime_plugin.WindowCommand):
    def run(self):
        try:
            proc = subprocess.run(["dprint", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            out = strip_ansi(proc.stdout or proc.stderr)
            msg = "dprint " + out.strip() if proc.returncode == 0 else "dprint error:\n" + out.strip()
        except FileNotFoundError:
            msg = "dprint binary not found in PATH."
        sublime.message_dialog(msg)
