@echo off
rem 一键产出 standalone 两种分发形态：便携 zip + Inno Setup 安装器。
rem 依赖 Inno Setup 便携版（ISCC 路径见下，或装到 Program Files 后用默认路径）。
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
set /p "APP_VERSION="<VERSION
if not exist "%PY%" (
  python -m venv "%~dp0.venv"
  if errorlevel 1 exit /b 1
)
"%PY%" -m pip install -r requirements-build.txt
set ISCC=%LOCALAPPDATA%\InnoSetup\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe
if not exist "%ISCC%" (
  echo [!] 未找到 Inno Setup ISCC.exe，仅产出便携 zip。可下载便携版解压到 %%LOCALAPPDATA%%\InnoSetup
  echo     https://jrsoftware.org/isdl.php
)

rem 1) standalone 构建（有产物则跳过，FORCE=1 强制重编）
set "NEEDS_BUILD=0"
if not exist "dist-nuitka-standalone\monitor_controller.dist\MonitorToolbox2025.exe" set "NEEDS_BUILD=1"
if "%FORCE%"=="1" set "NEEDS_BUILD=1"
if "%NEEDS_BUILD%"=="1" (
  "%PY%" -m nuitka ^
    --standalone ^
    --enable-plugin=pyqt6 ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=assets/app/icon.ico ^
    --include-package=qfluentwidgets ^
    --include-package-data=qfluentwidgets ^
    --company-name=FallmoonXD ^
    --product-name="Mimonitor Toolbox 2025" ^
    --file-version=%APP_VERSION% ^
    --product-version=%APP_VERSION% ^
    --include-data-dir=assets/app=assets/app ^
  --include-data-dir=assets/display=assets/display ^
    --include-data-files=assets/runtime/adb.exe=assets/runtime/adb.exe ^
    --include-data-files=assets/runtime/AdbWinApi.dll=assets/runtime/AdbWinApi.dll ^
    --include-data-files=assets/runtime/AdbWinUsbApi.dll=assets/runtime/AdbWinUsbApi.dll ^
    --include-data-files=assets/runtime/MtkDirectTool.jar=assets/runtime/MtkDirectTool.jar ^
    --include-data-files=assets/runtime/ColorfulLedTool.jar=assets/runtime/ColorfulLedTool.jar ^
    --include-data-files=assets/adb_guardian/adbguardian-signed.apk=assets/adb_guardian/adbguardian-signed.apk ^
    --output-filename=MonitorToolbox2025.exe ^
    --output-dir=dist-nuitka-standalone ^
    --assume-yes-for-downloads ^
    monitor_controller.py
)

rem 2) 便携 zip（解压出一个 MonitorToolbox2025-portable 文件夹）
if not exist dist-installer mkdir dist-installer
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\package_portable.ps1"
if errorlevel 1 exit /b 1

rem 3) Inno Setup 安装器
if exist "%ISCC%" (
  "%ISCC%" "/DMyAppVersion=%APP_VERSION%" "installer\MonitorToolbox.iss"
  if errorlevel 1 exit /b 1
)

echo Done!
echo   - dist-installer\MonitorToolbox2025-portable.zip
echo   - dist-installer\MonitorToolbox2025-Setup.exe
pause
endlocal
