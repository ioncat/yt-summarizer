Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)

' ── Backend BAT ─────────────────────────────────────────────────────────────
backendBat = fso.GetSpecialFolder(2) & "\yts_backend.bat"
Set f = fso.OpenTextFile(backendBat, 2, True)
f.WriteLine "@echo off"
f.WriteLine "title YT Summarizer — Backend :8000"
f.WriteLine ":: Освобождаем порт 8000 если занят"
f.WriteLine "for /f ""tokens=5"" %%a in ('netstat -aon ^| findstr "":8000 "" ^| findstr ""LISTENING"" 2^>nul') do taskkill /f /pid %%a >nul 2>&1"
f.WriteLine "cd /d """ & root & "\backend"""
f.WriteLine "call .venv\Scripts\activate"
f.WriteLine "echo."
f.WriteLine "echo  [Backend] http://localhost:8000"
f.WriteLine "echo  Press Ctrl+C to stop"
f.WriteLine "echo."
f.WriteLine "python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"
f.Close

' ── Frontend BAT ────────────────────────────────────────────────────────────
frontendBat = fso.GetSpecialFolder(2) & "\yts_frontend.bat"
Set f = fso.OpenTextFile(frontendBat, 2, True)
f.WriteLine "@echo off"
f.WriteLine "title YT Summarizer — Frontend :3000"
f.WriteLine ":: Освобождаем порт 3000 если занят"
f.WriteLine "for /f ""tokens=5"" %%a in ('netstat -aon ^| findstr "":3000 "" ^| findstr ""LISTENING"" 2^>nul') do taskkill /f /pid %%a >nul 2>&1"
f.WriteLine "cd /d """ & root & "\frontend"""
f.WriteLine "echo."
f.WriteLine "echo  [Frontend] http://localhost:3000"
f.WriteLine "echo  Press Ctrl+C to stop"
f.WriteLine "echo."
f.WriteLine "npm run dev"
f.Close

' ── Запуск ──────────────────────────────────────────────────────────────────
wtExe = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\WindowsApps\wt.exe"

If fso.FileExists(wtExe) Then
    ' Windows Terminal: два pane в одном окне (верх — backend, низ — frontend)
    shell.Run "wt cmd /k """ & backendBat & """ ; split-pane -H cmd /k """ & frontendBat & """", 1, False
Else
    ' Fallback: два обычных cmd окна
    shell.Run "cmd /k """ & backendBat & """", 1, False
    WScript.Sleep 500
    shell.Run "cmd /k """ & frontendBat & """", 1, False
End If

' ── Открыть браузер после старта ────────────────────────────────────────────
WScript.Sleep 5000
shell.Run "http://localhost:3000"
