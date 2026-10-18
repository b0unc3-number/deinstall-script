import java.io.*;
import java.lang.reflect.*;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;
import java.util.concurrent.TimeUnit;

/**
 * Deinstall Script (расширение .dis) — интерпретатор на Java (совместим с Java 8).
 * Синтаксис почти как в Python, но: func / elseif / loop / ret / true-false-null /
 * try-catch / throw. Библиотеки Python доступны через import (мост через python).
 * Запуск:  java DeinstallScript script.dis [args...]
 *          java DeinstallScript              (REPL)
 */
public class DeinstallScript {
    static final String VERSION = "0.1.0";

    // ===================== Ошибки =====================
    static class DisError extends RuntimeException {
        final String msg; int line;
        DisError(String msg, int line) { super(msg); this.msg = msg; this.line = line; }
    }
    static class SyntaxError extends DisError {
        SyntaxError(String msg, int line) { super(msg, line); }
    }
    static class ExitEx extends RuntimeException {
        final int code;
        ExitEx(int code) { super(null, null, false, false); this.code = code; }
    }
    static class RetEx extends RuntimeException {
        final Object value;
        RetEx(Object value) { super(null, null, false, false); this.value = value; }
    }
    static class BreakEx extends RuntimeException {
        BreakEx() { super(null, null, false, false); }
    }
    static class ContEx extends RuntimeException {
        ContEx() { super(null, null, false, false); }
    }

    // ===================== Лексер =====================
    static final Set<String> KEYWORDS = new HashSet<String>(Arrays.asList(
        "func", "if", "elseif", "else", "while", "loop", "in", "ret", "break",
        "continue", "try", "catch", "throw", "import", "as", "and", "or", "not",
        "lambda", "pass", "true", "false", "null", "var"));
    static final String[] OPS3 = {"**=", "//="};
    static final String[] OPS2 = {"==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=", "**", "//"};
    static final String[] OPS1 = {"+", "-", "*", "/", "%", "=", "<", ">", "(", ")", "[", "]", "{", "}", ",", ":", "."};

    static class Token {
        String kind; Object value; int line; boolean fstr; String raw;
        Token(String kind, Object value, int line) { this(kind, value, line, false, ""); }
        Token(String kind, Object value, int line, boolean fstr, String raw) {
            this.kind = kind; this.value = value; this.line = line; this.fstr = fstr; this.raw = raw;
        }
        public String toString() { return kind + "(" + value + ")@" + line; }
    }

    static String unescape(String s, int line) {
        StringBuilder out = new StringBuilder();
        int i = 0, n = s.length();
        while (i < n) {
            char c = s.charAt(i);
            if (c != '\\') { out.append(c); i++; continue; }
            i++;
            if (i >= n) throw new SyntaxError("лишний обратный слэш в строке", line);
            char e = s.charAt(i++);
            switch (e) {
                case 'n': out.append('\n'); break;
                case 't': out.append('\t'); break;
                case 'r': out.append('\r'); break;
                case '0': out.append('\0'); break;
                case '\\': out.append('\\'); break;
                case '\'': out.append('\''); break;
                case '"': out.append('"'); break;
                case 'u': {
                    int j = s.indexOf('}', i);
                    if (j < 0) throw new SyntaxError("незакрытая \\u{...}", line);
                    out.append((char) Integer.parseInt(s.substring(i + 1, j), 16));
                    i = j + 1;
                    break;
                }
                default: out.append('\\').append(e);
            }
        }
        return out.toString();
    }

    static ArrayList<Token> lex(String src) {
        ArrayList<Token> toks = new ArrayList<Token>();
        int i = 0, n = src.length(), line = 1, bracket = 0;
        boolean atBol = true;
        int[] indents = new int[64];
        int iTop = 0;
        indents[0] = 0;

        while (i < n) {
            if (atBol && bracket == 0) {
                int j = i, col = 0;
                while (j < n && (src.charAt(j) == ' ' || src.charAt(j) == '\t')) {
                    col = src.charAt(j) == '\t' ? (col / 4 + 1) * 4 : col + 1;
                    j++;
                }
                if (j < n && src.charAt(j) == '#') {
                    while (j < n && src.charAt(j) != '\n' && src.charAt(j) != '\r') j++;
                }
                if (j < n && (src.charAt(j) == '\n' || src.charAt(j) == '\r')) {
                    if (src.charAt(j) == '\r' && j + 1 < n && src.charAt(j + 1) == '\n') j += 2; else j += 1;
                    line++;
                    i = j;
                    continue;
                }
                if (j >= n) { i = n; break; }
                if (col > indents[iTop]) {
                    indents[++iTop] = col;
                    toks.add(new Token("INDENT", col, line));
                } else if (col < indents[iTop]) {
                    while (iTop > 0 && col < indents[iTop]) {
                        iTop--;
                        toks.add(new Token("DEDENT", col, line));
                    }
                    if (indents[iTop] != col)
                        throw new SyntaxError("неправильные отступы (табуляция и пробелы не совпадают)", line);
                }
                atBol = false;
                i = j;
                continue;
            }
            char c = src.charAt(i);
            if (c == ' ' || c == '\t') { i++; continue; }
            if (c == '\n') {
                line++;
                if (bracket == 0) {
                    toks.add(new Token("NEWLINE", null, line - 1));
                    atBol = true;
                }
                i++;
                continue;
            }
            if (c == '\r') { i++; continue; }
            if (c == '#') {
                while (i < n && src.charAt(i) != '\n' && src.charAt(i) != '\r') i++;
                continue;
            }
            if (c >= '0' && c <= '9') {
                int start = i;
                if (c == '0' && i + 1 < n && (src.charAt(i + 1) == 'x' || src.charAt(i + 1) == 'X')) {
                    i += 2;
                    while (i < n && Character.digit(src.charAt(i), 16) >= 0) i++;
                    toks.add(new Token("NUM", Long.parseLong(src.substring(start + 2, i), 16), line));
                    continue;
                }
                if (c == '0' && i + 1 < n && (src.charAt(i + 1) == 'b' || src.charAt(i + 1) == 'B')) {
                    i += 2;
                    while (i < n && (src.charAt(i) == '0' || src.charAt(i) == '1')) i++;
                    toks.add(new Token("NUM", Long.parseLong(src.substring(start + 2, i), 2), line));
                    continue;
                }
                boolean isf = false;
                while (i < n && Character.isDigit(src.charAt(i))) i++;
                if (i + 1 < n && src.charAt(i) == '.' && Character.isDigit(src.charAt(i + 1))) {
                    isf = true; i++;
                    while (i < n && Character.isDigit(src.charAt(i))) i++;
                }
                if (i < n && (src.charAt(i) == 'e' || src.charAt(i) == 'E')) {
                    int save = i; i++;
                    if (i < n && (src.charAt(i) == '+' || src.charAt(i) == '-')) i++;
                    if (i < n && Character.isDigit(src.charAt(i))) {
                        while (i < n && Character.isDigit(src.charAt(i))) i++;
                        isf = true;
                    } else i = save;
                }
                String text = src.substring(start, i);
                toks.add(new Token("NUM", isf ? (Object) Double.parseDouble(text) : (Object) Long.parseLong(text), line));
                continue;
            }
            boolean isf = false;
            if ((c == 'f' || c == 'F') && i + 1 < n && (src.charAt(i + 1) == '"' || src.charAt(i + 1) == '\'')) {
                isf = true; i++; c = src.charAt(i);
            } else if ((c == 'f' || c == 'F') && i + 3 < n && src.charAt(i + 1) == src.charAt(i + 2)
                    && src.charAt(i + 1) == src.charAt(i + 3) && (src.charAt(i + 1) == '"' || src.charAt(i + 1) == '\'')) {
                isf = true; i++; c = src.charAt(i);
            }
            if (c == '"' || c == '\'') {
                boolean triple = i + 2 < n && src.charAt(i + 1) == c && src.charAt(i + 2) == c;
                String delim = triple ? "" + c + c + c : "" + c;
                i += delim.length();
                int start = i;
                while (true) {
                    if (i >= n) throw new SyntaxError("незакрытая строка", line);
                    char ch = src.charAt(i);
                    if (ch == '\\') { i += 2; continue; }
                    if (!triple && ch == '\n') throw new SyntaxError("незакрытая строка", line);
                    if (src.startsWith(delim, i)) break;
                    i++;
                }
                String raw = src.substring(start, i);
                i += delim.length();
                if (triple) for (int q = 0; q < raw.length(); q++) if (raw.charAt(q) == '\n') line++;
                toks.add(new Token("STR", null, line, isf, raw));
                continue;
            }
            if (Character.isLetter(c) || c == '_') {
                int start = i;
                while (i < n && (Character.isLetterOrDigit(src.charAt(i)) || src.charAt(i) == '_')) i++;
                String w = src.substring(start, i);
                toks.add(new Token(KEYWORDS.contains(w) ? w : "NAME", w, line));
                continue;
            }
            boolean hit = false;
            String[] all = new String[OPS3.length + OPS2.length + OPS1.length];
            System.arraycopy(OPS3, 0, all, 0, OPS3.length);
            System.arraycopy(OPS2, 0, all, OPS3.length, OPS2.length);
            System.arraycopy(OPS1, 0, all, OPS3.length + OPS2.length, OPS1.length);
            for (String op : all) {
                if (src.startsWith(op, i)) {
                    toks.add(new Token(op, op, line));
                    i += op.length();
                    if (op.equals("(") || op.equals("[") || op.equals("{")) bracket++;
                    else if (op.equals(")") || op.equals("]") || op.equals("}")) {
                        bracket--;
                        if (bracket < 0) throw new SyntaxError("лишняя скобка '" + op + "'", line);
                    }
                    hit = true;
                    break;
                }
            }
            if (!hit) throw new SyntaxError("неизвестный символ '" + c + "'", line);
        }
        if (bracket > 0) throw new SyntaxError("не закрыта скобка", line);
        while (iTop > 0) { iTop--; toks.add(new Token("DEDENT", 0, line)); }
        if (toks.isEmpty() || !toks.get(toks.size() - 1).kind.equals("NEWLINE"))
            toks.add(new Token("NEWLINE", null, line));
        toks.add(new Token("EOF", null, line));
        return toks;
    }

    // ===================== AST =====================
    interface Node { int line(); }
    static abstract class Base implements Node {
        int line;
        Base(int line) { this.line = line; }
        public int line() { return line; }
    }
    static class NNum extends Base { Object v; NNum(Object v, int l){super(l); this.v=v;} }
    static class NStr extends Base { String v; NStr(String v, int l){super(l); this.v=v;} }
    static class NFStr extends Base { List<Object[]> parts; NFStr(List<Object[]> p, int l){super(l); this.parts=p;} }
    static class NLit extends Base { Object v; NLit(Object v, int l){super(l); this.v=v;} }
    static class NName extends Base { String id; NName(String id, int l){super(l); this.id=id;} }
    static class NList extends Base { List<Node> items; NList(List<Node> i, int l){super(l); this.items=i;} }
    static class NDict extends Base { List<Node[]> pairs; NDict(List<Node[]> p, int l){super(l); this.pairs=p;} }
    static class NLambda extends Base {
        List<String[]> params; String rest, kwrest; Node body;
        NLambda(List<String[]> p, String r, String k, Node b, int l){super(l); params=p; rest=r; kwrest=k; body=b;}
    }
    static class NBin extends Base { String op; Node left, right;
        NBin(String op, Node a, Node b, int l){super(l); this.op=op; left=a; right=b;} }
    static class NUn extends Base { String op; Node operand;
        NUn(String op, Node a, int l){super(l); this.op=op; operand=a;} }
    static class NCmp extends Base { Node left; String[] ops; List<Node> rights;
        NCmp(Node a, String[] o, List<Node> r, int l){super(l); left=a; ops=o; rights=r;} }
    static class NCall extends Base {
        Node func; List<Object[]> args; List<Object[]> kwargs;
        NCall(Node f, List<Object[]> a, List<Object[]> k, int l){super(l); func=f; args=a; kwargs=k;}
    }
    static class NIndex extends Base { Node obj, index; NIndex(Node o, Node i, int l){super(l); obj=o; index=i;} }
    static class NSlice extends Base { Node obj, start, stop, step;
        NSlice(Node o, Node a, Node b, Node c, int l){super(l); obj=o; start=a; stop=b; step=c;} }
    static class NAttr extends Base { Node obj; String name; NAttr(Node o, String n, int l){super(l); obj=o; name=n;} }
    static class NAssign extends Base { List<Node> targets, values;
        NAssign(List<Node> t, List<Node> v, int l){super(l); targets=t; values=v;} }
    static class NAug extends Base { Node target; String op; Node value;
        NAug(Node t, String o, Node v, int l){super(l); target=t; op=o; value=v;} }
    static class NExpr extends Base { Node value; NExpr(Node v, int l){super(l); value=v;} }
    static class NIf extends Base { List<Object[]> branches; List<Node> orelse;
        NIf(List<Object[]> b, List<Node> e, int l){super(l); branches=b; orelse=e;} }
    static class NWhile extends Base { Node cond; List<Node> body;
        NWhile(Node c, List<Node> b, int l){super(l); cond=c; body=b;} }
    static class NLoop extends Base { String[] targets; Node iter; List<Node> body;
        NLoop(String[] t, Node i, List<Node> b, int l){super(l); targets=t; iter=i; body=b;} }
    static class NFunc extends Base {
        String name, rest, kwrest; List<Object[]> params; List<Node> body;
        NFunc(String n, List<Object[]> p, String r, String k, List<Node> b, int l){
            super(l); name=n; params=p; rest=r; kwrest=k; body=b;}
    }
    static class NRet extends Base { Node value; NRet(Node v, int l){super(l); value=v;} }
    static class NBreak extends Base { NBreak(int l){super(l);} }
    static class NCont extends Base { NCont(int l){super(l);} }
    static class NPass extends Base { NPass(int l){super(l);} }
    static class NThrow extends Base { Node value; NThrow(Node v, int l){super(l); value=v;} }
    static class NTry extends Base { List<Node> body, cbody; String name;
        NTry(List<Node> b, String n, List<Node> c, int l){super(l); body=b; name=n; cbody=c;} }
    static class NImport extends Base { String module, alias;
        NImport(String m, String a, int l){super(l); module=m; alias=a;} }
    static class NPy2Print extends Base { List<Node> values; boolean nl;
        NPy2Print(List<Node> v, boolean nl, int l){super(l); values=v; this.nl=nl;} }
    static class NSuperfast extends Base { boolean enabled;
        NSuperfast(boolean e, int l){super(l); enabled=e;} }

    static final String[] AUGOPS = {"+=", "-=", "*=", "/=", "//=", "%=", "**="};

    // ===================== Парсер =====================
    static class Parser {
        List<Token> toks; int pos;
        Parser(List<Token> t) { toks = t; }

        Token peek() { return peek(0); }
        Token peek(int k) { return toks.get(Math.min(pos + k, toks.size() - 1)); }
        Token next() { Token t = toks.get(pos); if (!t.kind.equals("EOF")) pos++; return t; }
        boolean check(String kind) { return peek().kind.equals(kind); }
        boolean accept(String kind) { if (check(kind)) { next(); return true; } return false; }
        Token expect(String kind, String msg) {
            if (check(kind)) return next();
            Token t = peek();
            throw new SyntaxError(msg != null ? msg : "ожидалось '" + kind + "', получено '" + t.kind + "'", t.line);
        }

        List<Node> parseProgram() {
            ArrayList<Node> stmts = new ArrayList<Node>();
            while (true) {
                while (accept("NEWLINE")) {}
                if (check("EOF")) break;
                stmts.add(parseStmt());
            }
            return stmts;
        }

        List<Node> parseBlock() {
            expect(":", null);
            Token t = peek();
            if (t.kind.equals("NEWLINE")) {
                next();
                expect("INDENT", "ожидался отступ после ':'");
                ArrayList<Node> body = new ArrayList<Node>();
                while (true) {
                    while (accept("NEWLINE")) {}
                    if (check("DEDENT") || check("EOF")) break;
                    body.add(parseStmt());
                }
                expect("DEDENT", null);
                if (body.isEmpty()) throw new SyntaxError("пустой блок (используйте pass)", t.line);
                return body;
            }
            ArrayList<Node> one = new ArrayList<Node>();
            one.add(parseStmt());
            return one;
        }

