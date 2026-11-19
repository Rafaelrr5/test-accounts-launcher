@echo off
rem Instalacao do zero: ambiente Python, biblioteca, configuracao das contas e atalhos na area de trabalho.
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH" e rode de novo.
  pause & exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente Python...
  %PY% -m venv .venv || goto :erro
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :erro

".venv\Scripts\python.exe" launcher.py setup || goto :erro
".venv\Scripts\python.exe" launcher.py shortcut || goto :erro
echo.
echo Pronto. Use o atalho "Contas de teste" na area de trabalho.
pause
exit /b 0

:erro
echo.
echo Algo deu errado (mensagem acima). Corrija e rode instalar.bat de novo: o que ja foi feito e mantido.
pause
exit /b 1
