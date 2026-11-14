@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0third_player_mod\patch.ps1" -Action Uninstall
set "SOF_PATCH_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %SOF_PATCH_EXIT%
