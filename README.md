# Sublime Text 4 dprint plugin

A lightweight plugin that runs [**dprint**](https://dprint.dev/) automatically after every file save — if a project contains a `dprint.json` or `dprint.jsonc` configuration file.

Tested on **Sublime Text 4 (Build 4200)** across  
**Ubuntu 22.04**, **Windows 11**, and **macOS 13+**.

---

## Features

- Runs `dprint fmt` automatically after each save  
- No UI flicker or reloads — seamless background execution  
- ANSI-clean logs (no `[33m` junk from Prettierd or other formatters)  
- Fully isolated: does **not** interfere with other on-save plugins  
- Safe revert — file reloads only if modified on disk  
- Dedicated log panel: `View → Show Panel → Output → Dprint`

---

## Requirements

1. **Sublime Text 4** (Build 4200 or newer)  
2. **[dprint](https://dprint.dev/install/)** installed globally and available in your system `PATH`
    ```bash
    dprint --version
    ```
## Install

Install [Sublime Text 4](https://www.sublimetext.com/), if not installed.
Also install [dprint](https://dprint.dev/install/) globaly.

Place `dprint_on_save.py` at the specific path and restart the Sublime.

- macOS
```bash
cd Library/Application\ Support/Sublime\ Text\ 3/Packages/User
```

- Linux (Ubuntu)
```bash
cd ~/.config/sublime-text/Packages/User
```
- Windows
```powershell
cd "$env:APPDATA\Sublime Text\Packages\User"
```

### Alternative (git clone installation)

You can also install it directly from GitHub:

```bash
cd ~/.config/sublime-text/Packages
git clone https://github.com/HelloXiuXiu/dprint-sublime-plugin.git dprint-on-save
```

### To update later

```bash
cd ~/.config/sublime-text/Packages/dprint-on-save
git pull origin main
```

## Usage

- Open a project containing dprint.json
- Save any supported file (Ctrl+S / Cmd+S)
- The plugin will run dprint fmt in the background
- On success — quiet reload; on error — see output in
View → Show Panel → Output → Dprint

### Notes

- The plugin runs silently unless dprint reports an error.
- If dprint isn’t found, check your PATH or create a symlink (linux), e.g.

```
sudo ln -s ~/.dprint/bin/dprint /usr/local/bin/dprint
```
- Works safely alongside PrettierdFormat and other format-on-save tools.


### Development TO-DO:
- Strip ANSI escape sequences from stderr/stdout
- Use isolated output panel (output.dprint)
- Serialize runs per file (no race conditions)
- Submit to Package Control repository
- Optional: add debug-mode logging flag

Authors: @HelloXiuXiu 
Co-Author: @timur-mustafin
License: MIT