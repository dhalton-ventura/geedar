@echo off
setlocal
cd /d %~dp0

set "ENV_DIR=%~dp0env"
set "PATH=%ENV_DIR%;%ENV_DIR%\Library\mingw-w64\bin;%ENV_DIR%\Library\usr\bin;%ENV_DIR%\Library\bin;%ENV_DIR%\Scripts;%ENV_DIR%\bin;%PATH%"

"%ENV_DIR%\python.exe" -m streamlit run "VisualTool.py" --server.address=127.0.0.1
pause