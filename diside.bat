@echo off
rem Deinstall Studio — запуск IDE для языка Deinstall Script
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0deinstall_ide.py" %*
) else (
    python "%~dp0deinstall_ide.py" %*
)
