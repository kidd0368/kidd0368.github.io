@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
where node.exe >nul 2>&1
if errorlevel 1 goto missing_node
if not exist "%~dp0server.mjs" goto missing_server
node.exe -e "if(Number(process.versions.node.split('.')[0])<22) process.exit(1)"
if errorlevel 1 goto old_node
echo Starting Margin Pressure Radar...
echo Open: http://127.0.0.1:8787/?stock=2492
echo Keep this window open. Press Ctrl+C to stop.
node.exe "%~dp0server.mjs"
set "radar_exit=%errorlevel%"
echo.
if not "%radar_exit%"=="0" echo Server exited with code %radar_exit%.
pause
exit /b %radar_exit%

:missing_node
echo Node.js 22 or newer is required. Install Node.js, then run this file again.
pause
exit /b 1

:old_node
echo Your Node.js version is too old. Node.js 22 or newer is required.
node.exe --version
pause
exit /b 1

:missing_server
echo Cannot find server.mjs in this folder.
echo Keep this launcher inside the host folder next to server.mjs.
pause
exit /b 1