        Node parseStmt() {
            Token t = peek();
            String k = t.kind;
            if (k.equals("var")) {
                next();
                Node node = parseSimple();
                if (!(node instanceof NAssign))
                    throw new SyntaxError("после 'var' ожидается присваивание: var x = ...", t.line);
                return node;
            }
            if (k.equals("func")) {
                next();
                String name = (String) expect("NAME", "ожидалось имя функции").value;
                expect("(", null);
                ArrayList<Object[]> params = new ArrayList<Object[]>();
                String rest = null, kwrest = null;
                if (!check(")")) {
                    while (true) {
                        if (accept("**")) kwrest = ((String) expect("NAME", null).value);
                        else if (accept("*")) rest = ((String) expect("NAME", null).value);
                        else {
                            String pname = ((String) expect("NAME", null).value);
                            Node def = null;
                            if (accept("=")) def = parseOr();
                            params.add(new Object[]{pname, def});
                        }
                        if (!accept(",")) break;
                    }
                }
                expect(")", null);
                return new NFunc(name, params, rest, kwrest, parseBlock(), t.line);
            }
            if (k.equals("if")) {
                next();
                ArrayList<Object[]> branches = new ArrayList<Object[]>();
                branches.add(new Object[]{parseOr(), parseBlock()});
                List<Node> orelse = new ArrayList<Node>();
                while (accept("elseif")) branches.add(new Object[]{parseOr(), parseBlock()});
                if (accept("else")) orelse = parseBlock();
                return new NIf(branches, orelse, t.line);
            }
            if (k.equals("while")) { next(); return new NWhile(parseOr(), parseBlock(), t.line); }
            if (k.equals("loop")) {
                next();
                ArrayList<String> targets = new ArrayList<String>();
                if (accept("(")) {
                    targets.add(((String) expect("NAME", null).value));
                    while (accept(",")) targets.add(((String) expect("NAME", null).value));
                    expect(")", null);
                } else {
                    targets.add((String) expect("NAME", "ожидалась переменная цикла").value);
                    while (check(",")) { next(); targets.add(((String) expect("NAME", null).value)); }
                }
                expect("in", "ожидалось 'in'");
                return new NLoop(targets.toArray(new String[0]), parseOr(), parseBlock(), t.line);
            }
            if (k.equals("try")) {
                next();
                List<Node> body = parseBlock();
                expect("catch", "ожидалось 'catch'");
                String name = check("NAME") ? (String) next().value : null;
                return new NTry(body, name, parseBlock(), t.line);
            }
            if (k.equals("ret")) {
                next();
                if (check("NEWLINE") || check("DEDENT") || check("EOF")) return new NRet(null, t.line);
                ArrayList<Node> vals = new ArrayList<Node>();
                vals.add(parseOr());
                while (check(",")) { next(); vals.add(parseOr()); }
                return new NRet(vals.size() == 1 ? vals.get(0) : new NList(vals, t.line), t.line);
            }
            if (k.equals("throw")) { next(); return new NThrow(parseOr(), t.line); }
            if (k.equals("break")) { next(); return new NBreak(t.line); }
            if (k.equals("continue")) { next(); return new NCont(t.line); }
            if (k.equals("pass")) { next(); return new NPass(t.line); }
            if (k.equals("import")) {
                next();
                StringBuilder sb = new StringBuilder(((String) expect("NAME", null).value));
                while (check(".")) { next(); sb.append('.').append(((String) expect("NAME", null).value)); }
                String alias = null;
                if (accept("as")) alias = ((String) expect("NAME", null).value);
                return new NImport(sb.toString(), alias, t.line);
            }
            if (k.equals("NAME") && ((String) t.value).equals("superfast")
                    && peek(1).kind.equals(".") && peek(2).kind.equals("NAME")
                    && (((String) peek(2).value).equals("enable") || ((String) peek(2).value).equals("disable"))
                    && (peek(3).kind.equals("NEWLINE") || peek(3).kind.equals("DEDENT") || peek(3).kind.equals("EOF"))) {
                // директива C-ускорения: superfast.enable / superfast.disable
                next(); next();
                boolean en = ((String) next().value).equals("enable");
                return new NSuperfast(en, t.line);
            }
            if (k.equals("NAME") && ((String) t.value).equals("pythontwo")
                    && peek(1).kind.equals(".") && peek(2).kind.equals("NAME")
                    && ((String) peek(2).value).equals("print")
                    && !peek(3).kind.equals("(") && !peek(3).kind.equals("{")) {
                // печать в стиле Python 2: pythontwo.print "а", "б",
                next(); next(); next();
                ArrayList<Node> values = new ArrayList<Node>();
                boolean nl = true;
                if (!(check("NEWLINE") || check("DEDENT") || check("EOF"))) {
                    values.add(parseOr());
                    while (check(",")) {
                        next();
                        if (check("NEWLINE") || check("DEDENT") || check("EOF")) { nl = false; break; }
                        values.add(parseOr());
                    }
                }
                return new NPy2Print(values, nl, t.line);
            }
            return parseSimple();
        }

        Node parseSimple() {
            Node first = parseOr();
            ArrayList<Node> exprs = new ArrayList<Node>();
            exprs.add(first);
            while (check(",")) { next(); exprs.add(parseOr()); }
            String aug = null;
            for (String op : AUGOPS) if (check(op)) { aug = op; break; }
            if (aug != null) {
                next();
                Node tg = exprs.get(0);
                if (exprs.size() != 1 || !(tg instanceof NName || tg instanceof NIndex || tg instanceof NAttr))
                    throw new SyntaxError("нельзя использовать '" + aug + "' с таким выражением", peek().line);
                return new NAug(tg, aug, parseOr(), tg.line());
            }
            if (accept("=")) {
                ArrayList<Node> values = new ArrayList<Node>();
                values.add(parseOr());
                while (check(",")) { next(); values.add(parseOr()); }
                for (Node tg : exprs)
                    if (!(tg instanceof NName || tg instanceof NIndex || tg instanceof NAttr))
                        throw new SyntaxError("нельзя присвоить этому выражению", tg.line());
                return new NAssign(exprs, values, first.line());
            }
            if (exprs.size() == 1) return new NExpr(first, first.line());
            return new NExpr(new NList(exprs, first.line()), first.line());
        }

        Node parseOr() {
            Node left = parseAnd();
            while (check("or")) { int l = next().line; left = new NBin("or", left, parseAnd(), l); }
            return left;
        }
        Node parseAnd() {
            Node left = parseNot();
            while (check("and")) { int l = next().line; left = new NBin("and", left, parseNot(), l); }
            return left;
        }
        Node parseNot() {
            if (check("not")) { int l = next().line; return new NUn("not", parseNot(), l); }
            return parseCmp();
        }
        Node parseCmp() {
            Node left = parseAdd();
            ArrayList<String> ops = new ArrayList<String>();
            ArrayList<Node> rights = new ArrayList<Node>();
            while (true) {
                Token t = peek();
                String kd = t.kind;
                if (kd.equals("==") || kd.equals("!=") || kd.equals("<") || kd.equals("<=")
                        || kd.equals(">") || kd.equals(">=")) {
                    next(); ops.add(kd); rights.add(parseAdd());
                } else if (kd.equals("in")) {
                    next(); ops.add("in"); rights.add(parseAdd());
                } else if (kd.equals("not") && peek(1).kind.equals("in")) {
                    next(); next(); ops.add("not in"); rights.add(parseAdd());
                } else break;
            }
            if (ops.isEmpty()) return left;
            return new NCmp(left, ops.toArray(new String[0]), rights, left.line());
        }
        Node parseAdd() {
            Node left = parseMul();
            while (peek().kind.equals("+") || peek().kind.equals("-")) {
                Token op = next();
                left = new NBin(op.kind, left, parseMul(), op.line);
            }
            return left;
        }
        Node parseMul() {
            Node left = parseUnary();
            while (peek().kind.equals("*") || peek().kind.equals("/") || peek().kind.equals("//")
                    || peek().kind.equals("%")) {
                Token op = next();
                left = new NBin(op.kind, left, parseUnary(), op.line);
            }
            return left;
        }
        Node parseUnary() {
            if (peek().kind.equals("-") || peek().kind.equals("+")) {
                Token op = next();
                return new NUn(op.kind, parseUnary(), op.line);
            }
            return parsePower();
        }
        Node parsePower() {
            Node base = parsePostfix();
            if (accept("**")) return new NBin("**", base, parseUnary(), base.line());
            return base;
        }
        Node parsePostfix() {
            Node node = parseAtom();
            while (true) {
                if (check("(") || check("{")) {
                    // фирменный синтаксис: вызов функции через () или {}
                    Token open = next();
                    int l = open.line;
                    Object[] ak = parseCallArgs();
                    expect(open.kind.equals("(") ? ")" : "}", null);
                    @SuppressWarnings("unchecked")
                    List<Object[]> args = (List<Object[]>) ak[0];
                    @SuppressWarnings("unchecked")
                    List<Object[]> kwargs = (List<Object[]>) ak[1];
                    node = new NCall(node, args, kwargs, l);
                } else if (check("[")) {
                    int l = next().line;
                    Node first = null;
                    if (!check(":")) first = parseOr();
                    if (accept(":")) {
                        Node stop = null;
                        if (!check("]") && !check(":")) stop = parseOr();
                        Node step = null;
                        if (accept(":")) if (!check("]")) step = parseOr();
                        expect("]", null);
                        node = new NSlice(node, first, stop, step, l);
                    } else {
                        expect("]", null);
                        node = new NIndex(node, first, l);
                    }
                } else if (check(".")) {
                    int l = next().line;
                    node = new NAttr(node, (String) expect("NAME", "ожидалось имя атрибута").value, l);
                } else return node;
            }
        }
        Node parseAtom() {
            Token t = peek();
            String k = t.kind;
            if (k.equals("NUM")) { next(); return new NNum(t.value, t.line); }
            if (k.equals("STR")) {
                next();
                if (t.fstr) return new NFStr(parseFstr(t), t.line);
                return new NStr(unescape(t.raw, t.line), t.line);
            }
            if (k.equals("true") || k.equals("True")) { next(); return new NLit(Boolean.TRUE, t.line); }
            if (k.equals("false") || k.equals("False")) { next(); return new NLit(Boolean.FALSE, t.line); }
            if (k.equals("null") || k.equals("None")) { next(); return new NLit(null, t.line); }
            if (k.equals("lambda")) {
                next();
                ArrayList<String[]> params = new ArrayList<String[]>();
                String rest = null, kwrest = null;
                if (!check(":")) {
                    while (true) {
                        if (accept("**")) kwrest = ((String) expect("NAME", null).value);
                        else if (accept("*")) rest = ((String) expect("NAME", null).value);
                        else params.add(new String[]{((String) expect("NAME", null).value), null});
                        if (!accept(",")) break;
                    }
                }
                expect(":", null);
                return new NLambda(params, rest, kwrest, parseOr(), t.line);
            }
            if (k.equals("NAME")) { next(); return new NName((String) t.value, t.line); }
            if (k.equals("(")) {
                next();
                ArrayList<Node> items = new ArrayList<Node>();
                if (!check(")")) {
                    items.add(parseOr());
                    while (accept(",")) { if (check(")")) break; items.add(parseOr()); }
                }
                expect(")", null);
                if (items.size() == 1) return items.get(0);
                return new NList(items, t.line);   // кортежи — списки
            }
            if (k.equals("[")) {
                next();
                ArrayList<Node> items = new ArrayList<Node>();
                if (!check("]")) {
                    items.add(parseOr());
                    while (accept(",")) { if (check("]")) break; items.add(parseOr()); }
                }
                expect("]", null);
                return new NList(items, t.line);
            }
            if (k.equals("{")) {
                next();
                ArrayList<Node[]> pairs = new ArrayList<Node[]>();
                if (!check("}")) {
                    Node key = parseOr();
                    expect(":", null);
                    pairs.add(new Node[]{key, parseOr()});
                    while (accept(",")) {
                        if (check("}")) break;
                        key = parseOr();
                        expect(":", null);
                        pairs.add(new Node[]{key, parseOr()});
                    }
                }
                expect("}", null);
                return new NDict(pairs, t.line);
            }
            throw new SyntaxError("неожиданный токен '" + k + "'", t.line);
        }

        List<Object[]> parseFstr(Token tok) {
            String raw = tok.raw;
            ArrayList<Object[]> parts = new ArrayList<Object[]>();
            int i = 0;
            StringBuilder buf = new StringBuilder();
            while (i < raw.length()) {
                char c = raw.charAt(i);
                if (c == '{') {
                    if (i + 1 < raw.length() && raw.charAt(i + 1) == '{') { buf.append('{'); i += 2; continue; }
                    int depth = 0, j = i + 1;
                    Character instr = null;
                    while (j < raw.length()) {
                        char ch = raw.charAt(j);
                        if (instr != null) {
                            if (ch == '\\') { j += 2; continue; }
                            if (ch == instr) instr = null;
                        } else if (ch == '"' || ch == '\'') instr = ch;
                        else if (ch == '{') depth++;
                        else if (ch == '}') { if (depth == 0) break; depth--; }
                        j++;
                    }
                    if (j >= raw.length()) throw new SyntaxError("незакрытая '{' в f-строке", tok.line);
                    String inner = raw.substring(i + 1, j);
                    String exprSrc = inner, spec = null;
                    int d2 = 0, sp = -1;
                    Character in2 = null;
                    for (int p = 0; p < inner.length(); p++) {
                        char ch = inner.charAt(p);
                        if (in2 != null) { if (ch == '\\') p++; else if (ch == in2) in2 = null; }
                        else if (ch == '"' || ch == '\'') in2 = ch;
                        else if (ch == '(' || ch == '[' || ch == '{') d2++;
                        else if (ch == ')' || ch == ']' || ch == '}') d2--;
                        else if (ch == ':' && d2 == 0) { sp = p; break; }
                    }
                    if (sp >= 0) { exprSrc = inner.substring(0, sp); spec = inner.substring(sp + 1); }
                    if (exprSrc.trim().isEmpty()) throw new SyntaxError("пустые фигурные скобки в f-строке", tok.line);
                    Node node = parseFragment(exprSrc, tok.line);
                    parts.add(new Object[]{buf.toString(), node, spec});
                    buf.setLength(0);
                    i = j + 1;
                } else if (c == '}') {
                    if (i + 1 < raw.length() && raw.charAt(i + 1) == '}') { buf.append('}'); i += 2; continue; }
                    throw new SyntaxError("непарная '}' в f-строке", tok.line);
                } else { buf.append(c); i++; }
            }
            parts.add(new Object[]{buf.toString(), null, null});
            return parts;
        }
        Object[] parseCallArgs() {
            ArrayList<Object[]> args = new ArrayList<Object[]>();
            ArrayList<Object[]> kwargs = new ArrayList<Object[]>();
            if (check(")") || check("}")) return new Object[]{args, kwargs};
            while (true) {
                if (accept("**")) kwargs.add(new Object[]{"dstar", "", parseOr()});
                else if (accept("*")) args.add(new Object[]{"star", parseOr()});
                else {
                    Node e = parseOr();
                    if (check("=") && e instanceof NName) {
                        next();
                        kwargs.add(new Object[]{"kw", ((NName) e).id, parseOr()});
                    } else args.add(new Object[]{"pos", e});
                }
                if (!accept(",")) break;
            }
            return new Object[]{args, kwargs};
        }
    }

    static Node parseFragment(String src, int line) {
        Parser p = new Parser(lex(src));
        Node node = p.parseOr();
        while (p.check("NEWLINE")) p.next();
        if (!p.check("EOF"))
            throw new SyntaxError("лишний код внутри фигурных скобок f-строки", line);
        return node;
    }

    static List<Node> parse(String source) {
        return new Parser(lex(source)).parseProgram();
    }

    // ===================== Значения и окружения =====================
    static final Object MISSING = new Object();

    static class Env {
        Map<String, Object> vars = new LinkedHashMap<String, Object>();
        Env parent;
        Env(Env parent) { this.parent = parent; }

        Object lookup(String name) {
            for (Env e = this; e != null; e = e.parent) {
                if (e.vars.containsKey(name)) return e.vars.get(name);
            }
            throw new DisError("неизвестная переменная '" + name + "'", 0);
        }
        void assign(String name, Object value) {
            for (Env e = this; e != null; e = e.parent) {
                if (e.vars.containsKey(name)) { e.vars.put(name, value); return; }
            }
            vars.put(name, value);
        }
        void define(String name, Object value) { vars.put(name, value); }
    }

