@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL%==0 (set "PY=py -3") else (set "PY=python")
if not exist .venv\Scripts\python.exe (
  echo [1/3] Создание окружения...
  %PY% -m venv .venv
  if errorlevel 1 (echo Не установлен Python 3.10+ & pause & exit /b 1)
)
echo [2/3] Проверка зависимостей...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (echo Ошибка установки зависимостей. Проверьте Интернет и pip. & pause & exit /b 1)
echo [3/3] Открывайте http://127.0.0.1:8000
start "" /B .venv\Scripts\python.exe -m backend.open_browser
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause
