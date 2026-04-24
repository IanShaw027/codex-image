@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"

if not "%CODEX_IMAGE_PYTHON%"=="" (
  call :run_override "%CODEX_IMAGE_PYTHON%" %*
  exit /b %ERRORLEVEL%
)

where py >NUL 2>&1
if not errorlevel 1 (
  call :run_py -3 %*
  if not errorlevel 1 exit /b 0
  call :run_py -3.13 %*
  if not errorlevel 1 exit /b 0
  call :run_py -3.12 %*
  if not errorlevel 1 exit /b 0
  call :run_py -3.11 %*
  if not errorlevel 1 exit /b 0
)

call :run_exe python3.13 %*
if not errorlevel 1 exit /b 0
call :run_exe python3.12 %*
if not errorlevel 1 exit /b 0
call :run_exe python3.11 %*
if not errorlevel 1 exit /b 0
call :run_exe python3 %*
if not errorlevel 1 exit /b 0
call :run_exe python %*
if not errorlevel 1 exit /b 0

echo python 3.11+ is required for codex-image. Set CODEX_IMAGE_PYTHON or install Python 3.11+.
exit /b 1

:run_override
set "PYTHON=%~1"
shift
"%PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1 || (
  echo python 3.11+ is required for codex-image. CODEX_IMAGE_PYTHON points to an unsupported interpreter.>&2
  exit /b 1
)
"%PYTHON%" "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_py
set "PY_SELECTOR=%~1"
shift
py %PY_SELECTOR% -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1 || exit /b 1
py %PY_SELECTOR% "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_exe
set "PYTHON=%~1"
shift
where "%PYTHON%" >NUL 2>&1 || exit /b 1
"%PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1 || exit /b 1
"%PYTHON%" "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%
