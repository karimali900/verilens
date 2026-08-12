@echo off
rem VeriLens (المدقق) - run backend + frontend with one command (Windows)
setlocal
cd /d "%~dp0"

set "BACKEND_VENV=backend\.venv"
set "PYTHON=python"

echo VeriLens (المدقق) - starting...

if not exist "%BACKEND_VENV%\Scripts\python.exe" (
    echo Creating backend virtualenv...
    %PYTHON% -m venv "%BACKEND_VENV%"
    if errorlevel 1 (
        echo ERROR: Python not found. Install Python 3.10+ from python.org and tick "Add to PATH".
        pause & exit /b 1
    )
)
echo Installing backend dependencies...
"%BACKEND_VENV%\Scripts\pip.exe" install -q -r backend\requirements.txt

if not exist "frontend\node_modules" (
    echo Installing frontend dependencies ^(npm install^)...
    pushd frontend
    call npm install
    popd
)

where ffprobe >nul 2>nul
if errorlevel 1 echo WARN: ffmpeg not found - video verification will fail. Install via: winget install Gyan.FFmpeg
where yt-dlp >nul 2>nul
if errorlevel 1 echo WARN: yt-dlp not found - video URL downloading will fail. Install via: winget install yt-dlp

echo Starting backend on port 8012...
start "VeriLens Backend" cmd /k ""%BACKEND_VENV%\Scripts\uvicorn.exe" app.main:app --host 0.0.0.0 --port 8012"
pushd frontend
start "VeriLens Frontend" cmd /k "npx vite --host --port 3012"
popd

echo.
echo Backend:  http://localhost:8012
echo Frontend: http://localhost:3012
start http://localhost:3012
echo Close the two terminal windows to stop the servers.
endlocal
