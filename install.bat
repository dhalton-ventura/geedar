@echo off
:: This batch file helps setting up the GEEDaR application.
:: Installs Portable Python, the Google Cloud CLI, associates the user account to the Earth Engine API and sets a default cloud project for the API.
:: Author: Dhalton Ventura
chcp 1252 >nul
setlocal EnableDelayedExpansion

echo.
echo This is the installer for GEEDaR 2.1
echo.

:: Current directory
cd /d "%~dp0"
set "CUR_DIR=%~sdp0"
:: Remove backslash
if "%CUR_DIR:~-1%"=="\" set "CUR_DIR=%CUR_DIR:~0,-1%"

:: Write Permission Check
echo test > test.tmp 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Write permission denied in this directory.
    echo The installation will only work in a folder where you have writing permissions.
    echo Please move this folder to a user directory, like Documents or Desktop, or run the script as Administrator.
    echo.
    goto :end
)
:: Remove the temporary test file
del test.tmp

:: Variables for Portable Python
set "ENV_DIR=%CUR_DIR%\env"
set "PYTHON_ZIP=%CUR_DIR%\python-embed.zip"
set "GET_PIP=%CUR_DIR%\get-pip.py"
:: Using Python 3.14 stable release
set "URL_PYTHON=https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip"
set "URL_GETPIP=https://bootstrap.pypa.io/get-pip.py"

:: Variables for Google Cloud CLI
set "URL_GCLOUD=https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe"
set "GCLOUD_INST=%CUR_DIR%\GoogleCloudSDKInstaller.exe"


echo.
echo ===================================================
echo [1] Python environment setup (Portable)
echo ===================================================
echo.

echo [1.1] Checking environment installation...

:: Look for python executable to verify if environment already exists.
if exist "%ENV_DIR%\python.exe" (
	echo.
    echo [OK] The 'env' folder already exists and will be used.
	echo.
    goto :gcloud_check
)

:: If not found, ask user about downloading and installing the environment.
echo.
echo No python environment folder was found.
set /p "op=[USER INPUT] Download and install Portable Python now? Y/[N]: "
if /i "%op%" neq "Y" (
	echo.
    echo [CANCELLED] Aborted installation.
	echo.
    goto :end
)

:: Download Portable Python and the pip installer script
echo.
echo [1.2] Downloading Portable Python and pip installer...
echo.
if not exist "%PYTHON_ZIP%" (
    curl -# -L -o "%PYTHON_ZIP%" "%URL_PYTHON%"
)
if not exist "%GET_PIP%" (
    curl -# -L -o "%GET_PIP%" "%URL_GETPIP%"
)

if not exist "%PYTHON_ZIP%" (
    echo.
    echo [ERROR] Failed to download Python.
    echo.
    goto :end
)

:: Extract the zip file using native Windows tar command
echo.
echo [1.3] Extracting Python...
mkdir "%ENV_DIR%"
tar -xf "%PYTHON_ZIP%" -C "%ENV_DIR%"

:: Enable site-packages in the embeddable python by uncommenting 'import site' in the ._pth file
powershell -Command "(Get-Content '%ENV_DIR%\python314._pth') -replace '#import site', 'import site' | Set-Content '%ENV_DIR%\python314._pth'"

:: Install pip
echo.
echo [1.4] Installing pip module...
"%ENV_DIR%\python.exe" "%GET_PIP%" --no-warn-script-location

:: Install basic build tools missing from Portable Python
echo.
echo [1.4.1] Installing build tools...
"%ENV_DIR%\python.exe" -m pip install setuptools wheel --no-warn-script-location

:: Install GEEDaR dependencies using pip (which uses native Windows certificates and proxies)
echo.
echo [1.5] Installing GEEDaR packages (this may take a while, please wait)...
echo.
"%ENV_DIR%\python.exe" -m pip install pandas sqlalchemy func_timeout fastkml earthengine-api pyodbc streamlit streamlit-folium --no-warn-script-location

if %errorlevel% neq 0 (
	echo.
	echo [ERROR] Failed to install Python dependencies via pip.
	echo.
	goto :end
)

:: Clean up downloaded files
echo [1.6] Cleaning up temporary package cache...
del "%PYTHON_ZIP%"
del "%GET_PIP%"

echo.
echo [SUCCESS] Environment created.
echo.

:gcloud_check
echo.
echo ===================================================
echo [2] Google Cloud configuration
echo ===================================================
echo.
:: Check Google Cloud CLI installation.
echo.
echo [2.1] Checking Google Cloud CLI installation...

