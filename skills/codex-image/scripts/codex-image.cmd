@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"

if not "%CODEX_IMAGE_PYTHON%"=="" goto run_override

where py >NUL 2>&1
if errorlevel 1 goto check_exes

py -3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1
if not errorlevel 1 goto run_py3
py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1
if not errorlevel 1 goto run_py313
py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1
if not errorlevel 1 goto run_py312
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1
if not errorlevel 1 goto run_py311

:check_exes
where python3.13 >NUL 2>&1
if not errorlevel 1 (
  python3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1
  if not errorlevel 1 goto run_python313
)
where python3.12 >NUL 2>&1
if not errorlevel 1 (
  python3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1
  if not errorlevel 1 goto run_python312
)
where python3.11 >NUL 2>&1
if not errorlevel 1 (
  python3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1
  if not errorlevel 1 goto run_python311
)
where python3 >NUL 2>&1
if not errorlevel 1 (
  python3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1
  if not errorlevel 1 goto run_python3
)
where python >NUL 2>&1
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1
  if not errorlevel 1 goto run_python
)

echo python 3.11+ is required for codex-image. Set CODEX_IMAGE_PYTHON or install Python 3.11+.
exit /b 1

:run_override
"%CODEX_IMAGE_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >NUL 2>&1 || (
  echo python 3.11+ is required for codex-image. CODEX_IMAGE_PYTHON points to an unsupported interpreter.>&2
  exit /b 1
)
"%CODEX_IMAGE_PYTHON%" "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_py3
py -3 "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_py313
py -3.13 "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_py312
py -3.12 "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_py311
py -3.11 "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_python313
python3.13 "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_python312
python3.12 "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_python311
python3.11 "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_python3
python3 "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%

:run_python
python "%SCRIPT_DIR%codex_image.py" %*
exit /b %ERRORLEVEL%
