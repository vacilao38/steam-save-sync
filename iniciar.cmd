@echo off
setlocal
where py >nul 2>nul
if errorlevel 1 goto python
py -3 "%~dp0steam_saves.py" %*
goto done
:python
python "%~dp0steam_saves.py" %*
:done
pause
