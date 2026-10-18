# Deinstall Script (`.dis`)

**Deinstall Script** — это язык программирования. Он **ничего не удаляет** — несмотря
на название, это полноценный скриптовый язык со знакомым синтаксисом.

Ключевые идеи:
- Синтаксис **похож на Python, но немного изменён** (`func`, `elseif`, `loop`, `ret`,
  `true/false/null`, `try/catch`, `throw`).
- Отступы, как в Python, — блоки кода определяются пробелами.
- **Можно использовать любые библиотеки Python** через `import` — язык написан
  на Python, а Java-версия умеет ходить в Python через «мост».
- Реализован **дважды**: на Python (`deinstall.py`) и на Java (`DeinstallScript.java`).
  Один и тот же скрипт `.dis` работает в обеих версиях.

---

## Быстрый старт

Нужен установленный Python 3 и/или Java (проверьте: `python --version`, `java -version`).

```bat
:: Python-версия
python deinstall.py examples\hello.dis
dis.bat examples\hello.dis

:: Java-версия (сначала: javac -encoding UTF-8 DeinstallScript.java)
java -Dfile.encoding=UTF-8 DeinstallScript examples\hello.dis
disj.bat examples\hello.dis

:: REPL (просто запустите без аргументов)
python deinstall.py
java -Dfile.encoding=UTF-8 DeinstallScript

:: Проверка синтаксиса без запуска
python deinstall.py --check script.dis

:: IDE с подсветкой и автодополнением
diside.bat
```

Пример `examples/hello.dis`:

```
# Привет, мир! — Deinstall Script
func greet(name):
    println{f"Привет, {name}!"}

greet("Deinstall Script")

x = 10
if x * 2 > 15:
    println{"x большой"}
elseif x == 0:
    println{"x равен нулю"}
else:
    println{"x нормальный"}

loop i in range(3):
    println{f"итерация {i}"}
```

---

## Фирменный синтаксис: вызов функций через `{ }`

Главное отличие от Python — функции (и методы) можно вызывать **фигурными скобками**:

```
println{"Привет, мир!"}
println{"а", "б", sep=" - "}       # именованные аргументы как в Python
add{1, 2, c=10}                    # любая своя функция тоже
words.append{"деинсталл"}          # и методы тоже
```

`println{text}` — печать строки с переносом. Скобки `()` — такой же синоним,
на выбор. `print(...)` оставлен для совместимости, а `println` всегда ставит перенос.

---

## Печать в стиле Python 2: `pythontwo.print`

Если очень хочется старую добрую печать «как в Python 2» — она есть,
через модуль `pythontwo`:

```
pythontwo.print "привет"                # привет
pythontwo.print "а", "б", "в"           # а б в
pythontwo.print "без переноса,",        # хвостовая запятая убирает перенос
pythontwo.print "продолжение"           # без переноса продолжение
pythontwo.print                         # пустая строка
pythontwo.print("можно и так", "тоже")  # и обычным вызовом — тоже работает
```

Как в Python 2: значения печатаются через пробел, перенос — автоматически,
а **хвостовая запятая** (`print "текст",`) гасит перенос. Вариант
`pythontwo.print(...)`/`pythontwo.print{...}` работает как обычная функция.

---

## C-ускорение: `superfast.enable`

Если **первой строкой** скрипта написать

```
superfast.enable
```

то Deinstall Script не интерпретирует программу, а **генерирует код на C,
компилирует его настоящим C-компилятором и запускает нативным кодом** —
это в разы быстрее обычного режима. Для тяжёлых циклов и вычислений:

```
superfast.enable

func collatz_steps(n):
    steps = 0
    while n != 1:
        if n % 2 == 0:
            n = n // 2
        else:
            n = n * 3 + 1
        steps += 1
    ret steps

total = 0
loop i in range(1, 200000):
    total += collatz_steps(i)
println{f"суммарно шагов: {total}"}
```

