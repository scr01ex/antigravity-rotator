@echo off
setlocal
cd /d "%~dp0"

if "%1"=="start" goto do_start
if "%1"=="--daemon" goto do_start
if "%1"=="-d" goto do_start
if "%1"=="stop" goto do_stop
if "%1"=="restart" goto do_restart
if "%1"=="status" goto do_status
if "%1"=="logs" goto do_logs
if "%1"=="help" goto do_help
if "%1"=="--help" goto do_help
if "%1"=="-h" goto do_help

echo [INFO] Starting Antigravity Rotator in foreground mode (Ctrl+C to stop)...
echo [TIP] To run in the background and close this terminal, use: run.bat start
python rotator.py
exit /b %ERRORLEVEL%

:do_start
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $conn = Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue; if ($conn) { $p = ($conn.OwningProcess | Select-Object -Unique -First 1); Write-Host \"[WARN] Rotator is already running in background (PID $p).\"; exit 0 } exit 1 }"
if %ERRORLEVEL% equ 0 exit /b 0

echo [INFO] Starting Antigravity Rotator in background...
set PY_EXE=python
where pythonw >nul 2>&1 && set PY_EXE=pythonw

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { [Environment]::SetEnvironmentVariable('CLOUD_CODE_URL', 'http://127.0.0.1:8888', 'User'); $dir = '%~dp0'.TrimEnd('\'); $res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = '%PY_EXE% rotator.py'; CurrentDirectory = $dir }; if ($res.ReturnValue -eq 0) { Set-Content -Path (Join-Path $dir '.rotator.pid') -Value $res.ProcessId } }"

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { Start-Sleep -Seconds 1; $conn = Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue; if ($conn) { $p = ($conn.OwningProcess | Select-Object -Unique -First 1); Write-Host \"[OK] Rotator started in background (PID $p).\"; Write-Host '     Logs: rotator.log'; Write-Host '     You can safely close this terminal window now.'; exit 0 } else { Write-Host '[ERROR] Rotator failed to start. Check rotator.log for details.'; Remove-Item -Path '%~dp0.rotator.pid' -ErrorAction SilentlyContinue; exit 1 } }"
exit /b %ERRORLEVEL%

:do_stop
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { [Environment]::SetEnvironmentVariable('CLOUD_CODE_URL', $null, 'User'); $pidFile = '%~dp0.rotator.pid'; if (Test-Path $pidFile) { $procId = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1); if ($procId) { Write-Host \"[INFO] Stopping background Rotator (PID $procId)...\"; Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }; Remove-Item $pidFile -Force -ErrorAction SilentlyContinue }; $conns = Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue; if ($conns) { $conns.OwningProcess | Select-Object -Unique | ForEach-Object { Write-Host \"[INFO] Terminating process on port 8888 (PID $_)...\"; Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } } }"
python account_manager.py unconfigure-ide
echo [OK] Rotator stopped and Antigravity unlinked.
exit /b 0

:do_restart
call "%~f0" stop
powershell -NoProfile -Command "Start-Sleep -Seconds 1" >nul 2>&1
call "%~f0" start
exit /b 0

:do_status
echo ================================================================================
echo                            ROTATOR STATUS CHECK                                 
echo ================================================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $pidFile = '%~dp0.rotator.pid'; $conn = Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue; if (Test-Path $pidFile) { $procId = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1); if ($procId -and (Get-Process -Id $procId -ErrorAction SilentlyContinue)) { Write-Host \"[PROCESS] Rotator daemon: RUNNING (PID $procId)\" } elseif ($conn) { $p = ($conn.OwningProcess | Select-Object -Unique -First 1); Write-Host \"[PROCESS] Rotator process: RUNNING on port 8888 (PID $p)\" } else { Write-Host '[PROCESS] Rotator process: STOPPED (not listening on port 8888)' } } elseif ($conn) { $p = ($conn.OwningProcess | Select-Object -Unique -First 1); Write-Host \"[PROCESS] Rotator process: RUNNING on port 8888 (PID $p)\" } else { Write-Host '[PROCESS] Rotator process: STOPPED (not listening on port 8888)' }; $c = [Environment]::GetEnvironmentVariable('CLOUD_CODE_URL', 'User'); if ($c) { Write-Host \"[ENV VAR] CLOUD_CODE_URL: $c (active for Antigravity desktop and CLI)\" } else { Write-Host '[ENV VAR] CLOUD_CODE_URL: not set' } }"

python -c "import json; from config import IDE_SETTINGS_FILE; print(f'[IDE SETTINGS] Linked to proxy: {json.loads(IDE_SETTINGS_FILE.read_text()).get(\"jetski.cloudCodeUrl\")}' if (IDE_SETTINGS_FILE.exists() and json.loads(IDE_SETTINGS_FILE.read_text()).get(\"jetski.cloudCodeUrl\")) else '[IDE SETTINGS] Direct connection to Google Cloud Code (default)') if IDE_SETTINGS_FILE.exists() else print('[IDE SETTINGS] settings.json not found')"
echo.
python account_manager.py list
exit /b %ERRORLEVEL%

:do_logs
if not exist "%~dp0rotator.log" echo [INFO] No log file found yet. & exit /b 0
powershell -NoProfile -Command "Get-Content -Path '%~dp0rotator.log' -Wait -Tail 20"
exit /b 0

:do_help
echo Antigravity Rotator Windows Launcher:
echo   run.bat          - Start proxy in foreground (Ctrl+C to stop)
echo   run.bat start    - Start proxy in background
echo   run.bat status   - Show account statuses and cooldowns
echo   run.bat logs     - Follow real-time logs
echo   run.bat stop     - Stop background proxy and unlink Antigravity
echo   run.bat restart  - Restart background proxy
exit /b 0
