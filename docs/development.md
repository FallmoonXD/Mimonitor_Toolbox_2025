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
$env:MIMONITOR_ADB_SERVER_PORT = '5099'
$env:MIMONITOR_SETTINGS_PATH = Join-Path $env:TEMP ('mimonitor-2025-tests-' + [guid]::NewGuid().ToString('N') + '.json')
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Java 回执用例使用模拟 native/Provider 接口，编译并执行实际 helper 回执代码。本机有 `javac` 和 `java` 时执行；没有 JDK 时跳过相应用例。

2026-10-13 原生模式控制改动的完整 465 项本地测试通过，包含实际 Java helper 代码的模拟回执测试。实机结果与尚待验收的操作见 [兼容记录](2025-compatibility.md)。

同日本地部署的 Nuitka standalone 构建发现旧标题栏 slot 在控件删除后仍响应标题变化；修复后增加回归用例，466 项测试通过。已部署程序并验证可见窗口与实机连接；该本地构建未创建发布标签。

随后完成 OSD 对照适配，478 项测试通过，新增控制已逐档实机验收并更新本地 standalone 程序。当时安装后的校色恢复核对仅覆盖当前 Dolby 模式，后来发现 SDR、HDR 漏恢复；已在下一轮修复记录中更正。详情见 [OSD 对照表](2025-osd-options.md) 与 [系统画面设置](2025-system-picture-settings.md)。

## Windows 构建

使用已安装项目依赖的 Python 运行构建脚本。发布编译应使用 python.org 的 Python，安装器构建另需 Inno Setup。

| 脚本 | 产物 |
| --- | --- |
| `build.bat` | `dist-nuitka/MonitorToolbox2025.exe` |
| `build_nuitka_standalone.bat` | `dist-nuitka-standalone/monitor_controller.dist/MonitorToolbox2025.exe` |
| `build_installer.bat` | `dist-installer/MonitorToolbox2025-portable.zip` 和 `MonitorToolbox2025-Setup.exe` |

构建脚本使用项目内的 `.venv\Scripts\python.exe`；没有虚拟环境时，用 PATH 中的 `python` 创建它，再安装项目依赖。打包脚本在独立临时目录中生成便携包，完成后清理临时目录。

## 本机工作区

本机项目集中在 `F:\Chatgpt\test\Redmi_G_Pro_27U_2025`，源码、Git 历史、构建入口和开发环境都在此目录。安装验证记录与只读实机检查脚本放在 `.local/`，不提交个人数据。旧版程序备份、旧仓库和临时发布目录已清理；正式校色档案仍在原档案库。

GitHub Actions 在 `main` 推送或 PR 时执行测试；只有 `v2025-*` 标签触发发布构建。标签版本必须与 `VERSION` 一致。发布构建包含应用和托盘图标、上游署名、便携包、当前用户安装器及 SHA256 校验文件，先创建草稿 Release。下载草稿附件核对哈希并完成打包程序、安装及卸载验收后，再发布该 Release。

首版为 `v2025-0.1.0`，应用和安装器版本均为 0.1.0。安装器默认使用当前用户目录，不要求管理员权限；应用配置仍位于 `%LOCALAPPDATA%\.gpro_controller_2025`。本地重新编译可设置 `FORCE=1` 后运行 `build_installer.bat`。

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