(`superfast.disable` или отсутствие строки — обычный режим; пример:
`examples/superfast.dis`. Замер скорости: `python deinstall.py examples/superfast.dis`.)

Замер на этой машине (20 000 чисел Коллатца): обычный режим — около
23 секунд, а с `superfast.enable` — примерно 1 секунда (первый запуск
тратит ещё несколько секунд на компиляцию, дальше готовый нативный код
берётся из кэша).

Как это работает и что нужно:

* Нужен любой C-компилятор: `gcc`, `clang`, `cl`, `tcc` или `zig` в `PATH`.
  Ещё варианты: положить TCC в `tools/tcc/tcc.exe` рядом с интерпретатором
  или указать свой: `set DIS_CC=gcc`.
* Что C-бэкенд умеет: числа и строки, вся арифметика (включая `//`, `%`,
  `**` с Python-семантикой), сравнения, `and/or/not`, `if/elseif/else`,
  `while`, `loop ... in range(...)`, функции `func`/`ret`, f-строки,
  `print`/`println`/`pythontwo.print`, `import math` (`math.sqrt`, `math.pi`
  и другие), `str/int/float/abs/min/max/exit`, `input()` — ввод с
  клавиатуры (работает и в собранном `.exe`), `int()`/`float()` от строки,
  `break/continue`, `+=` и т.п.
* Чего не умеет (списки, словари, `import json`, `try/catch`, методы строк
  и т. д.) — скрипт **честно выполняется обычным способом**, а в stderr
  появляется одна строка-пометка вроде
  `[superfast] списки... — выполняю обычным способом`. Результат всегда
  правильный, просто без ускорения.
* Пометки можно выключить: `set DIS_SUPERFAST_QUIET=1`.
* В Java-версии строка `superfast.enable` тоже понимается, но ускорение
  выполняет Python-версия (`deinstall.py`) — см. `dis.bat`.

Ограничения быстрого режима (всё это тоже просто уходит в обычный режим):
переменные честные и одного типа, глобальные переменные из функций менять
нельзя, `and/or` как значение — только для логических выражений,
`min/max` — одного типа, `loop` — только по `range(...)`.

---

## IDE: Deinstall Studio

В комплекте — редактор для языка с подсветкой и автодополнением:

```
diside.bat                          — запустить IDE в один клик
diside.bat examples\superfast.dis   — сразу открыть файл
python deinstall_ide.py             — то же самое из командной строки
```

Что умеет:

* **подсветка синтаксиса** — ключевые слова, встроенные функции, строки,
  числа, комментарии, имена после `func`, директива `superfast`, скобки;
* **автодополнение** — появляется при наборе или по `Ctrl+Space`: ключевые
  слова, встроенные функции, имена функций и переменных из самого скрипта,
  а после точки — атрибуты модулей (`math.` → `sqrt`, `pi`, `floor`, …);
  `Enter`/`Tab` — принять подсказку, `Esc` — закрыть;
* **запуск** — `F5` открывает отдельное окно командной строки и запускает
  скрипт через `dis.bat` (Python-версия); `Ctrl+F5` — через `disj.bat`
  (Java-версия); аргументы командной строки пишутся в поле «аргументы»
  на панели;
* окно после завершения скрипта **не закрывается**: результат и ошибки
  остаются на экране, а окно закрывается командой `exit` — как при
  обычном запуске из консоли; для быстрых проверок есть и запуск во
  встроенной консоли IDE (меню «Запуск»);
* **проверка синтаксиса** — `F6`; при ошибке курсор встаёт на нужную строку;
* **сборка в .exe** — `F7`: скрипт переводится в C и компилируется тем же
  бэкендом, что у `superfast`; рядом со скриптом появляется `<имя>.exe`,
  которому Python не нужен (если конструкция не переводится в C — IDE
  честно скажет, что именно);
* удобства: номера строк, подсветка текущей строки и парных скобок,
  автоотступы, парные кавычки и скобки, поиск (`Ctrl+F`), переход к строке
  (`Ctrl+G`), комментарий (`Ctrl+/`), шаблоны кода в меню «Вставка»;
