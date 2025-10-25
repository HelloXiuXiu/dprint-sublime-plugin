"""
dprint on save — Sublime Text 4 plugin (v1.4-mac-friendly)
----------------------------------------------------------
Runs dprint automatically after each file save, if a nearby dprint.json/jsonc exists.

Changes vs v1.3:
- Reads stdout/stderr as raw bytes → cleans all ANSI escapes (mac-safe)
- “Quiet” mode: panel shows only on error (no flicker)
- Still serialized per-file, no debounce
"""

import os, re, threading, subprocess, sublime, sublime_plugin

# --------------------------------------------------------------------------
# ANSI cleaner
# --------------------------------------------------------------------------
ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
def strip_ansi(text):
    return ANSI_RE.sub("", text or "")

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def on_main_thread(fn, *a, **kw): sublime.set_timeout(lambda: fn(*a, **kw), 0)

def get_panel(win):
    p = win.create_output_panel("dprint")
    p.set_read_only(False)
    return p

def write_panel(win, msg, show=True):
    def _append():
        p = get_panel(win)
        p.run_command("append", {"characters": msg + "\n"})
        if show:
            win.run_command("show_panel", {"panel": "output.dprint"})
        p.set_read_only(True)
    on_main_thread(_append)

# --------------------------------------------------------------------------
# find config / which
# --------------------------------------------------------------------------
def find_dprint_config(start):
    cur = start
    while True:
        for name in ("dprint.json", "dprint.jsonc"):
            p = os.path.join(cur, name)
            if os.path.isfile(p): return p
        parent = os.path.dirname(cur)
        if parent == cur: return None
        cur = parent

def which(cmd):
    paths = os.environ.get("PATH", "").split(os.pathsep)
    exts  = [""] + os.environ.get("PATHEXT", "").split(os.pathsep)
    for d in paths:
        for e in exts:
            c = os.path.join(d, cmd + e)
            if os.path.isfile(c) and os.access(c, os.X_OK): return c
    return None

# --------------------------------------------------------------------------
# concurrency
# --------------------------------------------------------------------------
_lock = threading.Lock()
_running, _pending = {}, set()

def _start_or_pending(path, factory):
    with _lock:
        if path in _running:
            _pending.add(path); return None
        ev = threading.Event(); _running[path] = ev; return factory(ev)

def _finish(path, view, cfg, cls):
    with _lock:
        ev = _running.pop(path, None)
        if ev: ev.set()
        if path in _pending:
            _pending.discard(path)
            on_main_thread(lambda: cls(view, path, cfg).start())

# --------------------------------------------------------------------------
# worker
# --------------------------------------------------------------------------
class DprintRunner(threading.Thread):
    def __init__(self, view, path, cfg, done=None):
        threading.Thread.__init__(self, daemon=True)
        self.view, self.window, self.path, self.cfg, self._done = (
            view, view.window() or sublime.active_window(), path, cfg, done)

    def run(self):
        bin = which("dprint") or "dprint"
        try:
            proc = subprocess.Popen(
                [bin, "fmt", self.path, "--config", self.cfg],
                cwd=os.path.dirname(self.path),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out_b, err_b = proc.communicate()
            out = strip_ansi(out_b.decode("utf-8", "ignore"))
            err = strip_ansi(err_b.decode("utf-8", "ignore"))

            if proc.returncode != 0:
                low = (out + err).lower()
                if "no files" in low or "no matching files" in low: return
                write_panel(self.window,
                    f"dprint fmt failed (exit {proc.returncode}):\n\nSTDOUT:\n{out}\n\nSTDERR:\n{err}",
                    show=True)
                return

            # success → silent
            on_main_thread(self._maybe_revert)

        except FileNotFoundError:
            write_panel(self.window, "dprint binary not found in PATH. Install from https://dprint.dev/")
        except Exception as e:
            write_panel(self.window, f"Unexpected error: {e}")
        finally:
            _finish(self.path, self.view, self.cfg, lambda v, p, c: DprintRunner(v, p, c))

    def _maybe_revert(self):
        v = self.view
        if not v or v.is_loading() or v.is_dirty(): return
        try:
            disk = open(self.path, "rb").read()
        except Exception: return
        buf = v.substr(sublime.Region(0, v.size())).encode("utf-8", "replace")
        if buf != disk: v.run_command("revert")

# --------------------------------------------------------------------------
# event listener
# --------------------------------------------------------------------------
class DprintOnSave(sublime_plugin.EventListener):
    _l, _busy = threading.Lock(), set()
    def on_post_save_async(self, view):
        vid = view.id()
        with self._l:
            if vid in self._busy: return
            self._busy.add(vid)
        try:
            path = view.file_name()
            if not path: return
            cfg = find_dprint_config(os.path.dirname(path))
            if not cfg: return
            def start():
                r = _start_or_pending(path, lambda ev=None: DprintRunner(view, path, cfg, ev))
                if r: r.start()
            on_main_thread(start)
        finally:
            with self._l: self._busy.discard(vid)

# --------------------------------------------------------------------------
# command — show version
# --------------------------------------------------------------------------
class DprintShowVersionCommand(sublime_plugin.WindowCommand):
    def run(self):
        bin = which("dprint") or "dprint"
        try:
            p = subprocess.Popen([bin, "--version"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out_b, err_b = p.communicate()
            out = strip_ansi((out_b or err_b).decode("utf-8", "ignore"))
            msg = f"dprint {out.strip()}" if p.returncode == 0 else f"dprint error:\n{out.strip()}"
        except FileNotFoundError:
            msg = "dprint binary not found in PATH."
        sublime.message_dialog(msg)
