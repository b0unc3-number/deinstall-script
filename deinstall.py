#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deinstall Script (расширение .dis) — интерпретатор на Python.
Язык похож на Python, но с немного изменённым синтаксисом:
  func / elseif / loop / ret / true-false-null / try-catch / throw
Всё, что импортируется через import — обычные библиотеки Python.
Запуск:  python deinstall.py script.dis [аргументы...]
         python deinstall.py            (REPL)
"""
import builtins as _bi
import importlib
import sys

VERSION = "0.1.0"

# ============================================================ Ошибки

class DisError(Exception):
    def __init__(self, message, line=0):
        super().__init__(message)
        self.message = message
        self.line = line

class DisSyntaxError(DisError):
    pass

class DisRuntimeError(DisError):
    pass

# ============================================================ Лексер

KEYWORDS = {
    "func", "if", "elseif", "else", "while", "loop", "in", "ret", "break",
    "continue", "try", "catch", "throw", "import", "as", "and", "or", "not",
    "lambda", "pass", "true", "false", "null", "True", "False", "None", "var",
}
OPS3 = ["**=", "//="]
OPS2 = ["==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=", "**", "//"]
OPS1 = ["+", "-", "*", "/", "%", "=", "<", ">", "(", ")", "[", "]", "{", "}", ",", ":", "."]

class Token:
    __slots__ = ("kind", "value", "line", "fstr", "raw")
    def __init__(self, kind, value, line, fstr=False, raw=""):
        self.kind = kind      # NAME/NUM/STR/NEWLINE/INDENT/DEDENT/EOF/ключевое/оператор
        self.value = value
        self.line = line
        self.fstr = fstr
        self.raw = raw
    def __str__(self):
        return "%s(%r)@%d" % (self.kind, self.value, self.line)

def _unescape(s, line):
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c); i += 1; continue
        i += 1
        if i >= n:
            raise DisSyntaxError("лишний обратный слэш в строке", line)
        e = s[i]; i += 1
        if e == "n": out.append("\n")
        elif e == "t": out.append("\t")
        elif e == "r": out.append("\r")
        elif e == "0": out.append("\0")
        elif e == "\\": out.append("\\")
        elif e == "'": out.append("'")
        elif e == '"': out.append('"')
        elif e == "u" and i < n and s[i] == "{":
            j = s.find("}", i)
            if j < 0: raise DisSyntaxError("незакрытая \\u{...}", line)
            out.append(chr(int(s[i+1:j], 16))); i = j + 1
        else:
            out.append("\\" + e)
    return "".join(out)

def lex(src):
    toks = []
    i, n, line = 0, len(src), 1
    bracket = 0
    at_bol = True
    indents = [0]

    def err(msg, ln):
        raise DisSyntaxError(msg, ln)

    while i < n:
        # ---- начало строки: отступы, пустые и комментарии ----
        if at_bol and bracket == 0:
            j, col = i, 0
            while j < n and src[j] in " \t":
                col = (col // 4 + 1) * 4 if src[j] == "\t" else col + 1
                j += 1
            if j < n and src[j] == "#":
                while j < n and src[j] not in "\r\n":
                    j += 1
            if j < n and src[j] in "\r\n":
                if src[j] == "\r" and j + 1 < n and src[j+1] == "\n":
                    j += 2
                else:
                    j += 1
                line += 1
                i = j          # пустая/комментарийная строка — без NEWLINE
                continue
            if j >= n:
                i = n
                break
            if col > indents[-1]:
                indents.append(col)
                toks.append(Token("INDENT", col, line))
            elif col < indents[-1]:
                while indents and col < indents[-1]:
                    indents.pop()
                    toks.append(Token("DEDENT", col, line))
                if indents[-1] != col:
                    err("неправильные отступы (табуляция и пробелы не совпадают)", line)
            at_bol = False
            i = j
            continue

        c = src[i]
        if c in " \t":
            i += 1; continue
        if c == "\n":
            line += 1
            if bracket == 0:
                toks.append(Token("NEWLINE", None, line - 1))
                at_bol = True
            i += 1; continue
        if c == "\r":
            i += 1; continue
        if c == "#":
            while i < n and src[i] not in "\r\n":
                i += 1
            continue
        # ---- числа ----
        if c.isdigit():
            start = i
            if c == "0" and i + 1 < n and src[i+1] in "xX":
                i += 2
                while i < n and src[i] in "0123456789abcdefABCDEF":
                    i += 1
                toks.append(Token("NUM", int(src[start:i], 16), line)); continue
            if c == "0" and i + 1 < n and src[i+1] in "bB":
                i += 2
                while i < n and src[i] in "01":
                    i += 1
                toks.append(Token("NUM", int(src[start:i], 2), line)); continue
            isf = False
            while i < n and src[i].isdigit():
                i += 1
            if i + 1 < n and src[i] == "." and src[i+1].isdigit():
                isf = True; i += 1
                while i < n and src[i].isdigit():
                    i += 1
            if i < n and src[i] in "eE":
                save = i; i += 1
                if i < n and src[i] in "+-":
                    i += 1
                if i < n and src[i].isdigit():
                    while i < n and src[i].isdigit():
                        i += 1
                    isf = True
                else:
                    i = save
            text = src[start:i]
            toks.append(Token("NUM", float(text) if isf else int(text), line)); continue
        # ---- строки (в т.ч. f-строки и многострочные) ----
        isf = False
        if c in "fF" and i + 1 < n and src[i+1] in "\"'":
            isf = True; i += 1; c = src[i]
        elif c in "fF" and i + 3 < n and src[i+1] == src[i+2] and src[i+1] == src[i+3] and src[i+1] in "\"'":
            isf = True; i += 1; c = src[i]
        if c in "\"'":
            triple = src[i:i+3] == c * 3
            delim = c * 3 if triple else c
            i += len(delim)
            start = i
            while True:
                if i >= n:
                    err("незакрытая строка", line)
                ch = src[i]
                if ch == "\\":
                    i += 2; continue
                if not triple and ch == "\n":
                    err("незакрытая строка", line)
                if src.startswith(delim, i):
                    break
                i += 1
            raw = src[start:i]
            i += len(delim)
            if triple:
                line += raw.count("\n")
            toks.append(Token("STR", None, line, isf, raw)); continue
        # ---- имена и ключевые слова ----
        if c.isalpha() or c == "_":
            start = i
            while i < n and (src[i].isalnum() or src[i] == "_"):
                i += 1
            w = src[start:i]
            toks.append(Token(w if w in KEYWORDS else "NAME", w, line)); continue
        # ---- операторы (сначала более длинные) ----
        hit = False
        for op in OPS3 + OPS2 + OPS1:
            if src.startswith(op, i):
                toks.append(Token(op, op, line))
                i += len(op)
                if op in "([{":
                    bracket += 1
                elif op in ")]}":
                    bracket -= 1
                    if bracket < 0:
                        err("лишняя скобка '%s'" % op, line)
                hit = True
                break
        if not hit:
            err("неизвестный символ '%s'" % c, line)
        continue

    if bracket > 0:
        raise DisSyntaxError("не закрыта скобка", line)
    while len(indents) > 1:
        indents.pop()
        toks.append(Token("DEDENT", 0, line))
    if not toks or toks[-1].kind != "NEWLINE":
        toks.append(Token("NEWLINE", None, line))
    toks.append(Token("EOF", None, line))
    return toks

# ============================================================ AST

class Node:
    __slots__ = ()

def _n(cls, slots):
    cls.__slots__ = ("line",) + slots
    def __init__(self, *a, **kw):
        self.line = kw.pop("line", 0)
        for name, val in zip(self.__slots__[1:], a):
            setattr(self, name, val)
    cls.__init__ = __init__
    return cls

class NNum(Node):     pass
class NStr(Node):     pass
class NFStr(Node):    pass
class NLit(Node):     pass
class NName(Node):    pass
class NList(Node):    pass
class NDict(Node):    pass
class NLambda(Node):  pass
class NBin(Node):     pass
class NUn(Node):      pass
class NCmp(Node):     pass
class NCall(Node):    pass
class NIndex(Node):   pass
class NSlice(Node):   pass
class NAttr(Node):    pass
class NAssign(Node):  pass
class NAug(Node):     pass
class NExpr(Node):    pass
class NIf(Node):      pass
class NWhile(Node):   pass
class NLoop(Node):    pass
class NFunc(Node):    pass
class NRet(Node):     pass
class NBreak(Node):   pass
class NCont(Node):    pass
class NThrow(Node):   pass
class NTry(Node):     pass
class NImport(Node):  pass
class NPass(Node):    pass
class NPy2Print(Node): pass   # pythontwo.print "а", "б",   (как в Python 2)
class NSuperfast(Node): pass  # superfast.enable / superfast.disable (C-ускорение)

_n(NNum, ("value",))
_n(NStr, ("value",))
_n(NFStr, ("parts",))          # [(литерал, узел|None, спека|None)]
_n(NLit, ("value",))
_n(NName, ("id",))
_n(NList, ("items",))
_n(NDict, ("pairs",))
_n(NLambda, ("params", "rest", "kwrest", "body"))
_n(NBin, ("op", "left", "right"))
_n(NUn, ("op", "operand"))
_n(NCmp, ("left", "ops", "rights"))
_n(NCall, ("func", "args", "kwargs"))   # args: [(pos|star, узел)]; kwargs: [(kw|dstar, имя, узел)]
_n(NIndex, ("obj", "index"))
_n(NSlice, ("obj", "start", "stop", "step"))
_n(NAttr, ("obj", "name"))
_n(NAssign, ("targets", "values"))
_n(NAug, ("target", "op", "value"))
_n(NExpr, ("value",))
_n(NIf, ("branches", "orelse"))
_n(NWhile, ("cond", "body"))
_n(NLoop, ("targets", "iter", "body"))
_n(NFunc, ("name", "params", "rest", "kwrest", "body"))
_n(NRet, ("value",))
_n(NBreak, ())
_n(NCont, ())
_n(NThrow, ("value",))
_n(NTry, ("body", "name", "cbody"))
_n(NImport, ("module", "alias"))
_n(NPass, ())
_n(NPy2Print, ("values", "newline"))
_n(NSuperfast, ("enabled",))

# ============================================================ Парсер

AUGOPS = ("+=", "-=", "*=", "/=", "//=", "%=", "**=")

class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self, k=0):
        p = min(self.pos + k, len(self.toks) - 1)
        return self.toks[p]

    def next(self):
        t = self.toks[self.pos]
        if t.kind != "EOF":
            self.pos += 1
        return t

    def check(self, kind):
        return self.peek().kind == kind

    def accept(self, kind):
        if self.check(kind):
            self.next()
            return True
        return False

    def expect(self, kind, msg=None):
        if self.check(kind):
            return self.next()
        t = self.peek()
        raise DisSyntaxError(msg or "ожидалось '%s', получено '%s'" % (kind, t.kind), t.line)

    def parse_program(self):
        stmts = []
        while True:
            while self.accept("NEWLINE"):
                pass
            if self.check("EOF"):
                break
            stmts.append(self.parse_stmt())
        return stmts

    def parse_block(self):
        self.expect(":")
        t = self.peek()
        if t.kind == "NEWLINE":
            self.next()
            self.expect("INDENT", "ожидался отступ после ':'")
            body = []
            while True:
                while self.accept("NEWLINE"):
                    pass
                if self.check("DEDENT") or self.check("EOF"):
                    break
                body.append(self.parse_stmt())
            self.expect("DEDENT")
            if not body:
                raise DisSyntaxError("пустой блок (используйте pass)", t.line)
            return body
        return [self.parse_stmt()]     # однострочный блок

    def parse_stmt(self):
        t = self.peek()
        k = t.kind
        if k == "var":
            self.next()
            node = self.parse_simple()
            if not isinstance(node, NAssign):
                raise DisSyntaxError("после 'var' ожидается присваивание: var x = ...", t.line)
            return node
        if k == "func":
            self.next()
            name = self.expect("NAME", "ожидалось имя функции").value
            self.expect("(")
            params, rest, kwrest = [], None, None
            if not self.check(")"):
                while True:
                    if self.accept("**"):
                        kwrest = self.expect("NAME").value
                    elif self.accept("*"):
                        rest = self.expect("NAME").value
                    else:
                        pname = self.expect("NAME").value
                        default = None
                        if self.accept("="):
                            default = self.parse_or()
                        params.append((pname, default))
                    if not self.accept(","):
                        break
            self.expect(")")
            return NFunc(name, params, rest, kwrest, self.parse_block(), line=t.line)
        if k == "if":
            branches = []
            self.next()
            cond = self.parse_or()
            branches.append((cond, self.parse_block()))
            orelse = []
            while self.accept("elseif"):
                c = self.parse_or()
                branches.append((c, self.parse_block()))
            if self.accept("else"):
                orelse = self.parse_block()
            return NIf(branches, orelse, line=t.line)
        if k == "while":
            self.next()
            cond = self.parse_or()
            return NWhile(cond, self.parse_block(), line=t.line)
        if k == "loop":
            self.next()
            targets = []
            if self.accept("("):
                targets.append(self.expect("NAME").value)
                while self.accept(","):
                    targets.append(self.expect("NAME").value)
                self.expect(")")
            else:
                targets.append(self.expect("NAME", "ожидалась переменная цикла").value)
                while self.check(","):
                    self.next()
                    targets.append(self.expect("NAME").value)
            self.expect("in", "ожидалось 'in'")
            it = self.parse_or()
            return NLoop(targets, it, self.parse_block(), line=t.line)
        if k == "try":
            self.next()
            body = self.parse_block()
            self.expect("catch", "ожидалось 'catch'")
            name = self.expect("NAME").value if self.check("NAME") else None
            return NTry(body, name, self.parse_block(), line=t.line)
        if k == "ret":
            self.next()
            if self.check("NEWLINE") or self.check("DEDENT") or self.check("EOF"):
                return NRet(None, line=t.line)
            vals = [self.parse_or()]
            while self.check(","):
                self.next()
                vals.append(self.parse_or())
            return NRet(vals[0] if len(vals) == 1 else NList(vals, line=t.line), line=t.line)
        if k == "throw":
            self.next()
            return NThrow(self.parse_or(), line=t.line)
        if k == "break":
            self.next()
            return NBreak(line=t.line)
        if k == "continue":
            self.next()
            return NCont(line=t.line)
        if k == "pass":
            self.next()
            return NPass(line=t.line)
        if k == "import":
            self.next()
            parts = [self.expect("NAME").value]
            while self.check("."):
                self.next()
                parts.append(self.expect("NAME").value)
            alias = None
            if self.accept("as"):
                alias = self.expect("NAME").value
            return NImport(".".join(parts), alias, line=t.line)
        if k == "NAME" and t.value == "superfast" and self.peek(1).kind == "." \
                and self.peek(2).kind == "NAME" and self.peek(2).value in ("enable", "disable") \
                and self.peek(3).kind in ("NEWLINE", "DEDENT", "EOF"):
            # директива C-ускорения: superfast.enable / superfast.disable
            self.next(); self.next()
            mode = self.next().value
            return NSuperfast(mode == "enable", line=t.line)
        if k == "NAME" and t.value == "pythontwo" and self.peek(1).kind == "." \
                and self.peek(2).kind == "NAME" and self.peek(2).value == "print" \
                and self.peek(3).kind not in ("(", "{"):
            # печать в стиле Python 2: pythontwo.print "а", "б",
            self.next(); self.next(); self.next()
            values = []
            newline = True
            if not (self.check("NEWLINE") or self.check("DEDENT") or self.check("EOF")):
                values.append(self.parse_or())
                while self.check(","):
                    self.next()
                    if self.check("NEWLINE") or self.check("DEDENT") or self.check("EOF"):
                        newline = False
                        break
                    values.append(self.parse_or())
            return NPy2Print(values, newline, line=t.line)
        return self.parse_simple()

    def parse_simple(self):
        first = self.parse_or()
        exprs = [first]
        while self.check(","):
            self.next()
            exprs.append(self.parse_or())
        aug = None
        for op in AUGOPS:
            if self.check(op):
                aug = op
                break
        if aug:
            self.next()
            if len(exprs) != 1 or not isinstance(exprs[0], (NName, NIndex, NAttr)):
                raise DisSyntaxError("нельзя использовать '%s' с таким выражением" % aug, self.peek().line)
            return NAug(exprs[0], aug, self.parse_or(), line=exprs[0].line)
        if self.accept("="):
            values = [self.parse_or()]
            while self.check(","):
                self.next()
                values.append(self.parse_or())
            for t2 in exprs:
                if not isinstance(t2, (NName, NIndex, NAttr)):
                    raise DisSyntaxError("нельзя присвоить этому выражению", t2.line)
            return NAssign(exprs, values, line=exprs[0].line)
        if len(exprs) == 1:
            return NExpr(first, line=first.line)
        return NExpr(NList(exprs, line=first.line), line=first.line)

    def parse_or(self):
        left = self.parse_and()
        while self.check("or"):
            line = self.next().line
            left = NBin("or", left, self.parse_and(), line=line)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.check("and"):
            line = self.next().line
            left = NBin("and", left, self.parse_not(), line=line)
        return left

    def parse_not(self):
        if self.check("not"):
            line = self.next().line
            return NUn("not", self.parse_not(), line=line)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_add()
        ops, rights = [], []
        while True:
            t = self.peek()
            if t.kind in ("==", "!=", "<", "<=", ">", ">="):
                self.next(); ops.append(t.kind); rights.append(self.parse_add())
            elif t.kind == "in":
                self.next(); ops.append("in"); rights.append(self.parse_add())
            elif t.kind == "not" and self.peek(1).kind == "in":
                self.next(); self.next(); ops.append("not in"); rights.append(self.parse_add())
            else:
                break
        if not ops:
            return left
        return NCmp(left, ops, rights, line=left.line)

    def parse_add(self):
        left = self.parse_mul()
        while self.peek().kind in ("+", "-"):
            op = self.next()
            left = NBin(op.kind, left, self.parse_mul(), line=op.line)
        return left

    def parse_mul(self):
        left = self.parse_unary()
        while self.peek().kind in ("*", "/", "//", "%"):
            op = self.next()
            left = NBin(op.kind, left, self.parse_unary(), line=op.line)
        return left

    def parse_unary(self):
        if self.peek().kind in ("-", "+"):
            op = self.next()
            return NUn(op.kind, self.parse_unary(), line=op.line)
        return self.parse_power()

    def parse_power(self):
        base = self.parse_postfix()
        if self.accept("**"):
            return NBin("**", base, self.parse_unary(), line=base.line)
        return base

    def parse_postfix(self):
        node = self.parse_atom()
        while True:
            if self.check("("):
                line = self.next().line
                args, kwargs = self.parse_call_args()
                self.expect(")")
                node = NCall(node, args, kwargs, line=line)
            elif self.check("{"):
                # фирменный синтаксис: вызов функции через фигурные скобки
                line = self.next().line
                args, kwargs = self.parse_call_args()
                self.expect("}")
                node = NCall(node, args, kwargs, line=line)
            elif self.check("["):
                line = self.next().line
                first = None
                if not self.check(":"):
                    first = self.parse_or()
                if self.accept(":"):
                    stop = None
                    if not self.check("]") and not self.check(":"):
                        stop = self.parse_or()
                    step = None
                    if self.accept(":"):
                        if not self.check("]"):
                            step = self.parse_or()
                    self.expect("]")
                    node = NSlice(node, first, stop, step, line=line)
                else:
                    self.expect("]")
                    node = NIndex(node, first, line=line)
            elif self.check("."):
                line = self.next().line
                name = self.expect("NAME", "ожидалось имя атрибута").value
                node = NAttr(node, name, line=line)
            else:
                return node

    def parse_call_args(self):
        """Аргументы вызова: (a, b, key=val, *list, dict) — одинаково для () и {}."""
        args, kwargs = [], []
        if self.check(")") or self.check("}"):
            return args, kwargs
        while True:
            if self.accept("**"):
                kwargs.append(("dstar", "", self.parse_or()))
            elif self.accept("*"):
                args.append(("star", self.parse_or()))
            else:
                e = self.parse_or()
                if self.check("=") and isinstance(e, NName):
                    self.next()
                    kwargs.append(("kw", e.id, self.parse_or()))
                else:
                    args.append(("pos", e))
            if not self.accept(","):
                break
        return args, kwargs

    def parse_atom(self):
        t = self.peek()
        k = t.kind
        if k == "NUM":
            self.next()
            return NNum(t.value, line=t.line)
        if k == "STR":
            self.next()
            if t.fstr:
                return NFStr(self.parse_fstr(t), line=t.line)
            return NStr(_unescape(t.raw, t.line), line=t.line)
        if k in ("true", "True"):
            self.next(); return NLit(True, line=t.line)
        if k in ("false", "False"):
            self.next(); return NLit(False, line=t.line)
        if k in ("null", "None"):
            self.next(); return NLit(None, line=t.line)
        if k == "lambda":
            self.next()
            params, rest, kwrest = [], None, None
            if not self.check(":"):
                while True:
                    if self.accept("**"):
                        kwrest = self.expect("NAME").value
                    elif self.accept("*"):
                        rest = self.expect("NAME").value
                    else:
                        params.append((self.expect("NAME").value, None))
                    if not self.accept(","):
                        break
            self.expect(":")
            return NLambda(params, rest, kwrest, self.parse_or(), line=t.line)
        if k == "NAME":
            self.next()
            return NName(t.value, line=t.line)
        if k == "(":
            self.next()
            items = []
            if not self.check(")"):
                items.append(self.parse_or())
                while self.accept(","):
                    if self.check(")"):
                        break
                    items.append(self.parse_or())
            self.expect(")")
            if len(items) == 1:
                return items[0]
            return NList(items, line=t.line)     # кортежи в Deinstall Script — списки
        if k == "[":
            self.next()
            items = []
            if not self.check("]"):
                items.append(self.parse_or())
                while self.accept(","):
                    if self.check("]"):
                        break
                    items.append(self.parse_or())
            self.expect("]")
            return NList(items, line=t.line)
        if k == "{":
            self.next()
            pairs = []
            if not self.check("}"):
                key = self.parse_or()
                self.expect(":")
                pairs.append((key, self.parse_or()))
                while self.accept(","):
                    if self.check("}"):
                        break
                    key = self.parse_or()
                    self.expect(":")
                    pairs.append((key, self.parse_or()))
            self.expect("}")
            return NDict(pairs, line=t.line)
        raise DisSyntaxError("неожиданный токен '%s'" % k, t.line)

    def parse_fstr(self, tok):
        raw, parts, i, buf = tok.raw, [], 0, ""
        while i < len(raw):
            c = raw[i]
            if c == "{":
                if raw[i+1:i+2] == "{":
                    buf += "{"; i += 2; continue
                depth, j, instr = 0, i + 1, None
                while j < len(raw):
                    ch = raw[j]
                    if instr:
                        if ch == "\\":
                            j += 2; continue
                        if ch == instr:
                            instr = None
                    elif ch in "\"'":
                        instr = ch
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        if depth == 0:
                            break
                        depth -= 1
                    j += 1
                if j >= len(raw):
                    raise DisSyntaxError("незакрытая '{' в f-строке", tok.line)
                inner = raw[i+1:j]
                expr_src, spec = inner, None
                depth, instr, sp = 0, None, -1
                for p, ch in enumerate(inner):
                    if instr:
                        if ch == "\\":
                            continue
                        if ch == instr:
                            instr = None
                    elif ch in "\"'":
                        instr = ch
                    elif ch in "([{":
                        depth += 1
                    elif ch in ")]}":
                        depth -= 1
                    elif ch == ":" and depth == 0:
                        sp = p
                        break
                if sp >= 0:
                    expr_src, spec = inner[:sp], inner[sp+1:]
                if not expr_src.strip():
                    raise DisSyntaxError("пустые фигурные скобки в f-строке", tok.line)
                node = parse_expr_fragment(expr_src, tok.line)
                parts.append((buf, node, spec))
                buf = ""
                i = j + 1
            elif c == "}":
                if raw[i+1:i+2] == "}":
                    buf += "}"; i += 2; continue
                raise DisSyntaxError("непарная '}' в f-строке", tok.line)
            else:
                buf += c
                i += 1
        parts.append((buf, None, None))
        return parts

def parse_expr_fragment(src, line):
    toks = lex(src)
    p = Parser(toks)
    node = p.parse_or()
    while p.check("NEWLINE"):
        p.next()
    if not p.check("EOF"):
        raise DisSyntaxError("лишний код внутри фигурных скобок f-строки", line)
    return node

def parse(source):
    return Parser(lex(source)).parse_program()

# ============================================================ Исполнитель

class Env:
    __slots__ = ("vars", "parent")
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def lookup(self, name):
        e = self
        while e is not None:
            v = e.vars.get(name)
            if v is not None or name in e.vars:
                return v
            e = e.parent
        b = getattr(_bi, name, _MISSING)
        if b is not _MISSING:
            return b
        raise DisRuntimeError("неизвестная переменная '%s'" % name)

    def assign(self, name, value):
        e = self
        while e is not None:
            if name in e.vars:
                e.vars[name] = value
                return
            e = e.parent
        self.vars[name] = value

    def define(self, name, value):
        self.vars[name] = value

_MISSING = object()

class FuncVal:
    __slots__ = ("name", "params", "rest", "kwrest", "body", "env", "line")
    def __init__(self, node, env):
        self.name = node.name
        self.params = []
        for pname, default in node.params:
            self.params.append((pname, _EVAL(default, env) if default is not None else _MISSING))
        self.rest = node.rest
        self.kwrest = node.kwrest
        self.body = node.body
        self.env = env
        self.line = node.line
    def __str__(self):
        return "<func %s>" % self.name

    def __call__(self, *args, **kwargs):
        ip = Interpreter._current
        if ip is None:
            raise DisRuntimeError("нет активного интерпретатора", self.line)
        return ip.call_user(self, list(args), dict(kwargs), self.line)

class LambdaVal:
    __slots__ = ("params", "rest", "kwrest", "body", "env", "line")
    def __init__(self, node, env):
        self.params = [(p, _MISSING) for p, _d in node.params]
        self.rest = node.rest
        self.kwrest = node.kwrest
        self.body = [NRet(node.body, line=node.line)]
        self.env = env
        self.line = node.line
    def __str__(self):
        return "<lambda>"

    def __call__(self, *args, **kwargs):
        ip = Interpreter._current
        if ip is None:
            raise DisRuntimeError("нет активного интерпретатора", self.line)
        return ip.call_user(self, list(args), dict(kwargs), self.line)

class ErrorVal:
    __slots__ = ("message", "line", "kind")
    def __init__(self, message, line, kind="Error"):
        self.message = message
        self.line = line
        self.kind = kind
    def __str__(self):
        return "%s: %s" % (self.kind, self.message)

class _Return(Exception):
    def __init__(self, value): self.value = value
class _Break(Exception): pass
class _Continue(Exception): pass
class _Exit(Exception):
    def __init__(self, code): self.code = code

def _EVAL(node, env):
    return Interpreter._dummy_eval(node, env)

class Interpreter:
    def __init__(self, argv):
        self.globals = Env(None)
        self.frames = [("<main>", 0)]
        self.globals.define("argv", list(argv))
        install_builtins(self.globals)

    # ---------- утилиты ----------
    @staticmethod
    def _dummy_eval(node, env):
        return Interpreter._current.eval(node, env)
    _current = None

    def run(self, stmts):
        Interpreter._current = self
        try:
            for s in stmts:
                self.exec(s, self.globals)
        finally:
            Interpreter._current = None

    def truthy(self, v):
        try:
            return bool(v)
        except Exception:
            return True

    def traceback(self):
        out = []
        for name, line in reversed(self.frames):
            out.append("  строка %d, %s" % (line, name))
        return out

    # ---------- операторы ----------
    def exec(self, node, env):
        if isinstance(node, NExpr):
            self.eval(node.value, env)
        elif isinstance(node, NPass):
            pass
        elif isinstance(node, NAssign):
            vals = [self.eval(v, env) for v in node.values]
            if len(node.targets) == 1:
                value = vals[0] if len(vals) == 1 else vals
                self.assign_to(node.targets[0], value, env)
            else:
                if len(vals) == 1:
                    vals = self.unpack(vals[0], len(node.targets), node.line)
                if len(vals) != len(node.targets):
                    raise DisRuntimeError("не то количество значений для присваивания", node.line)
                for t, v in zip(node.targets, vals):
                    self.assign_to(t, v, env)
        elif isinstance(node, NAug):
            cur = self.eval(node.target, env)
            val = self.eval(node.value, env)
            op = node.op[0] if node.op != "//=" else "//"
            if node.op == "**=":
                res = self.binop("**", cur, val, node.line)
            else:
                res = self.binop(op, cur, val, node.line)
            self.assign_to(node.target, res, env)
        elif isinstance(node, NIf):
            for cond, body in node.branches:
                if self.truthy(self.eval(cond, env)):
                    self.exec_block(body, env)
                    return
            self.exec_block(node.orelse, env)
        elif isinstance(node, NWhile):
            while self.truthy(self.eval(node.cond, env)):
                try:
                    self.exec_block(node.body, env)
                except _Break:
                    break
                except _Continue:
                    continue
        elif isinstance(node, NLoop):
            it = self.eval(node.iter, env)
            try:
                iterator = iter(it)
            except TypeError:
                raise DisRuntimeError("по объекту типа '%s' нельзя итерироваться" % self.tname(it), node.line)
            while True:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                except TypeError:
                    raise DisRuntimeError("по объекту типа '%s' нельзя итерироваться" % self.tname(it), node.line)
                if len(node.targets) == 1:
                    env.assign(node.targets[0], item)
                else:
                    vals = self.unpack(item, len(node.targets), node.line)
                    for name, v in zip(node.targets, vals):
                        env.assign(name, v)
                try:
                    self.exec_block(node.body, env)
                except _Break:
                    break
                except _Continue:
                    continue
        elif isinstance(node, NFunc):
            env.define(node.name, FuncVal(node, env))
        elif isinstance(node, NRet):
            raise _Return(self.eval(node.value, env) if node.value is not None else None)
        elif isinstance(node, NBreak):
            raise _Break()
        elif isinstance(node, NCont):
            raise _Continue()
        elif isinstance(node, NThrow):
            v = self.eval(node.value, env)
            raise DisRuntimeError(v.message if isinstance(v, ErrorVal) else str(v), node.line)
        elif isinstance(node, NTry):
            try:
                self.exec_block(node.body, env)
            except (_Return, _Break, _Continue):
                raise
            except _Exit:
                raise
            except DisError as e:
                self.exec_block(node.cbody, self.error_env(e, env, node))
            except RecursionError as e:
                self.exec_block(node.cbody, self.error_env(DisRuntimeError("переполнение стека рекурсии", node.line), env, node))
            except SystemExit:
                raise
            except KeyboardInterrupt:
                raise
            except BaseException as e:
                msg = str(e) or type(e).__name__
                self.exec_block(node.cbody, self.error_env(DisRuntimeError(msg, node.line), env, node))
        elif isinstance(node, NImport):
            name, line = node.module, node.line
            try:
                if node.alias:
                    mod = importlib.import_module(name)
                else:
                    mod = __import__(name)
            except BaseException as e:
                raise DisRuntimeError("не удалось импортировать '%s': %s" % (name, e), line)
            env.assign(node.alias or name.split(".")[0], mod)
        elif isinstance(node, NPy2Print):
            vals = [self.eval(v, env) for v in node.values]
            end = "\n" if node.newline else " "
            sys.stdout.write(" ".join(str(v) for v in vals) + end)
            sys.stdout.flush()
        elif isinstance(node, NSuperfast):
            pass   # директива: C-режим включается в main() до запуска
        else:
            raise DisRuntimeError("неизвестный узел %s" % type(node).__name__, getattr(node, "line", 0))

    def error_env(self, e, env, node):
        if e.line == 0:
            e.line = node.line
        child = Env(env)
        err = ErrorVal(e.message, e.line, "SyntaxError" if isinstance(e, DisSyntaxError) else "RuntimeError")
        if node.name:
            child.define(node.name, err)
        return child

    def exec_block(self, body, env):
        for s in body:
            self.exec(s, env)

    def assign_to(self, target, value, env):
        if isinstance(target, NName):
            env.assign(target.id, value)
        elif isinstance(target, NIndex):
            obj = self.eval(target.obj, env)
            idx = self.eval(target.index, env)
            try:
                obj[idx] = value
            except DisError:
                raise
            except BaseException as e:
                raise DisRuntimeError("не получилось присвоить по индексу: %s" % (str(e) or type(e).__name__), target.line)
        elif isinstance(target, NAttr):
            obj = self.eval(target.obj, env)
            try:
                setattr(obj, target.name, value)
            except BaseException:
                raise DisRuntimeError("нельзя установить атрибут '%s'" % target.name, target.line)
        else:
            raise DisRuntimeError("нельзя присвоить этому выражению", target.line)

    def unpack(self, item, count, line):
        if isinstance(item, str):
            seq = list(item)
        elif isinstance(item, dict):
            seq = list(item.keys())
        else:
            try:
                seq = list(item)
            except TypeError:
                raise DisRuntimeError("нельзя разложить объект типа '%s'" % self.tname(item), line)
        if len(seq) != count:
            raise DisRuntimeError("не удалось разложить: ожидалось %d значений, получено %d" % (count, len(seq)), line)
        return seq

    def tname(self, v):
        return type_name(v)

    # ---------- выражения ----------
    def eval(self, node, env):
        k = type(node)
        if k is NNum or k is NStr or k is NLit:
            return node.value
        if k is NFStr:
            out = []
            for lit, sub, spec in node.parts:
                out.append(lit)
                if sub is not None:
                    v = self.eval(sub, env)
                    try:
                        out.append(format(v, spec) if spec else str(v))
                    except DisError:
                        raise
                    except BaseException as e:
                        raise DisRuntimeError("ошибка формата в f-строке: %s" % e, node.line)
            return "".join(out)
        if k is NName:
            try:
                return env.lookup(node.id)
            except DisError as e:
                if e.line == 0:
                    e.line = node.line
                raise
        if k is NList:
            return [self.eval(i, env) for i in node.items]
        if k is NDict:
            d = {}
            for kn, vn in node.pairs:
                key = self.eval(kn, env)
                try:
                    d[key] = self.eval(vn, env)
                except TypeError:
                    raise DisRuntimeError("ключ словаря должен быть неизменяемым", node.line)
            return d
        if k is NLambda:
            return LambdaVal(node, env)
        if k is NBin:
            if node.op == "and":
                l = self.eval(node.left, env)
                return self.eval(node.right, env) if self.truthy(l) else l
            if node.op == "or":
                l = self.eval(node.left, env)
                return l if self.truthy(l) else self.eval(node.right, env)
            l = self.eval(node.left, env)
            r = self.eval(node.right, env)
            return self.binop(node.op, l, r, node.line)
        if k is NUn:
            v = self.eval(node.operand, env)
            if node.op == "not":
                return not self.truthy(v)
            try:
                return -v if node.op == "-" else +v
            except DisError:
                raise
            except BaseException as e:
                raise DisRuntimeError("унарный '%s': %s" % (node.op, str(e) or type(e).__name__), node.line)
        if k is NCmp:
            prev = self.eval(node.left, env)
            for op, rn in zip(node.ops, node.rights):
                cur = self.eval(rn, env)
                if not self.cmpop(op, prev, cur, node.line):
                    return False
                prev = cur
            return True
        if k is NCall:
            return self.eval_call(node, env)
        if k is NIndex:
            obj = self.eval(node.obj, env)
            idx = self.eval(node.index, env)
            try:
                return obj[idx]
            except DisError:
                raise
            except BaseException as e:
                raise DisRuntimeError("ошибка индексации '%s'[%s]: %s" % (self.tname(obj), self.tname(idx), str(e) or type(e).__name__), node.line)
        if k is NSlice:
            obj = self.eval(node.obj, env)
            a = self.eval(node.start, env) if node.start else None
            b = self.eval(node.stop, env) if node.stop else None
            c = self.eval(node.step, env) if node.step else None
            try:
                return obj[a:b:c]
            except DisError:
                raise
            except BaseException as e:
                raise DisRuntimeError("ошибка среза: %s" % (str(e) or type(e).__name__), node.line)
        if k is NAttr:
            obj = self.eval(node.obj, env)
            try:
                return getattr(obj, node.name)
            except DisError:
                raise
            except BaseException:
                raise DisRuntimeError("у типа '%s' нет атрибута '%s'" % (self.tname(obj), node.name), node.line)
        raise DisRuntimeError("неизвестный узел %s" % type(node).__name__, node.line)

    def binop(self, op, l, r, line):
        try:
            if op == "+": return l + r
            if op == "-": return l - r
            if op == "*": return l * r
            if op == "/": return l / r
            if op == "//": return l // r
            if op == "%": return l % r
            if op == "**": return l ** r
        except DisError:
            raise
        except BaseException as e:
            raise DisRuntimeError("операция '%s': %s" % (op, str(e) or type(e).__name__), line)
        raise DisRuntimeError("неизвестная операция '%s'" % op, line)

    def cmpop(self, op, l, r, line):
        try:
            if op == "==": return l == r
            if op == "!=": return l != r
            if op == "in": return l in r
            if op == "not in": return l not in r
            if op == "<": return l < r
            if op == "<=": return l <= r
            if op == ">": return l > r
            if op == ">=": return l >= r
        except DisError:
            raise
        except BaseException as e:
            raise DisRuntimeError("сравнение '%s': %s" % (op, str(e) or type(e).__name__), line)
        raise DisRuntimeError("неизвестное сравнение '%s'" % op, line)

    def eval_call(self, node, env):
        f = self.eval(node.func, env)
        args, kwargs = [], {}
        for kind, sub in node.args:
            v = self.eval(sub, env)
            if kind == "pos":
                args.append(v)
            else:
                try:
                    args.extend(v)
                except TypeError:
                    raise DisRuntimeError("*аргумент должен быть последовательностью", node.line)
        for kind, name, sub in node.kwargs:
            v = self.eval(sub, env)
            if kind == "kw":
                kwargs[name] = v
            else:
                if not isinstance(v, dict):
                    raise DisRuntimeError("**аргумент должен быть словарём", node.line)
                kwargs.update(v)
        return self.call(f, args, kwargs, node.line)

    def call(self, f, args, kwargs, line):
        if isinstance(f, (FuncVal, LambdaVal)):
            return self.call_user(f, args, kwargs, line)
        if isinstance(f, ErrorVal):
            raise DisRuntimeError("объект ошибки '%s' нельзя вызвать" % f.message, line)
        if not callable(f):
            raise DisRuntimeError("объект типа '%s' не является функцией" % self.tname(f), line)
        self.frames.append((getattr(f, "__name__", None) or str(f), line))
        try:
            return f(*args, **kwargs)
        except DisError:
            raise
        except _Exit:
            raise
        except BaseException as e:
            raise DisRuntimeError(str(e) or type(e).__name__, line)
        finally:
            self.frames.pop()

    def call_user(self, f, args, kwargs, line):
        env = Env(f.env)
        kw = dict(kwargs)
        fname = getattr(f, "name", "<lambda>")
        i = 0
        for pname, default in f.params:
            if i < len(args):
                env.define(pname, args[i]); i += 1
            elif pname in kw:
                env.define(pname, kw.pop(pname))
            elif default is not _MISSING:
                env.define(pname, default)
            else:
                raise DisRuntimeError("не передан аргумент '%s' в %s()" % (pname, fname), line)
        if f.rest:
            env.define(f.rest, list(args[i:]))
            i = len(args)
        if i < len(args):
            raise DisRuntimeError("слишком много аргументов для %s()" % fname, line)
        if kw:
            if f.kwrest:
                env.define(f.kwrest, kw)
            else:
                raise DisRuntimeError("лишние именованные аргументы: %s" % ", ".join(kw), line)
        self.frames.append((fname, line))
        try:
            self.exec_block(f.body, env)
        except _Return as r:
            return r.value
        finally:
            self.frames.pop()
        return None

# ============================================================ Встроенные

def type_name(v):
    if v is None: return "null"
    if isinstance(v, bool): return "bool"
    if isinstance(v, int): return "int"
    if isinstance(v, float): return "float"
    if isinstance(v, str): return "str"
    if isinstance(v, (list, tuple)): return "list"
    if isinstance(v, dict): return "dict"
    if isinstance(v, range): return "range"
    if isinstance(v, (FuncVal, LambdaVal)): return "func"
    if isinstance(v, ErrorVal): return "error"
    import types as _t
    if isinstance(v, _t.ModuleType): return "module"
    if isinstance(v, _t.FunctionType): return "func"
    if isinstance(v, type): return "class"
    return "object"

def install_builtins(g):
    def _print(*a, **kw):
        sep = kw.pop("sep", " ")
        end = kw.pop("end", "\n")
        if kw:
            raise TypeError("print(): лишние аргументы %s" % ", ".join(kw))
        sys.stdout.write(sep.join(str(x) for x in a) + end)
        sys.stdout.flush()

    def _type(v):
        return type_name(v)

    def _len(v):
        try:
            return len(v)
        except TypeError:
            raise DisRuntimeError("у типа '%s' нет длины" % type_name(v))

    def _map(f, *its):
        return list(map(f, *its))

    def _filter(f, it):
        return list(filter(f, it))

    def _reversed(it):
        return list(reversed(it))

    def _range(*a):
        return range(*a)

    def _int(v, base=None):
        if base is not None:
            return int(v, base)
        if isinstance(v, str):
            return int(v.strip(), 10)
        return int(v)

    def _input(prompt=""):
        if prompt:
            sys.stdout.write(str(prompt))
            sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "":
            return ""
        return line.rstrip("\r\n")

    def _read_file(path, encoding="utf-8"):
        with open(str(path), encoding=encoding) as fh:
            return fh.read()

    def _write_file(path, text, encoding="utf-8"):
        with open(str(path), "w", encoding=encoding) as fh:
            fh.write(str(text))

    def _exists(path):
        import os
        return os.path.exists(str(path))

    def _exit(code=0):
        raise _Exit(int(code))

    class _PyTwoModule:
        """Модуль в стиле Python 2: pythontwo.print(...)"""
        print = staticmethod(_print)

    class _SuperfastModule:
        """Директива C-ускорения (работает как first statement скрипта)."""
        def enable(self):
            return None
        def disable(self):
            return None

    g.define("pythontwo", _PyTwoModule())
    g.define("superfast", _SuperfastModule())

    for name, fn in [
        ("print", _print), ("println", _print), ("type", _type), ("len", _len), ("map", _map),
        ("filter", _filter), ("reversed", _reversed), ("range", _range),
        ("int", _int), ("input", _input), ("read_file", _read_file),
        ("write_file", _write_file), ("exists", _exists), ("exit", _exit),
        ("str", str), ("float", float), ("bool", bool), ("list", list),
        ("dict", dict), ("abs", abs), ("min", min), ("max", max),
        ("sum", sum), ("round", round), ("sorted", sorted),
        ("enumerate", enumerate), ("zip", zip), ("any", any), ("all", all),
        ("repr", repr), ("format", format),
    ]:
        g.define(name, fn)

# ============================================================ C-ускорение (superfast)

C_KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if",
    "inline", "int", "long", "register", "restrict", "return", "short",
    "signed", "sizeof", "static", "struct", "switch", "typedef", "union",
    "unsigned", "void", "volatile", "while", "_Bool",
}

class CUnsupported(Exception):
    """Конструкция вне подмножества C-бэкенда — повод выполнить скрипт обычным способом."""
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason

def _c_ident(name):
    """Безопасное C-имя для переменной/функции Deinstall Script."""
    if all(c.isascii() and (c.isalnum() or c == "_") for c in name) and name not in C_KEYWORDS:
        return "_u_" + name
    return "_h" + "_".join("%x" % ord(c) for c in name) + "_x"

def _c_string(s):
    """Строковый литерал C (UTF-8 байты, экранирование)."""
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == "\\": out.append("\\\\")
        elif ch == '"': out.append('\\"')
        elif ch == "\n": out.append("\\n")
        elif ch == "\r": out.append("\\r")
        elif ch == "\t": out.append("\\t")
        elif o < 32 or o == 127: out.append("\\%03o" % o)
        else: out.append(ch)
    out.append('"')
    return "".join(out)

_CT = {"I": "long long", "F": "double", "S": "const char*", "B": "long long"}
_CTN = {"I": "число", "F": "дробное", "S": "строка", "B": "логическое"}
_CZERO = {"I": "0", "F": "0.0", "S": '""', "B": "0"}

C_PRELUDE = r'''/* Сгенерировано Deinstall Script (superfast.enable) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <math.h>
#ifdef _WIN32
#include <windows.h>
#endif

static void dis_rt_error(const char* m){
    fflush(stdout);
    fputs("DeinstallError: ", stderr);
    fputs(m, stderr);
    fputs("\n", stderr);
    exit(1);
}
static void dis_zero_div(void){ dis_rt_error("деление на ноль"); }
static double dis_div(double a, double b){
    if (b == 0.0) dis_zero_div();
    return a / b;
}
static long long dis_floordiv_i(long long a, long long b){
    long long q, r;
    if (b == 0) dis_zero_div();
    q = a / b; r = a % b;
    if (r != 0 && ((r > 0) != (b > 0))) q -= 1;
    return q;
}
static long long dis_floormod_i(long long a, long long b){
    long long r;
    if (b == 0) dis_zero_div();
    r = a % b;
    if (r != 0 && ((r > 0) != (b > 0))) r += b;
    return r;
}
static double dis_floordiv_f(double a, double b){
    if (b == 0.0) dis_zero_div();
    return floor(a / b);
}
static double dis_floormod_f(double a, double b){
    if (b == 0.0) dis_zero_div();
    return a - floor(a / b) * b;
}
static double dis_pow_f(double a, double b){
    if (a == 0.0 && b < 0.0) dis_rt_error("0 в отрицательной степени");
    return pow(a, b);
}
static void dis_zero_step(void){ dis_rt_error("шаг range() не может быть нулём"); }
static int dis_truth_s(const char* s){ return s != 0 && s[0] != 0; }
static const char* dis_b2s(long long v){ return v ? "True" : "False"; }
static char* dis_i2s(long long v){
    char buf[32];
    size_t n;
    char* r;
    sprintf(buf, "%lld", v);
    n = strlen(buf);
    r = (char*)malloc(n + 1);
    if (!r) dis_rt_error("нет памяти");
    memcpy(r, buf, n + 1);
    return r;
}
static char* dis_f2s(double v){
    char buf[64];
    int p;
    char* r;
    size_t n;
    if (v != v) { strcpy(buf, "nan"); }
    else if (v == (double)INFINITY) { strcpy(buf, "inf"); }
    else if (v == -(double)INFINITY) { strcpy(buf, "-inf"); }
    else if (v == floor(v) && fabs(v) < 1e16) { sprintf(buf, "%lld.0", (long long)v); }
    else {
        for (p = 1; p <= 17; p++) {
            sprintf(buf, "%.*g", p, v);
            if (strtod(buf, 0) == v) break;
        }
        if (!strchr(buf, '.') && !strchr(buf, 'e') && !strchr(buf, 'n') && !strchr(buf, 'i')) {
            strcat(buf, ".0");
        }
    }
    n = strlen(buf);
    r = (char*)malloc(n + 1);
    if (!r) dis_rt_error("нет памяти");
    memcpy(r, buf, n + 1);
    return r;
}
static char* dis_concat(const char* a, const char* b){
    size_t la = strlen(a), lb = strlen(b);
    char* r = (char*)malloc(la + lb + 1);
    if (!r) dis_rt_error("нет памяти");
    memcpy(r, a, la);
    memcpy(r + la, b, lb + 1);
    return r;
}
static char* dis_input(const char* prompt){
    size_t cap = 128, n = 0;
    char* buf;
    int c;
    if (prompt && prompt[0]) fputs(prompt, stdout);
    fflush(stdout);
    buf = (char*)malloc(cap);
    if (!buf) dis_rt_error("нет памяти");
    for (;;) {
        c = fgetc(stdin);
        if (c == EOF || c == '\n') break;
        if (n + 1 >= cap) {
            char* nb;
            cap *= 2;
            nb = (char*)realloc(buf, cap);
            if (!nb) dis_rt_error("нет памяти");
            buf = nb;
        }
        buf[n++] = (char)c;
    }
    if (n > 0 && buf[n - 1] == '\r') n--;
    buf[n] = 0;
    return buf;
}
static long long dis_s2i(const char* s){
    char* end;
    long long v;
    const char* p = s;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    errno = 0;
    v = strtoll(p, &end, 10);
    while (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r') end++;
    if (end == p || *end != 0) dis_rt_error("int(): строка не является числом");
    if (errno == ERANGE) dis_rt_error("int(): число вне диапазона");
    return v;
}
static double dis_s2f(const char* s){
    char* end;
    double v;
    const char* p = s;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    v = strtod(p, &end);
    while (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r') end++;
    if (end == p || *end != 0) dis_rt_error("float(): строка не является числом");
    return v;
}
static void dis_out_i(long long v){ printf("%lld", v); }
static void dis_out_b(long long v){ fputs(v ? "True" : "False", stdout); }
static void dis_out_f(double v){ char* s = dis_f2s(v); fputs(s, stdout); free(s); }
static void dis_out_s(const char* s){ fputs(s, stdout); }
static void dis_start(void){
#ifdef _WIN32
    SetConsoleOutputCP(65001);
    SetConsoleCP(65001);
#endif
    setvbuf(stdout, 0, _IOLBF, 0);
}
'''

class _CFunc:
    __slots__ = ("node", "locals", "ret", "mixed")
    def __init__(self, node):
        self.node = node
        self.locals = {}
        for pname, _d in node.params:
            self.locals[pname] = None
        self.ret = None
        self.mixed = False

class CGen:
    BANNED = {"print", "println", "pythontwo", "superfast", "range", "str",
              "int", "float", "abs", "min", "max", "exit", "math"}

    def __init__(self, stmts):
        self.stmts = stmts
        self.funcs = {}
        self.gvars = {}
        self.assigned = set()
        self.top_assigned = set()
        self.math_names = set()
        self.out = []
        self.ind = 0
        self.tmp = 0

    # ---------- служебное ----------
    def emit(self, s):
        self.out.append("    " * self.ind + s)

    def _tmpname(self):
        self.tmp += 1
        return "_dis_t%d" % self.tmp

    # ---------- разбор (что вообще есть в скрипте) ----------
    def _scan(self, stmts, depth):
        for s in stmts:
            if isinstance(s, NFunc):
                if depth:
                    raise CUnsupported("функция внутри функции")
                if s.name in self.funcs:
                    raise CUnsupported("повторное определение функции '%s'" % s.name)
                if s.name in self.BANNED:
                    raise CUnsupported("функция с именем '%s' конфликтует со встроенной" % s.name)
                if s.rest or s.kwrest:
                    raise CUnsupported("функция с *args/**kwargs")
                for pname, d in s.params:
                    if d is not None:
                        raise CUnsupported("значение по умолчанию у параметра")
                    self.assigned.add(pname)
                self.funcs[s.name] = _CFunc(s)
                self._scan(s.body, depth + 1)
            elif isinstance(s, NImport):
                if s.module != "math":
                    raise CUnsupported("import '%s'" % s.module)
                self.math_names.add(s.alias or "math")
            elif isinstance(s, NAssign):
                if len(s.targets) != 1 or len(s.values) != 1:
                    raise CUnsupported("присваивание нескольких значений")
                if not isinstance(s.targets[0], NName):
                    raise CUnsupported("присваивание не переменной")
                self.assigned.add(s.targets[0].id)
                if depth == 0:
                    self.top_assigned.add(s.targets[0].id)
            elif isinstance(s, NAug):
                if not isinstance(s.target, NName):
                    raise CUnsupported("присваивание не переменной")
                self.assigned.add(s.target.id)
                if depth == 0:
                    self.top_assigned.add(s.target.id)
            elif isinstance(s, NLoop):
                if len(s.targets) != 1:
                    raise CUnsupported("несколько переменных цикла")
                self.assigned.add(s.targets[0])
                if depth == 0:
                    self.top_assigned.add(s.targets[0])
                self._scan(s.body, depth)
            elif isinstance(s, NIf):
                for _c, b in s.branches:
                    self._scan(b, depth)
                self._scan(s.orelse, depth)
            elif isinstance(s, NWhile):
                self._scan(s.body, depth)
            elif isinstance(s, (NExpr, NPy2Print, NPass, NRet, NBreak, NCont, NSuperfast)):
                pass
            elif isinstance(s, NThrow):
                raise CUnsupported("throw")
            elif isinstance(s, NTry):
                raise CUnsupported("try/catch")
            else:
                raise CUnsupported("конструкция %s" % type(s).__name__)

    # ---------- главный вход ----------
    def generate(self):
        self._scan(self.stmts, 0)
        bad = self.assigned & (self.BANNED | self.math_names)
        if bad:
            raise CUnsupported("имя '%s' занято встроенным" % sorted(bad)[0])
        top = [s for s in self.stmts if not isinstance(s, NFunc)]
        for _round in range(8):
            snap = self._snapshot()
            for f in self.funcs.values():
                self._stmts(f.node.body, f.locals, f, 0, False)
            self._stmts(top, self.gvars, None, 0, False)
            if snap == self._snapshot():
                break
        for f in self.funcs.values():
            for pname, _d in f.node.params:
                if f.locals.get(pname) is None:
                    f.locals[pname] = "I"
            if f.mixed and f.ret is not None:
                raise CUnsupported("в функции '%s' ret и с значением, и без" % f.node.name)
        self.emit(C_PRELUDE)
        for f in self.funcs.values():
            ret, name, params = self._sig_parts(f)
            self.emit("static %s %s(%s);" % (ret, name, params))
        for f in self.funcs.values():
            self._gen_func(f)
        self._gen_main(top)
        return "\n".join(self.out)

    def _snapshot(self):
        fs = tuple((n, tuple(sorted(f.locals.items())), f.ret, f.mixed) for n, f in self.funcs.items())
        return (tuple(sorted(self.gvars.items())), fs)

    def _sig_parts(self, f):
        if f.ret is None:
            ret = "void"
        else:
            ret = _CT["I" if f.ret == "B" else f.ret]
        params = []
        for pname, _d in f.node.params:
            t = f.locals.get(pname) or "I"
            params.append("%s %s" % (_CT[t], _c_ident(pname)))
        return ret, _c_ident(f.node.name), (", ".join(params) if params else "void")

    def _gen_func(self, f):
        ret, name, params = self._sig_parts(f)
        self.emit("static %s %s(%s) {" % (ret, name, params))
        self.ind += 1
        for vname, vt in f.locals.items():
            if vname in [p for p, _d in f.node.params]:
                continue
            self.emit("%s %s = %s;" % (_CT[vt], _c_ident(vname), _CZERO[vt]))
        self._stmts(f.node.body, f.locals, f, 0, True)
        if f.ret is None:
            self.emit("return;")
        else:
            self.emit("return %s;" % (_CZERO[f.ret] if f.ret != "B" else "0"))
        self.ind -= 1
        self.emit("}")

    def _gen_main(self, top):
        self.emit("int main(void) {")
        self.ind += 1
        self.emit("dis_start();")
        for vname, vt in self.gvars.items():
            self.emit("%s %s = %s;" % (_CT[vt], _c_ident(vname), _CZERO[vt]))
        self._stmts(top, self.gvars, None, 0, True)
        self.emit("return 0;")
        self.ind -= 1
        self.emit("}")

    # ---------- типы ----------
    def _widen(self, a, b, what):
        if a is None: return b
        if b is None: return a
        if a == b: return a
        if a in ("I", "B") and b in ("I", "B"): return "I"
        if a in ("I", "B", "F") and b in ("I", "B", "F"): return "F"
        raise CUnsupported("'%s' используется и как %s, и как %s" % (what, _CTN.get(a, a), _CTN.get(b, b)))

    def _set_var(self, name, t, scope, func):
        if func is not None and name not in scope and name in self.top_assigned:
            raise CUnsupported("функция изменяет глобальную переменную '%s'" % name)
        scope[name] = self._widen(scope.get(name), t, name)

    # ---------- операторы ----------
    def _stmts(self, stmts, scope, func, loopdepth, emit):
        for s in stmts:
            self._st(s, scope, func, loopdepth, emit)

    def _st(self, node, scope, func, loopdepth, emit):
        if isinstance(node, (NPass, NSuperfast, NFunc, NImport)):
            return
        if isinstance(node, NExpr):
            if self._nop_call(node.value):
                return
            info = self._print_info(node.value)
            if info is not None:
                self._print_call(info[0], info[1], "\n", scope, func, emit)
                return
            t, code = self._ex(node.value, scope, func)
            if emit and code:
                self.emit(code + ";")
            return
        if isinstance(node, NPy2Print):
            args = [("pos", v) for v in node.values]
            self._print_call(args, [], "\n" if node.newline else " ", scope, func, emit)
            return
        if isinstance(node, NAssign):
            vt, vc = self._ex(node.values[0], scope, func)
            if vt == "V":
                raise CUnsupported("присваивание выражения без значения")
            self._set_var(node.targets[0].id, vt, scope, func)
            if emit:
                self.emit("%s = %s;" % (_c_ident(node.targets[0].id), vc))
            return
        if isinstance(node, NAug):
            name = node.target.id
            cur = scope.get(name)
            if cur is None:
                raise CUnsupported("'%s' для неизвестной переменной '%s'" % (node.op, name))
            vt, vc = self._ex(node.value, scope, func)
            if vt == "V":
                raise CUnsupported("операция с выражением без значения")
            op = "//" if node.op == "//=" else node.op[:-1]
            rt, code = self._binop_code(op, cur, _c_ident(name), vt, vc, node.value)
            self._set_var(name, rt, scope, func)
            if emit:
                self.emit("%s = %s;" % (_c_ident(name), code))
            return
        if isinstance(node, NIf):
            for i, (cond, body) in enumerate(node.branches):
                ct, cc = self._ex(cond, scope, func, cond=True)
                if emit:
                    self.emit("%sif (%s) {" % ("} else " if i else "", self._truth(ct, cc)))
                self.ind += 1
                self._stmts(body, scope, func, loopdepth, emit)
                self.ind -= 1
                if emit:
                    self.emit("}")
            if node.orelse:
                if emit:
                    self.out[-1] = self.out[-1] + " else {"
                self.ind += 1
                self._stmts(node.orelse, scope, func, loopdepth, emit)
                self.ind -= 1
                if emit:
                    self.emit("}")
            return
        if isinstance(node, NWhile):
            ct, cc = self._ex(node.cond, scope, func, cond=True)
            if emit:
                self.emit("while (%s) {" % self._truth(ct, cc))
            self.ind += 1
            self._stmts(node.body, scope, func, loopdepth + 1, emit)
            self.ind -= 1
            if emit:
                self.emit("}")
            return
        if isinstance(node, NLoop):
            tgt = node.targets[0]
            it = node.iter
            if not (isinstance(it, NCall) and isinstance(it.func, NName) and it.func.id == "range"):
                raise CUnsupported("loop только по range(...)")
            if it.kwargs:
                raise CUnsupported("range с именованными аргументами")
            pargs = []
            for kind, sub in it.args:
                if kind != "pos":
                    raise CUnsupported("звёздочки в range()")
                pargs.append(sub)
            if not 1 <= len(pargs) <= 3:
                raise CUnsupported("range() с %d аргументами" % len(pargs))
            codes = []
            for a in pargs:
                at, ac = self._ex(a, scope, func)
                if at not in ("I", "B"):
                    raise CUnsupported("range() с дробным")
                codes.append(ac)
            self._set_var(tgt, "I", scope, func)
            if emit:
                a1 = self._tmpname(); b1 = self._tmpname(); s1 = self._tmpname(); v1 = self._tmpname()
                name = _c_ident(tgt)
                if len(codes) == 1:
                    self.emit("{ long long %s = 0, %s = %s, %s = 1, %s;" % (a1, b1, codes[0], s1, v1))
                elif len(codes) == 2:
                    self.emit("{ long long %s = %s, %s = %s, %s = 1, %s;" % (a1, codes[0], b1, codes[1], s1, v1))
                else:
                    self.emit("{ long long %s = %s, %s = %s, %s = %s, %s;" % (a1, codes[0], b1, codes[1], s1, codes[2], v1))
                self.ind += 1
                self.emit("if (%s == 0) dis_zero_step();" % s1)
                self.emit("for (%s = %s; (%s > 0) ? (%s < %s) : (%s > %s); %s += %s) {" % (v1, a1, s1, v1, b1, v1, b1, v1, s1))
                self.ind += 1
                self.emit("%s = %s;" % (name, v1))
                self._stmts(node.body, scope, func, loopdepth + 1, emit)
                self.ind -= 1
                self.emit("}")
                self.ind -= 1
                self.emit("}")
            else:
                self._stmts(node.body, scope, func, loopdepth + 1, emit)
            return
        if isinstance(node, NRet):
            if func is None:
                raise CUnsupported("ret вне функции")
            if node.value is None:
                func.mixed = True
                if emit:
                    self.emit("return;")
                return
            t, code = self._ex(node.value, scope, func)
            if t == "V":
                raise CUnsupported("ret выражения без значения")
            func.ret = self._widen(func.ret, t, "ret")
            if emit:
                self.emit("return %s;" % self._cast_ret(t, code, func.ret))
            return
        if isinstance(node, NBreak):
            if loopdepth == 0:
                raise CUnsupported("break вне цикла")
            if emit:
                self.emit("break;")
            return
        if isinstance(node, NCont):
            if loopdepth == 0:
                raise CUnsupported("continue вне цикла")
            if emit:
                self.emit("continue;")
            return
        raise CUnsupported("оператор %s" % type(node).__name__)

    # ---------- печать ----------
    def _print_info(self, node):
        if not isinstance(node, NCall):
            return None
        fn = node.func
        if isinstance(fn, NName) and fn.id in ("print", "println"):
            return (node.args, node.kwargs)
        if isinstance(fn, NAttr) and isinstance(fn.obj, NName) \
                and fn.obj.id == "pythontwo" and fn.name == "print":
            return (node.args, node.kwargs)
        return None

    def _nop_call(self, node):
        if isinstance(node, NCall) and isinstance(node.func, NAttr) \
                and isinstance(node.func.obj, NName) and node.func.obj.id == "superfast" \
                and node.func.name in ("enable", "disable") and not node.args and not node.kwargs:
            return True
        return False

    def _print_call(self, args, kwargs, default_end, scope, func, emit):
        sep, end = " ", default_end
        for kind, name, sub in kwargs:
            if kind != "kw" or name not in ("sep", "end") or not isinstance(sub, NStr):
                raise CUnsupported("print: именованные аргументы — только sep=/end= строками")
            if name == "sep":
                sep = sub.value
            else:
                end = sub.value
        first = True
        for kind, sub in args:
            if kind != "pos":
                raise CUnsupported("print(*...)")
            t, code = self._ex(sub, scope, func)
            if t == "V":
                raise CUnsupported("print: выражение без значения")
            if emit:
                if not first and sep:
                    self.emit("fputs(%s, stdout);" % _c_string(sep))
                if t == "S":
                    self.emit("dis_out_s(%s);" % code)
                elif t == "I":
                    self.emit("dis_out_i(%s);" % code)
                elif t == "B":
                    self.emit("dis_out_b(%s);" % code)
                else:
                    self.emit("dis_out_f(%s);" % code)
            first = False
        if emit and end:
            self.emit("fputs(%s, stdout);" % _c_string(end))

    def _pure(self, n):
        if isinstance(n, (NNum, NStr, NLit, NName)):
            return True
        if isinstance(n, NFStr):
            return all(self._pure(sub) for _l, sub, _s in n.parts if sub is not None)
        if isinstance(n, NUn):
            return self._pure(n.operand)
        if isinstance(n, NBin):
            return self._pure(n.left) and self._pure(n.right)
        if isinstance(n, NCmp):
            return self._pure(n.left) and all(self._pure(r) for r in n.rights)
        if isinstance(n, NAttr):
            return isinstance(n.obj, NName) and n.obj.id == "math"
        return False

    # ---------- выражения ----------
    def _truth(self, t, code):
        if t in ("I", "B"):
            return "((%s) != 0)" % code
        if t == "F":
            return "((%s) != 0.0)" % code
        if t == "S":
            return "dis_truth_s(%s)" % code
        raise CUnsupported("выражение без значения в условии")

    def _cast_ret(self, t, code, ret):
        nt = "I" if t == "B" else t
        nr = "I" if ret == "B" else ret
        if nr == nt:
            return code
        if nr == "F" and nt == "I":
            return "((double)(%s))" % code
        raise CUnsupported("несовместимый тип возврата")

    def _cast_arg(self, at, ac, pt, fname, pname):
        na = "I" if at == "B" else at
        np = "I" if pt == "B" else pt
        if np == na:
            return ac
        if np == "F" and na == "I":
            return "((double)(%s))" % ac
        raise CUnsupported("аргумент '%s' в %s(): %s, а параметр — %s" % (pname, fname, _CTN.get(at, at), _CTN.get(pt, pt)))

    def _ex(self, n, scope, func, cond=False):
        k = type(n)
        if k is NNum:
            v = n.value
            if isinstance(v, int):
                if abs(v) > 2 ** 62:
                    raise CUnsupported("слишком большое целое")
                return "I", "(%dLL)" % v
            r = repr(float(v))
            if "inf" in r or "nan" in r:
                raise CUnsupported("бесконечность/NaN")
            return "F", "((double)(%s))" % r
        if k is NStr:
            return "S", _c_string(n.value)
        if k is NLit:
            if n.value is True:
                return "B", "1"
            if n.value is False:
                return "B", "0"
            raise CUnsupported("null")
        if k is NFStr:
            segs = []
            for lit, sub, spec in n.parts:
                if spec:
                    raise CUnsupported("формат ':%s' в f-строке" % spec)
                if lit:
                    segs.append(_c_string(lit))
                if sub is not None:
                    t, code = self._ex(sub, scope, func)
                    if t == "V":
                        raise CUnsupported("f-строка с выражением без значения")
                    if t == "S":
                        segs.append(code)
                    elif t == "I":
                        segs.append("dis_i2s(%s)" % code)
                    elif t == "B":
                        segs.append("dis_b2s(%s)" % code)
                    else:
                        segs.append("dis_f2s(%s)" % code)
            if not segs:
                return "S", '""'
            code = segs[0]
            for more in segs[1:]:
                code = "dis_concat(%s, %s)" % (code, more)
            return "S", code
        if k is NName:
            if n.id in scope:
                t = scope[n.id]
                if t is None:
                    t = "I"   # предварительная оценка: параметр ещё не уточнён
                return t, _c_ident(n.id)
            if n.id in self.gvars:
                return self.gvars[n.id], _c_ident(n.id)
            raise CUnsupported("неизвестная переменная '%s'" % n.id)
        if k is NBin:
            op = n.op
            if op in ("and", "or"):
                lt, ls = self._ex(n.left, scope, func, cond=True)
                rt, rs = self._ex(n.right, scope, func, cond=True)
                if not cond and not (lt == "B" and rt == "B"):
                    raise CUnsupported("and/or возвращают значение — поддержаны только для логических и в условиях")
                cop = "&&" if op == "and" else "||"
                return "B", "((%s) %s (%s))" % (self._truth(lt, ls), cop, self._truth(rt, rs))
            lt, ls = self._ex(n.left, scope, func)
            rt, rs = self._ex(n.right, scope, func)
            return self._binop_code(op, lt, ls, rt, rs, n.right)
        if k is NUn:
            t, code = self._ex(n.operand, scope, func)
            if n.op == "not":
                return "B", "(!%s)" % self._truth(t, code)
            if t not in ("I", "B", "F"):
                raise CUnsupported("унарный '%s' для %s" % (n.op, _CTN.get(t, t)))
            nt = "I" if t == "B" else t
            if n.op == "-":
                return nt, "(-(%s))" % code
            return nt, "(+(%s))" % code
        if k is NCmp:
            for i, right in enumerate(n.rights):
                if i < len(n.rights) - 1 and not self._pure(right):
                    raise CUnsupported("цепочка сравнений с вызовом")
            parts = []
            prev_t, prev_c = self._ex(n.left, scope, func)
            for op, right in zip(n.ops, n.rights):
                if op in ("in", "not in"):
                    raise CUnsupported("оператор 'in'")
                rt, rc = self._ex(right, scope, func)
                parts.append(self._cmp_code(op, prev_t, prev_c, rt, rc))
                prev_t, prev_c = rt, rc
            if len(parts) == 1:
                return "B", parts[0]
            return "B", "(%s)" % " && ".join(parts)
        if k is NCall:
            return self._ex_call(n, scope, func)
        if k is NAttr:
            obj = n.obj
            if isinstance(obj, NName) and obj.id in self.math_names:
                consts = {"pi": "3.141592653589793", "e": "2.718281828459045",
                          "tau": "6.283185307179586", "inf": "((double)INFINITY)"}
                if n.name in consts:
                    return "F", consts[n.name]
                raise CUnsupported("math.%s" % n.name)
            if isinstance(obj, NName) and obj.id == "superfast":
                return "V", "0"
            raise CUnsupported("атрибут '.%s'" % n.name)
        raise CUnsupported("выражение %s" % k.__name__)

    def _binop_code(self, op, lt, ls, rt, rs, rnode):
        if lt == "V" or rt == "V":
            raise CUnsupported("операция с выражением без значения")
        if lt == "S" or rt == "S":
            if op == "+" and lt == "S" and rt == "S":
                return "S", "dis_concat(%s, %s)" % (ls, rs)
            raise CUnsupported("операция '%s' со строкой" % op)
        a = "I" if lt == "B" else lt
        b = "I" if rt == "B" else rt
        both_i = (a == "I" and b == "I")
        if op == "**":
            if both_i and isinstance(rnode, NNum) and isinstance(rnode.value, int) \
                    and not isinstance(rnode.value, bool) and rnode.value >= 0:
                return "I", "((long long)pow((double)(%s), (double)(%s)))" % (ls, rs)
            return "F", "(dis_pow_f((double)(%s), (double)(%s)))" % (ls, rs)
        if op == "/":
            return "F", "(dis_div((double)(%s), (double)(%s)))" % (ls, rs)
        if op == "//":
            if both_i:
                return "I", "dis_floordiv_i(%s, %s)" % (ls, rs)
            return "F", "dis_floordiv_f((double)(%s), (double)(%s))" % (ls, rs)
        if op == "%":
            if both_i:
                return "I", "dis_floormod_i(%s, %s)" % (ls, rs)
            return "F", "dis_floormod_f((double)(%s), (double)(%s))" % (ls, rs)
        if op in ("+", "-", "*"):
            if both_i:
                return "I", "((%s) %s (%s))" % (ls, op, rs)
            return "F", "(((double)(%s)) %s ((double)(%s)))" % (ls, op, rs)
        raise CUnsupported("операция '%s'" % op)

    def _cmp_code(self, op, lt, ls, rt, rs):
        if lt == "V" or rt == "V":
            raise CUnsupported("сравнение с выражением без значения")
        if lt == "S" or rt == "S":
            if lt != "S" or rt != "S":
                raise CUnsupported("сравнение строки с числом")
            cop = {"==": "== 0", "!=": "!= 0", "<": "< 0", "<=": "<= 0", ">": "> 0", ">=": ">= 0"}[op]
            return "(strcmp(%s, %s) %s)" % (ls, rs, cop)
        na = "I" if lt == "B" else lt
        nb = "I" if rt == "B" else rt
        if na == "F" or nb == "F":
            return "(((double)(%s)) %s ((double)(%s)))" % (ls, op, rs)
        return "((%s) %s (%s))" % (ls, op, rs)

    # ---------- вызовы ----------
    _MATH1 = {"sqrt": "sqrt", "sin": "sin", "cos": "cos", "tan": "tan",
              "asin": "asin", "acos": "acos", "atan": "atan", "exp": "exp",
              "log": "log", "log2": "log2", "log10": "log10", "fabs": "fabs",
              "sinh": "sinh", "cosh": "cosh", "tanh": "tanh"}

    def _ex_call(self, n, scope, func):
        pos = []
        for kind, sub in n.args:
            if kind != "pos":
                raise CUnsupported("*аргументы")
            pos.append(sub)
        for _kind, _name, _sub in n.kwargs:
            raise CUnsupported("именованные аргументы (кроме print)")
        fn = n.func
        if isinstance(fn, NName):
            name = fn.id
            if name == "str" and len(pos) == 1:
                t, c = self._ex(pos[0], scope, func)
                if t == "S": return "S", c
                if t == "I": return "S", "dis_i2s(%s)" % c
                if t == "B": return "S", "dis_b2s(%s)" % c
                if t == "F": return "S", "dis_f2s(%s)" % c
                raise CUnsupported("str(выражение без значения)")
            if name == "int" and len(pos) == 1:
                t, c = self._ex(pos[0], scope, func)
                if t in ("I", "B"): return "I", c
                if t == "F": return "I", "((long long)(%s))" % c
                if t == "S": return "I", "dis_s2i(%s)" % c
                raise CUnsupported("int() от %s" % _CTN.get(t, t))
            if name == "float" and len(pos) == 1:
                t, c = self._ex(pos[0], scope, func)
                if t in ("I", "B"): return "F", "((double)(%s))" % c
                if t == "F": return "F", c
                if t == "S": return "F", "dis_s2f(%s)" % c
                raise CUnsupported("float() от %s" % _CTN.get(t, t))
            if name == "abs" and len(pos) == 1:
                t, c = self._ex(pos[0], scope, func)
                if t in ("I", "B"): return "I", "(llabs(%s))" % c
                if t == "F": return "F", "(fabs(%s))" % c
                raise CUnsupported("abs() от %s" % _CTN.get(t, t))
            if name in ("min", "max") and len(pos) == 2:
                if not (self._pure(pos[0]) and self._pure(pos[1])):
                    raise CUnsupported("min/max с вызовом функции")
                t1, c1 = self._ex(pos[0], scope, func)
                t2, c2 = self._ex(pos[1], scope, func)
                if (t1, t2) == ("B", "I"):
                    t1 = "I"
                if (t1, t2) == ("I", "B"):
                    t2 = "I"
                if t1 != t2:
                    raise CUnsupported("min/max с разными типами")
                if t1 == "V":
                    raise CUnsupported("min/max выражения без значения")
                op = "<" if name == "min" else ">"
                if t1 == "S":
                    return "S", "(strcmp(%s, %s) %s 0 ? (%s) : (%s))" % (c1, c2, op, c1, c2)
                if t1 == "B":
                    return "B", "((%s) %s (%s) ? (%s) : (%s))" % (c1, op, c2, c1, c2)
                return t1, "((%s) %s (%s) ? (%s) : (%s))" % (c1, op, c2, c1, c2)
            if name == "exit" and len(pos) == 1:
                t, c = self._ex(pos[0], scope, func)
                if t not in ("I", "B", "F"):
                    raise CUnsupported("exit() с не-числом")
                return "V", "exit((int)(%s))" % c
            if name == "input":
                if not pos:
                    return "S", 'dis_input("")'
                if len(pos) > 1:
                    raise CUnsupported("input() с несколькими аргументами")
                t, c = self._ex(pos[0], scope, func)
                if t == "S": return "S", "dis_input(%s)" % c
                if t == "I": return "S", "dis_input(dis_i2s(%s))" % c
                if t == "B": return "S", "dis_input(dis_b2s(%s))" % c
                if t == "F": return "S", "dis_input(dis_f2s(%s))" % c
                raise CUnsupported("input() без значения")
            if name == "range":
                raise CUnsupported("range() вне loop")
            if name in ("print", "println"):
                raise CUnsupported("print — только отдельным оператором")
            if name in self.funcs:
                return self._user_call(name, pos, scope, func)
            raise CUnsupported("вызов '%s()'" % name)
        if isinstance(fn, NAttr):
            obj = fn.obj
            if isinstance(obj, NName) and obj.id in self.math_names:
                return self._math_call(fn.name, pos, scope, func)
            if isinstance(obj, NName) and obj.id == "pythontwo" and fn.name == "print":
                raise CUnsupported("pythontwo.print — только отдельным оператором")
            if isinstance(obj, NName) and obj.id == "superfast" and fn.name in ("enable", "disable"):
                return "V", "0"
            raise CUnsupported("вызов метода .%s()" % fn.name)
        raise CUnsupported("вызов сложного выражения")

    def _user_call(self, name, pos, scope, func):
        f = self.funcs[name]
        plist = [p for p, _d in f.node.params]
        if len(pos) != len(plist):
            raise CUnsupported("у %s() %d параметр(ов), передано %d" % (name, len(plist), len(pos)))
        codes = []
        for i, a in enumerate(pos):
            at, ac = self._ex(a, scope, func)
            if at == "V":
                raise CUnsupported("аргумент без значения в %s()" % name)
            pname = plist[i]
            f.locals[pname] = self._widen(f.locals.get(pname), "I" if at == "B" else at, pname)
            codes.append(self._cast_arg(at, ac, f.locals[pname], name, pname))
        call = "%s(%s)" % (_c_ident(name), ", ".join(codes))
        if f.ret is None:
            return "V", call
        return f.ret, call

    def _math_call(self, name, pos, scope, func):
        def num1():
            if len(pos) != 1:
                raise CUnsupported("math.%s: нужно 1 число" % name)
            t, c = self._ex(pos[0], scope, func)
            if t not in ("I", "B", "F"):
                raise CUnsupported("math.%s: не число" % name)
            return c
        if name in self._MATH1:
            return "F", "(%s((double)(%s)))" % (self._MATH1[name], num1())
        if name == "floor":
            return "I", "((long long)(floor((double)(%s))))" % num1()
        if name == "ceil":
            return "I", "((long long)(ceil((double)(%s))))" % num1()
        if name == "trunc":
            return "I", "((long long)((double)(%s)))" % num1()
        if name == "isqrt":
            return "I", "((long long)(sqrt((double)(%s))))" % num1()
        if name in ("pow", "atan2", "hypot", "fmod", "copysign"):
            if len(pos) != 2:
                raise CUnsupported("math.%s: нужно 2 числа" % name)
            cs = []
            for a in pos:
                t, c = self._ex(a, scope, func)
                if t not in ("I", "B", "F"):
                    raise CUnsupported("math.%s: не число" % name)
                cs.append(c)
            return "F", "(%s((double)(%s), (double)(%s)))" % (name, cs[0], cs[1])
        raise CUnsupported("math.%s()" % name)

# ============================================================ Поиск C-компилятора

_CC_CACHE = []

def _guess_cc_kind(path):
    base = path.lower().replace("\\", "/").rsplit("/", 1)[-1]
    if base.startswith("zig"):
        return "zig"
    if base.startswith("tcc"):
        return "tcc"
    if base in ("cl", "cl.exe"):
        return "cl"
    return "gcc"

def find_c_compiler():
    """Ищет tcc/gcc/clang/zig/cl. Возвращает (вид, [команда]) или None."""
    if _CC_CACHE:
        return _CC_CACHE[0]
    import os as _os
    import shutil as _sh
    found = None
    env_cc = _os.environ.get("DIS_CC")
    if env_cc:
        parts = env_cc.split()
        found = (_guess_cc_kind(parts[0]), parts)
    if found is None:
        here = _os.path.dirname(_os.path.abspath(__file__))
        for p in (_os.path.join(here, "tools", "tcc", "tcc.exe"),
                  _os.path.join(here, "tools", "tcc", "tcc"),
                  _os.path.join(here, "tools", "gcc", "bin", "gcc.exe")):
            if _os.path.isfile(p):
                found = (_guess_cc_kind(p), [p])
                break
    if found is None:
        for exe in ("tcc", "gcc", "clang", "zig", "cl", "cc"):
            w = _sh.which(exe)
            if w:
                found = (_guess_cc_kind(w), [w])
                break
    if found is None:
        # компиляторы, поставленные через winget (PATH в старых процессах ещё не обновлён)
        import glob as _glob
        la = _os.environ.get("LOCALAPPDATA") or ""
        if la:
            links = _os.path.join(la, "Microsoft", "WinGet", "Links")
            for exe in ("gcc.exe", "clang.exe", "tcc.exe", "zig.exe", "cl.exe"):
                p = _os.path.join(links, exe)
                if _os.path.isfile(p):
                    found = (_guess_cc_kind(p), [p])
                    break
        if found is None and la:
            pats = _glob.glob(_os.path.join(la, "Microsoft", "WinGet", "Packages", "*", "**", "gcc.exe"), recursive=True)
            pats += _glob.glob(_os.path.join(la, "Microsoft", "WinGet", "Packages", "*", "**", "clang.exe"), recursive=True)
            if pats:
                p = sorted(pats)[0]
                found = (_guess_cc_kind(p), [p])
    _CC_CACHE.append(found)
    return found

def _sf_note(msg):
    import os as _os
    if _os.environ.get("DIS_SUPERFAST_QUIET"):
        return
    sys.stderr.write("[superfast] %s\n" % msg)
    sys.stderr.flush()

def run_superfast_c(stmts, filename):
    """Пробует выполнить скрипт нативным C. Код выхода или None (обычный режим)."""
    try:
        code = CGen(stmts).generate()
    except CUnsupported as u:
        _sf_note("%s — выполняю обычным способом" % u.reason)
        return None
    cc = find_c_compiler()
    if cc is None:
        _sf_note("C-компилятор не найден (нужен gcc/clang/cl/tcc/zig) — выполняю обычным способом")
        return None
    kind, base = cc
    import os as _os
    import subprocess as _sp
    import tempfile as _tf
    import shutil as _sh
    name = _os.path.basename(base[0])
    tmpdir = _tf.mkdtemp(prefix="dis_superfast_")
    try:
        import hashlib
        cpath = _os.path.join(tmpdir, "prog.c")
        with open(cpath, "w", encoding="utf-8") as fh:
            fh.write(code)
        cache = _os.path.join(_tf.gettempdir(), "deinstall_c_cache")
        try:
            if not _os.path.isdir(cache):
                _os.makedirs(cache)
        except OSError:
            cache = None
        if cache:
            exe = _os.path.join(cache, "dis_%s.exe" % hashlib.sha1(code.encode("utf-8")).hexdigest()[:16])
        else:
            exe = _os.path.join(tmpdir, "prog.exe" if _os.name == "nt" else "prog")
        if cache and _os.path.isfile(exe):
            _sf_note("%s: беру готовый нативный код из кэша" % name)
            try:
                r = _sp.run([exe], cwd=_os.getcwd())
            except KeyboardInterrupt:
                return 130
            return r.returncode
        if kind == "zig":
            cmd = base + ["cc", "-O2", "-o", exe, cpath]
        elif kind == "tcc":
            cmd = base + ["-o", exe, cpath]
        elif kind == "cl":
            cmd = base + ["/nologo", "/O2", "/utf-8", cpath, "/Fe:" + exe]
        else:
            cmd = base + ["-O2", "-o", exe, cpath, "-lm"]
        try:
            pr = _sp.run(cmd, cwd=tmpdir, capture_output=True, text=True, timeout=120)
        except BaseException as e:
            _sf_note("не удалось запустить %s (%s) — выполняю обычным способом" % (name, e))
            return None
        if pr.returncode != 0:
            err = (pr.stderr or pr.stdout or "").strip()
            _sf_note("C-компиляция не удалась — выполняю обычным способом")
            if err:
                _sf_note(err.splitlines()[0][:300])
            return None
        _sf_note("%s: собрал нативный код — запускаю" % name)
        try:
            r = _sp.run([exe], cwd=_os.getcwd())
        except KeyboardInterrupt:
            return 130
        return r.returncode
    finally:
        _sh.rmtree(tmpdir, ignore_errors=True)

# ============================================================ Оформление ошибок

def render_error(err, source_lines=None, filename=None):
    out = ["DeinstallError: %s" % err.message]
    if filename:
        out.append("  файл: %s" % filename)
    if err.line and source_lines and 0 < err.line <= len(source_lines):
        out.append("  строка %d: %s" % (err.line, source_lines[err.line-1].rstrip()))
    elif err.line:
        out.append("  строка %d" % err.line)
    return "\n".join(out)

def run_source(source, argv, filename=None, interp=None, stmts=None):
    lines = source.splitlines()
    if stmts is None:
        try:
            stmts = parse(source)
        except DisSyntaxError as e:
            print(render_error(e, lines, filename), file=sys.stderr)
            return None
    if interp is None:
        interp = Interpreter(argv)
    try:
        interp.run(stmts)
    except _Exit as e:
        sys.exit(e.code)
    except DisError as e:
        msg = render_error(e, lines, filename)
        tb = interp.traceback()
        if tb:
            msg += "\n" + "\n".join(tb)
        print(msg, file=sys.stderr)
        return None
    return interp

# ============================================================ REPL

def _code_unbalanced(s):
    depth = 0
    instr = None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if instr:
            if c == "\\":
                i += 2; continue
            if c == instr:
                instr = None
        elif c in "\"'":
            if s[i:i+3] == c * 3:
                instr = c * 3; i += 3; continue
            instr = c
        elif c == "#":
            break
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        i += 1
    return depth > 0 or instr is not None

_pending = []

def _read_line(prompt):
    if _pending:
        return _pending.pop(0)
    try:
        return input(prompt)
    except EOFError:
        raise SystemExit(0)

def read_statement():
    first = _read_line("dis> ")
    lines = [first]
    while True:
        src = "\n".join(lines)
        if _code_unbalanced(src):
            lines.append(_read_line("... "))
            continue
        stripped = lines[-1]
        cut = stripped.find("#")
        if cut >= 0:
            stripped = stripped[:cut]
        if stripped.rstrip().endswith(":"):
            while True:
                line = _read_line("... ")
                if line.strip() == "":
                    lines.append(line); continue
                if line[:1] in " \t":
                    lines.append(line); continue
                _pending.append(line)
                break
        return "\n".join(lines)

def repl():
    print("Deinstall Script %s (Python). help() — справка, exit() — выход." % VERSION)
    interp = Interpreter(["<repl>"])
    while True:
        try:
            src = read_statement()
        except KeyboardInterrupt:
            print()
            continue
        if not src.strip():
            continue
        try:
            stmts = parse(src)
            last = _MISSING
            for s in stmts:
                if isinstance(s, NExpr):
                    last = interp.eval(s.value, interp.globals)
                else:
                    interp.exec(s, interp.globals)
            if last is not _MISSING and last is not None:
                print(repr(last))
        except (DisSyntaxError, DisRuntimeError) as e:
            print(render_error(e, src.splitlines()), file=sys.stderr)
        except _Exit as e:
            raise SystemExit(e.code)
        except KeyboardInterrupt:
            print()
        except SystemExit:
            raise
        except BaseException as e:
            print("DeinstallError: %s" % (str(e) or type(e).__name__), file=sys.stderr)

# ============================================================ CLI

HELP = """Deinstall Script %s — язык программирования (не удаляет ничего!)
Запуск:
  python deinstall.py script.dis [аргументы...]  — выполнить скрипт
  python deinstall.py                            — REPL
  python deinstall.py --check script.dis         — только проверить синтаксис
