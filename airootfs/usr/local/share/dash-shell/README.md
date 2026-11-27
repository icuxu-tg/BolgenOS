# dash — мини-shell в духе fish/dash

Small interactive POSIX‑sh interpreter written in Python3, with fish‑like UX, command history, Tab completion, syntax `&&`/`||`, functions, `read`, `source`, `type`, arithmetic `$(( ))`, glob expansion, variables `$VAR`, `${VAR}`, and background jobs.

## Files

| File | Purpose |
|---|---|
| `dash.py` | Core interpreter / REPL |
| `dash` | Wrapper script to run `python3 dash.py` |
| `shkit.sh` | POSIX‑sh helper library (logging, `need`, `run`, `confirm`, `on_exit`, `shkit_tmpdir`) |
| `daily_report.sh` | Git‑commit daily report in Markdown |
| `shellmenu.sh` | Interactive menu to launch local `.sh` / `.py` scripts |
| `README.md` | This file |
| `.gitignore` | Ignores Android/runtime caches |

## Quick start

```sh
# interactive mode
./dash

# or run directly
python3 dash.py
```

## Features

- **Prompt** – colored `user@host ~/path (git) ❯`, red on error.
- **History** – saved to `~/.dash_history`, Ctrl+R search.
- **Tab completion** – commands, files, variable names.
- **Pipeline** – `cmd1 | cmd2`, `>`, `>>`, `2>`.
- **Boolean operators** – `&&`, `||`, `!`.
- **Arithmetic** – `$(( expression ))`.
- **Functions** – `name() { ... }`, `$1…$#`, `$@`.
- **Built‑ins** – `cd`, `pwd`, `echo`, `set`, `export`, `unset`, `alias`, `unalias`, `history`, `help`, `clear`, `which`, `type`, `jobs`, `fg`, `bg`, `wait`, `exit`, `read`, `source`.
- **Variable expansion** – `$VAR`, `${VAR}`, `$(( ))`, `$(cmd)`.
- **Glob** – `* ? []` for filenames.
- **~** and **OLDPWD** support.

## License

MIT (see LICENSE or add one if you wish).