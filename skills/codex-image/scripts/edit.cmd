@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%SCRIPT_DIR%codex_image.py" edit %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%SCRIPT_DIR%codex_image.py" edit %*
  exit /b %ERRORLEVEL%
)

echo python is required 1>&2
exit /b 1