    interface Builtin { Object call(Interpreter ip, List<Object> args, Map<String, Object> kwargs, int line); }

    static class FuncVal {
        String name, rest, kwrest;
        List<Object[]> params = new ArrayList<Object[]>();   // {имя, значение по умолчанию | MISSING}
        List<Node> body;
        Env env;
        int line;
        FuncVal(NFunc node, Env env) {
            this.name = node.name; this.rest = node.rest; this.kwrest = node.kwrest;
            this.body = node.body; this.env = env; this.line = node.line;
            for (Object[] p : node.params) {
                Node def = (Node) p[1];
                params.add(new Object[]{p[0], def == null ? MISSING : Interpreter.current.eval(def, env)});
            }
        }
    }

    static class LambdaVal {
        List<Object[]> params = new ArrayList<Object[]>();
        String rest, kwrest;
        List<Node> body;
        Env env;
        int line;
        LambdaVal(NLambda node, Env env) {
            for (Object[] p : node.params) params.add(new Object[]{p[0], MISSING});
            this.rest = node.rest; this.kwrest = node.kwrest;
            this.body = new ArrayList<Node>();
            body.add(new NRet(node.body, node.line));
            this.env = env; this.line = node.line;
        }
    }

    static class ErrorVal {
        final String message, kind; final int line;
        ErrorVal(String message, int line, String kind) { this.message = message; this.line = line; this.kind = kind; }
    }

    static class RangeVal {
        final long from, to, step;
        RangeVal(long from, long to, long step) { this.from = from; this.to = to; this.step = step; }
        long size() {
            if (step > 0) return from >= to ? 0 : (to - from + step - 1) / step;
            return from <= to ? 0 : (from - to - step - 1) / (-step);
        }
        long get(long i) { return from + i * step; }
    }

    static class JavaClassVal { final Class<?> cls; JavaClassVal(Class<?> c) { cls = c; } }

    static class PyModuleVal {
        final String name;
        Map<String, Object> attrs = new LinkedHashMap<String, Object>();
        PyModuleVal(String name) { this.name = name; }
    }

    static class Bound {
        final Object recv; final String name;
        Bound(Object recv, String name) { this.recv = recv; this.name = name; }
    }

    static class ReflectStatic implements Builtin {
        final Class<?> cls; final String name;
        ReflectStatic(Class<?> cls, String name) { this.cls = cls; this.name = name; }
        public Object call(Interpreter ip, List<Object> args, Map<String, Object> kwargs, int line) {
            if (!kwargs.isEmpty()) throw new DisError("статические методы Java не принимают именованные аргументы", line);
            return ip.reflectInvoke(null, cls, name, args, line);
        }
    }

    // ===================== Исполнитель =====================
    static class Interpreter {
        static Interpreter current = null;
        Env globals;
        List<String[]> frames = new ArrayList<String[]>();

        Interpreter(List<String> argv) {
            globals = new Env(null);
            globals.define("argv", new ArrayList<Object>(argv));
            installBuiltins(globals);
        }

        void run(List<Node> stmts) {
            Interpreter prev = Interpreter.current;
            Interpreter.current = this;
            try {
                for (Node s : stmts) exec(s, globals);
            } finally {
                Interpreter.current = prev;
            }
        }

        List<String> traceback() {
            List<String> out = new ArrayList<String>();
            for (int i = frames.size() - 1; i >= 0; i--)
                out.add("  строка " + frames.get(i)[1] + ", " + frames.get(i)[0]);
            return out;
        }

        boolean truthy(Object o) {
            if (o == null) return false;
            if (o instanceof Boolean) return (Boolean) o;
            if (o instanceof Long) return ((Long) o) != 0L;
            if (o instanceof Double) { double d = (Double) o; return d != 0 && !Double.isNaN(d); }
            if (o instanceof String) return !((String) o).isEmpty();
            if (o instanceof List) return !((List<?>) o).isEmpty();
            if (o instanceof Map) return !((Map<?, ?>) o).isEmpty();
            if (o instanceof RangeVal) return ((RangeVal) o).size() > 0;
            return true;
        }

        // ---------- выполнение операторов ----------
        void exec(Node node, Env env) {
            if (node instanceof NExpr) { eval(((NExpr) node).value, env); return; }
            if (node instanceof NPass) return;
            if (node instanceof NAssign) {
                NAssign a = (NAssign) node;
                ArrayList<Object> vals = new ArrayList<Object>();
                for (Node v : a.values) vals.add(eval(v, env));
                if (a.targets.size() == 1) {
                    Object value = vals.size() == 1 ? vals.get(0) : vals;
                    assignTo(a.targets.get(0), value, env);
                } else {
                    if (vals.size() == 1) vals = unpack(vals.get(0), a.targets.size(), a.line);
                    if (vals.size() != a.targets.size())
                        throw new DisError("не то количество значений для присваивания", a.line);
                    for (int i = 0; i < vals.size(); i++) assignTo(a.targets.get(i), vals.get(i), env);
                }
                return;
            }
            if (node instanceof NAug) {
                NAug a = (NAug) node;
                Object cur = eval(a.target, env);
                Object val = eval(a.value, env);
                String op = a.op.substring(0, a.op.length() - 1);
                Object res = binop(op.equals("=") ? a.op : op, cur, val, a.line);
                assignTo(a.target, res, env);
                return;
            }
            if (node instanceof NIf) {
                NIf s = (NIf) node;
                for (Object[] br : s.branches) {
                    if (truthy(eval((Node) br[0], env))) { execBlock((List<Node>) br[1], env); return; }
                }
                execBlock(s.orelse, env);
                return;
            }
            if (node instanceof NWhile) {
                NWhile s = (NWhile) node;
                while (truthy(eval(s.cond, env))) {
                    try { execBlock(s.body, env); }
                    catch (BreakEx b) { break; }
                    catch (ContEx c) { /* continue */ }
                }
                return;
            }
            if (node instanceof NLoop) {
                NLoop s = (NLoop) node;
                Object it = eval(s.iter, env);
                Iterator<Object> iter = iterOf(it, s.line);
                while (iter.hasNext()) {
                    Object item = iter.next();
                    if (s.targets.length == 1) env.assign(s.targets[0], item);
                    else {
                        ArrayList<Object> vals = unpack(item, s.targets.length, s.line);
                        for (int i = 0; i < s.targets.length; i++) env.assign(s.targets[i], vals.get(i));
                    }
                    try { execBlock(s.body, env); }
                    catch (BreakEx b) { break; }
                    catch (ContEx c) { /* continue */ }
                }
                return;
            }
            if (node instanceof NFunc) {
                env.define(((NFunc) node).name, new FuncVal((NFunc) node, env));
                return;
            }
            if (node instanceof NRet) {
                NRet s = (NRet) node;
                throw new RetEx(s.value == null ? null : eval(s.value, env));
            }
            if (node instanceof NBreak) throw new BreakEx();
            if (node instanceof NCont) throw new ContEx();
            if (node instanceof NThrow) {
                Object v = eval(((NThrow) node).value, env);
                throw new DisError(v instanceof ErrorVal ? ((ErrorVal) v).message : str(v), node.line());
            }
            if (node instanceof NTry) {
                NTry s = (NTry) node;
                try {
                    execBlock(s.body, env);
                } catch (RetEx r) { throw r; }
                catch (BreakEx b) { throw b; }
                catch (ContEx c) { throw c; }
                catch (ExitEx e) { throw e; }
                catch (DisError e) {
                    if (e.line == 0) e.line = s.line;
                    Env child = new Env(env);
                    if (s.name != null)
                        child.define(s.name, new ErrorVal(e.msg, e.line, e instanceof SyntaxError ? "SyntaxError" : "RuntimeError"));
                    execBlock(s.cbody, child);
                } catch (StackOverflowError e) {
                    Env child = new Env(env);
                    if (s.name != null) child.define(s.name, new ErrorVal("переполнение стека рекурсии", s.line, "RuntimeError"));
                    execBlock(s.cbody, child);
                }
                return;
            }
            if (node instanceof NImport) {
                NImport s = (NImport) node;
                Object mod = doImport(s.module, s.line);
                String bind;
                if (s.alias != null) bind = s.alias;
                else if (mod instanceof JavaClassVal) {
                    int dot = s.module.lastIndexOf('.');
                    bind = dot >= 0 ? s.module.substring(dot + 1) : s.module;
                } else bind = s.module.split("\\.")[0];
                env.assign(bind, mod);
                return;
            }
            if (node instanceof NPy2Print) {
                NPy2Print s = (NPy2Print) node;
                StringBuilder sb = new StringBuilder();
                boolean first = true;
                for (Node v : s.values) {
                    if (!first) sb.append(' ');
                    first = false;
                    sb.append(str(eval(v, env)));
                }
                sb.append(s.nl ? "\n" : " ");
                System.out.print(sb.toString());
                System.out.flush();
                return;
            }
            if (node instanceof NSuperfast) {
                // директива superfast: C-ускорение выполняет Python-версия (deinstall.py)
                return;
            }
            throw new DisError("неизвестный узел", node.line());
        }

        void execBlock(List<Node> body, Env env) {
            if (body == null) return;
            for (Node s : body) exec(s, env);
        }

        void assignTo(Node target, Object value, Env env) {
            if (target instanceof NName) { env.assign(((NName) target).id, value); return; }
            if (target instanceof NIndex) {
                NIndex t = (NIndex) target;
                Object obj = eval(t.obj, env);
                Object idx = eval(t.index, env);
                indexSet(obj, idx, value, t.line);
                return;
            }
            if (target instanceof NAttr) throw new DisError("установка атрибутов в Java-версии не поддерживается", target.line());
            throw new DisError("нельзя присвоить этому выражению", target.line());
        }

        ArrayList<Object> unpack(Object item, int count, int line) {
            ArrayList<Object> seq = new ArrayList<Object>();
            if (item instanceof String) {
                for (char ch : ((String) item).toCharArray()) seq.add(String.valueOf(ch));
            } else if (item instanceof List) {
                seq.addAll((List<?>) item);
            } else if (item instanceof Map) {
                seq.addAll(((Map<?, ?>) item).keySet());
            } else if (item instanceof RangeVal) {
                Iterator<Object> it = iterOf(item, line);
                while (it.hasNext()) seq.add(it.next());
            } else {
                throw new DisError("нельзя разложить объект типа '" + tname(item) + "'", line);
            }
            if (seq.size() != count)
                throw new DisError("не удалось разложить: ожидалось " + count + " значений, получено " + seq.size(), line);
            return seq;
        }

        static Iterator<Object> iterOf(final Object o, final int line) {
            if (o instanceof List) return (Iterator<Object>) (Iterator<?>) ((List<?>) o).iterator();
            if (o instanceof Map) return (Iterator<Object>) (Iterator<?>) ((Map<?, ?>) o).keySet().iterator();
            if (o instanceof String) {
                final char[] cs = ((String) o).toCharArray();
                return new Iterator<Object>() {
                    int i = 0;
                    public boolean hasNext() { return i < cs.length; }
                    public Object next() { return String.valueOf(cs[i++]); }
                };
            }
            if (o instanceof RangeVal) {
                final RangeVal r = (RangeVal) o;
                return new Iterator<Object>() {
                    long i = 0;
                    public boolean hasNext() { return i < r.size(); }
                    public Object next() { return Long.valueOf(r.get(i++)); }
                };
            }
            throw new DisError("по объекту типа '" + tname(o) + "' нельзя итерироваться", line);
        }

        // ---------- вызовы ----------
        Object call(Object f, List<Object> args, Map<String, Object> kwargs, int line) {
            if (f instanceof FuncVal) return callUser((FuncVal) f, args, kwargs, line);
            if (f instanceof LambdaVal) return callUser((LambdaVal) f, args, kwargs, line);
            if (f instanceof Builtin) return ((Builtin) f).call(this, args, kwargs, line);
            if (f instanceof Bound) {
                Bound b = (Bound) f;
                return dispatchMethod(b.recv, b.name, args, kwargs, line);
            }
            if (f instanceof JavaClassVal) return construct((JavaClassVal) f, args, line);
            if (f instanceof ErrorVal)
                throw new DisError("объект ошибки '" + ((ErrorVal) f).message + "' нельзя вызвать", line);
            throw new DisError("объект типа '" + tname(f) + "' не является функцией", line);
        }

        Object callUser(FuncVal f, List<Object> args, Map<String, Object> kwargs, int line) {
            return callFuncBody(f.name, f.params, f.rest, f.kwrest, f.body, f.env, args, kwargs, line);
        }

        Object callUser(LambdaVal f, List<Object> args, Map<String, Object> kwargs, int line) {
            return callFuncBody("<lambda>", f.params, f.rest, f.kwrest, f.body, f.env, args, kwargs, line);
        }

        Object callFuncBody(String fname, List<Object[]> params, String rest, String kwrest,
                            List<Node> body, Env defEnv, List<Object> args, Map<String, Object> kwargs, int line) {
            Env env = new Env(defEnv);
            LinkedHashMap<String, Object> kw = new LinkedHashMap<String, Object>(kwargs);
            int i = 0;
            for (Object[] p : params) {
                String pname = (String) p[0];
                if (i < args.size()) { env.define(pname, args.get(i)); i++; }
                else if (kw.containsKey(pname)) { env.define(pname, kw.remove(pname)); }
                else if (p[1] != MISSING) { env.define(pname, p[1]); }
                else throw new DisError("не передан аргумент '" + pname + "' в " + fname + "()", line);
            }
            if (rest != null) {
                env.define(rest, new ArrayList<Object>(args.subList(i, args.size())));
                i = args.size();
            }
            if (i < args.size()) throw new DisError("слишком много аргументов для " + fname + "()", line);
            if (!kw.isEmpty()) {
                if (kwrest != null) env.define(kwrest, kw);
                else throw new DisError("лишние именованные аргументы: " + joinStr(kw.keySet(), ", "), line);
            }
            frames.add(new String[]{fname, String.valueOf(line)});
            try {
                execBlock(body, env);
            } catch (RetEx r) {
                return r.value;
            } finally {
                frames.remove(frames.size() - 1);
            }
            return null;
        }

        Object construct(JavaClassVal cv, List<Object> args, int line) {
            for (Constructor<?> c : cv.cls.getConstructors()) {
                Object[] coerced = coerceParams(c.getParameterTypes(), args);
                if (coerced != null) {
                    try {
                        return c.newInstance(coerced);
                    } catch (InvocationTargetException e) {
                        throw new DisError("Java-исключение: " + e.getCause(), line);
                    } catch (Exception e) {
                        throw new DisError("не удалось создать объект: " + e, line);
                    }
                }
            }
            throw new DisError("нет подходящего конструктора для " + cv.cls.getName(), line);
        }

        Object reflectInvoke(Object recv, Class<?> cls, String name, List<Object> args, int line) {
            Method best = null; Object[] bestArgs = null; int bestScore = -1;
            for (Method m : cls.getMethods()) {
                if (!m.getName().equals(name)) continue;
                if (recv == null && !Modifier.isStatic(m.getModifiers())) continue;
                Object[] coerced = coerceParams(m.getParameterTypes(), args);
                if (coerced == null) continue;
                int score = scoreParams(m.getParameterTypes());
                if (score > bestScore) { bestScore = score; best = m; bestArgs = coerced; }
            }
            if (best == null)
                throw new DisError("метод " + cls.getSimpleName() + "." + name + " не найден (аргументы не подходят)", line);
            try {
                return best.invoke(recv, bestArgs);
            } catch (InvocationTargetException e) {
                throw new DisError("Java-исключение: " + e.getCause(), line);
            } catch (Exception e) {
                throw new DisError("ошибка вызова Java-метода: " + e, line);
            }
        }

        static int scoreParams(Class<?>[] pts) {
            int s = 0;
            for (Class<?> p : pts) if (!p.equals(Object.class)) s++;
            return s;
        }

