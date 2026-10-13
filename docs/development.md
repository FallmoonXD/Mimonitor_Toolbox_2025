# 构建与测试

## 开发环境

Windows CI 使用 Python 3.12，依赖锁定在 `requirements-build.txt`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

## 离线测试

使用临时配置和 offscreen Qt：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:MIMONITOR_SETTINGS_PATH = Join-Path $env:TEMP ('mimonitor-2025-tests-' + [guid]::NewGuid().ToString('N') + '.json')
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Java 回执用例使用模拟 native/Provider 接口，编译并执行实际 helper 回执代码。本机有 `javac` 和 `java` 时执行；没有 JDK 时跳过相应用例。

2026-10-13 原生模式控制改动的完整 465 项本地测试通过，包含实际 Java helper 代码的模拟回执测试。实机结果与尚待验收的操作见 [兼容记录](2025-compatibility.md)。

## Windows 构建

使用已安装项目依赖的 Python 运行构建脚本。发布编译应使用 python.org 的 Python，安装器构建另需 Inno Setup。

| 脚本 | 产物 |
| --- | --- |
| `build.bat` | `dist-nuitka/MonitorToolbox2025.exe` |
| `build_nuitka_standalone.bat` | `dist-nuitka-standalone/monitor_controller.dist/MonitorToolbox2025.exe` |
| `build_installer.bat` | `dist-installer/MonitorToolbox2025-portable.zip` 和 `MonitorToolbox2025-Setup.exe` |

脚本优先使用本机 Python 3.13 的安装路径，找不到时使用 PATH 中的 `python`。使用上述虚拟环境时，可先在当前终端将 `.venv\Scripts` 加到 PATH；若机器存在脚本指定的 Python 3.13，需同时确认其已安装项目依赖。

GitHub Actions 在 `main` 推送或 PR 时执行测试；只有 `v2025-*` 标签触发发布构建。创建发布标签前应完成对应版本的实机与安装包验收。

## 桌面身份与配置

| 项目 | 2025 维护版 |
| --- | --- |
| 程序名 | `MonitorToolbox2025.exe` |
| 窗口/托盘名称 | 红米 G Pro 27U 2025 Toolbox |
| Windows 配置目录 | `%LOCALAPPDATA%\.gpro_controller_2025` |
| 启动项 | `RedmiToolbox2025.bat` |
| 默认 ADB Server 端口 | `5039`，设备端口仍为 `5555` |
| 安装目录 | `MonitorToolbox2025`，安装器采用独立 AppId |

单实例名称为 `mitv_gpro27u_2025_controller_single_instance`。程序不会自动导入原版配置；配置路径仍可用 `MIMONITOR_SETTINGS_PATH` 覆盖，ADB Server 端口仍可用 `MIMONITOR_ADB_SERVER_PORT` 覆盖。

桌面配置和进程身份虽已分开，两版仍使用相同的设备端 helper 部署路径，并控制同一台显示器。实机控制时使用一个控制版本。

## 项目来源

本分支基于上游 v2.9.0，并包含最初提交至上游 PR #19 的 2025 兼容修复。PR 已关闭，改动转至本仓库维护。上游源码和资源、原始 README 及提交历史保留。

后续同步上游时，按改动内容复核本设备的行为。2026 款测试结果与本仓库的 2025 款实机结果分别记录。
