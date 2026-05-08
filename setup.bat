@echo off
::
:: One-time After Effects permissions setup for the motion graphics pipeline.
::
:: nexrender patches AE's commandLineRenderer.jsx so the pipeline can drive AE
:: headlessly. The patch step needs to write inside C:\Program Files\Adobe\
:: Adobe After Effects *\, which is UAC-protected. This script creates the
:: Backup.Scripts folder and grants the current user full control so subsequent
:: pipeline runs can patch without admin.
::
:: Usage:
::   Right-click this file -> Run as administrator
::

:: --- self-elevate -----------------------------------------------------------
NET SESSION >nul 2>&1
if %errorlevel% NEQ 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: --- locate newest After Effects install ------------------------------------
set "AE_BASE=C:\Program Files\Adobe"
set "AE_DIR="
for /f "delims=" %%d in ('dir /b /ad /o-n "%AE_BASE%\Adobe After Effects *" 2^>nul') do (
    if not defined AE_DIR set "AE_DIR=%AE_BASE%\%%d"
)

if not defined AE_DIR (
    echo Error: No Adobe After Effects install found in %AE_BASE%
    echo Install After Effects 2026 or newer, then re-run this script.
    pause
    exit /b 1
)

echo Found: %AE_DIR%

:: --- create + grant ---------------------------------------------------------
if not exist "%AE_DIR%\Support Files\Backup.Scripts\Startup" mkdir "%AE_DIR%\Support Files\Backup.Scripts\Startup"
icacls "%AE_DIR%\Support Files\Backup.Scripts" /grant "%USERNAME%:(OI)(CI)F" /T >nul
icacls "%AE_DIR%\Support Files\Startup" /grant "%USERNAME%:(OI)(CI)F" /T >nul

echo.
echo Done. You can now run the pipeline normally.
pause