        Object[] coerceParams(Class<?>[] pts, List<Object> args) {
            if (pts.length != args.size()) return null;
            Object[] out = new Object[pts.length];
            for (int i = 0; i < pts.length; i++) {
                Object a = args.get(i);
                Class<?> p = pts[i];
                if (a == null) {
                    if (p.isPrimitive()) return null;
                    out[i] = null; continue;
                }
                if (p.isInstance(a)) { out[i] = a; continue; }
                if (a instanceof Long) {
                    long v = (Long) a;
                    if (p == long.class || p == Long.class) { out[i] = v; continue; }
                    if (p == int.class || p == Integer.class) { out[i] = (int) v; continue; }
                    if (p == short.class || p == Short.class) { out[i] = (short) v; continue; }
                    if (p == byte.class || p == Byte.class) { out[i] = (byte) v; continue; }
                    if (p == double.class || p == Double.class) { out[i] = (double) v; continue; }
                    if (p == float.class || p == Float.class) { out[i] = (float) v; continue; }
                    if (p == char.class || p == Character.class) { out[i] = (char) v; continue; }
                }
                if (a instanceof Double) {
                    double v = (Double) a;
                    if (p == double.class || p == Double.class) { out[i] = v; continue; }
                    if (p == float.class || p == Float.class) { out[i] = (float) v; continue; }
                }
                if (a instanceof Boolean && (p == boolean.class || p == Boolean.class)) { out[i] = a; continue; }
                if (a instanceof String) {
                    if (p == String.class) { out[i] = a; continue; }
                    if (p == char.class && ((String) a).length() == 1) { out[i] = ((String) a).charAt(0); continue; }
                }
                if (a instanceof List && List.class.isAssignableFrom(p)) { out[i] = a; continue; }
                if (a instanceof Map && Map.class.isAssignableFrom(p)) { out[i] = a; continue; }
                return null;
            }
            return out;
        }

        // ---------- вычисление выражений ----------
        Object eval(Node node, Env env) {
            if (node instanceof NNum) return ((NNum) node).v;
            if (node instanceof NStr) return ((NStr) node).v;
            if (node instanceof NLit) return ((NLit) node).v;
            if (node instanceof NFStr) {
                StringBuilder sb = new StringBuilder();
                for (Object[] part : ((NFStr) node).parts) {
                    sb.append((String) part[0]);
                    Node sub = (Node) part[1];
                    if (sub != null) {
                        Object v = eval(sub, env);
                        String spec = (String) part[2];
                        try {
                            sb.append(spec == null ? str(v) : applyFormat(v, spec, node.line()));
                        } catch (DisError e) { throw e; }
                        catch (RuntimeException e) {
                            throw new DisError("ошибка формата в f-строке: " + e.getMessage(), node.line());
                        }
                    }
                }
                return sb.toString();
            }
            if (node instanceof NName) {
                try {
                    return env.lookup(((NName) node).id);
                } catch (DisError e) {
                    if (e.line == 0) e.line = node.line();
                    throw e;
                }
            }
            if (node instanceof NList) {
                ArrayList<Object> out = new ArrayList<Object>();
                for (Node i : ((NList) node).items) out.add(eval(i, env));
                return out;
            }
            if (node instanceof NDict) {
                LinkedHashMap<Object, Object> d = new LinkedHashMap<Object, Object>();
                for (Node[] kv : ((NDict) node).pairs) {
                    Object k = eval(kv[0], env);
                    if (k instanceof List || k instanceof Map)
                        throw new DisError("ключ словаря должен быть неизменяемым", node.line());
                    d.put(k, eval(kv[1], env));
                }
                return d;
            }
            if (node instanceof NLambda) return new LambdaVal((NLambda) node, env);
            if (node instanceof NBin) {
                NBin b = (NBin) node;
                if (b.op.equals("and")) {
                    Object l = eval(b.left, env);
                    return truthy(l) ? eval(b.right, env) : l;
                }
                if (b.op.equals("or")) {
                    Object l = eval(b.left, env);
                    return truthy(l) ? l : eval(b.right, env);
                }
                Object l = eval(b.left, env);
                Object r = eval(b.right, env);
                return binop(b.op, l, r, b.line);
            }
            if (node instanceof NUn) {
                NUn u = (NUn) node;
                Object v = eval(u.operand, env);
                if (u.op.equals("not")) return !truthy(v);
                if (!isNum(v)) throw new DisError("унарный '" + u.op + "' нельзя применить к типу '" + tname(v) + "'", u.line);
                if (v instanceof Boolean) return Long.valueOf(u.op.equals("-") ? -1L : 1L);
                return u.op.equals("-") ? negate(v) : v;
            }
            if (node instanceof NCmp) {
                NCmp c = (NCmp) node;
                Object prev = eval(c.left, env);
                for (int i = 0; i < c.ops.length; i++) {
                    Object cur = eval(c.rights.get(i), env);
                    if (!cmpop(c.ops[i], prev, cur, c.line)) return Boolean.FALSE;
                    prev = cur;
                }
                return Boolean.TRUE;
            }
            if (node instanceof NCall) {
                NCall c = (NCall) node;
                Object f = eval(c.func, env);
                ArrayList<Object> args = new ArrayList<Object>();
                LinkedHashMap<String, Object> kwargs = new LinkedHashMap<String, Object>();
                for (Object[] a : c.args) {
                    Object v = eval((Node) a[1], env);
                    if (a[0].equals("pos")) args.add(v);
                    else {
                        try { iterOf(v, c.line); }
                        catch (DisError e) { throw new DisError("*аргумент должен быть последовательностью", c.line); }
                        Iterator<Object> it = iterOf(v, c.line);
                        while (it.hasNext()) args.add(it.next());
                    }
                }
                for (Object[] a : c.kwargs) {
                    Object v = eval((Node) a[2], env);
                    if (a[0].equals("kw")) kwargs.put((String) a[1], v);
                    else {
                        if (!(v instanceof Map)) throw new DisError("**аргумент должен быть словарём", c.line);
                        for (Map.Entry<?, ?> en : ((Map<?, ?>) v).entrySet())
                            kwargs.put(String.valueOf(en.getKey()), en.getValue());
                    }
                }
                return call(f, args, kwargs, c.line);
            }
            if (node instanceof NIndex) {
                NIndex ix = (NIndex) node;
                return indexGet(eval(ix.obj, env), eval(ix.index, env), ix.line);
            }
            if (node instanceof NSlice) {
                NSlice s = (NSlice) node;
                Object obj = eval(s.obj, env);
                Long a = s.start == null ? null : idxNumber(eval(s.start, env), s.line);
                Long b = s.stop == null ? null : idxNumber(eval(s.stop, env), s.line);
                Long k = s.step == null ? null : idxNumber(eval(s.step, env), s.line);
                return doSlice(obj, a, b, k, s.line);
            }
            if (node instanceof NAttr) {
                NAttr a = (NAttr) node;
                return attr(eval(a.obj, env), a.name, a.line);
            }
            throw new DisError("неизвестный узел", node.line());
        }

        // ---------- арифметика и сравнения ----------
        static boolean isNum(Object o) { return o instanceof Long || o instanceof Double || o instanceof Boolean; }
        static double asDouble(Object o) {
            if (o instanceof Long) return (Long) o;
            if (o instanceof Double) return (Double) o;
            return ((Boolean) o) ? 1.0 : 0.0;
        }
        static long asLong(Object o) {
            if (o instanceof Long) return (Long) o;
            if (o instanceof Double) return (long) (double) (Double) o;
            return ((Boolean) o) ? 1L : 0L;
        }
        static boolean integral(Object o) { return o instanceof Long || o instanceof Boolean; }
        static boolean bothIntegral(Object a, Object b) { return integral(a) && integral(b); }

        static Object negate(Object v) {
            if (v instanceof Long) return Long.valueOf(-(Long) v);
            return Double.valueOf(-(Double) v);
        }

        Object binop(String op, Object l, Object r, int line) {
            if (op.equals("+")) {
                if (l instanceof String && r instanceof String) return (String) l + (String) r;
                if (isNum(l) && isNum(r)) {
                    if (bothIntegral(l, r)) return Long.valueOf(asLong(l) + asLong(r));
                    return Double.valueOf(asDouble(l) + asDouble(r));
                }
                if (l instanceof List && r instanceof List) {
                    ArrayList<Object> out = new ArrayList<Object>((List<?>) l);
                    out.addAll((List<?>) r);
                    return out;
                }
                throw new DisError("нельзя сложить типы '" + tname(l) + "' и '" + tname(r) + "'", line);
            }
            if (op.equals("-")) {
                if (!isNum(l) || !isNum(r))
                    throw new DisError("нельзя вычесть тип '" + tname(r) + "' из '" + tname(l) + "'", line);
                if (bothIntegral(l, r)) return Long.valueOf(asLong(l) - asLong(r));
                return Double.valueOf(asDouble(l) - asDouble(r));
            }
            if (op.equals("*")) {
                if (isNum(l) && isNum(r)) {
                    if (bothIntegral(l, r)) return Long.valueOf(asLong(l) * asLong(r));
                    return Double.valueOf(asDouble(l) * asDouble(r));
                }
                if (l instanceof String && r instanceof Long) return repeat((String) l, (Long) r, line);
                if (l instanceof Long && r instanceof String) return repeat((String) r, (Long) l, line);
                if (l instanceof List && r instanceof Long) {
                    long cnt = (Long) r;
                    if (cnt < 0) throw new DisError("нельзя повторить список отрицательное число раз", line);
                    ArrayList<Object> out = new ArrayList<Object>();
                    for (int i = 0; i < cnt; i++) out.addAll((List<?>) l);
                    return out;
                }
                throw new DisError("нельзя умножить типы '" + tname(l) + "' и '" + tname(r) + "'", line);
            }
            if (!isNum(l) || !isNum(r))
                throw new DisError("операция '" + op + "' не поддерживает типы '" + tname(l) + "' и '" + tname(r) + "'", line);
            if (op.equals("/")) {
                double b = asDouble(r);
                if (b == 0) throw new DisError("деление на ноль", line);
                return Double.valueOf(asDouble(l) / b);
            }
            if (op.equals("//")) {
                if (bothIntegral(l, r)) {
                    long a = asLong(l), b = asLong(r);
                    if (b == 0) throw new DisError("деление на ноль", line);
                    return Long.valueOf(Math.floorDiv(a, b));
                }
                double a2 = asDouble(l), b2 = asDouble(r);
                if (b2 == 0) throw new DisError("деление на ноль", line);
                return Double.valueOf(Math.floor(a2 / b2));
            }
            if (op.equals("%")) {
                if (bothIntegral(l, r)) {
                    long a = asLong(l), b = asLong(r);
                    if (b == 0) throw new DisError("деление на ноль", line);
                    return Long.valueOf(Math.floorMod(a, b));
                }
                double a2 = asDouble(l), b2 = asDouble(r);
                if (b2 == 0) throw new DisError("деление на ноль", line);
                return Double.valueOf(a2 - b2 * Math.floor(a2 / b2));
            }
            if (op.equals("**")) {
                double a = asDouble(l), b = asDouble(r);
                if (bothIntegral(l, r) && r instanceof Long && asLong(r) >= 0) {
                    long base = asLong(l), exp = asLong(r), result = 1;
                    boolean overflow = false;
                    for (long i = 0; i < exp; i++) {
                        try { result = Math.multiplyExact(result, base); }
                        catch (ArithmeticException e) { overflow = true; break; }
                    }
                    if (!overflow) return Long.valueOf(result);
                }
                return Double.valueOf(Math.pow(a, b));
            }
            throw new DisError("неизвестная операция '" + op + "'", line);
        }

        static String repeat(String s, long cnt, int line) {
            if (cnt < 0) throw new DisError("нельзя повторить строку отрицательное число раз", line);
            StringBuilder sb = new StringBuilder();
            for (long i = 0; i < cnt; i++) sb.append(s);
            return sb.toString();
        }

        static boolean eq(Object a, Object b) {
            if (a == null || b == null) return a == b;
            if (isNum(a) && isNum(b)) return asDouble(a) == asDouble(b);
            if (a instanceof String && b instanceof String) return a.equals(b);
            if (a instanceof List && b instanceof List) {
                List<?> x = (List<?>) a, y = (List<?>) b;
                if (x.size() != y.size()) return false;
                for (int i = 0; i < x.size(); i++) if (!eq(x.get(i), y.get(i))) return false;
                return true;
            }
            if (a instanceof Map && b instanceof Map) {
                Map<?, ?> x = (Map<?, ?>) a, y = (Map<?, ?>) b;
                if (x.size() != y.size()) return false;
                for (Map.Entry<?, ?> e : x.entrySet()) {
                    Object v = null; boolean found = false;
                    for (Map.Entry<?, ?> e2 : y.entrySet()) if (eq(e.getKey(), e2.getKey())) { v = e2.getValue(); found = true; break; }
                    if (!found || !eq(e.getValue(), v)) return false;
                }
                return true;
            }
            if (a instanceof RangeVal && b instanceof RangeVal) {
                RangeVal x = (RangeVal) a, y = (RangeVal) b;
                return x.from == y.from && x.to == y.to && x.step == y.step;
            }
            return a.equals(b);
        }

        static int cmpOrd(Object a, Object b, int line) {
            if (isNum(a) && isNum(b)) return Double.compare(asDouble(a), asDouble(b));
            if (a instanceof String && b instanceof String) return ((String) a).compareTo((String) b);
            throw new DisError("нельзя сравнить типы '" + tname(a) + "' и '" + tname(b) + "'", line);
        }

        boolean cmpop(String op, Object l, Object r, int line) {
            if (op.equals("==")) return eq(l, r);
            if (op.equals("!=")) return !eq(l, r);
            if (op.equals("in")) return containsIn(r, l, line);
            if (op.equals("not in")) return !containsIn(r, l, line);
            int c = cmpOrd(l, r, line);
            if (op.equals("<")) return c < 0;
            if (op.equals("<=")) return c <= 0;
            if (op.equals(">")) return c > 0;
            if (op.equals(">=")) return c >= 0;
            throw new DisError("неизвестное сравнение '" + op + "'", line);
        }

        boolean containsIn(Object container, Object item, int line) {
            if (container instanceof List) {
                for (Object o : (List<?>) container) if (eq(o, item)) return true;
                return false;
            }
            if (container instanceof Map) {
                if (((Map<?, ?>) container).containsKey(item)) return true;
                for (Object k : ((Map<?, ?>) container).keySet()) if (eq(k, item)) return true;
                return false;
            }
            if (container instanceof String) {
                if (!(item instanceof String))
                    throw new DisError("в строке можно искать только строку", line);
                return ((String) container).contains((String) item);
            }
            if (container instanceof RangeVal) {
                if (!isNum(item)) return false;
                RangeVal rv = (RangeVal) container;
                double d = asDouble(item);
                if (d != Math.rint(d)) return false;
                long v = (long) d;
                if (rv.step > 0) { if (v < rv.from || v >= rv.to) return false; return (v - rv.from) % rv.step == 0; }
                if (v > rv.from || v <= rv.to) return false;
                return (rv.from - v) % (-rv.step) == 0;
            }
            throw new DisError("по объекту типа '" + tname(container) + "' нельзя проверять вхождение", line);
        }

        // ---------- индексы, срезы, длина ----------
        long idxNumber(Object idx, int line) {
            if (idx instanceof Long) return (Long) idx;
            if (idx instanceof Double && ((Double) idx) == Math.rint((Double) idx)) return ((Double) idx).longValue();
            throw new DisError("индекс должен быть целым числом, получен '" + tname(idx) + "'", line);
        }

        int lengthOf(Object o, int line) {
            if (o instanceof String) return ((String) o).length();
            if (o instanceof List) return ((List<?>) o).size();
            if (o instanceof Map) return ((Map<?, ?>) o).size();
            if (o instanceof RangeVal) return (int) ((RangeVal) o).size();
            throw new DisError("у типа '" + tname(o) + "' нет длины", line);
        }

