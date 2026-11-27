#!/usr/bin/env python3
# DESCRIPTION: Продвинутый мини-shell в духе fish/dash для BolgenOS
"""
Dash — интерактивный интерпретатор команд, встроенная оболочка терминала BolgenOS.

Особенности:
  * цветной промпт (пользователь, хост, путь, git-ветка, статус последней команды);
  * серые подсказки при вводе (autosuggestions) из истории и команд;
  * подсветка команд, путей, переменных, строк и операторов на лету;
  * Tab — дополнение команд, файлов, директорий и переменных, Ctrl+R — поиск;
  * история сохраняется в ~/.dash_history;
  * внешние команды, пайпы |, редиректы > >> < 2> 2>>, фоновый запуск &;
  * кавычки '...' (без подстановок) и "..." (с подстановками, без glob);
  * переменные $VAR/${VAR}/${VAR:-def}/$?/$$/$0, присваивания VAR=val, $(cmd), `cmd`, $((1+2));
  * системный /etc/dashrc и пользовательский ~/.dashrc;
  * режимы CLI: -c <cmd>, -l/--login, <script> [args...].
"""

import contextlib
import glob as globmod
import io
import os
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys

DASH_VERSION = "1.2-bolgenos"

# --- Цвета -----------------------------------------------------------------
NO_COLOR = os.environ.get("NO_COLOR") == "1"


class C:
    RESET = "" if NO_COLOR else "\x1b[0m"
    BOLD = "" if NO_COLOR else "\x1b[1m"
    DIM = "" if NO_COLOR else "\x1b[2m"
    GRAY = "" if NO_COLOR else "\x1b[90m"
    RED = "" if NO_COLOR else "\x1b[31m"
    GREEN = "" if NO_COLOR else "\x1b[32m"
    YELLOW = "" if NO_COLOR else "\x1b[33m"
    BLUE = "" if NO_COLOR else "\x1b[34m"
    MAGENTA = "" if NO_COLOR else "\x1b[35m"
    CYAN = "" if NO_COLOR else "\x1b[36m"


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def visible_len(text):
    return len(ANSI_RE.sub("", text))


class ShellError(Exception):
    """Ошибка разбора или выполнения команды."""


class ExitShell(Exception):
    """Завершение работы оболочки."""
    def __init__(self, code=0):
        super().__init__(code)
        self.code = code


class Cmd:
    """Одна команда в конвейере: аргументы и перенаправления."""
    def __init__(self):
        self.raw_argv = []
        self.argv = []
        self.env_prefix = {}
        self.infile = None
        self.outfile = None
        self.append = False
        self.errfile = None
        self.errappend = False


class Pipeline:
    """Конвейер из нескольких Cmd плюс правила соединения (&& || &)."""
    def __init__(self, cmds, background=False, connector="", negate=False):
        self.cmds = cmds
        self.background = background
        self.connector = connector   # '', '&&', '||'
        self.negate = negate         # префикс '!'


# Маркеры квотирования для сохранения семантики '...' и "..." при раскрытии токенов
Q_SQ = "\x01"   # одиночные кавычки: ничего не раскрывается
Q_DQ = "\x02"   # двойные кавычки: раскрываются $VAR/$(cmd)/$((...)), но без glob

VAR_RE = re.compile(
    r"\$\{([A-Za-z_]\w*|\d+|@|#|\?|\$)(?::-([^}]*))?\}|\$([A-Za-z_]\w*|\d+|@|#|\?|\$)"
)
FUNC_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{(.*)\}(.*)$", re.S)
ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)


