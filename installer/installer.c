/* Deinstall Script — установщик для Windows.
 *
 * Что делает:
 *   - копирует интерпретаторы (Python/Java), IDE, bat-файлы, примеры
 *     и документацию в выбранную папку;
 *   - умеет аккуратно удалять установку (/uninstall), не трогая
 *     пользовательские скрипты.
 *
 * Чего НЕ делает (специально):
 *   - НЕ изменяет переменные среды (PATH и т.п.);
 *   - НЕ пишет в реестр;
 *   - НЕ требует прав администратора.
 *
 * Сборка (MinGW-w64 / MSVC):
 *   gcc -O2 -municode installer.c -o deinstall-setup.exe
 *
 * Использование:
 *   deinstall-setup.exe                      интерактивная установка
 *   deinstall-setup.exe /dir D:\Deinstall    установить без вопросов
 *   deinstall-setup.exe /src <папка>         откуда брать файлы языка
 *   deinstall-setup.exe /uninstall [/dir …]  удалить установку
 *   /yes                                     не задавать вопросов
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <wchar.h>

#define MAXP 1024
#define VERSION L"1.0"

static HANDLE hout;
static int console_out = 1;

/* ---------------------------------------------------------------- вывод */

static void color(int c) {
    if (console_out) SetConsoleTextAttribute(hout, (WORD)c);
}
#define CLR_DEFAULT 7
#define CLR_GREEN   10
#define CLR_RED     12
#define CLR_YELLOW  14
#define CLR_CYAN    11

static void wputs(const wchar_t* s) {
    DWORD n = (DWORD)wcslen(s), w;
    if (n == 0) return;
    if (console_out && WriteConsoleW(hout, s, n, &w, NULL)) return;
    console_out = 0;
    {
        int len = WideCharToMultiByte(CP_UTF8, 0, s, (int)n, NULL, 0, NULL, NULL);
        char* buf;
        if (len <= 0) return;
        buf = (char*)malloc((size_t)len);
        if (!buf) return;
        WideCharToMultiByte(CP_UTF8, 0, s, (int)n, buf, len, NULL, NULL);
        fwrite(buf, 1, (size_t)len, stdout);
        fflush(stdout);
        free(buf);
    }
}

static void wsay(const wchar_t* fmt, ...) {
    wchar_t buf[2048];
    va_list ap;
    va_start(ap, fmt);
    vswprintf(buf, 2048, fmt, ap);
    va_end(ap);
    buf[2047] = 0;
    wputs(buf);
}

static void read_line(wchar_t* buf, DWORD cap) {
    DWORD n = 0;
    buf[0] = 0;
    if (!ReadConsoleW(GetStdHandle(STD_INPUT_HANDLE), buf, cap - 1, &n, NULL)) return;
    while (n > 0 && (buf[n - 1] == L'\r' || buf[n - 1] == L'\n')) n--;
    buf[n] = 0;
}

static int ask_yes_no(const wchar_t* q, int def_yes) {
    wchar_t b[64];
    for (;;) {
        wsay(L"%ls (%ls): ", q, def_yes ? L"Д/н" : L"д/Н");
        read_line(b, 64);
        if (!b[0]) return def_yes;
        if (b[0] == L'д' || b[0] == L'Д' || b[0] == L'y' || b[0] == L'Y') return 1;
        if (b[0] == L'н' || b[0] == L'Н' || b[0] == L'n' || b[0] == L'N') return 0;
    }
}

/* ---------------------------------------------------------------- пути */

static int exists(const wchar_t* p) {
    return GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES;
}

static void clean_path(wchar_t* p) {
    size_t n = wcslen(p);
    if (n >= 2 && p[0] == L'"' && p[n - 1] == L'"') {
        memmove(p, p + 1, (n - 2) * sizeof(wchar_t));
        n -= 2;
        p[n] = 0;
    }
    while (n > 3 && (p[n - 1] == L'\\' || p[n - 1] == L'/')) p[--n] = 0;
    for (size_t i = 0; i < n; i++)
        if (p[i] == L'/') p[i] = L'\\';
}

static void expand_path(wchar_t* p) {
    wchar_t tmp[MAXP];
    if (ExpandEnvironmentStringsW(p, tmp, MAXP)) {
        wcsncpy(p, tmp, MAXP - 1);
        p[MAXP - 1] = 0;
    }
}

static void join(wchar_t* out, const wchar_t* a, const wchar_t* b) {
    size_t n = wcslen(a);
    if (n && a[n - 1] == L'\\')
        swprintf(out, MAXP, L"%ls%ls", a, b);
    else
        swprintf(out, MAXP, L"%ls\\%ls", a, b);
    out[MAXP - 1] = 0;
}

