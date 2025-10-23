import os
import threading
import subprocess
import time
import re
import sublime
import sublime_plugin

# --- Config ---
SUPPORTED_EXTS = (".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".html", ".md", ".toml", ".yaml", ".yml")
DEBOUNCE_MS = 150  # small delay to reduce race conditions with other on-save plugins

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
    paths = os.environ.get("PATH", "").split(os.pathsep)
    exts = [""] + os.environ.get("PATHEXT", "").split(os.pathsep)
    for path in paths:
        cand = os.path.join(path, cmd)
        for ext in exts:
            c = cand + ext
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
    return None

class DprintRunner(threading.Thread):
    def __init__(self, view: sublime.View, file_path: str, config_path: str, delay_ms: int = DEBOUNCE_MS):
        super().__init__(daemon=True)
        self.view = view
        self.window = view.window() or sublime.active_window()
        self.file_path = file_path
        self.config_path = config_path
        self.delay_ms = delay_ms

    def run(self):
        # Debounce to avoid colliding with other on-save plugins
        time.sleep(max(0, self.delay_ms) / 1000.0)

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
                write_panel(self.window, "dprint fmt failed (exit {}):\n\nSTDOUT:\n{}\n\nSTDERR:\n{}".format(
                    proc.returncode, stdout, stderr
                ))
                return

            # If formatter modified the file on disk, pick changes in the view.
            on_main_thread(self._maybe_revert)
        except FileNotFoundError:
            write_panel(self.window, "dprint binary not found in PATH. Install from https://dprint.dev/")
        except Exception as e:
            write_panel(self.window, "Unexpected error: {}".format(e))

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
    _lock = threading.Lock()
    _busy = set()  # view.id() currently formatting

    def on_post_save_async(self, view: sublime.View):
        vid = view.id()
        with self._lock:
            if vid in self._busy:
                return
            self._busy.add(vid)

        try:
            file_path = view.file_name()
            if not file_path or not file_path.endswith(SUPPORTED_EXTS):
                return  # quiet skip

            folder = os.path.dirname(file_path)
            config_path = find_dprint_config(folder)
            if not config_path:
                return  # quiet skip if no config up the tree

            DprintRunner(view, file_path, config_path).start()
        finally:
            with self._lock:
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