        Object indexGet(Object obj, Object idx, int line) {
            if (obj instanceof Map) {
                Map<?, ?> m = (Map<?, ?>) obj;
                if (m.containsKey(idx)) return m.get(idx);
                for (Map.Entry<?, ?> e : m.entrySet()) if (eq(e.getKey(), idx)) return e.getValue();
                throw new DisError("ключ " + repr(idx) + " не найден", line);
            }
            long i = idxNumber(idx, line);
            if (obj instanceof List) {
                List<?> list = (List<?>) obj;
                if (i < 0) i += list.size();
                if (i < 0 || i >= list.size())
                    throw new DisError("индекс " + idx + " за пределами (длина " + list.size() + ")", line);
                return list.get((int) i);
            }
            if (obj instanceof String) {
                String s = (String) obj;
                if (i < 0) i += s.length();
                if (i < 0 || i >= s.length())
                    throw new DisError("индекс " + idx + " за пределами (длина " + s.length() + ")", line);
                return String.valueOf(s.charAt((int) i));
            }
            if (obj instanceof RangeVal) {
                RangeVal rv = (RangeVal) obj;
                if (i < 0) i += rv.size();
                if (i < 0 || i >= rv.size())
                    throw new DisError("индекс " + idx + " за пределами (длина " + rv.size() + ")", line);
                return Long.valueOf(rv.get(i));
            }
            throw new DisError("у типа '" + tname(obj) + "' нельзя взять индекс", line);
        }

        void indexSet(Object obj, Object idx, Object value, int line) {
            if (obj instanceof Map) {
                ((Map<Object, Object>) obj).put(idx, value);
                return;
            }
            long i = idxNumber(idx, line);
            if (obj instanceof List) {
                List<Object> list = (List<Object>) obj;
                if (i < 0) i += list.size();
                if (i < 0 || i >= list.size())
                    throw new DisError("индекс " + idx + " за пределами (длина " + list.size() + ")", line);
                list.set((int) i, value);
                return;
            }
            throw new DisError("по типу '" + tname(obj) + "' нельзя присваивать по индексу", line);
        }

        Object doSlice(Object obj, Long start, Long stop, Long step, int line) {
            int len = lengthOf(obj, line);
            long k = step == null ? 1 : step;
            if (k == 0) throw new DisError("шаг среза не может быть 0", line);
            long s, e;
            if (k > 0) {
                s = start == null ? 0 : start;
                e = stop == null ? len : stop;
                if (s < 0) { s += len; if (s < 0) s = 0; } else if (s > len) s = len;
                if (e < 0) { e += len; if (e < 0) e = 0; } else if (e > len) e = len;
            } else {
                s = start == null ? len - 1 : start;
                e = stop == null ? -1 : stop;
                if (s < 0) { s += len; if (s < -1) s = -1; } else if (s > len - 1) s = len - 1;
                if (e < 0) { e += len; if (e < -1) e = -1; } else if (e > len - 1) e = len - 1;
            }
            ArrayList<Object> out = new ArrayList<Object>();
            if (obj instanceof RangeVal) {
                RangeVal rv = (RangeVal) obj;
                for (long i = s; k > 0 ? i < e : i > e; i += k) out.add(Long.valueOf(rv.get(i)));
                return out;
            }
            for (long i = s; k > 0 ? i < e : i > e; i += k) out.add(indexGet(obj, Long.valueOf(i), line));
            return out;
        }

        // ---------- текстовое представление ----------
        static String strDouble(double d) {
            if (Double.isNaN(d)) return "nan";
            if (Double.isInfinite(d)) return d > 0 ? "inf" : "-inf";
            if (d == Math.floor(d) && Math.abs(d) < 1e16) {
                long l = (long) d;
                return l + ".0";
            }
            String j = Double.toString(d);
            int e = j.indexOf('E');
            if (e < 0) return j;
            String mant = j.substring(0, e);
            String exp = j.substring(e + 1);
            if (mant.endsWith(".0")) mant = mant.substring(0, mant.length() - 2);
            boolean neg = exp.startsWith("-");
            String digits = neg ? exp.substring(1) : exp;
            while (digits.length() < 2) digits = "0" + digits;
            return mant + "e" + (neg ? "-" : "+") + digits;
        }

        static String tname(Object v) {
            if (v == null) return "null";
            if (v instanceof Boolean) return "bool";
            if (v instanceof Long) return "int";
            if (v instanceof Double) return "float";
            if (v instanceof String) return "str";
            if (v instanceof List) return "list";
            if (v instanceof Map) return "dict";
            if (v instanceof RangeVal) return "range";
            if (v instanceof FuncVal || v instanceof LambdaVal || v instanceof Builtin) return "func";
            if (v instanceof ErrorVal) return "error";
            if (v instanceof ModuleVal || v instanceof PyModuleVal) return "module";
            if (v instanceof JavaClassVal) return "class";
            if (v instanceof Bound) return "method";
            if (v.getClass().isArray()) return "object";
            return v.getClass().getSimpleName();
        }

        static String str(Object v) {
            if (v == null) return "None";
            if (v instanceof Boolean) return ((Boolean) v) ? "True" : "False";
            if (v instanceof Long) return String.valueOf(v);
            if (v instanceof Double) return strDouble((Double) v);
            if (v instanceof String) return (String) v;
            if (v instanceof ErrorVal) { ErrorVal e = (ErrorVal) v; return e.kind + ": " + e.message; }
            if (v instanceof FuncVal) return "<func " + ((FuncVal) v).name + ">";
            if (v instanceof LambdaVal) return "<lambda>";
            if (v instanceof Builtin) return "<builtin>";
            if (v instanceof Bound) return "<method " + ((Bound) v).name + ">";
            if (v instanceof JavaClassVal) return "<class " + ((JavaClassVal) v).cls.getName() + ">";
            if (v instanceof ModuleVal) return "<module " + ((ModuleVal) v).name + ">";
            if (v instanceof PyModuleVal) return "<module " + ((PyModuleVal) v).name + ">";
            if (v instanceof RangeVal) {
                RangeVal r = (RangeVal) v;
                return r.step == 1 ? "range(" + r.from + ", " + r.to + ")"
                        : "range(" + r.from + ", " + r.to + ", " + r.step + ")";
            }
            if (v instanceof List) {
                StringBuilder sb = new StringBuilder("[");
                List<?> list = (List<?>) v;
                for (int i = 0; i < list.size(); i++) {
                    if (i > 0) sb.append(", ");
                    sb.append(repr(list.get(i)));
                }
                return sb.append("]").toString();
            }
            if (v instanceof Map) {
                StringBuilder sb = new StringBuilder("{");
                boolean first = true;
                for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                    if (!first) sb.append(", ");
                    first = false;
                    sb.append(repr(e.getKey())).append(": ").append(repr(e.getValue()));
                }
                return sb.append("}").toString();
            }
            return String.valueOf(v);
        }

        static String repr(Object v) {
            if (v instanceof String) {
                StringBuilder sb = new StringBuilder("'");
                for (char c : ((String) v).toCharArray()) {
                    if (c == '\'') sb.append("\\'");
                    else if (c == '\\') sb.append("\\\\");
                    else if (c == '\n') sb.append("\\n");
                    else if (c == '\t') sb.append("\\t");
                    else if (c == '\r') sb.append("\\r");
                    else sb.append(c);
                }
                return sb.append("'").toString();
            }
            return str(v);
        }

        static String joinStr(Collection<?> items, String sep) {
            StringBuilder sb = new StringBuilder();
            boolean first = true;
            for (Object o : items) {
                if (!first) sb.append(sep);
                first = false;
                sb.append(o);
            }
            return sb.toString();
        }

        // ---------- атрибуты и методы ----------
        static final Set<String> STR_METHODS = new HashSet<String>(Arrays.asList(
                "upper", "lower", "strip", "lstrip", "rstrip", "split", "replace",
                "find", "startswith", "endswith", "count", "join", "capitalize", "title"));
        static final Set<String> LIST_METHODS = new HashSet<String>(Arrays.asList(
                "append", "add", "pop", "insert", "index", "count", "reverse", "sort", "extend", "remove", "clear"));
        static final Set<String> MAP_METHODS = new HashSet<String>(Arrays.asList(
                "get", "keys", "values", "items", "pop", "has"));

        Object attr(Object obj, String name, int line) {
            if (obj == null) throw new DisError("у null нет атрибута '" + name + "'", line);
            if (obj instanceof ErrorVal) {
                ErrorVal e = (ErrorVal) obj;
                if (name.equals("message")) return e.message;
                if (name.equals("line")) return Long.valueOf(e.line);
                if (name.equals("kind")) return e.kind;
                throw new DisError("у ошибки нет атрибута '" + name + "'", line);
            }
            if (obj instanceof FuncVal) {
                if (name.equals("name")) return ((FuncVal) obj).name;
                throw new DisError("у функции нет атрибута '" + name + "'", line);
            }
            if (obj instanceof String && STR_METHODS.contains(name)) return new Bound(obj, name);
            if (obj instanceof List && LIST_METHODS.contains(name)) return new Bound(obj, name);
            if (obj instanceof Map && MAP_METHODS.contains(name)) return new Bound(obj, name);
            if (obj instanceof ModuleVal) {
                ModuleVal m = (ModuleVal) obj;
                if (m.members.containsKey(name)) return m.members.get(name);
                throw new DisError("в модуле '" + m.name + "' нет элемента '" + name + "'", line);
            }
            if (obj instanceof PyModuleVal) {
                PyModuleVal m = (PyModuleVal) obj;
                if (m.attrs.containsKey(name)) return m.attrs.get(name);
                Object res = PyBridge.getattr(m.name, name, line);
                if (res == PyBridge.PY_CALLABLE) {
                    final String mod = m.name;
                    final String fn = name;
                    Object b = new Builtin() {
                        public Object call(Interpreter ip, List<Object> args, Map<String, Object> kwargs, int l) {
                            return PyBridge.call(mod, fn, args, kwargs, l);
                        }
                    };
                    m.attrs.put(name, b);
                    return b;
                }
                m.attrs.put(name, res);
                return res;
            }
            if (obj instanceof JavaClassVal) {
                Class<?> cls = ((JavaClassVal) obj).cls;
                for (Method mm : cls.getMethods())
                    if (mm.getName().equals(name) && Modifier.isStatic(mm.getModifiers()))
                        return new ReflectStatic(cls, name);
                try {
                    Field f = cls.getField(name);
                    return f.get(null);
                } catch (Exception e) { /* дальше */ }
                throw new DisError("в классе " + cls.getSimpleName() + " нет элемента '" + name + "'", line);
            }
            if (obj instanceof Long || obj instanceof Double || obj instanceof Boolean || obj instanceof RangeVal
                    || obj instanceof FuncVal || obj instanceof LambdaVal)
                throw new DisError("у типа '" + tname(obj) + "' нет атрибута '" + name + "'", line);
            // объект Java
            for (Method mm : obj.getClass().getMethods())
                if (mm.getName().equals(name) && !Modifier.isStatic(mm.getModifiers()))
                    return new Bound(obj, name);
            try {
                Field f = obj.getClass().getField(name);
                return f.get(obj);
            } catch (Exception e) { /* дальше */ }
            throw new DisError("у типа '" + tname(obj) + "' нет атрибута '" + name + "'", line);
        }

        Object dispatchMethod(Object recv, String name, List<Object> args, Map<String, Object> kwargs, int line) {
            if (recv instanceof String) return strMethod((String) recv, name, args, kwargs, line);
            if (recv instanceof List) return listMethod((List<Object>) recv, name, args, kwargs, line);
            if (recv instanceof Map) return mapMethod((Map<Object, Object>) recv, name, args, kwargs, line);
            if (recv instanceof Long || recv instanceof Double || recv instanceof Boolean)
                throw new DisError("у типа '" + tname(recv) + "' нет метода '" + name + "'", line);
            if (!kwargs.isEmpty())
                throw new DisError("методы Java не принимают именованные аргументы", line);
            return reflectInvoke(recv, recv.getClass(), name, args, line);
        }

        static Object argAt(List<Object> args, int i, Object def) { return i < args.size() ? args.get(i) : def; }

        static void noKwargs(Map<String, Object> kwargs, int line) {
            if (!kwargs.isEmpty())
                throw new DisError("лишние именованные аргументы: " + joinStr(kwargs.keySet(), ", "), line);
        }

        Object strMethod(String s, String name, List<Object> args, Map<String, Object> kwargs, int line) {
            noKwargsExcept(kwargs, new HashSet<String>(Arrays.asList("sep", "old", "new")), line);
            switch (name) {
                case "upper": noKwargs(kwargs, line); return s.toUpperCase();
                case "lower": noKwargs(kwargs, line); return s.toLowerCase();
                case "strip": case "lstrip": case "rstrip": {
                    noKwargs(kwargs, line);
                    String chars = args.isEmpty() || args.get(0) == null ? null : str(args.get(0));
                    if (chars == null) {
                        if (name.equals("strip")) return s.trim();
                        if (name.equals("lstrip")) { int i = 0; while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; return s.substring(i); }
                        int i = s.length(); while (i > 0 && Character.isWhitespace(s.charAt(i - 1))) i--; return s.substring(0, i);
                    }
                    int a = 0, b = s.length();
                    if (!name.equals("rstrip")) while (a < b && chars.indexOf(s.charAt(a)) >= 0) a++;
                    if (!name.equals("lstrip")) while (b > a && chars.indexOf(s.charAt(b - 1)) >= 0) b--;
                    return s.substring(a, b);
                }
                case "split": {
                    Object sepo = kwOrArg(kwargs, "sep", args, 0, null, line);
                    String sep = sepo == null ? null : str(sepo);
                    if (sep == null) {
                        ArrayList<String> parts = new ArrayList<String>();
                        for (String p : s.trim().split("\\s+")) if (!p.isEmpty()) parts.add(p);
                        return parts;
                    }
                    ArrayList<String> parts2 = new ArrayList<String>(Arrays.asList(s.split(java.util.regex.Pattern.quote(sep), -1)));
                    return parts2;
                }
                case "replace": {
                    Object old = kwOrArg(kwargs, "old", args, 0, MISSING, line);
                    Object nw = kwOrArg(kwargs, "new", args, 1, MISSING, line);
                    if (old == MISSING || nw == MISSING)
                        throw new DisError("replace() требует аргументы old и new", line);
                    return s.replace(str(old), str(nw));
                }
                case "find": noKwargs(kwargs, line); return Long.valueOf(s.indexOf(str(arg(args, 0, line))));
                case "startswith": noKwargs(kwargs, line); return s.startsWith(str(arg(args, 0, line)));
                case "endswith": noKwargs(kwargs, line); return s.endsWith(str(arg(args, 0, line)));
                case "count": noKwargs(kwargs, line); {
                    String sub = str(arg(args, 0, line));
                    if (sub.isEmpty()) return Long.valueOf(s.length() + 1);
                    int c = 0, i = 0;
                    while ((i = s.indexOf(sub, i)) >= 0) { c++; i += sub.length(); }
                    return Long.valueOf(c);
                }
                case "join": {
                    noKwargs(kwargs, line);
                    Object it = arg(args, 0, line);
                    Iterator<Object> i2 = iterOf(it, line);
                    StringBuilder sb = new StringBuilder();
                    boolean first = true;
                    while (i2.hasNext()) { if (!first) sb.append(s); first = false; sb.append(str(i2.next())); }
                    return sb.toString();
                }
                case "capitalize": noKwargs(kwargs, line);
                    return s.isEmpty() ? s : Character.toUpperCase(s.charAt(0)) + s.substring(1).toLowerCase();
                case "title": noKwargs(kwargs, line); {
                    StringBuilder sb = new StringBuilder();
                    boolean cap = true;
                    for (char c : s.toCharArray()) {
                        sb.append(cap && Character.isLetter(c) ? Character.toUpperCase(c) : Character.toLowerCase(c));
                        cap = !Character.isLetterOrDigit(c);
                    }
                    return sb.toString();
                }
            }
            throw new DisError("у типа 'str' нет метода '" + name + "'", line);
        }

        static Object arg(List<Object> args, int i, int line) {
            if (i >= args.size()) throw new DisError("не хватает аргумента №" + (i + 1), line);
            return args.get(i);
        }

        static Object kwOrArg(Map<String, Object> kwargs, String kw, List<Object> args, int idx, Object def, int line) {
            if (kwargs.containsKey(kw)) return kwargs.get(kw);
            if (idx < args.size()) return args.get(idx);
            return def;
        }

        static void noKwargsExcept(Map<String, Object> kwargs, Set<String> allowed, int line) {
            for (String k : kwargs.keySet())
                if (!allowed.contains(k))
                    throw new DisError("лишний именованный аргумент '" + k + "'", line);
        }