* консоль прямо в IDE: вывод программы, поле ввода для `input()`,
  кнопка «Стоп»; кнопка «🧹 Очистить».

Самопроверка IDE: `python deinstall_ide.py --selftest` — проверяет
подсветку, автодополнение, запуск интерпретатора и C-бэкенд.

---

## Соответствие с Python

| Python | Deinstall Script | Зачем |
|---|---|---|
| `def` | `func` | короче и «по-своему» |
| `elif` | `elseif` | читается как «иначе если» |
| `for ... in` | `loop ... in` | `for` не занято |
| `return` | `ret` | короче |
| `True/False/None` | `true/false/null` | единый стиль (и Python-варианты тоже работают) |
| `except` | `catch` | привычнее многим |
| `del`/`raise` | — / `throw` | `throw` для своих ошибок |
| кортежи `(a, b)` | это **списки** | проще и совместимее |
| — | `var x = 5` | необязательное объявление (то же, что `x = 5`) |
| `list[...]`-comprehensions | нет | пишите цикл `loop` |

Всё остальное — как в Python: операторы, приоритеты, отступы, `#`-комментарии,
f-строки `f"..."`, срезы `a[1:4]`, `a[::2]`, `in`/`not in`, `and/or/not`,
словари, методы `.append()`, `.items()`, `.sort(key=...)` и т.д.

### Типы данных

`int`, `float`, `str`, `bool`, `list`, `dict`, `range`, `func`, `null`, `error`.

```
a = 42          # int
pi = 3.14       # float
s = "привет"    # str
ok = true       # bool
xs = [1, 2, 3]  # list, кортеж (1, 2) — тоже list
d = {"к": "в"}  # dict
r = range(10)   # range (можно индексировать и срезать)
nothing = null
```

### Функции

```
func add(a, b, c=0):          # аргумент по умолчанию
    ret a + b + c

func log(level, *lines):      # *rest — все лишние аргументы списком
    loop l in lines:
        print(f"[{level}] {l}")

func cfg(**opts):             # **kwrest — именованные аргументы словарём
    print(opts)

add(1, 2)                     # 3
add(1, 2, c=10)               # 13
log("INFO", "раз", "два")     # именованные и распаковка работают:
args = [4, 5]
opts = {"c": 6}
add(*args, **opts)            # 15

square = lambda x: x * x      # анонимные функции
```

Переменная ищется по цепочке областей видимости, присваивание меняет уже
существующую переменную (поэтому счётчики в вложенных функциях работают).

### Ошибки: try / catch / throw

```
func divide(a, b):
    if b == 0:
        throw "деление на ноль!"
    ret a / b

try:
    print(divide(10, 0))
catch e:
    print("Ошибка:", e.message, "в строке", e.line)   # у ошибки есть атрибуты
```

Любая ошибка (своя через `throw` или возникшая внутри) ловится одним `catch`.

---

## Библиотеки Python — в обеих версиях

```
import math
import random
import json
import datetime          # и любые другие: os, sys, re, sqlite3, requests...

print(math.sqrt(2), math.pi)
random.seed(42)
print(json.dumps({"a": [1, 2]}, indent=2, ensure_ascii=false))
```

- **Python-версия** (`deinstall.py`): всё работает напрямую — любой пакет с `pip`.
  Даже безымянные Python-функции доступны из коробки (`open`, `isinstance`, ...).
- **Java-версия**: `math`, `random`, `time` встроены по-java-ски, остальное
  импортируется через **мост в Python** (запускается `python -c`, значения
  переносятся через JSON). Нужен установленный `python` в PATH.
  Ограничение моста: результаты — только данные (числа/строки/списки/словари);
  с «живыми» объектами Python цепочки методов не работают.

## Классы Java — только в Java-версии

