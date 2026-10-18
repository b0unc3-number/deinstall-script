@echo off
rem Deinstall Script — запуск Java-версии интерпретатора (при необходимости компилирует)
rem Использование: disj.bat script.dis [аргументы...]
rem Внимание: класс ищется через "%~dp0." (точка обязательна: путь с "\" перед
rem кавычкой ломает разбор аргументов в java.exe)
if not exist "%~dp0DeinstallScript.class" javac -encoding UTF-8 "%~dp0DeinstallScript.java"
java -Dfile.encoding=UTF-8 -cp "%~dp0." DeinstallScript %*