static void dir_of(const wchar_t* path, wchar_t* out) {
    wchar_t* s;
    wcsncpy(out, path, MAXP - 1);
    out[MAXP - 1] = 0;
    s = wcsrchr(out, L'\\');
    if (s) *s = 0;
    else wcscpy(out, L".");
}

static int mkdir_p(const wchar_t* dir) {
    wchar_t tmp[MAXP];
    size_t n;
    if (exists(dir)) return 1;
    wcsncpy(tmp, dir, MAXP - 1);
    tmp[MAXP - 1] = 0;
    n = wcslen(tmp);
    for (size_t i = 3; i < n; i++) {
        if (tmp[i] == L'\\') {
            tmp[i] = 0;
            CreateDirectoryW(tmp, NULL);
            tmp[i] = L'\\';
        }
    }
    if (!CreateDirectoryW(tmp, NULL))
        return GetLastError() == ERROR_ALREADY_EXISTS;
    return 1;
}

/* .bat-файлы cmd надёжно читает только с CRLF, поэтому при копировании
 * приводим переводы строк к Windows-виду (исходники могут быть с LF). */
static int is_bat(const wchar_t* name) {
    size_t n = wcslen(name);
    return n >= 4 && !_wcsicmp(name + n - 4, L".bat");
}

static int copy_bat_crlf(const wchar_t* src, const wchar_t* dst) {
    HANDLE h, hw;
    LARGE_INTEGER size;
    DWORD n, got = 0, o = 0, wrote = 0;
    char *in, *out;
    int ok = 0;

    h = CreateFileW(src, GENERIC_READ, FILE_SHARE_READ, NULL,
                    OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    if (!GetFileSizeEx(h, &size) || size.QuadPart > 4 * 1024 * 1024) {
        CloseHandle(h);
        return 0;
    }
    n = (DWORD)size.QuadPart;
    in = (char*)malloc(n ? n : 1);
    if (!in || !ReadFile(h, in, n, &got, NULL)) {
        free(in);
        CloseHandle(h);
        return 0;
    }
    CloseHandle(h);

    out = (char*)malloc((size_t)got * 2 + 1);
    if (!out) {
        free(in);
        return 0;
    }
    for (DWORD i = 0; i < got; i++) {
        if (in[i] == '\n' && (i == 0 || in[i - 1] != '\r')) out[o++] = '\r';
        out[o++] = in[i];
    }

    hw = CreateFileW(dst, GENERIC_WRITE, 0, NULL,
                     CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (hw != INVALID_HANDLE_VALUE) {
        ok = WriteFile(hw, out, o, &wrote, NULL) && wrote == o;
        CloseHandle(hw);
        if (!ok) DeleteFileW(dst);
    }
    free(in);
    free(out);
    return ok;
}

/* Удаляем сгенерированные при работе файлы: __pycache__ и *.class. */
static int delete_generated(const wchar_t* dest) {
    static const wchar_t* PATTERNS[] = {
        L"__pycache__\\*.pyc",
        L"DeinstallScript*.class",
    };
    int removed = 0;

    for (size_t i = 0; i < sizeof(PATTERNS) / sizeof(PATTERNS[0]); i++) {
        wchar_t pat[MAXP], f[MAXP];
        WIN32_FIND_DATAW fd;
        HANDLE h;
        join(pat, dest, PATTERNS[i]);
        h = FindFirstFileW(pat, &fd);
        if (h == INVALID_HANDLE_VALUE) continue;
        do {
            join(f, dest, PATTERNS[i]);
            {
                wchar_t* s = wcsrchr(f, L'\\');
                if (s) wcscpy(s + 1, fd.cFileName);
            }
            if (DeleteFileW(f)) removed++;
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    {
        wchar_t pyc[MAXP];
        join(pyc, dest, L"__pycache__");
        RemoveDirectoryW(pyc);
    }
    return removed;
}

/* ------------------------------------------------------------ что ставим */

static const wchar_t* LANGFILES[] = {
    L"deinstall.py",
    L"DeinstallScript.java",
    L"deinstall_ide.py",
    L"dis.bat",
    L"disj.bat",
    L"diside.bat",
    L"README.md",
    L"LICENSE",
};

static const wchar_t* EXAMPLES[] = {
    L"hello.dis", L"minimal.dis", L"pytwo.dis", L"superfast.dis",
    L"fib.dis", L"collections.dis", L"py_lib.dis",
    L"python_only.dis", L"java_only.dis",
};

static int payload_ok(const wchar_t* dir) {
    wchar_t p[MAXP];
    join(p, dir, L"deinstall.py");
    if (!exists(p)) return 0;
    join(p, dir, L"deinstall_ide.py");
    return exists(p);
}

static void default_dir(wchar_t* out) {
    if (!GetEnvironmentVariableW(L"LOCALAPPDATA", out, MAXP))
        wcscpy(out, L"C:\\DeinstallScript");
    join(out, out, L"Deinstall Script");
}

static void check_tool(const wchar_t* exe, const wchar_t* hint) {
    wchar_t p[MAXP];
    if (SearchPathW(NULL, exe, NULL, MAXP, p, NULL)) {
        color(CLR_GREEN);
        wsay(L"  [+] %ls найден\n", exe);
        color(CLR_DEFAULT);
    } else {
        color(CLR_YELLOW);
        wsay(L"  [!] %ls не найден в PATH — %ls\n", exe, hint);
        color(CLR_DEFAULT);
    }
}

static void banner(void) {
    color(CLR_CYAN);
    wsay(L"Deinstall Script — установщик %ls\n", VERSION);
    wsay(L"==================================\n");
    color(CLR_DEFAULT);
    wsay(L"Интерпретаторы Python и Java, IDE, примеры и документация.\n");
    wsay(L"Установщик не меняет переменные среды и не пишет в реестр.\n\n");
}

/* -------------------------------------------------------------- установка */

static int do_install(const wchar_t* exe_dir, const wchar_t* src_arg,
                      const wchar_t* dir_arg, int yes) {
    wchar_t src[MAXP] = L"", dest[MAXP] = L"";
    wchar_t line[MAXP], s[MAXP], d[MAXP], exdir[MAXP];
    wchar_t fs[MAXP], fd[MAXP];
    int copied = 0, failed = 0;

    /* откуда копировать */
    if (src_arg) {
        wcsncpy(src, src_arg, MAXP - 1);
        src[MAXP - 1] = 0;
    } else if (payload_ok(exe_dir)) {
        wcsncpy(src, exe_dir, MAXP - 1);
        src[MAXP - 1] = 0;
    } else {
        wchar_t parent[MAXP];
        dir_of(exe_dir, parent);
        if (payload_ok(parent)) {
            wcsncpy(src, parent, MAXP - 1);
            src[MAXP - 1] = 0;
        }
    }
    if (!src[0]) {
        wsay(L"Файлы языка рядом с установщиком не найдены.\n");
        wsay(L"Введите папку, где лежит deinstall.py (пусто — отмена): ");
        read_line(line, MAXP);
        if (!line[0]) {
            wsay(L"Отменено.\n");
            return 0;
        }
        clean_path(line);
        expand_path(line);
        wcsncpy(src, line, MAXP - 1);
        src[MAXP - 1] = 0;
    }
    clean_path(src);
    expand_path(src);
    if (!payload_ok(src)) {
        color(CLR_RED);
        wsay(L"Ошибка: в папке нет deinstall.py / deinstall_ide.py:\n  %ls\n", src);
        color(CLR_DEFAULT);
        return 1;
    }
    wsay(L"Файлы языка: %ls\n", src);

    /* куда ставить */
    if (dir_arg) {
        wcsncpy(dest, dir_arg, MAXP - 1);
        dest[MAXP - 1] = 0;
    } else {
        default_dir(line);
        wsay(L"\nКуда установить? [%ls]: ", line);
        read_line(dest, MAXP);
        if (!dest[0]) {
            wcsncpy(dest, line, MAXP - 1);
            dest[MAXP - 1] = 0;
        }
    }
    clean_path(dest);
    expand_path(dest);
    if (!dest[0]) {
        wsay(L"Пустой путь — отмена.\n");
        return 1;
    }

    GetFullPathNameW(src, MAXP, fs, NULL);
    GetFullPathNameW(dest, MAXP, fd, NULL);
    if (!_wcsicmp(fs, fd)) {
        color(CLR_YELLOW);
        wsay(L"\nПапка установки совпадает с папкой исходников.\n");
        wsay(L"Скопируйте установщик в другое место (например, на рабочий стол)\n");
        wsay(L"или выберите другую папку установки.\n");
        color(CLR_DEFAULT);
        return 1;
    }

    join(s, dest, L"deinstall.py");
    if (exists(s) && !yes) {
        if (!ask_yes_no(L"\nВ этой папке уже есть Deinstall Script. Обновить?", 1)) {
            wsay(L"Отменено.\n");
            return 0;
        }
    }
    if (!yes && !dir_arg) {
        if (!ask_yes_no(L"Установить сюда?", 1)) {
            wsay(L"Отменено.\n");
            return 0;
        }
    }

    wsay(L"\nУстанавливаю в: %ls\n\n", dest);
    if (!mkdir_p(dest)) {
        color(CLR_RED);
        wsay(L"Не удалось создать папку (код %lu).\n", GetLastError());
        wsay(L"Подсказка: не устанавливайте в Program Files без прав администратора —\n");
        wsay(L"выберите папку в профиле пользователя.\n");
        color(CLR_DEFAULT);
        return 1;
    }

    for (size_t i = 0; i < sizeof(LANGFILES) / sizeof(LANGFILES[0]); i++) {
        join(s, src, LANGFILES[i]);
        join(d, dest, LANGFILES[i]);
        int ok;
        if (!exists(s)) {
            color(CLR_YELLOW);
            wsay(L"  [!] пропущен %ls (нет в исходниках)\n", LANGFILES[i]);
            color(CLR_DEFAULT);
            continue;
        }
        ok = is_bat(LANGFILES[i]) ? copy_bat_crlf(s, d) : CopyFileW(s, d, FALSE);
        if (ok) {
            copied++;
            wsay(L"  [+] %ls\n", LANGFILES[i]);
        } else {
            failed++;
            color(CLR_RED);
            wsay(L"  [x] %ls — ошибка %lu\n", LANGFILES[i], GetLastError());
            color(CLR_DEFAULT);
        }
    }

    join(exdir, dest, L"examples");
    if (mkdir_p(exdir)) {
        for (size_t i = 0; i < sizeof(EXAMPLES) / sizeof(EXAMPLES[0]); i++) {
            join(s, src, L"examples");
            join(s, s, EXAMPLES[i]);
            join(d, exdir, EXAMPLES[i]);
            if (!exists(s)) continue;
            if (CopyFileW(s, d, FALSE)) {
                copied++;
                wsay(L"  [+] examples\\%ls\n", EXAMPLES[i]);
            } else {
                failed++;
                color(CLR_RED);
                wsay(L"  [x] examples\\%ls — ошибка %lu\n", EXAMPLES[i], GetLastError());
                color(CLR_DEFAULT);
            }
        }
    }

    wsay(L"\n");
    color(failed ? CLR_YELLOW : CLR_GREEN);
    wsay(L"Готово! Файлов скопировано: %d", copied);
    if (failed) wsay(L", с ошибками: %d", failed);
    wsay(L"\n");
    color(CLR_DEFAULT);

    wsay(L"\nПроверка окружения (ничего не меняю, только сообщаю):\n");
    check_tool(L"python.exe", L"нужен для deinstall.py и IDE: https://python.org");
    check_tool(L"java.exe", L"нужен только для Java-версии: https://adoptium.net");

    wsay(L"\nКак запускать (программы установлены в:\n  %ls):\n", dest);
    join(s, dest, L"diside.bat");
    wsay(L"  IDE:            %ls\n", s);
    join(s, dest, L"dis.bat");
    wsay(L"  скрипт Python:  %ls  мой_скрипт.dis\n", s);
    join(s, dest, L"disj.bat");
    wsay(L"  скрипт Java:    %ls  мой_скрипт.dis\n", s);
    wsay(L"  сборка .exe:    в IDE, клавиша F7 (нужен C-компилятор, например gcc)\n");

    color(CLR_CYAN);
    wsay(L"\nПеременные среды НЕ изменялись.\n");
    color(CLR_DEFAULT);
    wsay(L"Чтобы запускать из любой папки, добавьте этот путь в PATH сами:\n");
    wsay(L"  Win+R → sysdm.cpl → «Дополнительно» → «Переменные среды…»\n");
    wsay(L"  → Path → Изменить → Создать → %ls\n", dest);
    wsay(L"\nУдаление: deinstall-setup.exe /uninstall\n");
    return failed ? 1 : 0;
}

/* -------------------------------------------------------------- удаление */

static int do_uninstall(const wchar_t* dir_arg, int yes) {
    wchar_t dest[MAXP] = L"", line[MAXP], p[MAXP], exdir[MAXP];
    int removed = 0;

    if (dir_arg) {
        wcsncpy(dest, dir_arg, MAXP - 1);
        dest[MAXP - 1] = 0;
    } else if (yes) {
        default_dir(dest);
    } else {
        default_dir(line);
        wsay(L"Откуда удалить? [%ls]: ", line);
        read_line(dest, MAXP);
        if (!dest[0]) {
            wcsncpy(dest, line, MAXP - 1);
            dest[MAXP - 1] = 0;
        }
    }
    clean_path(dest);
    expand_path(dest);
    if (!dest[0]) {
        wsay(L"Пустой путь — отмена.\n");
        return 1;
    }

    join(p, dest, L"deinstall.py");
    if (!exists(p)) {
        color(CLR_YELLOW);
        wsay(L"Похоже, в этой папке нет установленного Deinstall Script:\n  %ls\n", dest);
        color(CLR_DEFAULT);
        if (!yes && !ask_yes_no(L"Всё равно удалить известные файлы?", 0))
            return 0;
    } else if (!yes) {
        wsay(L"Удалить Deinstall Script из папки:\n  %ls\n", dest);
        if (!ask_yes_no(L"Продолжить?", 1)) {
            wsay(L"Отменено.\n");
            return 0;
        }
    }

    for (size_t i = 0; i < sizeof(LANGFILES) / sizeof(LANGFILES[0]); i++) {
        join(p, dest, LANGFILES[i]);
        if (DeleteFileW(p)) {
            removed++;
            wsay(L"  [-] %ls\n", LANGFILES[i]);
        }
    }
    join(exdir, dest, L"examples");
    for (size_t i = 0; i < sizeof(EXAMPLES) / sizeof(EXAMPLES[0]); i++) {
        join(p, exdir, EXAMPLES[i]);
        if (DeleteFileW(p)) {
            removed++;
            wsay(L"  [-] examples\\%ls\n", EXAMPLES[i]);
        }
    }
    RemoveDirectoryW(exdir);

    {
        int extra = delete_generated(dest);
        if (extra) {
            removed += extra;
            wsay(L"  [-] сгенерированные при работе файлы: %d\n", extra);
        }
    }

    wsay(L"\nУдалено файлов: %d\n", removed);
    if (RemoveDirectoryW(dest)) {
        color(CLR_GREEN);
        wsay(L"Папка полностью удалена.\n");
        color(CLR_DEFAULT);
    } else {
        color(CLR_YELLOW);
        wsay(L"В папке остались другие файлы (ваши скрипты не тронуты):\n  %ls\n", dest);
        color(CLR_DEFAULT);
    }
    wsay(L"Переменные среды и реестр не изменялись.\n");
    return 0;
}

/* ------------------------------------------------------------------ main */

static void usage(void) {
    wsay(L"Deinstall Script — установщик %ls\n\n", VERSION);
    wsay(L"  deinstall-setup.exe                      интерактивная установка\n");
    wsay(L"  deinstall-setup.exe /dir <папка>         установить в папку\n");
    wsay(L"  deinstall-setup.exe /src <папка>         откуда брать файлы языка\n");
    wsay(L"  deinstall-setup.exe /uninstall [/dir …]  удалить установку\n");
    wsay(L"  /yes                                     не задавать вопросов\n");
    wsay(L"\nУстановщик не меняет переменные среды и не пишет в реестр.\n");
}

int wmain(int argc, wchar_t* argv[]) {
    wchar_t exe[MAXP], exe_dir[MAXP];
    const wchar_t* src_arg = NULL;
    const wchar_t* dir_arg = NULL;
    int uninstall = 0, yes = 0;

    SetConsoleOutputCP(65001);
    SetConsoleCP(65001);
    SetConsoleTitleW(L"Deinstall Script — установка");
    hout = GetStdHandle(STD_OUTPUT_HANDLE);

    for (int i = 1; i < argc; i++) {
        if (!_wcsicmp(argv[i], L"/src") && i + 1 < argc) src_arg = argv[++i];
        else if (!_wcsicmp(argv[i], L"/dir") && i + 1 < argc) dir_arg = argv[++i];
        else if (!_wcsicmp(argv[i], L"/uninstall")) uninstall = 1;
        else if (!_wcsicmp(argv[i], L"/yes") || !_wcsicmp(argv[i], L"/y")) yes = 1;
        else if (!_wcsicmp(argv[i], L"/?") || !_wcsicmp(argv[i], L"/help") ||
                 !_wcsicmp(argv[i], L"-h") || !_wcsicmp(argv[i], L"--help")) {
            usage();
            return 0;
        } else {
            color(CLR_RED);
            wsay(L"Неизвестный параметр: %ls\n\n", argv[i]);
            color(CLR_DEFAULT);
            usage();
            return 2;
        }
    }

    GetModuleFileNameW(NULL, exe, MAXP);
    dir_of(exe, exe_dir);

    banner();
    if (uninstall) return do_uninstall(dir_arg, yes);
    return do_install(exe_dir, src_arg, dir_arg, yes);
}