```
import java.lang.Math
import java.time.LocalDate
import java.util.ArrayList

print(Math.PI, Math.sqrt(216))
print(LocalDate.now(), LocalDate.now().getYear())

words = ArrayList()
words.add("деинсталл")     # рефлексия: методы любого класса Java
print(words, len(words))
```

Импорт класса Java: `import java.X.Y` (или `as`-псевдоним). Вызов класса
создаёт объект, статические методы/поля и методы объектов доступны напрямую.

---

## Встроенные функции (одинаковы в обеих версиях)

`print(sep, end)`, `input`, `len`, `type`, `str`, `int`, `float`, `bool`,
`list`, `dict`, `abs`, `min`, `max`, `sum`, `round`, `sorted(key, reverse)`,
`reversed`, `enumerate`, `zip`, `map`, `filter`, `any`, `all`, `repr`,
`format`, `range`, `read_file(path)`, `write_file(path, text)`, `exists(path)`,
`exit(code)`, `argv` (список аргументов скрипта).

## Флаги командной строки

| Флаг | Значение |
|---|---|
| (без аргументов) | REPL |
| `script.dis [args...]` | выполнить скрипт |
| `--check script.dis` | проверить синтаксис |
| `--version` / `-v` | версия |
| `--help` / `-h` | справка |

---

## Отличия реализаций

| | deinstall.py | DeinstallScript.java |
|---|---|---|
| Библиотеки Python | напрямую | через мост (python в PATH) |
| Классы Java | нет | есть (рефлексия) |
| `open()` и прочие Python-функции | да (из Python builtins) | нет, используйте `read_file`/`write_file` |
| Кортежи из Python-функций | остаются кортежами | приходят как списки |
| Требование | Python 3.x | Java 8+ (`javac -encoding UTF-8`) |

Вывод `print` у всех чисел совпадает (`4/2` → `2.0`, как в Python).

---

## Структура проекта

```
deinstall script/
├── deinstall.py            — интерпретатор на Python (лексер, парсер, исполнитель)
├── DeinstallScript.java    — интерпретатор на Java (та же грамматика + мост в Python)
├── deinstall_ide.py        — IDE: подсветка, автодополнение, сборка в .exe
├── dis.bat / disj.bat      — запуск обеих версий в один клик
├── diside.bat              — запуск IDE в один клик
├── README.md               — этот файл
└── examples/
    ├── minimal.dis         — минимальный скрипт: println{"текст"}
    ├── pytwo.dis           — печать как в Python 2: pythontwo.print "текст",
    ├── superfast.dis       — C-ускорение: superfast.enable + бенчмарк
    ├── hello.dis           — базовый синтаксис (работает в обеих версиях)
    ├── fib.dis             — функции, рекурсия, лямбды (обе версии)
    ├── collections.dis     — списки, словари, срезы, try/catch (обе версии)
    ├── py_lib.dis          — библиотеки Python: math, random, json, time (обе версии)
    ├── python_only.dis     — привилегии Python-версии: datetime, os, sys
    └── java_only.dis       — привилегии Java-версии: java.lang.Math, java.time
```

## Как это устроено

Обе реализации — классические интерпретаторы «в лоб», но полностью рабочие:

1. **Лексер** — токенизация с отслеживанием отступов (INDENT/DEDENT, как в Python),
   f-строк, многострочных строк, скобочных продлений строк.
2. **Парсер** — рекурсивный спуск, строит AST с точными номерами строк.
3. **Исполнитель** — обход AST, окружения-цепочки, функции-замыкания,
   итераторы, `try/catch` через исключения, трассировка стека при ошибках.

В Python-версии значения — это настоящие объекты Python, поэтому любая
библиотека работает «бесплатно». В Java-версии значения — это
`Long/Double/String/ArrayList/LinkedHashMap/RangeVal` плюс классы Java через
рефлексию, а Python-библиотеки подключены подпроцессом `python -c` с
обменом через JSON (свой маленький JSON-парсер и сериализатор внутри).