        Object listMethod(List<Object> list, String name, List<Object> args, Map<String, Object> kwargs, int line) {
            noKwargsExcept(kwargs, new HashSet<String>(Arrays.asList("key", "reverse")), line);
            switch (name) {
                case "append": noKwargs(kwargs, line); list.add(arg(args, 0, line)); return null;
                case "add": noKwargs(kwargs, line); list.add(arg(args, 0, line)); return null;
                case "pop": noKwargs(kwargs, line); {
                    if (list.isEmpty()) throw new DisError("pop из пустого списка", line);
                    if (args.isEmpty()) return list.remove(list.size() - 1);
                    long i = idxNumber(arg(args, 0, line), line);
                    if (i < 0) i += list.size();
                    if (i < 0 || i >= list.size())
                        throw new DisError("индекс " + args.get(0) + " за пределами (длина " + list.size() + ")", line);
                    return list.remove((int) i);
                }
                case "insert": noKwargs(kwargs, line); {
                    long i = idxNumber(arg(args, 0, line), line);
                    if (i < 0) i = Math.max(0, i + list.size());
                    if (i > list.size()) i = list.size();
                    list.add((int) i, arg(args, 1, line));
                    return null;
                }
                case "index": noKwargs(kwargs, line); {
                    Object v = arg(args, 0, line);
                    for (int i = 0; i < list.size(); i++) if (eq(list.get(i), v)) return Long.valueOf(i);
                    throw new DisError("значение " + repr(v) + " не найдено в списке", line);
                }
                case "count": noKwargs(kwargs, line); {
                    Object v = arg(args, 0, line);
                    int c = 0;
                    for (Object o : list) if (eq(o, v)) c++;
                    return Long.valueOf(c);
                }
                case "reverse": noKwargs(kwargs, line); Collections.reverse(list); return null;
                case "clear": noKwargs(kwargs, line); list.clear(); return null;
                case "extend": noKwargs(kwargs, line); {
                    Object it = arg(args, 0, line);
                    Iterator<Object> i2 = iterOf(it, line);
                    while (i2.hasNext()) list.add(i2.next());
                    return null;
                }
                case "remove": noKwargs(kwargs, line); {
                    Object v = arg(args, 0, line);
                    for (int i = 0; i < list.size(); i++) if (eq(list.get(i), v)) { list.remove(i); return null; }
                    throw new DisError("значение " + repr(v) + " не найдено в списке", line);
                }
                case "sort": {
                    noKwargsExcept(kwargs, new HashSet<String>(Arrays.asList("key", "reverse")), line);
                    Object key = kwargs.get("key");
                    boolean rev = Boolean.TRUE.equals(kwargs.get("reverse"));
                    ArrayList<Object[]> dec = new ArrayList<Object[]>();
                    for (Object o : list) dec.add(new Object[]{key == null ? o : call(key, singleton(o), new LinkedHashMap<String, Object>(), line), o});
                    Collections.sort(dec, new Comparator<Object[]>() {
                        public int compare(Object[] a, Object[] b) { return cmpOrd(a[0], b[0], line); }
                    });
                    list.clear();
                    if (rev) Collections.reverse(dec);
                    for (Object[] p : dec) list.add(p[1]);
                    return null;
                }
            }
            throw new DisError("у типа 'list' нет метода '" + name + "'", line);
        }

        static List<Object> singleton(Object o) {
            ArrayList<Object> l = new ArrayList<Object>();
            l.add(o);
            return l;
        }

        Object mapMethod(Map<Object, Object> m, String name, List<Object> args, Map<String, Object> kwargs, int line) {
            noKwargs(kwargs, line);
            switch (name) {
                case "get": {
                    Object k = arg(args, 0, line);
                    if (m.containsKey(k)) return m.get(k);
                    for (Map.Entry<Object, Object> e : m.entrySet()) if (eq(e.getKey(), k)) return e.getValue();
                    return args.size() > 1 ? args.get(1) : null;
                }
                case "keys": return new ArrayList<Object>(m.keySet());
                case "values": return new ArrayList<Object>(m.values());
                case "items": {
                    ArrayList<Object> out = new ArrayList<Object>();
                    for (Map.Entry<Object, Object> e : m.entrySet()) {
                        ArrayList<Object> pair = new ArrayList<Object>();
                        pair.add(e.getKey()); pair.add(e.getValue());
                        out.add(pair);
                    }
                    return out;
                }
                case "pop": {
                    Object k = arg(args, 0, line);
                    if (m.containsKey(k)) return m.remove(k);
                    for (Map.Entry<Object, Object> e : m.entrySet()) if (eq(e.getKey(), k)) { Object v = e.getValue(); m.remove(e.getKey()); return v; }
                    return args.size() > 1 ? args.get(1) : null;
                }
                case "has": return Boolean.valueOf(m.containsKey(arg(args, 0, line)));
            }
            throw new DisError("у типа 'dict' нет метода '" + name + "'", line);
        }

        // ---------- импорт ----------
        Object doImport(String name, int line) {
            Object mod = makeModule(name);
            if (mod != null) return mod;
            Class<?> cls = findClass(name);
            if (cls != null) return new JavaClassVal(cls);
            if (PyBridge.available())
                return new PyModuleVal(name);
            throw new DisError("не удалось импортировать '" + name + "' (нет такого модуля, python для моста не найден)", line);
        }

        static Class<?> findClass(String name) {
            try {
                return Class.forName(name);
            } catch (ClassNotFoundException e) {
                if (!name.contains(".")) {
                    try { return Class.forName("java.lang." + name); }
                    catch (ClassNotFoundException e2) { return null; }
                }
                return null;
            }
        }

        // ---------- формат ----------
        static String applyFormat(Object v, String spec, int line) {
            if (spec == null || spec.isEmpty()) return str(v);
            String rest = spec;
            StringBuilder jf = new StringBuilder("%");
            char align = 0;
            if (!rest.isEmpty()) {
                char c0 = rest.charAt(0);
                if (c0 == '<' || c0 == '>' || c0 == '^') { align = c0; rest = rest.substring(1); }
                else if (rest.length() >= 2 && (rest.charAt(1) == '<' || rest.charAt(1) == '>' || rest.charAt(1) == '^')) {
                    align = rest.charAt(1); rest = rest.substring(2);
                }
            }
            if (align == '<') jf.append('-');
            char type = 's';
            if (!rest.isEmpty()) {
                char last = rest.charAt(rest.length() - 1);
                if ("fFeEgGds%".indexOf(last) >= 0) { type = last; rest = rest.substring(0, rest.length() - 1); }
            }
            jf.append(rest);
            boolean pct = type == '%';
            char jtype;
            switch (type) {
                case 'd': jtype = 'd'; break;
                case 'f': case 'F': jtype = 'f'; break;
                case 'e': case 'E': jtype = 'e'; break;
                case 'g': case 'G': jtype = 'g'; break;
                case '%': jtype = 'f'; break;
                default: jtype = 's';
            }
            jf.append(jtype);
            Object val = v;
            if (jtype == 'f' || jtype == 'e' || jtype == 'g') {
                if (!isNum(v)) throw new DisError("формат '" + spec + "' требует число, получено '" + tname(v) + "'", line);
                val = Double.valueOf(asDouble(v) * (pct ? 100 : 1));
            } else if (jtype == 'd') {
                if (v instanceof Double)
                    throw new DisError("формат 'd' требует целое число", line);
                if (!isNum(v)) throw new DisError("формат '" + spec + "' требует число", line);
                val = Long.valueOf(asLong(v));
            }
            try {
                String out = String.format(Locale.US, jf.toString(), val);
                return pct ? out + "%" : out;
            } catch (IllegalFormatException e) {
                throw new DisError("неправильный формат '" + spec + "'", line);
            }
        }
        // ==== PART D ====
        // ===================== Встроенные модули Java =====================
        static class ModuleVal {
        final String name;
        Map<String, Object> members = new LinkedHashMap<String, Object>();
        ModuleVal(String name) { this.name = name; }
    }