class Shell:
    def __init__(self, script_name="dash"):
        self.env = dict(os.environ)
        self.vars = {}                 # имя -> список значений
        self.exported = set()          # имена, экспортированные внутри сессии
        self.aliases = {}
        self.functions = {}
        self.params = []               # позиционные параметры текущей функции/скрипта
        self.script_name = script_name
        self.depth = 0                 # глубина вложенных вызовов/подстановок
        self.home = os.path.expanduser("~") or os.getcwd()
        self.hist_path = os.path.join(self.home, ".dash_history")
        self.history = self._load_history()
        self.bg = []                   # фоновые процессы
        self.last_status = 0
        self.cwd = os.getcwd()
        self._branch_cache = {}
        self._cmd_cache = None
        self._hits = 0

    # --- История ------------------------------------------------------------
    def _load_history(self):
        try:
            with open(self.hist_path, "r", encoding="utf-8", errors="replace") as f:
                return [line.rstrip("\n") for line in f if line.strip()][-2000:]
        except OSError:
            return []

    def save_history(self):
        try:
            with open(self.hist_path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.history[-2000:]) + "\n")
        except OSError:
            pass

    def add_history(self, line):
        if not line.strip():
            return
        if self.history and self.history[-1] == line:
            return
        self.history.append(line)
        self._hits += 1
        if self._hits >= 10:
            self.save_history()
            self._hits = 0

    def load_rc(self):
        for rc in ("/etc/dashrc", os.path.join(self.home, ".dashrc")):
            if os.path.isfile(rc):
                try:
                    with open(rc, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if content.strip():
                        self.run_line(content)
                except Exception as exc:
                    print(f"dash: {rc}: {exc}", file=sys.stderr)

    # --- Переменные ----------------------------------------------------------
    def lookup_list(self, name):
        if name == "?":
            return [str(self.last_status)]
        if name == "$":
            return [str(os.getpid())]
        if name == "0":
            return [self.script_name]
        if name == "@":
            return list(self.params)
        if name == "#":
            return [str(len(self.params))]
        if name.isdigit():
            idx = int(name) - 1
            return [self.params[idx]] if 0 <= idx < len(self.params) else []
        if name in self.vars:
            return list(self.vars[name])
        if name in self.env:
            return [self.env[name]]
        return []

    def lookup(self, name, default=""):
        vals = self.lookup_list(name)
        return vals[0] if vals else default

    def set_var(self, name, values, export_var=False):
        self.vars[name] = list(values)
        if export_var or name in self.env or name in self.exported:
            self.exported.add(name)
            self.env[name] = ":".join(self.vars[name]) if name == "PATH" else " ".join(self.vars[name])
        if name == "PATH":
            self._cmd_cache = None

    def child_env(self, extra=None):
        result = dict(self.env)
        for name in self.exported:
            vals = self.vars.get(name)
            if vals is not None:
                result[name] = ":".join(vals) if name == "PATH" else " ".join(vals)
            else:
                result.pop(name, None)
        if extra:
            result.update(extra)
        return result

    # --- Подстановки ---------------------------------------------------------
    def expand_arith(self, text):
        """Вычисляет $((выражение)) — целочисленная арифметика."""
        out = []
        i = 0
        while i < len(text):
            if text.startswith("$((", i):
                level = 2
                j = i + 3
                while j < len(text) and level:
                    if text[j] == "(":
                        level += 1
                    elif text[j] == ")":
                        level -= 1
                    j += 1
                if level:
                    out.append(text[i:])
                    break
                expr = text[i + 3:j - 2]
                expr = self.expand_cmdsub(expr)
                expr = self._expand_vars_plain(expr)
                expr = re.sub(
                    r"\b([A-Za-z_]\w*)\b",
                    lambda m: self.lookup(m.group(1), "0") if self.lookup(m.group(1), "0").lstrip("-").isdigit() else "0",
                    expr,
                )
                stripped = "".join(expr.split())
                if re.fullmatch(r"[0-9+\-*/%()<>=!&|^~]+", stripped):
                    try:
                        # Целочисленное деление как в POSIX sh
                        safe_expr = re.sub(r"(?<!/)/(?!/)", "//", stripped)
                        val = eval(safe_expr, {"__builtins__": {}}, {})
                        out.append(str(int(val)))
                    except Exception:
                        out.append("0")
                else:
                    out.append("0")
                i = j
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    def _expand_vars_plain(self, text):
        def _rep(m):
            name = m.group(1) or m.group(3)
            default_val = m.group(2)
            vals = self.lookup_list(name)
            if vals and vals != [""]:
                return " ".join(vals)
            if default_val is not None:
                return default_val
            return ""
        return VAR_RE.sub(_rep, text)

    def expand_cmdsub(self, text, depth=0):
        if depth > 5:
            return text
        if "`" in text:
            def _tick(m):
                try:
                    res, _ = self.run_line(m.group(1), capture=True)
                    return res.rstrip("\n")
                except Exception:
                    return ""
            text = re.sub(r"`([^`]+)`", _tick, text)
        if "$(" not in text:
            return text
        out = []
        i = 0
        while i < len(text):
            if text.startswith("$(", i) and not text.startswith("$((", i):
                level = 1
                j = i + 2
                while j < len(text) and level:
                    if text[j] == "(":
                        level += 1
                    elif text[j] == ")":
                        level -= 1
                    j += 1
                if level:
                    out.append(text[i:])
                    break
                inner = text[i + 2:j - 1]
                try:
                    result, _ = self.run_line(inner, capture=True)
                except Exception:
                    result = ""
                out.append(result.rstrip("\n"))
                i = j
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    def expand(self, token):
        """Раскрывает один токен с учётом квотирования (Q_SQ / Q_DQ)."""
        if token == Q_SQ or token == Q_DQ:
            return [""]

        # Разбиваем на сегменты: ('sq'|'dq'|'raw', str)
        segments = []
        i = 0
        cur_kind = "raw"
        cur_buf = []
        has_quotes = False
        while i < len(token):
            ch = token[i]
            if ch in (Q_SQ, Q_DQ):
                has_quotes = True
                if cur_buf:
                    segments.append((cur_kind, "".join(cur_buf)))
                    cur_buf = []
                new_kind = "sq" if ch == Q_SQ else "dq"
                cur_kind = "raw" if cur_kind == new_kind else new_kind
                i += 1
                continue
            cur_buf.append(ch)
            i += 1
        if cur_buf:
            segments.append((cur_kind, "".join(cur_buf)))

        if not segments and has_quotes:
            return [""]

        # Спецслучай: токен вида $VAR или "$@" без кавычек/с двойными — сохраняем список
        if len(segments) == 1 and segments[0][0] in ("raw", "dq"):
            seg_kind, seg_val = segments[0]
            if seg_val in ('$@', '${@}') and seg_kind == "dq":
                return list(self.params)
            if seg_kind == "raw":
                m_only = re.fullmatch(
                    r"\$(?:\{([A-Za-z_]\w*|\d+|@|#)\}|([A-Za-z_]\w*|\d+|@|#))", seg_val
                )
                if m_only:
                    return self.lookup_list(m_only.group(1) or m_only.group(2))

        out_parts = []
        has_unquoted_glob = False

        for seg_kind, seg_val in segments:
            if seg_kind == "sq":
                out_parts.append(seg_val)
                continue

            if seg_kind == "raw":
                if not has_quotes and not out_parts:
                    if seg_val == "~":
                        out_parts.append(self.home)
                        continue
                    if seg_val.startswith("~/"):
                        seg_val = self.home + seg_val[1:]

            val = self.expand_arith(seg_val)
            val = self.expand_cmdsub(val)

            parts = []
            j = 0
            while j < len(val):
                ch = val[j]
                if ch == "\\" and j + 1 < len(val) and seg_kind == "raw":
                    parts.append(val[j + 1])
                    j += 2
                    continue
                if ch == "$":
                    m = VAR_RE.match(val, j)
                    if m:
                        name = m.group(1) or m.group(3)
                        default_val = m.group(2)
                        vals = self.lookup_list(name)
                        if vals and vals != [""]:
                            parts.append(" ".join(vals))
                        elif default_val is not None:
                            parts.append(self._expand_vars_plain(default_val))
                        j = m.end()
                        continue
                if seg_kind == "raw" and ch in "*?[":
                    has_unquoted_glob = True
                parts.append(ch)
                j += 1
            out_parts.append("".join(parts))

        word = "".join(out_parts)
        if has_unquoted_glob:
            matches = globmod.glob(word)
            if matches:
                return sorted(matches)
        return [word]

    # --- Лексер / парсер -----------------------------------------------------
    @staticmethod
    def tokenize(line):
        """Токенизатор с поддержкой кавычек ('...'/\"...\"), экранирования и операторов."""
        tokens = []
        buf = []
        in_tok = False
        quote = None   # None, "'", '"'
        i = 0
        n = len(line)

        def flush():
            nonlocal buf, in_tok
            if in_tok:
                tokens.append("".join(buf))
                buf = []
                in_tok = False

        while i < n:
            ch = line[i]
            if quote is None:
                if ch == "#" and not in_tok:
                    while i < n and line[i] != "\n":
                        i += 1
                    continue
                if ch == "\\" and i + 1 < n:
                    if line[i + 1] == "\n":
                        i += 2
                        continue
                    buf.append("\\" + line[i + 1])
                    in_tok = True
                    i += 2
                    continue
                if ch in (" ", "\t", "\r"):
                    flush()
                    i += 1
                    continue
                if ch == "\n":
                    flush()
                    if tokens and tokens[-1] not in (";", "&&", "||", "|"):
                        tokens.append(";")
                    i += 1
                    continue
                if ch == "'":
                    buf.append(Q_SQ)
                    in_tok = True
                    quote = "'"
                    i += 1
                    continue
                if ch == '"':
                    buf.append(Q_DQ)
                    in_tok = True
                    quote = '"'
                    i += 1
                    continue
                # Подстановка $(...) или $((...)) не должна дробиться на пробелы/операторы раньше времени
                if ch == "$" and i + 1 < n and line[i + 1] == "(":
                    is_arith = line.startswith("$((", i)
                    level = 2 if is_arith else 1
                    j = i + (3 if is_arith else 2)
                    while j < n and level > 0:
                        if line[j] == "(":
                            level += 1
                        elif line[j] == ")":
                            level -= 1
                        j += 1
                    buf.append(line[i:j])
                    in_tok = True
                    i = j
                    continue
                if ch in ("|", "&", ">", "<", ";"):
                    # Цифра прямо перед > / >> (например 2>)
                    if ch in (">", "<") and in_tok and "".join(buf).isdigit():
                        flush()
                    else:
                        flush()
                    if i + 1 < n and line[i:i + 2] in ("&&", "||", ">>", "<<"):
                        tokens.append(line[i:i + 2])
                        i += 2
                    else:
                        tokens.append(ch)
                        i += 1
                    continue
                buf.append(ch)
                in_tok = True
                i += 1
            elif quote == "'":
                if ch == "'":
                    buf.append(Q_SQ)
                    quote = None
                else:
                    buf.append(ch)
                i += 1
            elif quote == '"':
                if ch == "\\" and i + 1 < n and line[i + 1] in ('"', "\\", "$", "`", "\n"):
                    if line[i + 1] != "\n":
                        buf.append(line[i + 1])
                    i += 2
                    continue
                if ch == '"':
                    buf.append(Q_DQ)
                    quote = None
                else:
                    buf.append(ch)
                i += 1

        if quote is not None:
            raise ValueError("незакрытая кавычка")
        flush()
        return tokens

    def parse(self, tokens):
        pipelines = []
        cmds = []
        cur = Cmd()
        bg = False
        pending_conn = ""
        negate = False

        def flush():
            nonlocal cmds, cur, bg, pending_conn, negate
            if cur.raw_argv or cur.env_prefix or cur.infile or cur.outfile or cur.errfile:
                cmds.append(cur)
            if cmds:
                pipelines.append(Pipeline(cmds, bg, pending_conn, negate))
            return [], Cmd(), False, "", False

        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t == ";":
                cmds, cur, bg, pending_conn, negate = flush()
                i += 1
                continue
            if t in ("&&", "||"):
                cmds, cur, bg, pending_conn, negate = flush()
                pending_conn = t
                i += 1
                continue
            if t == "&":
                bg = True
                cmds, cur, bg, pending_conn, negate = flush()
                i += 1
                continue
            if t == "!" and not cur.raw_argv:
                negate = not negate
                i += 1
                continue
            if t == "|":
                if not cur.raw_argv:
                    raise ShellError("синтаксическая ошибка рядом с '|'")
                cmds.append(cur)
                cur = Cmd()
                i += 1
                continue

            # 2> и 2>>
            if t.isdigit() and i + 1 < len(tokens) and tokens[i + 1] in (">", ">>"):
                fd = int(t)
                op = tokens[i + 1]
                if i + 2 >= len(tokens):
                    raise ShellError("нет файла после перенаправления")
                target = tokens[i + 2]
                if fd == 2:
                    cur.errfile = target
                    cur.errappend = (op == ">>")
                elif fd == 1:
                    cur.outfile = target
                    cur.append = (op == ">>")
                i += 3
                continue

            if t in (">", ">>", "<"):
                if i + 1 >= len(tokens):
                    raise ShellError("нет файла после перенаправления")
                target = tokens[i + 1]
                if t == "<":
                    cur.infile = target
                else:
                    cur.outfile = target
                    cur.append = (t == ">>")
                i += 2
                continue

            # Префиксное присваивание VAR=val (до имени команды)
            if not cur.raw_argv and "=" in t and Q_SQ not in t:
                plain_prefix = t.replace(Q_DQ, "")
                m_asg = ASSIGN_RE.match(plain_prefix)
                if m_asg and "=" in t.split("=", 1)[0] + "=":
                    name = m_asg.group(1)
                    raw_val = t.split("=", 1)[1]
                    cur.env_prefix[name] = raw_val
                    i += 1
                    continue

            if not cur.raw_argv and Q_SQ not in t and Q_DQ not in t and t in self.aliases:
                alias_tokens = self.tokenize(self.aliases[t])
                cur.raw_argv.extend(alias_tokens)
            else:
                cur.raw_argv.append(t)
            i += 1

        flush()
        return pipelines

    # --- Встроенные команды --------------------------------------------------
    def builtins(self):
        return {
            "cd": self.bi_cd, "pwd": self.bi_pwd, "echo": self.bi_echo,
            "set": self.bi_set, "export": self.bi_export, "unset": self.bi_unset,
            "alias": self.bi_alias, "unalias": self.bi_unalias,
            "history": self.bi_history, "help": self.bi_help,
            "clear": self.bi_clear, "which": self.bi_which,
            "jobs": self.bi_jobs, "wait": self.bi_wait,
            "fg": self.bi_fg, "bg": self.bi_bg,
            "read": self.bi_read, "source": self.bi_source,
            ".": self.bi_source, "type": self.bi_type,
            "exec": self.bi_exec, "eval": self.bi_eval, "command": self.bi_command,
            "true": lambda a: 0, "false": lambda a: 1, ":": lambda a: 0,
            "exit": self.bi_exit,
        }

    def bi_cd(self, args):
        target = args[0] if args else self.home
        if target == "-":
            target = self.lookup("OLDPWD", self.home)
        path = os.path.expanduser(target)
        if not os.path.isabs(path):
            path = os.path.join(self.cwd, path)
        path = os.path.normpath(path)
        if not os.path.isdir(path):
            print(f"cd: нет такого каталога: {target}", file=sys.stderr)
            return 1
        self.set_var("OLDPWD", [self.cwd])
        os.chdir(path)
        self.cwd = os.getcwd()
        self.set_var("PWD", [self.cwd])
        return 0

    @staticmethod
    def bi_pwd(args):
        print(os.getcwd())
        return 0

    @staticmethod
    def bi_echo(args):
        newline = True
        interpret = False
        idx = 0
        while idx < len(args) and args[idx] in ("-n", "-e", "-ne", "-en"):
            if "n" in args[idx]:
                newline = False
            if "e" in args[idx]:
                interpret = True
            idx += 1
        out_args = args[idx:]
        if interpret:
            out_args = [bytes(a, "utf-8").decode("unicode_escape") for a in out_args]
        sys.stdout.write(" ".join(out_args) + ("\n" if newline else ""))
        return 0

    def bi_set(self, args):
        if not args:
            for name in sorted(set(self.vars) | set(self.env)):
                vals = self.lookup_list(name)
                mark = " [export]" if (name in self.exported or name in self.env) else ""
                print(f"{name}{mark}={' '.join(vals)}")
            return 0
        opts = []
        while args and args[0].startswith("-") and len(args[0]) > 1:
            opts.append(args.pop(0))
        if not args:
            return 0
        name = args.pop(0)
        if "-e" in opts or "--erase" in opts:
            self.vars.pop(name, None)
            self.exported.discard(name)
            self.env.pop(name, None)
            return 0
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            print(f"set: неверное имя: {name}", file=sys.stderr)
            return 1
        self.set_var(name, args or [""], export_var=("-x" in opts or "--export" in opts))
        return 0

    def bi_export(self, args):
        if not args:
            for name in sorted(set(self.exported) | set(self.env)):
                print(f"export {name}={shlex.quote(self.lookup(name, ''))}")
            return 0
        for arg in args:
            if "=" in arg:
                name, value = arg.split("=", 1)
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                    print(f"export: неверное имя: {name}", file=sys.stderr)
                    return 1
                self.set_var(name, [value], export_var=True)
            else:
                name = arg
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                    print(f"export: неверное имя: {name}", file=sys.stderr)
                    return 1
                self.set_var(name, self.lookup_list(name) or [""], export_var=True)
        return 0

    def bi_unset(self, args):
        opts = [a for a in args if a in ("-f", "-v")]
        names = [a for a in args if a not in opts]
        if "-f" not in opts:
            for name in names:
                self.vars.pop(name, None)
                self.exported.discard(name)
                self.env.pop(name, None)
                if name == "PATH":
                    self._cmd_cache = None
        if "-v" not in opts:
            for name in names:
                self.functions.pop(name, None)
        return 0

    def bi_alias(self, args):
        if not args:
            for name, value in sorted(self.aliases.items()):
                print(f"alias {name}={shlex.quote(value)}")
            return 0
        for arg in args:
            if "=" in arg:
                name, value = arg.split("=", 1)
                self.aliases[name] = value
            elif arg in self.aliases:
                print(f"alias {arg}={shlex.quote(self.aliases[arg])}")
        return 0

    def bi_unalias(self, args):
        for name in args:
            self.aliases.pop(name, None)
        return 0

    def bi_history(self, args):
        if args and args[0] == "-c":
            self.history.clear()
            self.save_history()
            return 0
        start = max(0, len(self.history) - 30)
        for i, line in enumerate(self.history[start:], start + 1):
            print(f"{i:5d}  {line}")
        return 0

    @staticmethod
    def bi_help(args):
        print(f"""Dash ({DASH_VERSION}) — оболочка терминала BolgenOS в духе fish/dash

Клавиши:
  Enter       выполнить команду
  Tab         дополнить команду/файл
  Right       принять серую подсказку
  Ctrl+R      поиск по истории
  Up/Down     история
  Ctrl+A/E    начало/конец строки
  Ctrl+W      удалить слово
  Ctrl+K/U    удалить до конца/начала строки
  Ctrl+L      очистить экран
  Ctrl+C      отменить ввод
  Ctrl+D      выйти

Синтаксис:  cmd | cmd > файл >> файл < файл 2> файл & ; && || ! $(cmd) `cmd` $((1+2)) $VAR $? $$
Функции:    name() {{ echo "$1"; }}; name аргумент
Встроенные: cd pwd echo set export unset alias unalias history help clear
            which type read source exec eval command jobs fg bg wait exit
""")
        return 0

    @staticmethod
    def bi_clear(args):
        sys.stdout.write("\x1b[2J\x1b[H")
        return 0

    def bi_which(self, args):
        status = 0
        path_env = self.child_env().get("PATH", "")
        for name in args:
            path = shutil.which(name, path=path_env)
            if path:
                print(path)
            else:
                print(f"which: не найдено: {name}", file=sys.stderr)
                status = 1
        return status

    def bi_jobs(self, args):
        alive = [(i, p, c) for i, (p, c) in enumerate(self.bg, 1) if p.poll() is None]
        for i, p, c in alive:
            print(f"[{i}] {p.pid} {' '.join(c.argv)}")
        if not alive:
            print("(нет фоновых задач)")
        return 0

    def bi_wait(self, args):
        for p, _ in self.bg:
            try:
                p.wait()
            except ChildProcessError:
                pass
        self.bg.clear()
        return 0

    @staticmethod
    def _job_index(arg, count):
        if not arg or arg == "%+":
            return count
        if arg.startswith("%"):
            arg = arg[1:]
        try:
            idx = int(arg)
            return idx if 1 <= idx <= count else None
        except ValueError:
            return None

    def bi_fg(self, args):
        if not self.bg:
            print("fg: нет фоновых задач", file=sys.stderr)
            return 1
        idx = self._job_index(args[0] if args else "", len(self.bg))
        if idx is None:
            print("fg: нет такой задачи", file=sys.stderr)
            return 1
        proc, cmd = self.bg[idx - 1]
        print(" ".join(cmd.argv))
        try:
            status = proc.wait()
        except ChildProcessError:
            status = 0
        except KeyboardInterrupt:
            status = 130
        self.bg.pop(idx - 1)
        self.last_status = status
        return status

    def bi_bg(self, args):
        if not self.bg:
            print("bg: нет фоновых задач", file=sys.stderr)
            return 1
        idx = self._job_index(args[0] if args else "", len(self.bg))
        if idx is None:
            print("bg: нет такой задачи", file=sys.stderr)
            return 1
        proc, cmd = self.bg[idx - 1]
        print(f"[{idx}] {proc.pid} {' '.join(cmd.argv)} &")
        return 0

    def bi_read(self, args):
        prompt = ""
        names = []
        i = 0
        while i < len(args):
            if args[i] == "-p" and i + 1 < len(args):
                prompt = args[i + 1]
                i += 2
                continue
            names.append(args[i])
            i += 1
        if not names:
            names = ["REPLY"]
        if prompt:
            sys.stdout.write(prompt)
            sys.stdout.flush()
        try:
            line = sys.stdin.readline()
        except OSError:
            return 1
        if not line:
            return 1
        values = line.rstrip("\r\n").split()
        if len(names) == 1:
            self.set_var(names[0], [" ".join(values)] if values else [""])
        else:
            for idx, name in enumerate(names):
                self.set_var(name, [values[idx]] if idx < len(values) else [""])
        return 0

    def bi_source(self, args):
        if not args:
            print("source: нужен файл", file=sys.stderr)
            return 1
        path = os.path.expanduser(args[0])
        if not os.path.isabs(path):
            path = os.path.join(self.cwd, path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            print(f"source: {exc}", file=sys.stderr)
            return 1
        self.depth += 1
        try:
            self.run_line(content)
        finally:
            self.depth -= 1
        return self.last_status

    def bi_type(self, args):
        status = 0
        builtins = self.builtins()
        path_env = self.child_env().get("PATH", "")
        for name in args:
            if name in self.functions:
                print(f"{name} — функция")
            elif name in self.aliases:
                print(f"{name} — псевдоним: {self.aliases[name]}")
            elif name in builtins:
                print(f"{name} — встроенная команда")
            else:
                path = shutil.which(name, path=path_env)
                if path:
                    print(f"{name} — {path}")
                else:
                    print(f"type: не найдено: {name}", file=sys.stderr)
                    status = 1
        return status

    def bi_exec(self, args):
        if not args:
            return 0
        env = self.child_env()
        try:
            os.execvpe(args[0], args, env)
        except FileNotFoundError:
            print(f"exec: команда не найдена: {args[0]}", file=sys.stderr)
            return 127
        except OSError as exc:
            print(f"exec: {exc}", file=sys.stderr)
            return 126

    def bi_eval(self, args):
        if not args:
            return 0
        self.depth += 1
        try:
            return self.run_line(" ".join(args))
        finally:
            self.depth -= 1

    def bi_command(self, args):
        if not args:
            return 0
        if args[0] == "-v":
            return self.bi_which(args[1:])
        builtins = self.builtins()
        if args[0] in builtins:
            return builtins[args[0]](args[1:])
        try:
            res = subprocess.run(args, cwd=self.cwd, env=self.child_env())
            return res.returncode
        except FileNotFoundError:
            print(f"dash: команда не найдена: {args[0]}", file=sys.stderr)
            return 127
        except PermissionError:
            print(f"dash: нет прав: {args[0]}", file=sys.stderr)
            return 126

    @staticmethod
    def bi_exit(args):
        try:
            code = int(args[0]) if args else 0
        except ValueError:
            code = 1
        raise ExitShell(code)

    # --- Выполнение ----------------------------------------------------------
    def run_line(self, line, capture=False):
        if self.depth > 20:
            raise ShellError("слишком глубокая вложенность вызовов")

        definition = FUNC_RE.match(line.strip())
        if definition and not capture:
            self.functions[definition.group(1)] = definition.group(2).strip()
            rest = definition.group(3).strip().lstrip(";").strip()
            if rest:
                return self.run_line(rest, capture=capture)
            self.last_status = 0
            return 0

        try:
            tokens = self.tokenize(line)
        except ValueError as exc:
            print(f"dash: синтаксис: {exc}", file=sys.stderr)
            self.last_status = 2
            return ("", 2) if capture else 2

        if not tokens:
            return ("", 0) if capture else 0

        try:
            pipelines = self.parse(tokens)
        except ShellError as exc:
            print(f"dash: {exc}", file=sys.stderr)
            self.last_status = 2
            return ("", 2) if capture else 2

        output = ""
        status = self.last_status
        for pipe in pipelines:
            if pipe.connector == "&&" and status != 0:
                continue
            if pipe.connector == "||" and status == 0:
                continue
            try:
                out, status = self.execute_pipeline(pipe, capture=capture)
            except ExitShell:
                raise
            if pipe.negate:
                status = 0 if status != 0 else 1
            if capture:
                output += out
            self.last_status = status

        if not capture:
            self._branch_cache.pop(self.cwd, None)
        return (output, status) if capture else status

    def call_builtin(self, cmd, name, func, capture):
        """Вызывает встроенную команду, уважая перенаправления."""
        saved = []
        opened = []
        try:
            if cmd.infile:
                f = open(cmd.infile, "rb")
                opened.append(f)
                saved.append((0, os.dup(0)))
                os.dup2(f.fileno(), 0)
            if cmd.outfile:
                f = open(cmd.outfile, "ab" if cmd.append else "wb")
                opened.append(f)
                saved.append((1, os.dup(1)))
                os.dup2(f.fileno(), 1)
            if cmd.errfile:
                f = open(cmd.errfile, "ab" if cmd.errappend else "wb")
                opened.append(f)
                saved.append((2, os.dup(2)))
                os.dup2(f.fileno(), 2)

            sys.stdout.flush()
            sys.stderr.flush()
            if capture and not cmd.outfile:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    status = func(cmd.argv[1:])
                return buf.getvalue(), status
            return "", func(cmd.argv[1:])
        except ExitShell:
            raise
        except OSError as exc:
            print(f"dash: {name}: {exc}", file=sys.stderr)
            return "", 1
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            for fd, old in reversed(saved):
                os.dup2(old, fd)
                os.close(old)
            for f in opened:
                f.close()

    def call_function(self, cmd, name, capture):
        """Вызывает пользовательскую функцию с позиционными параметрами."""
        saved = []
        opened = []
        old_params = self.params
        self.params = list(cmd.argv[1:])
        self.depth += 1
        try:
            if cmd.infile:
                f = open(cmd.infile, "rb")
                opened.append(f)
                saved.append((0, os.dup(0)))
                os.dup2(f.fileno(), 0)
            if cmd.outfile:
                f = open(cmd.outfile, "ab" if cmd.append else "wb")
                opened.append(f)
                saved.append((1, os.dup(1)))
                os.dup2(f.fileno(), 1)
            if cmd.errfile:
                f = open(cmd.errfile, "ab" if cmd.errappend else "wb")
                opened.append(f)
                saved.append((2, os.dup(2)))
                os.dup2(f.fileno(), 2)

            sys.stdout.flush()
            sys.stderr.flush()
            if capture and not cmd.outfile:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.run_line(self.functions[name], capture=False)
                return buf.getvalue(), self.last_status
            self.run_line(self.functions[name], capture=False)
            return "", self.last_status
        except ExitShell:
            raise
        except OSError as exc:
            print(f"dash: {name}: {exc}", file=sys.stderr)
            return "", 1
        finally:
            self.depth -= 1
            self.params = old_params
            sys.stdout.flush()
            sys.stderr.flush()
            for fd, old in reversed(saved):
                os.dup2(old, fd)
                os.close(old)
            for f in opened:
                f.close()

    def execute_pipeline(self, pipe, capture=False):
        for cmd in pipe.cmds:
            argv = []
            for token in cmd.raw_argv:
                argv.extend(self.expand(token))
            cmd.argv = argv
            expanded_env = {}
            for k, v in cmd.env_prefix.items():
                expanded_env[k] = " ".join(self.expand(v))
            cmd.env_prefix = expanded_env
            if cmd.infile:
                cmd.infile = self.expand(cmd.infile)[0]
            if cmd.outfile:
                cmd.outfile = self.expand(cmd.outfile)[0]
            if cmd.errfile:
                cmd.errfile = self.expand(cmd.errfile)[0]

        builtins = self.builtins()
        if len(pipe.cmds) == 1:
            cmd = pipe.cmds[0]
            # Чистое присваивание переменной без команды: FOO=bar
            if not cmd.argv and cmd.env_prefix:
                for k, v in cmd.env_prefix.items():
                    self.set_var(k, [v])
                return "", 0
            name = cmd.argv[0] if cmd.argv else ""
            if not name:
                return "", 0
            if name in self.functions:
                return self.call_function(cmd, name, capture)
            if name in builtins:
                return self.call_builtin(cmd, name, builtins[name], capture)

        procs = []
        prev_pipe = None
        opened = []
        last = None
        try:
            for idx, cmd in enumerate(pipe.cmds):
                if not cmd.argv:
                    raise ShellError("пустая команда в конвейере")

                in_pipe = prev_pipe if idx > 0 else None
                stdin = None
                if cmd.infile:
                    try:
                        stdin = open(cmd.infile, "rb")
                        opened.append(stdin)
                    except OSError as exc:
                        print(f"dash: {cmd.infile}: {exc}", file=sys.stderr)
                        return "", 1
                elif idx > 0:
                    stdin = in_pipe

                has_next = idx < len(pipe.cmds) - 1
                stdout = None
                if cmd.outfile:
                    try:
                        stdout = open(cmd.outfile, "ab" if cmd.append else "wb")
                        opened.append(stdout)
                    except OSError as exc:
                        print(f"dash: {cmd.outfile}: {exc}", file=sys.stderr)
                        return "", 1
                elif has_next or capture:
                    stdout = subprocess.PIPE

                stderr = None
                if cmd.errfile:
                    try:
                        stderr = open(cmd.errfile, "ab" if cmd.errappend else "wb")
                        opened.append(stderr)
                    except OSError as exc:
                        print(f"dash: {cmd.errfile}: {exc}", file=sys.stderr)
                        return "", 1

                try:
                    proc = subprocess.Popen(
                        cmd.argv,
                        stdin=stdin,
                        stdout=stdout,
                        stderr=stderr,
                        cwd=self.cwd,
                        env=self.child_env(cmd.env_prefix),
                    )
                except FileNotFoundError:
                    print(f"dash: команда не найдена: {cmd.argv[0]}", file=sys.stderr)
                    return "", 127
                except PermissionError:
                    print(f"dash: нет прав: {cmd.argv[0]}", file=sys.stderr)
                    return "", 126
                except OSError as exc:
                    print(f"dash: {exc}", file=sys.stderr)
                    return "", 1

                procs.append(proc)
                last = proc
                prev_pipe = proc.stdout if stdout == subprocess.PIPE else None
                if in_pipe is not None:
                    try:
                        in_pipe.close()
                    except OSError:
                        pass

            if pipe.background and not capture:
                idx = len(self.bg) + 1
                self.bg.append((last, pipe.cmds[-1]))
                print(f"[{idx}] {last.pid}")
                return "", 0

            data = b""
            if capture and last and last.stdout:
                data = last.stdout.read()

            status = 0
            for proc in procs:
                while True:
                    try:
                        code = proc.wait()
                        status = code
                        break
                    except ChildProcessError:
                        break
                    except KeyboardInterrupt:
                        status = 130

            self.bg = [(p, c) for p, c in self.bg if p.poll() is None]
            return data.decode("utf-8", "replace"), status
        finally:
            for handle in opened:
                try:
                    handle.close()
                except OSError:
                    pass

    # --- Промпт --------------------------------------------------------------
    def git_branch(self):
        try:
            cached = self._branch_cache.get(self.cwd, -1)
        except Exception:
            cached = -1
        if cached != -1:
            return cached
        branch = ""
        try:
            res = subprocess.run(
                ["git", "-C", self.cwd, "rev-parse", "--abbrev-ref", "HEAD"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=0.4,
            )
            if res.returncode == 0:
                branch = res.stdout.decode("utf-8", "replace").strip()
                if branch == "HEAD":
                    branch = ""
        except Exception:
            branch = ""
        self._branch_cache[self.cwd] = branch
        return branch

    def prompt(self):
        user = self.lookup("USER") or "user"
        host = socket.gethostname().split(".")[0]
        path = self.cwd
        if path == self.home:
            path = "~"
        elif path.startswith(self.home.rstrip("/") + "/"):
            path = "~" + path[len(self.home.rstrip("/")):]
        branch = self.git_branch()
        ind_color = C.GREEN if self.last_status == 0 else C.RED
        parts = [
            C.CYAN + user + C.RESET + "@" + C.CYAN + host + C.RESET,
            C.BLUE + path + C.RESET,
        ]
        if branch:
            parts.append(C.MAGENTA + "(" + branch + ")" + C.RESET)
        parts.append(ind_color + "❯" + C.RESET + " ")
        return " ".join(parts)

    # --- Дополнения ----------------------------------------------------------
    def command_names(self):
        if self._cmd_cache is None:
            names = set(self.builtins().keys()) | set(self.aliases.keys()) | set(self.functions.keys())
            path_env = self.child_env().get("PATH", "")
            for directory in path_env.split(os.pathsep):
                if not directory or not os.path.isdir(directory):
                    continue
                try:
                    for name in os.listdir(directory):
                        full = os.path.join(directory, name)
                        if os.access(full, os.X_OK) and os.path.isfile(full):
                            names.add(name)
                except OSError:
                    pass
            self._cmd_cache = sorted(names)
        return self._cmd_cache

    def candidates(self, word):
        if not word:
            return []
        if "/" in word or word.startswith(".") or word.startswith("~"):
            pattern = os.path.expanduser(word) + "*"
            found = globmod.glob(pattern)
            result = []
            for item in found:
                display = item
                if display.startswith(self.home + "/"):
                    display = "~" + display[len(self.home):]
                if os.path.isdir(item):
                    display += "/"
                result.append(display)
            return sorted(result)

        result = [c for c in self.command_names() if c.startswith(word)]
        try:
            result += [n + "/" for n in os.listdir(self.cwd)
                       if n.startswith(word) and os.path.isdir(os.path.join(self.cwd, n))]
            result += [n for n in os.listdir(self.cwd)
                       if n.startswith(word) and os.path.isfile(os.path.join(self.cwd, n))]
        except OSError:
            pass
        return sorted(set(result))


# --- Редактор строки в стиле fish ------------------------------------------
HL_RE = re.compile(
    r'(?P<op>&&|\|\||>>|<<|[|><;&])|(?P<dq>"(?:\\.|[^"\\])*")|'
    r"(?P<sq>'[^']*')|(?P<var>\$[A-Za-z_@#?$]\w*|\$\d+|\$\{[^}]+\})|"
    r"(?P<word>[^\s|><;&\"']+)"
)


class LineEditor:
    def __init__(self, shell):
        self.sh = shell
        self.fd = sys.stdin.fileno()
        self.old = None

    def __enter__(self):
        import termios
        import tty
        self.old = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        return self

    def __exit__(self, *args):
        import termios
        if self.old is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def read_key(self):
        b = os.read(self.fd, 1)
        if not b:
            return None
        byte = b[0]
        if byte == 0x1B:
            seq = b
            if select.select([self.fd], [], [], 0.06)[0]:
                try:
                    seq += os.read(self.fd, 24)
                except OSError:
                    pass
            return seq.decode("utf-8", "replace")
        if byte < 0x80:
            return chr(byte)
        if byte < 0xE0:
            n = 2
        elif byte < 0xF0:
            n = 3
        else:
            n = 4
        data = b
        for _ in range(n - 1):
            data += os.read(self.fd, 1) or b""
        return data.decode("utf-8", "replace")

    def highlight(self, text):
        if NO_COLOR or not text:
            return text
        out = []
        pos = 0
        prev_op = False
        first_word = True
        known = set(self.sh.command_names())
        for m in HL_RE.finditer(text):
            if m.start() > pos:
                out.append(text[pos:m.start()])
            pos = m.end()
            kind = m.lastgroup
            val = m.group()
            if kind == "op":
                out.append(C.RED + val + C.RESET)
                prev_op = True
                if val in ("|", "&&", "||", ";", "&"):
                    first_word = True
            elif kind in ("dq", "sq"):
                out.append(C.YELLOW + val + C.RESET)
                prev_op = False
                first_word = False
            elif kind == "var":
                out.append(C.MAGENTA + val + C.RESET)
                prev_op = False
                first_word = False
            else:
                if first_word:
                    if "=" in val and re.match(r"^[A-Za-z_]\w*=", val):
                        out.append(C.CYAN + val + C.RESET)
                        continue
                    color = C.GREEN if val in known else C.RED
                    first_word = False
                elif prev_op or val.startswith(("/", "./", "~/")):
                    color = C.BLUE
                else:
                    color = ""
                out.append(color + val + C.RESET if color else val)
                prev_op = False
        if pos < len(text):
            out.append(text[pos:])
        return "".join(out)

    def suggestion(self, buf):
        if not buf or buf.endswith(" "):
            return ""
        for item in reversed(self.sh.history):
            if item.startswith(buf) and item != buf:
                return item[len(buf):]
        if " " not in buf:
            for name in self.sh.command_names():
                if name.startswith(buf) and name != buf:
                    return name[len(buf):]
        return ""

    def render(self, prompt, buf, cursor):
        sug = self.suggestion(buf)
        sys.stdout.write("\r\x1b[2K" + prompt + self.highlight(buf) + C.GRAY + sug + C.RESET)
        total = visible_len(prompt) + len(buf) + len(sug)
        target = visible_len(prompt) + cursor
        back = max(0, total - target)
        if back:
            sys.stdout.write(f"\x1b[{back}D")
        sys.stdout.flush()

    def complete(self, buf, cursor):
        prefix = buf[:cursor]
        m = re.search(r"([^\s|><;&]+)$", prefix)
        word = m.group(1) if m else ""
        start = m.start(1) if m else cursor
        candidates = self.sh.candidates(word)
        if not candidates:
            return buf, cursor
        if len(candidates) == 1:
            rep = candidates[0]
            return buf[:start] + rep + buf[cursor:], start + len(rep)
        common = os.path.commonprefix(candidates)
        if len(common) > len(word):
            return buf[:start] + common + buf[cursor:], start + len(common)
        sys.stdout.write("\r\x1b[2K" + "\n" + "  ".join(candidates[:40]) + "\n")
        return buf, cursor

    def history_search(self):
        query = ""
        found = ""
        while True:
            sys.stdout.write("\r\x1b[2K" + C.CYAN + "поиск" + C.RESET + ": " + query)
            if found:
                sys.stdout.write("  " + C.DIM + found + C.RESET)
            sys.stdout.flush()
            key = self.read_key()
            if key is None or key in ("\n", "\r"):
                break
            if key in ("\x03", "\x1b"):
                found = ""
                break
            if key in ("\x7f", "\x08"):
                query = query[:-1]
            elif key in ("\x12",):
                continue
            elif len(key) == 1 and key.isprintable():
                query += key
            else:
                continue
            found = ""
            for item in reversed(self.sh.history):
                if query in item:
                    found = item
                    break
        sys.stdout.write("\r\x1b[2K")
        return found

    def readline(self, prompt):
        buf = ""
        cursor = 0
        hist_idx = len(self.sh.history)
        self.render(prompt, buf, cursor)
        while True:
            key = self.read_key()
            if key is None:
                sys.stdout.write("\n")
                return None
            if key in ("\n", "\r"):
                sys.stdout.write("\n")
                return buf
            if key == "\x03":
                sys.stdout.write("\r\x1b[2K" + prompt + "^C\n")
                return ""
            if key == "\x04":
                if not buf:
                    sys.stdout.write("\n")
                    return None
                continue
            if key == "\x1b":
                buf = ""
                cursor = 0
            elif key in ("\x1b[A", "\x1b[B"):
                if not self.sh.history:
                    continue
                if key.endswith("A"):
                    hist_idx = max(0, hist_idx - 1)
                else:
                    hist_idx = min(len(self.sh.history), hist_idx + 1)
                buf = self.sh.history[hist_idx] if hist_idx < len(self.sh.history) else ""
                cursor = len(buf)
            elif key == "\x1b[C":
                sug = self.suggestion(buf)
                if cursor == len(buf) and sug:
                    buf += sug
                    cursor = len(buf)
                else:
                    cursor = min(len(buf), cursor + 1)
            elif key == "\x1b[D":
                cursor = max(0, cursor - 1)
            elif key in ("\x1b[H", "\x1b[1~", "\x01"):
                cursor = 0
            elif key in ("\x1b[F", "\x1b[4~", "\x05"):
                cursor = len(buf)
            elif key == "\x1b[3~":
                buf = buf[:cursor] + buf[cursor + 1:]
            elif key in ("\x7f", "\x08"):
                if cursor > 0:
                    buf = buf[:cursor - 1] + buf[cursor:]
                    cursor -= 1
            elif key == "\x0b":
                buf = buf[:cursor]
            elif key == "\x15":
                buf = buf[cursor:]
                cursor = 0
            elif key == "\x17":  # Ctrl+W
                left = buf[:cursor].rstrip()
                pos = left.rfind(" ")
                pos = pos + 1 if pos >= 0 else 0
                buf = buf[:pos] + buf[cursor:]
                cursor = pos
            elif key == "\x0c":
                sys.stdout.write("\x1b[2J\x1b[H")
            elif key == "\x12":
                found = self.history_search()
                if found:
                    buf = found
                    cursor = len(buf)
            elif key == "\t":
                buf, cursor = self.complete(buf, cursor)
            elif len(key) >= 1 and key.isprintable():
                buf = buf[:cursor] + key + buf[cursor:]
                cursor += len(key)
            self.render(prompt, buf, cursor)


def fallback_input(prompt):
    plain = ANSI_RE.sub("", prompt)
    try:
        return input(plain)
    except EOFError:
        return None


def needs_more(text):
    """Возвращает True, если строка незавершена (перенос строки или незакрытые {/кавычки)."""
    if text.rstrip().endswith("\\"):
        return True
    return text.count("{") > text.count("}")


def read_with_editor(editor, prompt):
    if editor is None:
        return fallback_input(prompt)
    editor.__enter__()
    try:
        return editor.readline(prompt)
    finally:
        editor.__exit__()


def run_batch(sh, text):
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sh.run_line(line)
    return sh.last_status


def main():
    args = sys.argv[1:]
    cmd_str = None
    script_file = None
    script_args = []
    force_interactive = False

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--version":
            print(f"Dash {DASH_VERSION}")
            return
        if a == "--help":
            Shell.bi_help([])
            return
        if a in ("-c",):
            if i + 1 >= len(args):
                print("dash: -c: требуется аргумент", file=sys.stderr)
                raise SystemExit(2)
            cmd_str = args[i + 1]
            script_args = args[i + 2:]
            break
        if a in ("-l", "--login"):
            i += 1
            continue
        if a == "-i":
            force_interactive = True
            i += 1
            continue
        if a == "--":
            i += 1
            if i < len(args):
                script_file = args[i]
                script_args = args[i + 1:]
            break
        if a.startswith("-") and a != "-":
            # Поддержка комбинированных флагов вроде -lc
            if "c" in a:
                if i + 1 >= len(args):
                    print("dash: -c: требуется аргумент", file=sys.stderr)
                    raise SystemExit(2)
                cmd_str = args[i + 1]
                script_args = args[i + 2:]
                break
            if "i" in a:
                force_interactive = True
            i += 1
            continue
        script_file = a
        script_args = args[i + 1:]
        break

    sh = Shell(script_name=script_file or "dash")
    sh.params = list(script_args)

    if cmd_str is not None:
        try:
            code = sh.run_line(cmd_str)
            raise SystemExit(code if isinstance(code, int) else sh.last_status)
        except ExitShell as exc:
            raise SystemExit(exc.code)
        except ShellError as exc:
            print(f"dash: {exc}", file=sys.stderr)
            raise SystemExit(2)

    if script_file is not None:
        try:
            with open(script_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            print(f"dash: {script_file}: {exc}", file=sys.stderr)
            raise SystemExit(127)
        try:
            code = run_batch(sh, content)
            raise SystemExit(code)
        except ExitShell as exc:
            raise SystemExit(exc.code)
        except ShellError as exc:
            print(f"dash: {exc}", file=sys.stderr)
            raise SystemExit(2)

    interactive = force_interactive or (sys.stdin.isatty() and sys.stdout.isatty())

    if not interactive:
        try:
            code = run_batch(sh, sys.stdin.read())
            raise SystemExit(code)
        except ExitShell as exc:
            raise SystemExit(exc.code)

    sh.load_rc()
    print(C.BOLD + C.CYAN + "Dash" + C.RESET + " " + C.DIM +
          f"({DASH_VERSION}) — наберите help для справки" + C.RESET)

    editor = LineEditor(sh) if (sys.stdin.isatty() and sys.stdout.isatty()) else None
    try:
        while True:
            try:
                line = read_with_editor(editor, sh.prompt())
                if line is not None:
                    while needs_more(line):
                        more = read_with_editor(editor, C.DIM + "...> " + C.RESET)
                        if more is None:
                            break
                        line += "\n" + more
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                continue
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            sh.add_history(line)
            try:
                sh.run_line(line)
            except ExitShell as exc:
                raise SystemExit(exc.code)
            except ShellError as exc:
                print(f"dash: {exc}", file=sys.stderr)
                sh.last_status = 1
            except KeyboardInterrupt:
                sys.stdout.write("^C\n")
                sh.last_status = 130
            except Exception as exc:
                print(f"dash: {type(exc).__name__}: {exc}", file=sys.stderr)
                sh.last_status = 1
    finally:
        sh.save_history()


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    main()
