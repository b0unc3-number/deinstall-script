#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deinstall Studio — среда разработки (IDE) для языка Deinstall Script.

Возможности:
    * подсветка синтаксиса (тёмная тема);
    * автодополнение: слова из скрипта, ключевые слова, встроенные функции,
      атрибуты модулей (math., os., json., ...);
    * запуск скрипта интерпретатором Python (F5) и Java (Ctrl+F5);
    * проверка синтаксиса (F6);
    * сборка в .exe через C-бэкенд superfast (F7);
    * консоль с полем ввода для input(), номера строк, строка состояния.

Запуск:        python deinstall_ide.py [файл.dis]
Самопроверка:  python deinstall_ide.py --selftest
"""

import os
import re
import sys
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

DIS_PY = os.path.join(HERE, "deinstall.py")
JAVA_CLASS = os.path.join(HERE, "DeinstallScript.class")
DIS_BAT = os.path.join(HERE, "dis.bat")
DISJ_BAT = os.path.join(HERE, "disj.bat")
EXAMPLES = os.path.join(HERE, "examples")

# ===========================================================================
#  Данные языка
# ===========================================================================

KEYWORDS = [
    "func", "if", "elseif", "else", "while", "loop", "in", "ret",
    "break", "continue", "try", "catch", "throw", "import", "as",
    "and", "or", "not", "lambda", "pass", "var",
]

# Python-алиасы, которые понимает интерпретатор
PY_ALIASES = ["elif", "for", "return"]

CONSTS = ["true", "false", "null", "True", "False", "None"]

BUILTINS = [
    "print", "println", "pythontwo", "superfast",
    "type", "len", "map", "filter", "reversed", "range",
    "int", "float", "str", "bool", "list", "dict",
    "abs", "min", "max", "sum", "round", "sorted", "enumerate", "zip",
    "any", "all", "repr", "format", "input",
    "read_file", "write_file", "exists", "exit",
]

MODULES = [
    "math", "json", "os", "sys", "time", "random", "re", "datetime",
    "collections", "itertools", "statistics", "string", "functools",
    "decimal", "fractions", "pathlib", "subprocess", "platform",
    "base64", "hashlib", "csv", "sqlite3", "tkinter", "webbrowser",
    "urllib", "io", "copy", "glob", "shutil", "textwrap", "unicodedata",
]

MODULE_ATTRS = {
    "math": ["sqrt", "pi", "e", "tau", "inf", "nan", "pow", "floor", "ceil",
             "fabs", "factorial", "gcd", "log", "log2", "log10", "exp",
             "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "hypot",
             "degrees", "radians", "trunc", "copysign", "isclose"],
    "json": ["dumps", "loads", "dump", "load"],
    "os": ["getcwd", "listdir", "mkdir", "makedirs", "remove", "rmdir",
           "rename", "environ", "name", "sep", "path", "system", "getenv"],
    "sys": ["argv", "version", "version_info", "platform", "exit",
            "stdout", "stderr", "stdin", "path", "modules", "maxsize",
            "getrecursionlimit", "setrecursionlimit"],
    "time": ["time", "sleep", "perf_counter", "monotonic", "localtime",
             "gmtime", "strftime", "strptime", "mktime", "ctime", "asctime"],
    "random": ["random", "randint", "randrange", "choice", "choices",
               "shuffle", "seed", "uniform", "sample", "gauss"],
    "re": ["match", "search", "findall", "finditer", "sub", "split",
           "compile", "escape", "fullmatch", "IGNORECASE", "MULTILINE",
           "DOTALL"],
    "datetime": ["datetime", "date", "time", "timedelta", "timezone",
                 "now", "today", "utcnow", "fromtimestamp"],
}

SNIPPETS = [
    ("Функция  func …", "func имя(аргументы):\n    ret 0\n"),
    ("Условие  if …", "if условие:\n    \n"),
    ("Цикл  while …", "while условие:\n    \n"),
    ("Цикл  loop i in range(10)", "loop i in range(10):\n    println{i}\n"),
    ("try / catch", "try:\n    \ncatch err:\n    println{err}\n"),
    ("f-строка", 'println{f"значение: {x}"}'),
    ("superfast (C-ускорение)", "superfast.enable\n"),
]

WELCOME = ('# Deinstall Studio — IDE языка Deinstall Script\n'
           '# F5 — запустить, Ctrl+Space — автодополнение, F7 — собрать .exe\n'
           '\n'
           'func привет(имя):\n'
           '    println{f"Привет, {имя}!"}\n'
           '\n'
           'привет{"мир"}\n')

# ===========================================================================
#  Оформление
# ===========================================================================

COL = {
    "bg":        "#1e1e28",
    "bg_dark":   "#15151e",
    "panel":     "#2a2a3a",
    "fg":        "#d8dee9",
    "muted":     "#6b7394",
    "sel":       "#3a3a5c",
    "curline":   "#26263a",
    "kw":        "#c792ea",
    "builtin":   "#82aaff",
    "str":       "#c3e88d",
    "num":       "#f78c6c",
    "comment":   "#5c6370",
    "const":     "#ffcb6b",
    "func":      "#7fdbca",
    "directive": "#ff5370",
    "brace":     "#89ddff",
    "match":     "#3a4a6a",
    "out":       "#d8dee9",
    "err":       "#ff6b81",
    "sys":       "#6b7394",
    "in":        "#82aaff",
    "ok":        "#c3e88d",
}

FONT_EDIT = ("Consolas", 12)
FONT_NUM = ("Consolas", 11)
FONT_CONSOLE = ("Consolas", 11)
FONT_UI = ("Segoe UI", 10)

# Регулярка подсветки: порядок ветвлений важен!
HL_RE = re.compile(r'''
      (?P<comment>\#[^\n]*)
    | (?P<directive>\bsuperfast\s*\.\s*(?:enable|disable)\b)
    | (?P<str>(?:[fFrRbB]{0,2})?(?:'{3}[\s\S]*?'{3}|"{3}[\s\S]*?"{3}|"(?:\\.|[^"\\\n])*"?|'(?:\\.|[^'\\\n])*'?))
    | (?P<num>(?<![\w.])(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)(?![\w.]))
    | (?P<funcdef>\bfunc\s+(?P<fname>\w+))
    | (?P<kw>\b(?:func|elseif|elif|else|while|loop|in|ret|return|break|continue|try|catch|throw|import|as|and|or|not|lambda|pass|var|for)\b)
    | (?P<const>\b(?:true|false|null|True|False|None)\b)
    | (?P<builtin>\b(?:print|println|pythontwo|superfast|type|len|map|filter|reversed|range|int|float|str|bool|list|dict|abs|min|max|sum|round|sorted|enumerate|zip|any|all|repr|format|input|read_file|write_file|exists|exit)\b)
    | (?P<brace>[\[\]{}()])
''', re.VERBOSE)

PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
CLOSERS = ")]}\"'"

# запасные значения для keysym, если событие пришло без char
KEYSYM_CH = {
    "period": ".", "comma": ",", "underscore": "_", "backslash": "\\",
    "space": " ", "parenleft": "(", "parenright": ")", "bracketleft": "[",
    "bracketright": "]", "braceleft": "{", "braceright": "}", "quotedbl": '"',
    "apostrophe": "'", "colon": ":", "semicolon": ";", "slash": "/",
    "minus": "-", "plus": "+", "asterisk": "*", "equal": "=", "greater": ">",
    "less": "<", "percent": "%", "exclam": "!", "question": "?", "at": "@",
    "numbersign": "#", "ampersand": "&", "bar": "|", "asciitilde": "~",
    "asciicircum": "^", "dollar": "$",
}


def ev_char(ev):
    """Символ события: ev.char, иначе — расшифровка keysym."""
    ch = getattr(ev, "char", "") or ""
    if ch:
        return ch
    ks = getattr(ev, "keysym", "") or ""
    if len(ks) == 1:
        return ks
    return KEYSYM_CH.get(ks, "")


def _offset_to_index(starts, off):
    """Преобразует смещение в строке в индекс Tk («строка.столбец»)."""
    import bisect
    ln = bisect.bisect_right(starts, off) - 1
    return "%d.%d" % (ln + 1, off - starts[ln])


class App:
    def __init__(self, root, path=None):
        self.root = root
        self.path = None
        self.dirty = False
        self.proc = None
        self.queue = queue.Queue()
        self._hl_job = None
        self._str_spans = []
        self._com_spans = []
        self._line_starts = [0]
        self._popup_open = False
        self._popup_start = None
        self._popup_module = None
        self._popup_items = []

        root.title("Deinstall Studio")
        root.geometry("1150x760")
        root.minsize(860, 540)
        root.configure(bg=COL["bg"])

        self._build_menu()
        self._build_toolbar()
        self._build_findbar()
        self._build_main()
        self._build_status()
        self._bind_keys()

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        if path:
            self.open_path(path)
        else:
            self.text.insert("1.0", WELCOME)
            self.text.edit_reset()
            self.dirty = False
            self._update_title()
            self.do_highlight()
        self._update_status()
        root.after(80, self._poll_queue)

    # ------------------------------------------------------------------
    #  Меню
    # ------------------------------------------------------------------
    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)

        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Новый", accelerator="Ctrl+N", command=self.new_file)
        f.add_command(label="Открыть…", accelerator="Ctrl+O", command=self.open_file)
        f.add_command(label="Сохранить", accelerator="Ctrl+S", command=self.save_file)
        f.add_command(label="Сохранить как…", accelerator="Ctrl+Shift+S",
                      command=lambda: self.save_file(save_as=True))
        f.add_separator()
        f.add_command(label="Собрать .exe (C-бэкенд)…", accelerator="F7",
                      command=self.compile_exe)
        f.add_separator()
        f.add_command(label="Выход", command=self.on_close)
        m.add_cascade(label="Файл", menu=f)

        e = tk.Menu(m, tearoff=0)
        e.add_command(label="Отменить", accelerator="Ctrl+Z",
                      command=lambda: self._event("<<Undo>>"))
        e.add_command(label="Вернуть", accelerator="Ctrl+Y",
                      command=lambda: self._event("<<Redo>>"))
        e.add_separator()
        e.add_command(label="Вырезать", accelerator="Ctrl+X",
                      command=lambda: self._event("<<Cut>>"))
        e.add_command(label="Копировать", accelerator="Ctrl+C",
                      command=lambda: self._event("<<Copy>>"))
        e.add_command(label="Вставить", accelerator="Ctrl+V",
                      command=lambda: self._event("<<Paste>>"))
        e.add_separator()
        e.add_command(label="Найти…", accelerator="Ctrl+F", command=self.show_findbar)
        e.add_command(label="Перейти к строке…", accelerator="Ctrl+G",
                      command=self.goto_line)
        e.add_command(label="Комментировать / раскомментировать", accelerator="Ctrl+/",
                      command=self.toggle_comment)
        m.add_cascade(label="Правка", menu=e)

        r = tk.Menu(m, tearoff=0)
        r.add_command(label="Запустить в отдельном окне (dis.bat)", accelerator="F5",
                      command=self.run_python)
        r.add_command(label="Java в отдельном окне (disj.bat)", accelerator="Ctrl+F5",
                      command=self.run_java)
        r.add_separator()
        r.add_command(label="Запустить во встроенной консоли IDE",
                      command=self.run_python_inside)
        r.add_command(label="Java во встроенной консоли IDE",
                      command=self.run_java_inside)
        r.add_separator()
        r.add_command(label="Проверить синтаксис", accelerator="F6", command=self.check_syntax)
        r.add_command(label="Стоп", command=self.stop_proc)
        r.add_command(label="Очистить консоль", command=self.clear_console)
        m.add_cascade(label="Запуск", menu=r)

        ins = tk.Menu(m, tearoff=0)
        for label, text in SNIPPETS:
            ins.add_command(label=label, command=lambda t=text: self.insert_snippet(t))
        m.add_cascade(label="Вставка", menu=ins)

        ex = tk.Menu(m, tearoff=0)
        files = []
        if os.path.isdir(EXAMPLES):
            files = sorted(f for f in os.listdir(EXAMPLES) if f.endswith(".dis"))
        for fname in files:
            full = os.path.join(EXAMPLES, fname)
            ex.add_command(label="  " + fname,
                           command=lambda p=full: self.open_path(p))
        if files:
            ex.add_separator()
        ex.add_command(label="Открыть папку examples", command=self.open_examples_dir)
        m.add_cascade(label="Примеры", menu=ex)

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Горячие клавиши", command=self.show_hotkeys)
        h.add_command(label="О программе", command=self.show_about)
        m.add_cascade(label="Справка", menu=h)

        self.root.configure(menu=m)

    # ------------------------------------------------------------------
    #  Панель инструментов
    # ------------------------------------------------------------------
    def _tbtn(self, parent, text, cmd):
        b = tk.Button(parent, text=text, command=cmd, bg=COL["panel"],
                      fg=COL["fg"], activebackground=COL["sel"],
                      activeforeground="#ffffff", relief="flat", bd=0,
                      padx=10, pady=3, font=FONT_UI)
        b.pack(side="left", padx=2, pady=2)
        return b

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=COL["bg_dark"])
        bar.grid(row=0, column=0, sticky="ew")
        self._tbtn(bar, "▶ Запустить в окне", self.run_python)
        self._tbtn(bar, "☕ Java в окне", self.run_java)
        self._tbtn(bar, "⌨ В консоли IDE", self.run_python_inside)
        self._tbtn(bar, "✓ Синтаксис", self.check_syntax)
        self._tbtn(bar, "⚡ Собрать .exe", self.compile_exe)
        self._tbtn(bar, "■ Стоп", self.stop_proc)
        self._tbtn(bar, "🧹", self.clear_console)
        tk.Label(bar, text="аргументы:", bg=COL["bg_dark"], fg=COL["muted"],
                 font=FONT_UI).pack(side="left", padx=(14, 2))
        self.args_var = tk.StringVar()
        tk.Entry(bar, textvariable=self.args_var, bg=COL["bg"], fg=COL["fg"],
                 insertbackground=COL["fg"], font=FONT_CONSOLE, relief="flat",
                 width=18).pack(side="left", pady=3, padx=(0, 6))

    # ------------------------------------------------------------------
    #  Строка поиска
    # ------------------------------------------------------------------
    def _build_findbar(self):
        bar = tk.Frame(self.root, bg=COL["panel"])
        self.findbar = bar
        tk.Label(bar, text="  Найти:", bg=COL["panel"], fg=COL["muted"],
                 font=FONT_UI).pack(side="left")
        self.find_var = tk.StringVar()
        ent = tk.Entry(bar, textvariable=self.find_var, bg=COL["bg"],
                       fg=COL["fg"], insertbackground=COL["fg"],
                       font=FONT_CONSOLE, relief="flat", width=34)
        ent.pack(side="left", padx=4, pady=3)
        ent.bind("<Return>", lambda ev: self.find_next(1))
        ent.bind("<Shift-Return>", lambda ev: self.find_next(-1))
        ent.bind("<Escape>", lambda ev: self.hide_findbar())
        self.find_entry = ent
        self._tbtn(bar, "Далее", lambda: self.find_next(1))
        self._tbtn(bar, "Назад", lambda: self.find_next(-1))
        self._tbtn(bar, "Закрыть", self.hide_findbar)

    # ------------------------------------------------------------------
    #  Редактор и консоль
    # ------------------------------------------------------------------
    def _build_main(self):
        pane = tk.PanedWindow(self.root, orient="vertical", bg=COL["bg_dark"],
                              sashwidth=6, relief="flat", bd=0)
        pane.grid(row=2, column=0, sticky="nsew")
        self.root.rowconfigure(2, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.paned = pane

        ed = tk.Frame(pane, bg=COL["bg"])
        pane.add(ed, stretch="always", minsize=220)
        self._build_editor(ed)

        cs = tk.Frame(pane, bg=COL["bg_dark"])
        pane.add(cs, stretch="never", minsize=110)
        self._build_console(cs)

    def _build_editor(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        self.line_nums = tk.Text(parent, width=5, padx=6, pady=4, takefocus=0,
                                 bg=COL["bg_dark"], fg=COL["muted"], font=FONT_NUM,
                                 relief="flat", highlightthickness=0, state="disabled",
                                 wrap="none", cursor="arrow")
        self.line_nums.grid(row=0, column=0, rowspan=2, sticky="ns")

        self.text = tk.Text(parent, bg=COL["bg"], fg=COL["fg"],
                            insertbackground="#ffffff", selectbackground=COL["sel"],
                            selectforeground="#ffffff", font=FONT_EDIT, undo=True,
                            maxundo=-1, wrap="none", relief="flat",
                            highlightthickness=0, padx=8, pady=4, tabs="4c")
        self.text.grid(row=0, column=1, sticky="nsew")

        vs = tk.Scrollbar(parent, command=self.text.yview, width=12)
        vs.grid(row=0, column=2, rowspan=2, sticky="ns")
        hs = tk.Scrollbar(parent, command=self.text.xview, orient="horizontal",
                          width=12)
        hs.grid(row=1, column=1, sticky="ew")
        self.vscroll = vs
        self.text.configure(xscrollcommand=hs.set, yscrollcommand=self._on_yview)

        t = self.text
        t.tag_configure("kw", foreground=COL["kw"])
        t.tag_configure("builtin", foreground=COL["builtin"])
        t.tag_configure("str", foreground=COL["str"])
        t.tag_configure("num", foreground=COL["num"])
        t.tag_configure("comment", foreground=COL["comment"],
                        font=(FONT_EDIT[0], FONT_EDIT[1], "italic"))
        t.tag_configure("const", foreground=COL["const"])
        t.tag_configure("func", foreground=COL["func"])
        t.tag_configure("directive", foreground=COL["directive"])
        t.tag_configure("brace", foreground=COL["brace"])
        t.tag_configure("match", background=COL["match"])
        t.tag_configure("cur", background=COL["curline"])
        t.tag_lower("cur")

    def _build_console(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        self.console = tk.Text(parent, bg=COL["bg_dark"], fg=COL["out"],
                               font=FONT_CONSOLE, relief="flat",
                               highlightthickness=0, padx=6, pady=3,
                               wrap="word", state="disabled")
        self.console.grid(row=0, column=0, sticky="nsew")
        vs = tk.Scrollbar(parent, command=self.console.yview, width=12)
        vs.grid(row=0, column=1, sticky="ns")
        self.console.configure(yscrollcommand=vs.set)
        self.console.tag_configure("out", foreground=COL["out"])
        self.console.tag_configure("err", foreground=COL["err"])
        self.console.tag_configure("sys", foreground=COL["sys"])
        self.console.tag_configure("in", foreground=COL["in"])
        self.console.tag_configure("ok", foreground=COL["ok"])

        bar = tk.Frame(parent, bg=COL["panel"])
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        tk.Label(bar, text="  ввод →", bg=COL["panel"], fg=COL["in"],
                 font=FONT_UI).pack(side="left")
        self.stdin_entry = tk.Entry(bar, bg=COL["bg"], fg=COL["fg"],
                                    insertbackground=COL["fg"], font=FONT_CONSOLE,
                                    relief="flat")
        self.stdin_entry.pack(side="left", fill="x", expand=True, padx=6, pady=3)
        self.stdin_entry.bind("<Return>", self._send_stdin)

    def _build_status(self):
        self.status_var = tk.StringVar(value="готово")
        tk.Label(self.root, textvariable=self.status_var, anchor="w",
                 bg=COL["panel"], fg=COL["muted"], font=FONT_UI, padx=8).grid(
            row=3, column=0, sticky="ew")

    def _on_yview(self, first, last):
        self.vscroll.set(first, last)
        self.line_nums.yview_moveto(first)

    # ------------------------------------------------------------------
    #  Горячие клавиши
    # ------------------------------------------------------------------
    def _event(self, seq):
        return lambda: self.text.event_generate(seq, when="tail")

    def _bind_keys(self):
        t = self.text
        t.bind("<<Modified>>", self._on_modified)
        t.bind("<KeyPress>", self.on_key_press)
        t.bind("<KeyRelease>", self.on_key_release)
        t.bind("<ButtonRelease-1>", self.on_cursor_move)
        t.bind("<Return>", self.on_return)
        t.bind("<KP_Enter>", self.on_return)
        t.bind("<Tab>", self.on_tab)
        t.bind("<Shift-Tab>", self.on_shift_tab)
        t.bind("<Escape>", self.on_escape)
        t.bind("<BackSpace>", self.on_backspace)
        t.bind("<Control-space>", self.on_ctrl_space)
        t.bind("<Control-z>", lambda ev: (self._event("<<Undo>>")(), "break")[1])
        t.bind("<Control-y>", lambda ev: (self._event("<<Redo>>")(), "break")[1])
        t.bind("<Control-a>", self._select_all)
        t.bind("<Control-f>", lambda ev: (self.show_findbar(), "break")[1])
        t.bind("<Control-g>", lambda ev: (self.goto_line(), "break")[1])
        t.bind("<Control-slash>", self._on_comment_key)
        t.bind("<Control-n>", lambda ev: (self.new_file(), "break")[1])
        t.bind("<Control-o>", lambda ev: (self.open_file(), "break")[1])
        t.bind("<Control-s>", self._on_save_key)
        t.bind("<Control-F5>", lambda ev: (self.run_java(), "break")[1])
        self.root.bind("<F5>", lambda ev: self.run_python())
        self.root.bind("<F6>", lambda ev: self.check_syntax())
        self.root.bind("<F7>", lambda ev: self.compile_exe())

    def _select_all(self, ev=None):
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    # ------------------------------------------------------------------
    #  Подсветка синтаксиса
    # ------------------------------------------------------------------
    def schedule_highlight(self):
        if self._hl_job is not None:
            try:
                self.root.after_cancel(self._hl_job)
            except Exception:
                pass
        self._hl_job = self.root.after(80, self.do_highlight)

    def do_highlight(self):
        self._hl_job = None
        t = self.text
        content = t.get("1.0", "end-1c")
        starts = [0]
        for m in re.finditer("\n", content):
            starts.append(m.end())
        self._line_starts = starts
        for tag in ("kw", "builtin", "str", "num", "comment", "const",
                    "func", "directive", "brace"):
            t.tag_remove(tag, "1.0", "end")
        self._str_spans = []
        self._com_spans = []
        for m in HL_RE.finditer(content):
            if m.start("funcdef") != -1:
                s1, e1 = m.span("funcdef")
                s2, e2 = m.span("fname")
                t.tag_add("kw", _offset_to_index(starts, s1),
                          _offset_to_index(starts, e1))
                t.tag_add("func", _offset_to_index(starts, s2),
                          _offset_to_index(starts, e2))
                continue
            for name in ("comment", "str", "num", "kw", "const",
                         "builtin", "directive", "brace"):
                s = m.start(name)
                if s == -1:
                    continue
                e = m.end(name)
                if name == "str":
                    self._str_spans.append((s, e))
                elif name == "comment":
                    self._com_spans.append((s, e))
                t.tag_add(name, _offset_to_index(starts, s),
                          _offset_to_index(starts, e))
                break
        self._update_line_numbers(starts)
        self._update_cursor_line()
        self._match_bracket()

    def _update_line_numbers(self, starts):
        n = len(starts)
        if n == getattr(self, "_line_count", 0):
            self.line_nums.yview_moveto(self.text.yview()[0])
            return
        self._line_count = n
        self.line_nums.configure(state="normal")
        self.line_nums.delete("1.0", "end")
        self.line_nums.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)))
        self.line_nums.configure(state="disabled")
        self.line_nums.yview_moveto(self.text.yview()[0])

    # ------------------------------------------------------------------
    #  Курсор, текущая строка, парные скобки
    # ------------------------------------------------------------------
    def _update_cursor_line(self):
        t = self.text
        t.tag_remove("cur", "1.0", "end")
        t.tag_add("cur", "insert linestart", "insert lineend+1c")

    def cur_offset(self):
        v = self.text.count("1.0", "insert", "chars")
        if v is None:
            return 0
        if isinstance(v, tuple):
            v = v[0]
        return v

    def _in_spans(self, off, spans, inclusive=False):
        for a, b in spans:
            if a > off:
                break
            if a <= off < b or (inclusive and a <= off <= b):
                return True
        return False

    OPEN_BR = "([{"
    CLOSE_BR = ")]}"

    def _match_bracket(self):
        t = self.text
        t.tag_remove("match", "1.0", "end")
        content = t.get("1.0", "end-1c")
        off = self.cur_offset()
        pos = None
        if off < len(content) and content[off] in self.OPEN_BR:
            pos = off
            ch = content[off]
        elif off > 0 and content[off - 1] in self.CLOSE_BR:
            pos = off - 1
            ch = content[off - 1]
        if pos is None:
            return
        pairs = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}
        mate = pairs[ch]
        depth = 0
        if ch in self.OPEN_BR:
            i = pos
            end = min(len(content), pos + 4000)
            while i < end:
                c = content[i]
                if c == ch:
                    depth += 1
                elif c == mate:
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            if i >= end:
                return
            other = i
        else:
            i = pos
            start = max(0, pos - 4000)
            while i >= start:
                c = content[i]
                if c == ch:
                    depth += 1
                elif c == mate:
                    depth -= 1
                    if depth == 0:
                        break
                i -= 1
            if i < start:
                return
            other = i
        for p in (pos, other):
            idx = "1.0+%dc" % p
            t.tag_add("match", idx, idx + " +1c")

    def on_cursor_move(self, ev=None):
        self._update_cursor_line()
        self._match_bracket()
        self._update_status()

    def _update_status(self):
        line, col = self.text.index("insert").split(".")
        name = os.path.basename(self.path) if self.path else "новая программа"
        state = "изменён" if self.dirty else ("сохранён" if self.path else "")
        self.status_var.set("Строка %s, столбец %d    |    %s %s    |    Deinstall Studio %s"
                            % (line, int(col) + 1, name, state, VERSION))

    # ------------------------------------------------------------------
    #  Автодополнение
    # ------------------------------------------------------------------
    def _words_in_doc(self, content):
        words = set()
        words.update(KEYWORDS)
        words.update(PY_ALIASES)
        words.update(CONSTS)
        words.update(BUILTINS)
        words.update(MODULES)
        words.update(re.findall(r"\bfunc\s+(\w+)", content))
        words.update(re.findall(r"\bloop\s+(\w+)", content))
        words.update(re.findall(r"^\s*(\w+)\s*=", content, re.M))
        words.update(re.findall(r"\bimport\s+(\w+)", content))
        return words

    def completions_for(self, prefix, module=None):
        if module:
            pool = MODULE_ATTRS.get(module, [])
        else:
            pool = self._words_in_doc(self.text.get("1.0", "end-1c"))
        pref = prefix.lower()
        out = [w for w in pool if w.lower().startswith(pref) and w != prefix]
        out.sort(key=lambda w: (w.lower(), len(w)))
        return out

    def _word_before_cursor(self):
        before = self.text.get("insert linestart", "insert")
        m = re.search(r"(\w+)$", before)
        prefix = m.group(1) if m else ""
        return prefix, len(before) - len(prefix)

    def _ensure_popup(self):
        if getattr(self, "popup", None) is None:
            self.popup = tk.Listbox(self.text, bg=COL["panel"], fg=COL["fg"],
                                    selectbackground=COL["sel"],
                                    selectforeground="#ffffff",
                                    font=FONT_CONSOLE, highlightthickness=1,
                                    highlightbackground=COL["brace"],
                                    activestyle="none", relief="flat", bd=0)
            self.popup.bind("<ButtonRelease-1>", self._popup_click)
            self.text.bind("<MouseWheel>", lambda ev: self.close_popup(), add="+")

    def _popup_click(self, ev=None):
        self.accept_popup()
        self.text.focus_set()
        return "break"

    def maybe_popup(self, force=False):
        prefix, start = self._word_before_cursor()
        if not force and not prefix:
            self.close_popup()
            return
        off = self.cur_offset()
        if not force and (self._in_spans(off, self._str_spans, True)
                          or self._in_spans(off, self._com_spans, True)):
            self.close_popup()
            return
        items = self.completions_for(prefix)
        if not items:
            self.close_popup()
            return
        self.open_popup(items, start)

    def open_popup(self, items, start_col, module=None):
        if not items:
            self.close_popup()
            return
        self._ensure_popup()
        self._popup_items = items
        self._popup_start = start_col
        self._popup_module = module
        self._popup_open = True
        lb = self.popup
        lb.delete(0, "end")
        for it in items[:60]:
            lb.insert("end", it)
        lb.selection_clear(0, "end")
        lb.selection_set(0)
        lb.activate(0)
        import tkinter.font as tkfont
        f = tkfont.Font(font=FONT_CONSOLE)
        w = max(f.measure(it) for it in items[:60]) + 26
        rows = min(len(items), 12)
        h = rows * (f.metrics("linespace") + 3) + 4
        bb = self.text.bbox("insert")
        if bb is None:
            self.close_popup()
            return
        x = bb[0]
        y = bb[1] + bb[3]
        tw = self.text.winfo_width()
        th = self.text.winfo_height()
        if x + w > tw:
            x = max(0, tw - w)
        if y + h > th:
            yy = bb[1] - h
            y = yy if yy >= 0 else max(0, th - h)
        lb.place(x=x, y=y, width=w, height=h)
        lb.lift()

    def close_popup(self):
        self._popup_open = False
        self._popup_module = None
        self._popup_items = []
        if getattr(self, "popup", None) is not None:
            self.popup.place_forget()

    def refresh_popup(self):
        line = self.text.index("insert").split(".")[0]
        if self._popup_module:
            prefix = self.text.get("%s.%d" % (line, self._popup_start), "insert")
            if not re.fullmatch(r"\w*", prefix):
                self.close_popup()
                return
            items = [w for w in MODULE_ATTRS.get(self._popup_module, [])
                     if w.lower().startswith(prefix.lower())]
        else:
            prefix, start = self._word_before_cursor()
            if not prefix or start != self._popup_start:
                self.close_popup()
                return
            items = self.completions_for(prefix)
        if not items:
            self.close_popup()
            return
        self._popup_items = items
        lb = self.popup
        lb.delete(0, "end")
        for it in items[:60]:
            lb.insert("end", it)
        lb.selection_clear(0, "end")
        lb.selection_set(0)
        lb.activate(0)

    def _popup_move(self, d):
        lb = self.popup
        n = lb.size()
        if not n:
            return "break"
        sel = lb.curselection()
        i = sel[0] if sel else 0
        i = max(0, min(n - 1, i + d))
        lb.selection_clear(0, "end")
        lb.selection_set(i)
        lb.activate(i)
        lb.see(i)
        return "break"

    def accept_popup(self):
        if not self._popup_open:
            return False
        sel = self.popup.curselection()
        if not sel:
            self.close_popup()
            return False
        word = self.popup.get(sel[0])
        line = self.text.index("insert").split(".")[0]
        self.text.delete("%s.%d" % (line, self._popup_start), "insert")
        self.text.insert("insert", word)
        self.close_popup()
        return True

    # ------------------------------------------------------------------
    #  Клавиши и редактирование
    # ------------------------------------------------------------------
    def _on_modified(self, ev=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if not self.dirty:
                self.dirty = True
                self._update_title()
        self.schedule_highlight()

    def on_key_release(self, ev):
        self._update_cursor_line()
        self._match_bracket()
        self._update_status()
        if self._popup_open:
            self.refresh_popup()
            return
        ch = ev_char(ev)
        if not ch:
            return
        if ch == ".":
            before = self.text.get("insert linestart", "insert")[:-1]
            m = re.search(r"(\w+)$", before)
            mod = m.group(1) if m else ""
            off = self.cur_offset()
            if (mod in MODULE_ATTRS
                    and not self._in_spans(off, self._str_spans, True)
                    and not self._in_spans(off, self._com_spans, True)):
                self.open_popup(self.completions_for("", module=mod),
                                len(before) + 1, module=mod)
            return
        if ch.isalnum() or ch == "_":
            self.maybe_popup()

    def _pair_allowed(self, ch):
        off = self.cur_offset()
        if (self._in_spans(off, self._str_spans, True)
                or self._in_spans(off, self._com_spans, True)):
            return False
        if ch in "\"'":
            prev = self.text.get("insert-1c", "insert")
            if prev and (prev.isalnum() or prev == "_"):
                return False
        return True

    def on_key_press(self, ev):
        ch = ev_char(ev)
        if self._popup_open:
            ks = ev.keysym
            if ks == "Up":
                return self._popup_move(-1)
            if ks == "Down":
                return self._popup_move(1)
            if ch and ch in "({":
                self.accept_popup()
            elif ch and not (ch.isalnum() or ch == "_" or ch == "."):
                self.close_popup()
        if not ch:
            return
        if ch in CLOSERS:
            nxt = self.text.get("insert", "insert+1c")
            if nxt == ch:
                self.text.mark_set("insert", "insert+1c")
                return "break"
        if ch in PAIRS and self._pair_allowed(ch):
            self.text.insert("insert", ch + PAIRS[ch])
            self.text.mark_set("insert", "insert-1c")
            return "break"
        return None

    def on_return(self, ev=None):
        if self._popup_open:
            self.accept_popup()
            return "break"
        t = self.text
        line = t.get("insert linestart", "insert")
        indent = line[:len(line) - len(line.lstrip())]
        code = re.sub(r"#[^\n]*$", "", line.rstrip()).rstrip()
        extra = "    " if code.endswith(":") else ""
        t.insert("insert", "\n" + indent + extra)
        return "break"

    def on_tab(self, ev=None):
        if self._popup_open:
            self.accept_popup()
            return "break"
        col = int(self.text.index("insert").split(".")[1])
        self.text.insert("insert", " " * (4 - col % 4))
        return "break"

    def on_shift_tab(self, ev=None):
        t = self.text
        pre = t.get("insert linestart", "insert")
        sp = len(pre) - len(pre.rstrip(" "))
        k = min(4, sp)
        if k:
            t.delete("insert-%dc" % k, "insert")
        return "break"

    def on_escape(self, ev=None):
        if self._popup_open:
            self.close_popup()
        else:
            self.hide_findbar()
        return "break"

    def on_backspace(self, ev=None):
        if self._popup_open:
            self.close_popup()
            return "break"
        a = self.text.get("insert-1c", "insert")
        b = self.text.get("insert", "insert+1c")
        if a in PAIRS and PAIRS[a] == b:
            self.text.delete("insert-1c", "insert+1c")
            return "break"
        return None

    def on_ctrl_space(self, ev=None):
        self.maybe_popup(force=True)
        return "break"

    def _on_comment_key(self, ev=None):
        self.toggle_comment()
        return "break"

    def toggle_comment(self):
        t = self.text
        try:
            first = t.index("sel.first linestart")
            last = t.index("sel.last")
        except tk.TclError:
            first = t.index("insert linestart")
            last = t.index("insert lineend")
        l1 = int(t.index(first).split(".")[0])
        l2 = int(t.index(last).split(".")[0])
        lines = [t.get("%d.0" % i, "%d.end" % i) for i in range(l1, l2 + 1)]
        nonempty = [ln for ln in lines if ln.strip()]
        all_commented = bool(nonempty) and all(re.match(r"\s*#", ln) for ln in nonempty)
        for i, ln in enumerate(lines, start=l1):
            if not ln.strip():
                continue
            m = re.match(r"(\s*)(# ?)?(.*)$", ln)
            indent, rest = m.group(1), m.group(3)
            new = indent + rest if all_commented else indent + "# " + rest
            t.delete("%d.0" % i, "%d.end" % i)
            t.insert("%d.0" % i, new)
        return "break"

    def insert_snippet(self, text):
        self.text.insert("insert", text)
        self.text.focus_set()

    # ------------------------------------------------------------------
    #  Поиск и переход
    # ------------------------------------------------------------------
    def show_findbar(self):
        self.findbar.grid(row=1, column=0, sticky="ew")
        self.find_entry.focus_set()
        self.find_entry.select_range(0, "end")
        try:
            sel = self.text.get("sel.first", "sel.last")
            if sel and "\n" not in sel:
                self.find_var.set(sel)
                self.find_entry.select_range(0, "end")
        except tk.TclError:
            pass
        return "break"

    def hide_findbar(self):
        self.findbar.grid_remove()
        self.text.focus_set()

    def find_next(self, direction=1):
        needle = self.find_var.get()
        if not needle:
            return
        t = self.text
        if direction < 0:
            pos = t.search(needle, "insert", backwards=True, stopindex="1.0")
            if not pos:
                pos = t.search(needle, "end", backwards=True)
        else:
            pos = t.search(needle, "insert+1c" if t.tag_ranges("sel") else "insert")
            if not pos:
                pos = t.search(needle, "1.0")
        if not pos:
            self._insert_console("не найдено: %s\n" % needle, "sys")
            return
        end = "%s+%dc" % (pos, len(needle))
        t.tag_remove("sel", "1.0", "end")
        t.tag_add("sel", pos, end)
        t.mark_set("insert", pos)
        t.see(pos)

    def goto_line(self):
        from tkinter import simpledialog
        n = simpledialog.askinteger("Перейти к строке", "Номер строки:",
                                    parent=self.root, minvalue=1, maxvalue=1000000)
        if n:
            self.text.mark_set("insert", "%d.0" % n)
            self.text.see("insert")
            self.text.focus_set()
            self._update_cursor_line()
            self._update_status()
        return "break"

    # ------------------------------------------------------------------
    #  Файлы
    # ------------------------------------------------------------------
    def _update_title(self):
        name = os.path.basename(self.path) if self.path else "без имени"
        star = " •" if self.dirty else ""
        self.root.title("%s%s — Deinstall Studio" % (name, star))

    def _ask_save(self):
        if not self.dirty:
            return True
        who = os.path.basename(self.path) if self.path else "новой программе"
        ans = messagebox.askyesnocancel("Deinstall Studio",
                                        "Сохранить изменения в «%s»?" % who)
        if ans is None:
            return False
        if ans:
            return self.save_file()
        return True

    def new_file(self):
        if not self._ask_save():
            return "break"
        self.text.delete("1.0", "end")
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.path = None
        self.dirty = False
        self._update_title()
        self.do_highlight()
        self._update_status()
        return "break"

    def open_file(self):
        if not self._ask_save():
            return "break"
        p = filedialog.askopenfilename(
            title="Открыть скрипт",
            filetypes=[("Deinstall Script", "*.dis"), ("Все файлы", "*.*")],
            initialdir=os.path.dirname(self.path) if self.path else HERE)
        if p:
            self.open_path(p)
        return "break"

    def open_path(self, p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = fh.read()
        except OSError as e:
            messagebox.showerror("Deinstall Studio", "Не удалось открыть файл:\n%s" % e)
            return
        except UnicodeDecodeError:
            messagebox.showerror("Deinstall Studio", "Файл не в кодировке UTF-8")
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", data)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.path = os.path.abspath(p)
        self.dirty = False
        self._update_title()
        self.do_highlight()
        self._update_status()
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")

    def save_file(self, save_as=False):
        p = self.path
        if save_as or not p:
            p = filedialog.asksaveasfilename(
                title="Сохранить скрипт", defaultextension=".dis",
                filetypes=[("Deinstall Script", "*.dis"), ("Все файлы", "*.*")],
                initialfile=os.path.basename(self.path) if self.path else "программа.dis")
            if not p:
                return False
        try:
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(self.text.get("1.0", "end-1c"))
        except OSError as e:
            messagebox.showerror("Deinstall Studio", "Не удалось сохранить файл:\n%s" % e)
            return False
        self.path = os.path.abspath(p)
        self.dirty = False
        self._update_title()
        self._update_status()
        return True

    def _on_save_key(self, ev=None):
        self.save_file()
        return "break"

    def open_examples_dir(self):
        try:
            os.startfile(EXAMPLES)
        except Exception as e:
            messagebox.showerror("Deinstall Studio", "Не удалось открыть папку: %s" % e)

    # ------------------------------------------------------------------
    #  Консоль
    # ------------------------------------------------------------------
    def _insert_console(self, text, tag="out"):
        c = self.console
        c.configure(state="normal")
        c.insert("end", text, tag)
        c.see("end")
        c.configure(state="disabled")

    def clear_console(self):
        c = self.console
        c.configure(state="normal")
        c.delete("1.0", "end")
        c.configure(state="disabled")

    def _send_stdin(self, ev=None):
        line = self.stdin_entry.get()
        self.stdin_entry.delete(0, "end")
        if self.proc is not None and self.proc.poll() is None and self.proc.stdin:
            try:
                self.proc.stdin.write((line + "\n").encode("utf-8"))
                self.proc.stdin.flush()
                self._insert_console("← %s\n" % line, "in")
            except Exception as e:
                self._insert_console("не удалось передать ввод: %s\n" % e, "err")
        else:
            self._insert_console("нет запущенной программы — нажмите F5\n", "sys")
        return "break"

    # ------------------------------------------------------------------
    #  Запуск и сборка
    # ------------------------------------------------------------------
    def _prepare_run(self, parallel=False):
        if not parallel and self.proc is not None and self.proc.poll() is None:
            self._insert_console("уже выполняется другой процесс — нажмите «Стоп»\n", "sys")
            return None
        if self.dirty or not self.path:
            if not self.save_file():
                return None
        return self.path

    def _extra_args(self):
        s = (self.args_var.get() or "").strip()
        if not s:
            return []
        import shlex
        try:
            return shlex.split(s, posix=False)
        except ValueError:
            return s.split()

    def _start_proc(self, cmd, cwd, label):
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=cwd, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=flags)
        except OSError as e:
            self._insert_console("не удалось запустить: %s\n" % e, "err")
            return
        self._proc_label = label
        self._eofs = 0
        self._insert_console("\n[%s] %s\n" % (label, " ".join(cmd)), "sys")
        threading.Thread(target=self._reader,
                         args=(self.proc.stdout, "out", self.proc), daemon=True).start()
        threading.Thread(target=self._reader,
                         args=(self.proc.stderr, "err", self.proc), daemon=True).start()

    def _reader(self, pipe, tag, proc):
        try:
            for line in iter(pipe.readline, b""):
                self.queue.put((tag, line.decode("utf-8", "replace")))
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass
            self.queue.put(("eof", tag))

    def _poll_queue(self):
        try:
            while True:
                tag, data = self.queue.get_nowait()
                if tag == "eof":
                    self._eofs = getattr(self, "_eofs", 0) + 1
                    if self._eofs >= 2 and self.proc is not None:
                        rc = self.proc.wait()
                        label = getattr(self, "_proc_label", "процесс")
                        self.proc = None
                        self._eofs = 0
                        self.queue.put(("done", (label, rc)))
                elif tag == "done":
                    label, rc = data
                    self._insert_console("[%s] завершено, код %d\n" % (label, rc),
                                         "ok" if rc == 0 else "err")
                else:
                    self._insert_console(data, tag)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def stop_proc(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
            self._insert_console("[остановлено пользователем]\n", "sys")

    @staticmethod
    def _window_cmd(bat, script, args):
        """Команда для запуска скрипта в отдельном окне через dis.bat/disj.bat.

        cmd /k держит окно открытым и после завершения скрипта —
        закрывается только по команде exit. Слово call нужно, чтобы
        кавычки вокруг пути с пробелами не срезались самим cmd.
        """
        return ["cmd", "/k", "call", bat, script] + list(args)

    def _run_in_window(self, bat, label):
        p = self._prepare_run(parallel=True)
        if not p:
            return
        if not os.path.isfile(bat):
            self._insert_console("не найден %s рядом с IDE\n"
                                 % os.path.basename(bat), "err")
            return
        cmd = self._window_cmd(bat, p, self._extra_args())
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            subprocess.Popen(cmd, cwd=os.path.dirname(p) or HERE,
                             creationflags=flags)
        except OSError as e:
            self._insert_console("не удалось открыть окно: %s\n" % e, "err")
            return
        self._insert_console("[%s] открыто отдельное окно → %s\n"
                             "[%s] окно останется открытым и после завершения — "
                             "закройте его командой exit\n"
                             % (label, os.path.basename(bat), label), "sys")

    def run_python(self):
        self._run_in_window(DIS_BAT, "Python")

    def run_java(self):
        self._run_in_window(DISJ_BAT, "Java")

    def run_python_inside(self):
        p = self._prepare_run()
        if not p:
            return
        if not os.path.isfile(DIS_PY):
            self._insert_console("не найден deinstall.py рядом с IDE\n", "err")
            return
        self._start_proc([sys.executable, "-u", DIS_PY, p] + self._extra_args(),
                         os.path.dirname(p), "Python")

    def run_java_inside(self):
        p = self._prepare_run()
        if not p:
            return
        if not os.path.isfile(JAVA_CLASS):
            self._insert_console(
                "нет DeinstallScript.class — соберите: javac -encoding UTF-8 DeinstallScript.java\n",
                "err")
            return
        self._start_proc(["java", "-Dfile.encoding=UTF-8", "DeinstallScript", p]
                         + self._extra_args(), HERE, "Java")

    def check_syntax(self):
        if self.dirty or not self.path:
            if not self.save_file():
                return
        if not os.path.isfile(DIS_PY):
            self._insert_console("не найден deinstall.py рядом с IDE\n", "err")
            return
        src = self.text.get("1.0", "end-1c")
        try:
            import deinstall as dis
            dis.parse(src)
        except Exception as e:
            msg = getattr(e, "message", str(e))
            line = getattr(e, "line", None)
            self._insert_console("✗ ошибка%s: %s\n"
                                 % ((" (строка %s)" % line) if line else "", msg),
                                 "err")
            if line:
                self.text.mark_set("insert", "%d.0" % line)
                self.text.see("insert")
                self._update_cursor_line()
            return
        self._insert_console("✓ синтаксис в порядке: %s\n"
                             % os.path.basename(self.path), "ok")

    def compile_exe(self):
        if self.proc is not None and self.proc.poll() is None:
            self._insert_console("дождитесь завершения программы или нажмите «Стоп»\n", "sys")
            return
        if not os.path.isfile(DIS_PY):
            self._insert_console("не найден deinstall.py рядом с IDE — C-бэкенд недоступен\n", "err")
            return
        if self.dirty or not self.path:
            if not self.save_file():
                return
        out_exe = os.path.splitext(self.path)[0] + ".exe"
        self._insert_console("\n[Сборка] %s → %s\n"
                             % (os.path.basename(self.path), os.path.basename(out_exe)),
                             "sys")
        src = self.text.get("1.0", "end-1c")
        threading.Thread(target=self._compile_worker, args=(src, out_exe),
                         daemon=True).start()

    def _compile_worker(self, src, out_exe):
        q = self.queue
        try:
            import deinstall as dis
        except Exception as e:
            q.put(("err", "[Сборка] не удалось импортировать deinstall.py: %s\n" % e))
            return
        try:
            stmts = dis.parse(src)
        except Exception as e:
            msg = getattr(e, "message", str(e))
            line = getattr(e, "line", None)
            q.put(("err", "[Сборка] ошибка%s: %s\n"
                   % ((" (строка %s)" % line) if line else "", msg)))
            return
        try:
            code = dis.CGen(stmts).generate()
        except dis.CUnsupported as u:
            q.put(("err", "[Сборка] этот скрипт не переводится в C: %s\n" % u.reason))
            q.put(("sys", "[Сборка] подсказка: запустите через F5 — результат будет тем же.\n"))
            return
        except Exception as e:
            q.put(("err", "[Сборка] ошибка генерации C: %s\n" % e))
            return
        cc = dis.find_c_compiler()
        if cc is None:
            q.put(("err", "[Сборка] C-компилятор не найден (gcc/clang/cl/tcc/zig)\n"))
            return
        kind, base = cc
        import tempfile
        import shutil
        tmpdir = tempfile.mkdtemp(prefix="dis_ide_build_")
        cpath = os.path.join(tmpdir, "prog.c")
        cexe = os.path.join(tmpdir, "prog_build.exe" if os.name == "nt" else "prog_build")
        try:
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write(code)
            if kind == "zig":
                cmd = base + ["cc", "-O2", "-o", cexe, cpath]
            elif kind == "tcc":
                cmd = base + ["-o", cexe, cpath]
            elif kind == "cl":
                cmd = base + ["/nologo", "/O2", "/utf-8", cpath, "/Fe:" + cexe]
            else:
                cmd = base + ["-O2", "-o", cexe, cpath, "-lm"]
            q.put(("sys", "[Сборка] %s\n" % " ".join(cmd)))
            pr = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True,
                                timeout=180)
            if pr.returncode != 0:
                err = (pr.stderr or pr.stdout or "").strip()
                q.put(("err", "[Сборка] компиляция не удалась:\n%s\n" % err[:2000]))
                return
            shutil.copyfile(cexe, out_exe)
            size_kb = os.path.getsize(out_exe) / 1024.0
            q.put(("ok", "[Сборка] готово: %s (%.0f КБ) — нативный exe, Python не требуется\n"
                   % (out_exe, size_kb)))
        except Exception as e:
            q.put(("err", "[Сборка] ошибка: %s\n" % e))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    #  Диалоги и закрытие
    # ------------------------------------------------------------------
    def show_about(self):
        messagebox.showinfo(
            "О программе",
            "Deinstall Studio %s\n\n"
            "Среда разработки для языка Deinstall Script.\n\n"
            "• подсветка синтаксиса и автодополнение;\n"
            "• запуск в отдельном окне через dis.bat / disj.bat\n"
            "  (окно ждёт команду exit — результат и ошибки видны);\n"
            "• сборка в нативный .exe через C-бэкенд superfast.\n\n"
            "Интерпретаторы: deinstall.py, DeinstallScript.java" % VERSION)

    def show_hotkeys(self):
        messagebox.showinfo(
            "Горячие клавиши",
            "F5 — запустить в отдельном окне (через dis.bat)\n"
            "Ctrl+F5 — Java в отдельном окне (через disj.bat)\n"
            "F6 — проверить синтаксис\n"
            "F7 — собрать .exe (C-бэкенд)\n"
            "(окно ждёт команду exit — результат и ошибки остаются на экране)\n\n"
            "Ctrl+Space — автодополнение (при наборе появляется само)\n"
            "Tab / Shift+Tab — отступ / убрать отступ\n"
            "Enter — принять подсказку, иначе перенос строки с отступом\n"
            "Esc — закрыть подсказку или поиск\n\n"
            "Ctrl+N / Ctrl+O / Ctrl+S — новый / открыть / сохранить\n"
            "Ctrl+F — поиск, Ctrl+G — переход к строке\n"
            "Ctrl+/ — закомментировать / раскомментировать\n"
            "Ctrl+Z / Ctrl+Y — отменить / вернуть")

    def on_close(self):
        if self.proc is not None and self.proc.poll() is None:
            if not messagebox.askyesno("Deinstall Studio",
                                       "Программа ещё выполняется. Закрыть?"):
                return
            self.stop_proc()
        if self._ask_save():
            self.root.destroy()


# ===========================================================================
#  Самопроверка и запуск
# ===========================================================================

SELFTEST_SRC = '''func удвоить(n):
    ret n * 2

i = 0
loop i in range(3):
    println{удвоить(i)}

x = f"значение {i}"
y = true
z = 3.14
superfast.disable

# проверка подсветки
'''


def selftest():
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            ok = False

    root = tk.Tk()
    root.withdraw()
    app = App(root)
    app.text.delete("1.0", "end")
    app.text.insert("1.0", SELFTEST_SRC)
    app.do_highlight()
    t = app.text
    check("подсветка: ключевые слова", len(t.tag_ranges("kw")) > 0)
    check("подсветка: строки", len(t.tag_ranges("str")) > 0)
    check("подсветка: числа", len(t.tag_ranges("num")) > 0)
    check("подсветка: комментарии", len(t.tag_ranges("comment")) > 0)
    check("подсветка: имена функций (func)", len(t.tag_ranges("func")) > 0)
    check("подсветка: директива superfast", len(t.tag_ranges("directive")) > 0)
    check("подсветка: константы", len(t.tag_ranges("const")) > 0)

    comps = app.completions_for("pri")
    check("автодополнение: pri → print/println",
          "print" in comps and "println" in comps)
    comps = app.completions_for("")
    check("автодополнение: слова из скрипта (удвоить)", "удвоить" in comps)
    check("автодополнение: модули (math)", "math" in comps)
    comps = app.completions_for("", module="math")
    check("автодополнение: math.sqrt", "sqrt" in comps)

    check("dis.bat рядом с IDE", os.path.isfile(DIS_BAT))
    check("disj.bat рядом с IDE", os.path.isfile(DISJ_BAT))
    cmd = App._window_cmd(DIS_BAT, r"C:\путь с пробелом\тест.dis", ["--x", "1"])
    check("команда окна: cmd /k call dis.bat скрипт аргументы",
          cmd == ["cmd", "/k", "call", DIS_BAT, r"C:\путь с пробелом\тест.dis",
                  "--x", "1"])

    tmpf = os.path.join(tempfile.gettempdir(), "dis_ide_selftest.dis")
    with open(tmpf, "w", encoding="utf-8") as fh:
        fh.write('println{"IDE-тест"}\n')
    r = subprocess.run([sys.executable, "-u", DIS_PY, tmpf],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1"))
    check("запуск через интерпретатор (deinstall.py)",
          r.stdout.strip() == "IDE-тест")

    try:
        import deinstall as dis
        check("C-бэкенд доступен",
              hasattr(dis, "CGen") and hasattr(dis, "find_c_compiler"))
        code = dis.CGen(dis.parse('println{1 + 1}\n')).generate()
        check("C-генерация маленького скрипта", "printf" in code or "fputs" in code)
        code = dis.CGen(dis.parse('x = int(input("? "))\nprintln{x}\n')).generate()
        check("C-бэкенд: input() и int() от строки",
              "dis_input" in code and "dis_s2i" in code)
    except Exception as e:
        check("C-бэкенд доступен (%s)" % e, False)

    root.destroy()
    print("ИТОГ: " + ("всё хорошо" if ok else "есть ошибки"))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        sys.exit(selftest())
    if "--version" in args:
        print("Deinstall Studio " + VERSION)
        return
    path = None
    for a in args:
        if not a.startswith("-"):
            path = a
            break
    root = tk.Tk()
    App(root, path)
    root.mainloop()


if __name__ == "__main__":
    main()