:: First, try to execute directly. It will work if it is in the env. var. PATH.
where gcloud >nul 2>nul
if %errorlevel% equ 0 (
	echo.
    echo [OK] Google Cloud CLI already installed ^(PATH^).
	echo.
	for /f "tokens=*" %%i in ('where gcloud') do (
		set "GCLOUD_PATH=%%i"
		goto :gcloud_auth
	)
)
:: If it fails, try to find it in the default user installation folder.
if exist "%LocalAppData%\Google\Cloud SDK\bin\gcloud.cmd" (
	echo.
    echo [OK] Google Cloud CLI found in user AppData.
	echo.
	set "GCLOUD_PATH=%LocalAppData%\Google\Cloud SDK\bin\gcloud.cmd"
    goto :gcloud_auth
)
:: There's still the possibility that it was installed as a portable version.
if exist "%CUR_DIR%\google-cloud-sdk\bin\gcloud.cmd" (
	echo.
    echo [OK] A portable Google Cloud CLI was found.
	echo.
	set "GCLOUD_PATH=%CUR_DIR%\google-cloud-sdk\bin\gcloud.cmd"
    goto :gcloud_auth
)

:: No valid installation. Install it?
echo.
echo Google Cloud CLI was not found.
set /p "op=[USER INPUT] Download and install it now? Y/[N]: "
if /I "%op%" == "Y" (
	echo.
	echo [2.1.1] Downloading Google Cloud CLI installer...
	echo.

	:: Download (if not yet downloaded).
	if not exist "%GCLOUD_INST%" (
		curl -# -L -o "%GCLOUD_INST%" "%URL_GCLOUD%"  
	)
	if not exist "%GCLOUD_INST%" (
		echo.
		echo [ERROR] Failed to download Google Cloud CLI.
		echo.
		goto :end
	)
	echo.
	echo [SUCCESS] Google Cloud CLI installer downloaded.
	echo.

	:: Execute the downloaded installer.
	echo.
	echo [2.1.2] Google Cloud CLI will be installed now. It may take long. Please wait...
	echo.
	start /wait "" "%GCLOUD_INST%" /S /singleuser /nodesktop

	:: Got to install?
	where gcloud >nul 2>nul
	if %errorlevel% neq 0 (
		echo.
		echo [ERROR] Failed to install Google Cloud CLI.
		echo.
		goto :end
	)
	for /f "tokens=*" %%i in ('where gcloud') do (
		set "GCLOUD_PATH=%%i"
		goto :gcloud_install_success
	)
	:gcloud_install_success
	echo.
	echo [SUCCESS] Google Cloud CLI installed.
	echo.	
)

:: Google Cloud authentication.
:gcloud_auth
echo.
echo [2.2] Checking Google Cloud credentials...
echo.
:: Pointing CLOUDSDK_PYTHON to our new Portable Python environment
set "CLOUDSDK_PYTHON=%ENV_DIR%\python.exe"
call "%GCLOUD_PATH%" auth login

:: The user must provide a project id of Google Cloud. It will be saved to a json file.
echo.
echo [2.3] Google Cloud Project: your Google user account must have access to a Google Cloud project registered for use with Earth Engine.
echo.
set /p "PROJID=[USER INPUT] Please, enter the id of the project: "

:: Check if the project exists. If not, create it.
call "%GCLOUD_PATH%" projects describe %PROJID% > NUL 2>&1
if %ERRORLEVEL% neq 0 (
	echo.
    echo [2.3.1] Trying to create the project...
	echo.
	call "%GCLOUD_PATH%" projects create "%PROJID%" --name="GEEDaR default project"
	echo.
	:: Check again for project existence.
	call "%GCLOUD_PATH%" projects describe %PROJID% > NUL 2>&1
	if !ERRORLEVEL! neq 0 (
		echo.
		echo [ERROR] Could not create the project '%PROJID%'.
		echo.
		goto :end
	)
	echo.
	echo [SUCCESS] Project %PROJID% created.
	echo.
)

:: Enable the EE API.
echo.
echo [2.4] Enabling the EE API for the project...
echo.
call "%GCLOUD_PATH%" services enable earthengine.googleapis.com --project=%PROJID%

:: Save a JSON with the project id.
echo.
echo [2.5] Creating JSON config file for GEEDaR...
echo { "project_id": "%PROJID%" } > ee_init.json
if not exist "ee_init.json" (
	echo.
	echo [ERROR] Failed to create JSON file with Google Cloud project id.
	echo.
	goto :end
)
echo.
echo [SUCCESS] A json file (ee_init.json) was created for GEEDaR to know which cloud project should be used with the Earth Engine API...
echo.

echo.
echo ===================================================
echo [3] Earth Engine authentication
echo ===================================================
echo.

:: Run the EE authenticator using the Portable Python environment.
echo.
echo [3.1] Now authenticating the access to the Earth Engine API...
"%ENV_DIR%\python.exe" -m ee.cli.eecli authenticate --auth_mode=localhost --scopes=https://www.googleapis.com/auth/earthengine,https://www.googleapis.com/auth/cloud-platform --force
echo.
echo [FINISHED] You can test GEEDaR now.
echo.

:end
echo.
pause
