@echo off
REM === 1 啟動虛擬環境 ===
cd /d C:\Users\Case509\Desktop\goodbye
call venv\Scripts\activate.bat  2>nul

REM === 2 啟動 Waitress  ===
start "Django (Waitress)" cmd /k ^
"waitress-serve --listen=127.0.0.1:8000 goodBuy.wsgi:application"

REM 等 3 秒再開隧道
timeout /t 3 >nul

REM === 3 啟動 Cloudflared ===
start "Cloudflared Tunnel" cmd /k "
"C:\Program Files\Cloudflare\cloudflared.exe" tunnel --url http://localhost:8000"