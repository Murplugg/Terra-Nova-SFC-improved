@echo off
setlocal
py -3.12 -B "%~dp0setup_ui.py"
if errorlevel 1 (
  echo.
  echo Setup could not start or stopped unexpectedly.
  echo Install 64-bit Windows CPython 3.12 with Tcl/Tk and the Python launcher.
  echo If Python is installed without py.exe, run: python -B setup_ui.py
  pause
)
