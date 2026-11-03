@echo off
chcp 65001 >nul
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo 請先安裝 Node.js 22 或更新版本，再重新開啟此檔案。
  pause
  exit /b 1
)
echo 請開啟瀏覽器進入 http://127.0.0.1:8787/?stock=2492
echo 保持此視窗開啟。按 Ctrl+C 可停止。
node server.mjs
pause
