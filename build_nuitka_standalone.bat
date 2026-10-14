@echo off
rem Nuitka standalone 打包（文件夹形态，启动最快，zip 整个 dist 目录分发）。
rem 需要 python.org 安装的 Python（Microsoft Store 版缺少链接库，无法编译）。
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  python -m venv "%~dp0.venv"
  if errorlevel 1 exit /b 1
)
"%PY%" -m pip install -r requirements-build.txt
"%PY%" -m nuitka ^
  --standalone ^
  --enable-plugin=pyqt6 ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=assets/app/icon.ico ^
  --include-package=qfluentwidgets ^
  --include-package-data=qfluentwidgets ^
  --include-data-dir=assets/app=assets/app ^
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
echo Done! Check dist-nuitka-standalone\monitor_controller.dist\
pause
