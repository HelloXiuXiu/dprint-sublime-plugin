import sublime
import sublime_plugin
import subprocess
import os
import threading


def find_dprint_config(start_path):
    """Find nearest dprint.json or dprint.jsonc up the directory tree."""
    current = start_path
    while True:
        for name in ("dprint.json", "dprint.jsonc"):
            config_path = os.path.join(current, name)
            if os.path.exists(config_path):
                print(f"[dprint] Found config: {config_path}")
                return config_path
        parent = os.path.dirname(current)
        if parent == current:
            print("[dprint] No config found.")
            return None
        current = parent


class DprintFormatThread(threading.Thread):
    def __init__(self, view, file_path, config_path):
        super().__init__()
        self.view = view
        self.file_path = file_path
        self.config_path = config_path

    def run(self):
        try:
            print(f"[dprint] Formatting started for: {self.file_path}")
            original_code = self.view.substr(sublime.Region(0, self.view.size()))

            cmd = [
                "dprint",
                "fmt",
                f"--stdin={self.file_path}",
                "--config",
                self.config_path,
            ]
            print("[dprint] Running:", " ".join(cmd))

            result = subprocess.run(
                cmd,
                input=original_code,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            if result.returncode == 0:
                formatted = result.stdout
                if formatted and formatted.strip() != original_code.strip():
                    sublime.set_timeout(lambda: self._apply_edit(formatted), 0)
                    print("[dprint] File formatted successfully.")
                else:
                    print("[dprint] No formatting changes needed.")
            else:
                print("[dprint] Error:")
                print(result.stderr)
        except Exception as e:
            print("[dprint] Exception:", e)

    def _apply_edit(self, formatted):
        """Replace file content and auto-save silently."""
        self.view.run_command("dprint_replace_content", {"text": formatted})

        def save_after_format():
            if self.view.is_dirty():
                self.view.run_command("save")
            sublime.status_message("Formatted and saved with dprint")

        # Wait a tiny bit for Sublime to mark buffer dirty before saving
        sublime.set_timeout(save_after_format, 50)


class DprintReplaceContentCommand(sublime_plugin.TextCommand):
    def run(self, edit, text):
        old = self.view.substr(sublime.Region(0, self.view.size()))
        if old == text:
            # Nothing changed — skip to avoid gutter flicker
            return

        # Compute minimal diff region
        prefix_len = 0
        while prefix_len < len(old) and prefix_len < len(text) and old[prefix_len] == text[prefix_len]:
            prefix_len += 1

        suffix_len = 0
        while suffix_len < len(old) - prefix_len and suffix_len < len(text) - prefix_len and \
                old[-(suffix_len + 1)] == text[-(suffix_len + 1)]:
            suffix_len += 1

            # Avoid overlapping
            if suffix_len + prefix_len > len(old) or suffix_len + prefix_len > len(text):
                suffix_len = 0
                break

        start = prefix_len
        end_old = len(old) - suffix_len
        end_new = len(text) - suffix_len

        region = sublime.Region(start, end_old)
        new_content = text[start:end_new]
        self.view.replace(edit, region, new_content)


class DprintOnSave(sublime_plugin.EventListener):
    def on_post_save(self, view):
        file_path = view.file_name()
        if not file_path:
            print("[dprint] No file path.")
            return

        if not file_path.endswith((".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".html", ".md")):
            print(f"[dprint] Skipped (unsupported file): {file_path}")
            return

        folder = os.path.dirname(file_path)
        config_path = find_dprint_config(folder)
        if not config_path:
            print("[dprint] No config found — skipping.")
            return

        DprintFormatThread(view, file_path, config_path).start()