Синтаксис похож на Python, но: func, elseif, loop, ret, true/false/null,
try/catch, throw. Библиотеки Python доступны через import.
""" % VERSION

def main(args):
    if not args:
        repl()
        return
    a0 = args[0]
    if a0 in ("-v", "--version"):
        print("Deinstall Script %s (Python %d.%d)" % (VERSION, sys.version_info[0], sys.version_info[1]))
        return
    if a0 in ("-h", "--help"):
        print(HELP)
        return
    check = False
    if a0 in ("--check", "-c"):
        check = True
        args = args[1:]
        if not args:
            print(HELP, file=sys.stderr)
            sys.exit(2)
    path = args[0]
    try:
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
    except OSError as e:
        print("DeinstallError: не удалось открыть файл: %s" % e, file=sys.stderr)
        sys.exit(1)
    if check:
        try:
            parse(source)
        except DisSyntaxError as e:
            print(render_error(e, source.splitlines(), path), file=sys.stderr)
            sys.exit(1)
        print("Синтаксис в порядке: %s" % path)
        return
    try:
        stmts = parse(source)
    except DisSyntaxError as e:
        print(render_error(e, source.splitlines(), path), file=sys.stderr)
        sys.exit(1)
    if stmts and isinstance(stmts[0], NSuperfast) and stmts[0].enabled:
        rc = run_superfast_c(stmts, path)
        if rc is not None:
            sys.exit(rc)
    interp = run_source(source, [path] + list(args[1:]), path, stmts=stmts)
    if interp is None:
        sys.exit(1)

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\nПрервано", file=sys.stderr)
        sys.exit(130)