    static Builtin bf(final String name, final java.util.function.Function<List<Object>, Object> fn) {
        return new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kwargs, int line) {
                Interpreter.noKwargs(kwargs, line);
                try {
                    return fn.apply(args);
                } catch (DisError e) { throw e; }
                catch (RuntimeException e) { throw new DisError(name + "(): " + e.getMessage(), line); }
            }
        };
    }

    static Object makeModule(String name) {
        if (name.equals("math")) {
            ModuleVal m = new ModuleVal("math");
            m.members.put("pi", Math.PI);
            m.members.put("e", Math.E);
            m.members.put("tau", Math.PI * 2);
            m.members.put("inf", Double.POSITIVE_INFINITY);
            m.members.put("nan", Double.NaN);
            m.members.put("sqrt", bf("sqrt", a -> Double.valueOf(Math.sqrt(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("pow", bf("pow", a -> Double.valueOf(Math.pow(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L)), Interpreter.asDouble(Interpreter.argAt(a, 1, 0L))))));
            m.members.put("sin", bf("sin", a -> Double.valueOf(Math.sin(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("cos", bf("cos", a -> Double.valueOf(Math.cos(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("tan", bf("tan", a -> Double.valueOf(Math.tan(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("asin", bf("asin", a -> Double.valueOf(Math.asin(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("acos", bf("acos", a -> Double.valueOf(Math.acos(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("atan", bf("atan", a -> Double.valueOf(Math.atan(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("atan2", bf("atan2", a -> Double.valueOf(Math.atan2(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L)), Interpreter.asDouble(Interpreter.argAt(a, 1, 0L))))));
            m.members.put("exp", bf("exp", a -> Double.valueOf(Math.exp(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("log", bf("log", a -> {
                double x = Interpreter.asDouble(Interpreter.argAt(a, 0, 0L));
                if (a.size() > 1) return Double.valueOf(Math.log(x) / Math.log(Interpreter.asDouble(a.get(1))));
                return Double.valueOf(Math.log(x));
            }));
            m.members.put("log2", bf("log2", a -> Double.valueOf(Math.log(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))) / Math.log(2))));
            m.members.put("log10", bf("log10", a -> Double.valueOf(Math.log10(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("floor", bf("floor", a -> Long.valueOf((long) Math.floor(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("ceil", bf("ceil", a -> Long.valueOf((long) Math.ceil(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("trunc", bf("trunc", a -> Long.valueOf((long) Interpreter.asDouble(Interpreter.argAt(a, 0, 0L)))));
            m.members.put("fabs", bf("fabs", a -> Double.valueOf(Math.abs(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("radians", bf("radians", a -> Double.valueOf(Math.toRadians(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("degrees", bf("degrees", a -> Double.valueOf(Math.toDegrees(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("hypot", bf("hypot", a -> Double.valueOf(Math.hypot(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L)), Interpreter.asDouble(Interpreter.argAt(a, 1, 0L))))));
            m.members.put("isnan", bf("isnan", a -> Boolean.valueOf(Double.isNaN(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("isinf", bf("isinf", a -> Boolean.valueOf(Double.isInfinite(Interpreter.asDouble(Interpreter.argAt(a, 0, 0L))))));
            m.members.put("factorial", bf("factorial", a -> {
                long n = Interpreter.asLong(Interpreter.argAt(a, 0, 0L));
                if (n < 0) throw new DisError("factorial() требует неотрицательное число", 0);
                long r = 1;
                for (long i = 2; i <= n; i++) r = Math.multiplyExact(r, i);
                return Long.valueOf(r);
            }));
            m.members.put("gcd", bf("gcd", a -> {
                long x = Math.abs(Interpreter.asLong(Interpreter.argAt(a, 0, 0L)));
                long y = Math.abs(Interpreter.asLong(Interpreter.argAt(a, 1, 0L)));
                while (y != 0) { long t = x % y; x = y; y = t; }
                return Long.valueOf(x);
            }));
            return m;
        }
        if (name.equals("random")) {
            final Random rnd = new Random();
            ModuleVal m = new ModuleVal("random");
            m.members.put("random", bf("random", a -> Double.valueOf(rnd.nextDouble())));
            m.members.put("randint", bf("randint", a -> {
                long lo = Interpreter.asLong(a.get(0)), hi = Interpreter.asLong(a.get(1));
                if (hi < lo) throw new DisError("randint(): верхняя граница меньше нижней", 0);
                return Long.valueOf(lo + (long) (rnd.nextDouble() * (hi - lo + 1)));
            }));
            m.members.put("randrange", bf("randrange", a -> {
                long lo = Interpreter.asLong(Interpreter.argAt(a, 0, 0L));
                long hi = a.size() > 1 ? Interpreter.asLong(a.get(1)) : lo;
                lo = a.size() > 1 ? lo : 0L;
                if (hi <= lo) throw new DisError("randrange(): пустой диапазон", 0);
                return Long.valueOf(lo + (long) (rnd.nextDouble() * (hi - lo)));
            }));
            m.members.put("uniform", bf("uniform", a -> {
                double lo = Interpreter.asDouble(a.get(0)), hi = Interpreter.asDouble(a.get(1));
                return Double.valueOf(lo + rnd.nextDouble() * (hi - lo));
            }));
            m.members.put("choice", bf("choice", a -> {
                Object it = a.get(0);
                List<Object> list = new ArrayList<Object>();
                Iterator<Object> i = Interpreter.iterOf(it, 0);
                while (i.hasNext()) list.add(i.next());
                if (list.isEmpty()) throw new DisError("choice() из пустой последовательности", 0);
                return list.get((int) (rnd.nextDouble() * list.size()));
            }));
            m.members.put("shuffle", bf("shuffle", a -> {
                if (!(a.get(0) instanceof List)) throw new DisError("shuffle() требует список", 0);
                Collections.shuffle((List<?>) a.get(0), rnd);
                return null;
            }));
            m.members.put("sample", bf("sample", a -> {
                List<Object> pool = new ArrayList<Object>();
                Iterator<Object> i = Interpreter.iterOf(a.get(0), 0);
                while (i.hasNext()) pool.add(i.next());
                long k = Interpreter.asLong(a.get(1));
                if (k > pool.size()) throw new DisError("sample(): выборка больше населения", 0);
                ArrayList<Object> out = new ArrayList<Object>();
                for (int q = (int) k; q > 0; q--) out.add(pool.remove((int) (rnd.nextDouble() * pool.size())));
                return out;
            }));
            m.members.put("seed", bf("seed", a -> { rnd.setSeed(Interpreter.asLong(Interpreter.argAt(a, 0, 0L))); return null; }));
            m.members.put("gauss", bf("gauss", a -> Double.valueOf(rnd.nextGaussian() * Interpreter.asDouble(a.get(1)) + Interpreter.asDouble(a.get(0)))));
            return m;
        }
        if (name.equals("time")) {
            ModuleVal m = new ModuleVal("time");
            m.members.put("time", bf("time", a -> Double.valueOf(System.currentTimeMillis() / 1000.0)));
            m.members.put("monotonic", bf("monotonic", a -> Double.valueOf(System.nanoTime() / 1e9)));
            m.members.put("perf_counter", bf("perf_counter", a -> Double.valueOf(System.nanoTime() / 1e9)));
            m.members.put("sleep", bf("sleep", a -> {
                try { Thread.sleep((long) (Interpreter.asDouble(Interpreter.argAt(a, 0, 0L)) * 1000)); }
                catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                return null;
            }));
            return m;
        }
        return null;
    }

    // ===================== Встроенные функции =====================
    static void installBuiltins(Env g) {
        Builtin printFn = new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                String sep = " ", end = "\n";
                if (kw.containsKey("sep")) sep = str(kw.get("sep"));
                if (kw.containsKey("end")) end = str(kw.get("end"));
                kw.remove("sep"); kw.remove("end");
                if (!kw.isEmpty()) throw new DisError("print(): лишние аргументы " + joinStr(kw.keySet(), ", "), line);
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < args.size(); i++) {
                    if (i > 0) sb.append(sep);
                    sb.append(str(args.get(i)));
                }
                sb.append(end);
                System.out.print(sb.toString());
                System.out.flush();
                return null;
            }
        };
        g.define("print", printFn);
        g.define("println", printFn);
        ModuleVal py2 = new ModuleVal("pythontwo");
        py2.members.put("print", printFn);
        g.define("pythontwo", py2);
        ModuleVal sf = new ModuleVal("superfast");
        Builtin sfNoop = new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                return null;
            }
        };
        sf.members.put("enable", sfNoop);
        sf.members.put("disable", sfNoop);
        g.define("superfast", sf);
        g.define("type", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                return tname(Interpreter.argAt(args, 0, null));
            }
        });
        g.define("len", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                return Long.valueOf(ip.lengthOf(Interpreter.arg(args, 0, line), line));
            }
        });
        g.define("range", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                long a, b, s = 1;
                if (args.size() == 1) { a = 0; b = Interpreter.asLong(args.get(0)); }
                else if (args.size() == 2) { a = Interpreter.asLong(args.get(0)); b = Interpreter.asLong(args.get(1)); }
                else if (args.size() == 3) {
                    a = Interpreter.asLong(args.get(0)); b = Interpreter.asLong(args.get(1)); s = Interpreter.asLong(args.get(2));
                } else throw new DisError("range() принимает 1-3 аргумента", line);
                if (s == 0) throw new DisError("range(): шаг не может быть 0", line);
                return new RangeVal(a, b, s);
            }
        });
        g.define("str", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                return str(Interpreter.argAt(args, 0, null));
            }
        });
        g.define("repr", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                return repr(Interpreter.argAt(args, 0, null));
            }
        });
        g.define("format", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                return applyFormat(Interpreter.argAt(args, 0, null), Interpreter.argAt(args, 1, "") == null ? "" : str(Interpreter.argAt(args, 1, "")), line);
            }
        });
        g.define("bool", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                return Boolean.valueOf(ip.truthy(Interpreter.argAt(args, 0, null)));
            }
        });
        g.define("int", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Object v = Interpreter.arg(args, 0, line);
                if (v instanceof Long) return v;
                if (v instanceof Double) { double d = (Double) v; return Long.valueOf((long) d); }
                if (v instanceof Boolean) return Long.valueOf((Boolean) v ? 1 : 0);
                if (v instanceof String) {
                    String s = ((String) v).trim();
                    try {
                        if (args.size() > 1) return Long.parseLong(s, (int) Interpreter.asLong(args.get(1)));
                        return Long.parseLong(s, 10);
                    } catch (NumberFormatException e) {
                        throw new DisError("не удалось преобразовать " + repr(s) + " в int", line);
                    }
                }
                throw new DisError("не удалось преобразовать тип '" + tname(v) + "' в int", line);
            }
        });
        g.define("float", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Object v = Interpreter.arg(args, 0, line);
                if (v instanceof Double) return v;
                if (v instanceof Long) return Double.valueOf((double) (Long) v);
                if (v instanceof Boolean) return Double.valueOf((Boolean) v ? 1 : 0);
                if (v instanceof String) {
                    String s = ((String) v).trim();
                    if (s.equalsIgnoreCase("inf") || s.equalsIgnoreCase("+inf") || s.equalsIgnoreCase("infinity"))
                        return Double.POSITIVE_INFINITY;
                    if (s.equalsIgnoreCase("-inf") || s.equalsIgnoreCase("-infinity")) return Double.NEGATIVE_INFINITY;
                    if (s.equalsIgnoreCase("nan")) return Double.NaN;
                    try { return Double.parseDouble(s); }
                    catch (NumberFormatException e) {
                        throw new DisError("не удалось преобразовать " + repr(s) + " в float", line);
                    }
                }
                throw new DisError("не удалось преобразовать тип '" + tname(v) + "' в float", line);
            }
        });
        g.define("list", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                if (args.isEmpty()) return new ArrayList<Object>();
                Object v = args.get(0);
                ArrayList<Object> out = new ArrayList<Object>();
                if (v == null) return out;
                if (v instanceof List) { out.addAll((List<?>) v); return out; }
                if (v instanceof Map) { out.addAll(((Map<?, ?>) v).keySet()); return out; }
                if (v instanceof String || v instanceof RangeVal) {
                    Iterator<Object> it = ip.iterOf(v, line);
                    while (it.hasNext()) out.add(it.next());
                    return out;
                }
                throw new DisError("не удалось преобразовать тип '" + tname(v) + "' в list", line);
            }
        });
        g.define("dict", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                LinkedHashMap<Object, Object> out = new LinkedHashMap<Object, Object>();
                if (args.isEmpty()) return out;
                Object v = args.get(0);
                if (v instanceof Map) { out.putAll((Map<?, ?>) v); return out; }
                if (v instanceof List) {
                    for (Object p : (List<?>) v) {
                        if (!(p instanceof List) || ((List<?>) p).size() != 2)
                            throw new DisError("dict() из списка требует пары [ключ, значение]", line);
                        out.put(((List<?>) p).get(0), ((List<?>) p).get(1));
                    }
                    return out;
                }
                throw new DisError("не удалось преобразовать тип '" + tname(v) + "' в dict", line);
            }
        });
        g.define("abs", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Object v = Interpreter.arg(args, 0, line);
                if (v instanceof Long) return Long.valueOf(Math.abs((Long) v));
                if (v instanceof Double) return Double.valueOf(Math.abs((Double) v));
                if (v instanceof Boolean) return Long.valueOf((Boolean) v ? 1 : 0);
                throw new DisError("abs() требует число", line);
            }
        });
        g.define("sum", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Object it = Interpreter.arg(args, 0, line);
                boolean allInt = true;
                long li = 0; double dd = 0;
                Iterator<Object> i = ip.iterOf(it, line);
                while (i.hasNext()) {
                    Object v = i.next();
                    if (!Interpreter.isNum(v)) throw new DisError("sum(): не число в последовательности", line);
                    if (allInt && v instanceof Long) li += (Long) v;
                    else { if (allInt) { dd = li; allInt = false; } dd += Interpreter.asDouble(v); }
                }
                return allInt ? (Object) Long.valueOf(li) : (Object) Double.valueOf(dd);
            }
        });
        g.define("round", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Object v = Interpreter.arg(args, 0, line);
                if (!Interpreter.isNum(v)) throw new DisError("round() требует число", line);
                int n = args.size() > 1 ? (int) Interpreter.asLong(args.get(1)) : 0;
                BigDecimal bd = BigDecimal.valueOf(Interpreter.asDouble(v));
                try {
                    if (n == 0) return Long.valueOf(bd.setScale(0, RoundingMode.HALF_EVEN).longValueExact());
                    return Double.valueOf(bd.setScale(n, RoundingMode.HALF_EVEN).doubleValue());
                } catch (ArithmeticException e) {
                    throw new DisError("round(): " + e.getMessage(), line);
                }
            }
        });
        g.define("min", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                return minMax(ip, args, true, line);
            }
        });
        g.define("max", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                return minMax(ip, args, false, line);
            }
        });
        g.define("sorted", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Object key = kw.get("key");
                boolean rev = Boolean.TRUE.equals(kw.get("reverse"));
                kw.remove("key"); kw.remove("reverse");
                Interpreter.noKwargs(kw, line);
                Object it = Interpreter.arg(args, 0, line);
                ArrayList<Object[]> dec = new ArrayList<Object[]>();
                Iterator<Object> i = ip.iterOf(it, line);
                while (i.hasNext()) {
                    Object o = i.next();
                    dec.add(new Object[]{key == null ? o : ip.call(key, Interpreter.singleton(o), new LinkedHashMap<String, Object>(), line), o});
                }
                Collections.sort(dec, new Comparator<Object[]>() {
                    public int compare(Object[] a, Object[] b) { return cmpOrd(a[0], b[0], line); }
                });
                ArrayList<Object> out = new ArrayList<Object>();
                if (rev) Collections.reverse(dec);
                for (Object[] p : dec) out.add(p[1]);
                return out;
            }
        });
        g.define("reversed", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                ArrayList<Object> out = new ArrayList<Object>();
                Iterator<Object> i = ip.iterOf(Interpreter.arg(args, 0, line), line);
                while (i.hasNext()) out.add(i.next());
                Collections.reverse(out);
                return out;
            }
        });
        g.define("enumerate", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Object it = Interpreter.arg(args, 0, line);
                long start = Interpreter.asLong(Interpreter.argAt(args, 1, 0L));
                ArrayList<Object> out = new ArrayList<Object>();
                Iterator<Object> i = ip.iterOf(it, line);
                while (i.hasNext()) {
                    ArrayList<Object> pair = new ArrayList<Object>();
                    pair.add(Long.valueOf(start++));
                    pair.add(i.next());
                    out.add(pair);
                }
                return out;
            }
        });
        g.define("zip", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                ArrayList<Iterator<Object>> its = new ArrayList<Iterator<Object>>();
                for (Object a : args) its.add(ip.iterOf(a, line));
                ArrayList<Object> out = new ArrayList<Object>();
                boolean go = !its.isEmpty();
                while (go) {
                    ArrayList<Object> row = new ArrayList<Object>();
                    for (Iterator<Object> it : its) {
                        if (!it.hasNext()) { go = false; break; }
                        row.add(it.next());
                    }
                    if (go) out.add(row);
                }
                return out;
            }
        });
        g.define("any", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Iterator<Object> i = ip.iterOf(Interpreter.arg(args, 0, line), line);
                while (i.hasNext()) if (ip.truthy(i.next())) return Boolean.TRUE;
                return Boolean.FALSE;
            }
        });
        g.define("all", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Iterator<Object> i = ip.iterOf(Interpreter.arg(args, 0, line), line);
                while (i.hasNext()) if (!ip.truthy(i.next())) return Boolean.FALSE;
                return Boolean.TRUE;
            }
        });
        g.define("map", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Object f = Interpreter.arg(args, 0, line);
                ArrayList<Iterator<Object>> its = new ArrayList<Iterator<Object>>();
                for (int i = 1; i < args.size(); i++) its.add(ip.iterOf(args.get(i), line));
                ArrayList<Object> out = new ArrayList<Object>();
                boolean go = !its.isEmpty();
                while (go) {
                    ArrayList<Object> row = new ArrayList<Object>();
                    for (Iterator<Object> it : its) {
                        if (!it.hasNext()) { go = false; break; }
                        row.add(it.next());
                    }
                    if (go) out.add(ip.call(f, row, new LinkedHashMap<String, Object>(), line));
                }
                return out;
            }
        });
        g.define("filter", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                Object f = Interpreter.arg(args, 0, line);
                ArrayList<Object> out = new ArrayList<Object>();
                Iterator<Object> i = ip.iterOf(Interpreter.arg(args, 1, line), line);
                while (i.hasNext()) {
                    Object v = i.next();
                    if (ip.truthy(ip.call(f, Interpreter.singleton(v), new LinkedHashMap<String, Object>(), line))) out.add(v);
                }
                return out;
            }
        });
        g.define("input", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                if (!args.isEmpty()) { System.out.print(str(args.get(0))); System.out.flush(); }
                try {
                    if (stdinReader == null) stdinReader = new BufferedReader(new InputStreamReader(System.in));
                    String l = stdinReader.readLine();
                    return l == null ? "" : l;
                } catch (IOException e) {
                    throw new DisError("ошибка ввода: " + e, line);
                }
            }
        });
        g.define("read_file", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                try {
                    byte[] data = java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(str(Interpreter.arg(args, 0, line))));
                    String enc = args.size() > 1 ? str(args.get(1)) : "UTF-8";
                    return new String(data, java.nio.charset.Charset.forName(enc));
                } catch (IOException e) {
                    throw new DisError("не удалось прочитать файл: " + e.getMessage(), line);
                }
            }
        });
        g.define("write_file", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                try {
                    String enc = args.size() > 2 ? str(args.get(2)) : "UTF-8";
                    java.nio.file.Files.write(java.nio.file.Paths.get(str(Interpreter.arg(args, 0, line))),
                            str(Interpreter.arg(args, 1, line)).getBytes(java.nio.charset.Charset.forName(enc)));
                    return null;
                } catch (IOException e) {
                    throw new DisError("не удалось записать файл: " + e.getMessage(), line);
                }
            }
        });
        g.define("exists", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                return Boolean.valueOf(java.nio.file.Files.exists(java.nio.file.Paths.get(str(Interpreter.arg(args, 0, line)))));
            }
        });
        g.define("exit", new Builtin() {
            public Object call(Interpreter ip, List<Object> args, Map<String, Object> kw, int line) {
                Interpreter.noKwargs(kw, line);
                throw new ExitEx((int) Interpreter.asLong(Interpreter.argAt(args, 0, 0L)));
            }
        });
    }

    static Object minMax(Interpreter ip, List<Object> args, boolean min, int line) {
        Object best = null;
        boolean first = true;
        if (args.size() == 1 && (args.get(0) instanceof List || args.get(0) instanceof Map
                || args.get(0) instanceof String || args.get(0) instanceof RangeVal)) {
            Iterator<Object> i = ip.iterOf(args.get(0), line);
            while (i.hasNext()) {
                Object v = i.next();
                if (first) { best = v; first = false; }
                else if ((min ? cmpOrd(v, best, line) : cmpOrd(best, v, line)) < 0) best = v;
            }
        } else {
            if (args.isEmpty()) throw new DisError((min ? "min" : "max") + "(): нет аргументов", line);
            best = args.get(0);
            for (int i = 1; i < args.size(); i++) {
                Object v = args.get(i);
                if ((min ? cmpOrd(v, best, line) : cmpOrd(best, v, line)) < 0) best = v;
            }
        }
        if (first) throw new DisError((min ? "min" : "max") + "(): пустая последовательность", line);
        return best;
    }
    }

    // ===================== JSON (для моста в Python) =====================
    static class Json {
        static String dump(Object v) {
            StringBuilder sb = new StringBuilder();
            dumpInto(sb, v);
            return sb.toString();
        }
        static void dumpInto(StringBuilder sb, Object v) {
            if (v == null) { sb.append("null"); return; }
            if (v instanceof Boolean) { sb.append(v.toString()); return; }
            if (v instanceof Long) { sb.append(v.toString()); return; }
            if (v instanceof Double) { sb.append(Interpreter.strDouble((Double) v)); return; }
            if (v instanceof String) { quote(sb, (String) v); return; }
            if (v instanceof List) {
                sb.append('[');
                boolean first = true;
                for (Object o : (List<?>) v) {
                    if (!first) sb.append(',');
                    first = false;
                    dumpInto(sb, o);
                }
                sb.append(']');
                return;
            }
            if (v instanceof Map) {
                sb.append('{');
                boolean first = true;
                for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                    if (!first) sb.append(',');
                    first = false;
                    quote(sb, String.valueOf(e.getKey()));
                    sb.append(':');
                    dumpInto(sb, e.getValue());
                }
                sb.append('}');
                return;
            }
            if (v instanceof FuncVal || v instanceof LambdaVal || v instanceof Bound
                    || v instanceof JavaClassVal || v instanceof Interpreter.ModuleVal || v instanceof PyModuleVal)
                throw new DisError("нельзя передать значение типа '" + Interpreter.tname(v) + "' в Python", 0);
            quote(sb, Interpreter.str(v));
        }
        static void quote(StringBuilder sb, String s) {
            sb.append('"');
            for (char c : s.toCharArray()) {
                if (c == '"') sb.append("\\\"");
                else if (c == '\\') sb.append("\\\\");
                else if (c == '\n') sb.append("\\n");
                else if (c == '\r') sb.append("\\r");
                else if (c == '\t') sb.append("\\t");
                else if (c == '\b') sb.append("\\b");
                else if (c == '\f') sb.append("\\f");
                else if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                else sb.append(c);
            }
            sb.append('"');
        }
        static Object parse(String s) {
            P p = new P(s);
            Object v = p.value();
            p.ws();
            if (p.i < p.n) throw new DisError("JSON: лишние данные", 0);
            return v;
        }
        static class P {
            final String s; int i, n;
            P(String s) { this.s = s; this.n = s.length(); }
            void ws() { while (i < n && Character.isWhitespace(s.charAt(i))) i++; }
            char cur() { return s.charAt(i); }
            Object value() {
                ws();
                if (i >= n) throw new DisError("JSON: неожиданный конец", 0);
                char c = cur();
                if (c == '{') return obj();
                if (c == '[') return arr();
                if (c == '"') return strv();
                if (c == 't') { lit("true"); return Boolean.TRUE; }
                if (c == 'f') { lit("false"); return Boolean.FALSE; }
                if (c == 'n') { lit("null"); return null; }
                return num();
            }
            void lit(String w) {
                if (!s.startsWith(w, i)) throw new DisError("JSON: ожидалось " + w, 0);
                i += w.length();
            }
            Object obj() {
                LinkedHashMap<Object, Object> m = new LinkedHashMap<Object, Object>();
                i++;
                ws();
                if (cur() == '}') { i++; return m; }
                while (true) {
                    ws();
                    if (cur() != '"') throw new DisError("JSON: ожидался ключ", 0);
                    Object k = strv();
                    ws();
                    if (cur() != ':') throw new DisError("JSON: ожидалось ':'", 0);
                    i++;
                    m.put(k, value());
                    ws();
                    if (cur() == ',') { i++; continue; }
                    if (cur() == '}') { i++; return m; }
                    throw new DisError("JSON: ожидалась '}'", 0);
                }
            }
            Object arr() {
                ArrayList<Object> a = new ArrayList<Object>();
                i++;
                ws();
                if (cur() == ']') { i++; return a; }
                while (true) {
                    a.add(value());
                    ws();
                    if (cur() == ',') { i++; continue; }
                    if (cur() == ']') { i++; return a; }
                    throw new DisError("JSON: ожидалась ']'", 0);
                }
            }
            String strv() {
                StringBuilder sb = new StringBuilder();
                i++;
                while (true) {
                    if (i >= n) throw new DisError("JSON: незакрытая строка", 0);
                    char c = s.charAt(i++);
                    if (c == '"') return sb.toString();
                    if (c == '\\') {
                        char e = s.charAt(i++);
                        switch (e) {
                            case '"': sb.append('"'); break;
                            case '\\': sb.append('\\'); break;
                            case '/': sb.append('/'); break;
                            case 'n': sb.append('\n'); break;
                            case 't': sb.append('\t'); break;
                            case 'r': sb.append('\r'); break;
                            case 'b': sb.append('\b'); break;
                            case 'f': sb.append('\f'); break;
                            case 'u': sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                            default: throw new DisError("JSON: неверный escape \\" + e, 0);
                        }
                    } else sb.append(c);
                }
            }
            Object num() {
                int start = i;
                if (i < n && (s.charAt(i) == '-' || s.charAt(i) == '+')) i++;
                boolean isf = false;
                while (i < n && Character.isDigit(s.charAt(i))) i++;
                if (i < n && s.charAt(i) == '.') { isf = true; i++; while (i < n && Character.isDigit(s.charAt(i))) i++; }
                if (i < n && (s.charAt(i) == 'e' || s.charAt(i) == 'E')) {
                    isf = true; i++;
                    if (i < n && (s.charAt(i) == '+' || s.charAt(i) == '-')) i++;
                    while (i < n && Character.isDigit(s.charAt(i))) i++;
                }
                String t = s.substring(start, i);
                try {
                    return isf ? (Object) Double.parseDouble(t) : (Object) Long.parseLong(t);
                } catch (NumberFormatException e) {
                    throw new DisError("JSON: неверное число " + t, 0);
                }
            }
        }
    }

    // ===================== Мост в Python =====================
    static class PyBridge {
        static final Object PY_CALLABLE = new Object();
        static String pyCmd;
        static boolean checked;

        static final String GETATTR_PROG =
            "import importlib, sys, json\n" +
            "obj = importlib.import_module(sys.argv[1])\n" +
            "for part in sys.argv[2].split('.'):\n" +
            "    obj = getattr(obj, part)\n" +
            "is_call = callable(obj)\n" +
            "print(json.dumps({'ok': True, 'callable': is_call, 'v': None if is_call else obj}, default=str))\n";
        static final String CALL_PROG =
            "import importlib, sys, json\n" +
            "obj = importlib.import_module(sys.argv[1])\n" +
            "for part in sys.argv[2].split('.'):\n" +
            "    obj = getattr(obj, part)\n" +
            "payload = json.load(open(sys.argv[3], encoding='utf-8'))\n" +
            "args, kwargs = payload[0], payload[1]\n" +
            "try:\n" +
            "    res = obj(*args, **kwargs)\n" +
            "except Exception as e:\n" +
            "    print(json.dumps({'ok': False, 'err': '%s: %s' % (type(e).__name__, e)}, default=str))\n" +
            "else:\n" +
            "    print(json.dumps({'ok': True, 'v': res}, default=str))\n";

        static boolean available() {
            if (!checked) {
                checked = true;
                for (String cand : new String[]{"python", "python3", "py"}) {
                    try {
                        ProcessBuilder pb = new ProcessBuilder(cand, "--version");
                        pb.redirectErrorStream(true);
                        Process p = pb.start();
                        drainStream(p.getInputStream());
                        if (p.waitFor(15, TimeUnit.SECONDS) && p.exitValue() == 0) { pyCmd = cand; break; }
                    } catch (Exception e) { /* пробуем следующий */ }
                }
            }
            return pyCmd != null;
        }

        static Object run(String prog, List<String> argv, int line) {
            ArrayList<String> cmd = new ArrayList<String>();
            cmd.add(pyCmd); cmd.add("-c"); cmd.add(prog);
            cmd.addAll(argv);
            try {
                File errFile = File.createTempFile("dis-py", ".err");
                ProcessBuilder pb = new ProcessBuilder(cmd);
                pb.redirectError(errFile);
                Process p = pb.start();
                String out = drainStream(p.getInputStream());
                if (!p.waitFor(60, TimeUnit.SECONDS)) {
                    p.destroyForcibly();
                    errFile.delete();
                    throw new DisError("Python-мост: тайм-аут", line);
                }
                if (p.exitValue() != 0) {
                    String err = readFile(errFile);
                    errFile.delete();
                    throw new DisError("Python-мост: " + (err.trim().isEmpty() ? "код " + p.exitValue() : err.trim()), line);
                }
                errFile.delete();
                String last = lastLine(out);
                if (last == null) throw new DisError("Python-мост: пустой ответ", line);
                Object json = Json.parse(last);
                if (!(json instanceof Map)) throw new DisError("Python-мост: неверный формат ответа", line);
                Map<?, ?> m = (Map<?, ?>) json;
                if (Boolean.FALSE.equals(m.get("ok")))
                    throw new DisError("Python-ошибка: " + m.get("err"), line);
                return m;
            } catch (DisError e) {
                throw e;
            } catch (Exception e) {
                throw new DisError("Python-мост: " + e, line);
            }
        }

        static Object getattr(String mod, String attr, int line) {
            if (!available()) throw new DisError("python не найден: библиотеки Python недоступны в Java-версии", line);
            Map<?, ?> res = (Map<?, ?>) run(GETATTR_PROG, Arrays.asList(mod, attr), line);
            if (Boolean.TRUE.equals(res.get("callable"))) return PY_CALLABLE;
            return res.get("v");
        }

        static Object call(String mod, String attr, List<Object> args, Map<String, Object> kwargs, int line) {
            if (!available()) throw new DisError("python не найден: библиотеки Python недоступны в Java-версии", line);
            ArrayList<Object> payload = new ArrayList<Object>();
            payload.add(args);
            payload.add(kwargs);
            File f = null;
            try {
                f = File.createTempFile("dis-py", ".json");
                java.nio.file.Files.write(f.toPath(), Json.dump(payload).getBytes(java.nio.charset.StandardCharsets.UTF_8));
                Map<?, ?> res = (Map<?, ?>) run(CALL_PROG, Arrays.asList(mod, attr, f.getPath()), line);
                return res.get("v");
            } catch (IOException e) {
                throw new DisError("Python-мост: не удалось записать временный файл: " + e, line);
            } finally {
                if (f != null) f.delete();
            }
        }

        static String drainStream(InputStream in) throws IOException {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int r;
            while ((r = in.read(buf)) >= 0) bos.write(buf, 0, r);
            return new String(bos.toByteArray(), java.nio.charset.StandardCharsets.UTF_8);
        }

        static String readFile(File f) {
            try {
                FileInputStream fis = new FileInputStream(f);
                try { return drainStream(fis); }
                finally { fis.close(); }
            } catch (IOException e) {
                return "";
            }
        }

        static String lastLine(String s) {
            String last = null;
            for (String l : s.split("\r?\n")) if (!l.trim().isEmpty()) last = l;
            return last;
        }
    }

    // ===================== CLI =====================
    static BufferedReader stdinReader;

    static String renderError(DisError e, List<String> srcLines, String filename) {
        StringBuilder sb = new StringBuilder("DeinstallError: ").append(e.msg);
        if (filename != null) sb.append("\n  файл: ").append(filename);
        if (e.line > 0 && srcLines != null && e.line <= srcLines.size())
            sb.append("\n  строка ").append(e.line).append(": ").append(srcLines.get(e.line - 1).trim());
        else if (e.line > 0)
            sb.append("\n  строка ").append(e.line);
        return sb.toString();
    }

    static List<String> splitLines(String s) {
        ArrayList<String> out = new ArrayList<String>(Arrays.asList(s.split("\n", -1)));
        for (int i = 0; i < out.size(); i++) out.set(i, out.get(i).replace("\r", ""));
        return out;
    }

    static int runSource(String source, List<String> argv, String filename, Interpreter interp) {
        List<String> lines = splitLines(source);
        List<Node> stmts;
        try {
            stmts = parse(source);
        } catch (DisError e) {
            System.err.println(renderError(e, lines, filename));
            return 1;
        }
        if (interp == null) interp = new Interpreter(argv);
        try {
            interp.run(stmts);
            return 0;
        } catch (ExitEx x) {
            return x.code;
        } catch (DisError e) {
            StringBuilder sb = new StringBuilder(renderError(e, lines, filename));
            for (String t : interp.traceback()) sb.append('\n').append(t);
            System.err.println(sb.toString());
            return 1;
        }
    }

    static boolean codeUnbalanced(String s) {
        int depth = 0;
        String instr = null;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (instr != null) {
                if (c == '\\') i++;
                else if (String.valueOf(c).equals(instr)) instr = null;
            } else if (c == '"' || c == '\'') {
                if (s.startsWith("" + c + c + c, i)) { instr = "" + c + c + c; i += 2; }
                else instr = String.valueOf(c);
            } else if (c == '#') break;
            else if (c == '(' || c == '[' || c == '{') depth++;
            else if (c == ')' || c == ']' || c == '}') depth--;
        }
        return depth > 0 || instr != null;
    }

    static final ArrayDeque<String> pendingLines = new ArrayDeque<String>();

    static String readLine(String prompt) throws IOException {
        if (!pendingLines.isEmpty()) return pendingLines.poll();
        System.out.print(prompt);
        System.out.flush();
        String l = stdinReader.readLine();
        if (l == null) throw new ExitEx(0);
        return l;
    }

    static String readStatement() throws IOException {
        ArrayList<String> lines = new ArrayList<String>();
        lines.add(readLine("dis> "));
        while (true) {
            String src = Interpreter.joinStr(lines, "\n");
            if (codeUnbalanced(src)) { lines.add(readLine("... ")); continue; }
            String last = lines.get(lines.size() - 1);
            int cut = last.indexOf('#');
            if (cut >= 0) last = last.substring(0, cut);
            if (last.trim().endsWith(":")) {
                while (true) {
                    String line = readLine("... ");
                    if (line.trim().isEmpty()) { lines.add(line); continue; }
                    if (line.startsWith(" ") || line.startsWith("\t")) { lines.add(line); continue; }
                    pendingLines.add(line);
                    break;
                }
            }
            return Interpreter.joinStr(lines, "\n");
        }
    }

    static void repl() throws IOException {
        stdinReader = new BufferedReader(new InputStreamReader(System.in));
        System.out.println("Deinstall Script " + VERSION + " (Java). exit() — выход.");
        ArrayList<String> argv = new ArrayList<String>();
        argv.add("<repl>");
        Interpreter interp = new Interpreter(argv);
        while (true) {
            String src;
            try {
                src = readStatement();
            } catch (ExitEx e) {
                return;
            }
            if (src.trim().isEmpty()) continue;
            List<String> lines = splitLines(src);
            try {
                List<Node> stmts = parse(src);
                Object last = null;
                for (Node s : stmts) {
                    if (s instanceof NExpr) last = interp.eval(((NExpr) s).value, interp.globals);
                    else interp.exec(s, interp.globals);
                }
                if (last != null) System.out.println(Interpreter.repr(last));
            } catch (DisError e) {
                System.err.println(renderError(e, lines, null));
            } catch (ExitEx e) {
                return;
            }
        }
    }

    // C-ускорение: Java-версия передаёт эстафету Python-версии (deinstall.py),
    // которая собирает скрипт нативным C. Если не вышло — null (обычный режим).
    static Integer superfastViaPython(String scriptPath, List<String> argv) {
        try {
            java.io.File script = new java.io.File(scriptPath).getAbsoluteFile();
            java.io.File dir = script.getParentFile();
            if (dir == null) dir = new java.io.File(".");
            java.io.File py = null;
            java.io.File[] cands = new java.io.File[] {
                new java.io.File(dir, "deinstall.py"),
                new java.io.File(dir, ".." + java.io.File.separator + "deinstall.py"),
                new java.io.File("deinstall.py")
            };
            for (java.io.File c : cands) {
                if (c.isFile()) { py = c; break; }
            }
            if (py == null) {
                try {
                    java.io.File cs = new java.io.File(DeinstallScript.class.getProtectionDomain()
                            .getCodeSource().getLocation().toURI());
                    java.io.File d2 = cs.isDirectory() ? cs : cs.getParentFile();
                    java.io.File c2 = new java.io.File(d2, "deinstall.py");
                    if (c2.isFile()) py = c2;
                } catch (Throwable t) { }
            }
            if (py == null) {
                sfNote("deinstall.py не найден — выполняю на JVM");
                return null;
            }
            ArrayList<String> cmd = new ArrayList<String>();
            cmd.add("python");
            cmd.add(py.getAbsolutePath());
            cmd.addAll(argv);
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.inheritIO();
            sfNote("C-сборку выполняет Python-версия (" + py.getName() + ")");
            Process proc = pb.start();
            return Integer.valueOf(proc.waitFor());
        } catch (Throwable t) {
            sfNote("не удалось запустить Python-версию (" + t.getMessage() + ") — выполняю на JVM");
            return null;
        }
    }

    static void sfNote(String msg) {
        if (System.getenv("DIS_SUPERFAST_QUIET") != null) return;
        System.err.println("[superfast] " + msg);
        System.err.flush();
    }

    public static void main(String[] args) throws IOException {
        try {
            if (args.length == 0) { repl(); return; }
            String a0 = args[0];
            if (a0.equals("-v") || a0.equals("--version")) {
                System.out.println("Deinstall Script " + VERSION + " (Java)");
                return;
            }
            if (a0.equals("-h") || a0.equals("--help")) {
                System.out.println("Deinstall Script " + VERSION + " — язык программирования (не удаляет ничего!)");
                System.out.println("Запуск:");
                System.out.println("  java DeinstallScript script.dis [аргументы...] — выполнить скрипт");
                System.out.println("  java DeinstallScript                          — REPL");
                System.out.println("  java DeinstallScript --check script.dis       — проверить синтаксис");
                System.out.println("Синтаксис похож на Python: func, elseif, loop, ret, true/false/null,");
                System.out.println("try/catch, throw. Библиотеки Python доступны через import (мост через python).");
                return;
            }
            int off = 0;
            boolean check = false;
            if (a0.equals("--check") || a0.equals("-c")) {
                check = true;
                off = 1;
                if (args.length == 1) { System.err.println("укажите файл"); System.exit(2); }
            }
            String path = args[off];
            String source;
            try {
                byte[] data = java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(path));
                source = new String(data, java.nio.charset.StandardCharsets.UTF_8);
            } catch (IOException e) {
                System.err.println("DeinstallError: не удалось открыть файл: " + e.getMessage());
                System.exit(1);
                return;
            }
            if (check) {
                try {
                    parse(source);
                } catch (DisError e) {
                    System.err.println(renderError(e, splitLines(source), path));
                    System.exit(1);
                    return;
                }
                System.out.println("Синтаксис в порядке: " + path);
                return;
            }
            ArrayList<String> argv = new ArrayList<String>();
            argv.add(path);
            for (int i = off + 1; i < args.length; i++) argv.add(args[i]);
            Integer sfCode = null;
            try {
                List<Node> first = parse(source);
                if (!first.isEmpty() && first.get(0) instanceof NSuperfast
                        && ((NSuperfast) first.get(0)).enabled) {
                    sfCode = superfastViaPython(path, argv);
                }
            } catch (DisError ignore) { }
            if (sfCode != null) System.exit(sfCode.intValue());
            System.exit(runSource(source, argv, path, null));
        } catch (ExitEx e) {
            System.exit(e.code);
        }
    }
}
