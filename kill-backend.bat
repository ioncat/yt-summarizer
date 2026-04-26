@echo off
setlocal

echo [YT Summarizer] Stopping backend processes...

for /f "skip=1 tokens=2 delims=," %%p in ('wmic process where "CommandLine like '%%uvicorn%%' or CommandLine like '%%main:app%%' or CommandLine like '%%yt-summarizer\\backend%%'" get ProcessId /format:csv 2^>nul') do (
    if not "%%p"=="" taskkill /F /T /PID %%p >nul 2>&1
)

for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /T /PID %%p >nul 2>&1
)

echo [YT Summarizer] Done. Current listeners on port 8000:
netstat -aon | findstr ":8000" | findstr "LISTENING"

endlocal
