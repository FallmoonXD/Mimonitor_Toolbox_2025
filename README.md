# Mimonitor Toolbox 2025

红米 G Pro 27U **2025 款**的 Windows ADB 控制工具维护仓库。

基于 [YiHoooong/Mimonitor_Toolbox](https://github.com/YiHoooong/Mimonitor_Toolbox) 的官方 v2.9.0，保留原作者代码、资源与提交历史。原作者的控制工具、界面和设备通信实现是本项目的基础；2025 款兼容修复由本仓库维护。上游原始说明保存在 [README.upstream.md](README.upstream.md)。

## 当前范围

| 项目 | 本仓库验证目标 |
| --- | --- |
| 显示器 | 红米 G Pro 27U 2025，Windows EDID `XMI27B3` |
| Android 身份 | `MiTV-MFFU1` / `beekeeper` |
| 实机固件 | Android 14 / `OS3.0.109.0.UFFMAMN` |
| 桌面平台 | Windows 11 |
| 当前阶段 | 源码开发与兼容验证，尚未发布独立安装包 |

维护者只有 2025 款设备。本仓库的实机结论限于上述型号和固件；2026 款、其他固件和继承的 macOS 移植均未在此维护分支完成实机验收。

## 2025 款兼容改动

- 当前场景优先采用原生画面 bank 和 Dolby 标志，避免数据库旧值导致错误场景显示。
- RGB gain 优先显示当前 bank 的 native 回读，避免 factory 白平衡 getter 与当前状态不一致。
- 未知 HDR 色调映射值保留原始信息，并清除旧选项高亮。
- RGB 与 HDR tone 的 checked 写入分别检查 native 返回码、原生回读和 Provider 结果；Provider 异常作为独立警告显示。
- 捕获到原生场景时，checked setter 检查目标 bank 和写入期间 bank 变化；预设无法确认目标 bank 时停止后续画质参数写入。

这些改动来自 [上游草稿 PR #19](https://github.com/YiHoooong/Mimonitor_Toolbox/pull/19)。后续在本仓库验证和维护，无需以 2026 款实机验证作为本仓库的发布前提。

### 验证进度

2026-10-13 的只读 ADB 验证确认：

- 原生 bank `13`、Dolby 标志 `1`；原生 RGB `1022/1008/942`。
- 两次读取的 **49 个 native 字段、112 个画质数据库字段前后一致**，PC 工具箱配置哈希不变。
- 把实机快照送入断开设备的修改后 UI，显示「Dolby Vision 自定义」及正确 RGB。
- 兼容修复提交的 443 项 Python/Java 测试通过，包含 native/Provider 模拟接口的实际 Java 回执执行。
- 拆分为独立仓库后，完整 445 项测试通过；新增检查确认官方配置与启动项不会被维护版覆盖或移除。

本轮没有在校色设备执行画质 setter、切换 HDR/输入/场景或扫描 20 点白平衡整表。checked 写入和跨模式预设的实机验收仍待完成。详见 [2025 款兼容与验证记录](docs/2025-compatibility.md)。

## 与官方版并存

2025 维护版采用独立的桌面身份：

| 项目 | 2025 维护版 |
| --- | --- |
| 程序名 | `MonitorToolbox2025.exe` |
| 窗口/托盘名称 | 红米 G Pro 27U 2025 Toolbox |
| Windows 配置目录 | `%LOCALAPPDATA%\.gpro_controller_2025` |
| 启动项 | `RedmiToolbox2025.bat` |
| 默认 ADB Server 端口 | `5039`，设备端口仍是 `5555` |
| 安装目录 | `MonitorToolbox2025`，使用独立安装器 AppId |

不会自动导入官方版配置。配置环境变量仍支持 `MIMONITOR_SETTINGS_PATH`，ADB Server 端口仍可用 `MIMONITOR_ADB_SERVER_PORT` 覆盖。

两版仍控制同一台显示器，并使用相同的设备端 helper 部署路径。切换控制版本时应断开另一版的设备连接，避免两版同时部署 helper 或写画质。

## 源码运行与测试

```powershell
python -m pip install -r requirements-build.txt
python monitor_controller.py
```

源码正常启动会执行原有连接逻辑，并可能部署设备 helper；运行前先检查配置与设备连接。

离线测试使用临时配置，不连接显示器：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:MIMONITOR_SETTINGS_PATH = Join-Path $env:TEMP 'mimonitor-2025-tests-config.json'
python -m unittest discover -s tests -q
```

Java 回执测试在本机有 `javac` 和 `java` 时执行；没有 JDK 时跳过这些用例。

## 构建

| 脚本 | 产物 |
| --- | --- |
| `build.bat` | `dist-nuitka/MonitorToolbox2025.exe` |
| `build_nuitka_standalone.bat` | `dist-nuitka-standalone/monitor_controller.dist/MonitorToolbox2025.exe` |
| `build_installer.bat` | `dist-installer/MonitorToolbox2025-portable.zip` 和 `MonitorToolbox2025-Setup.exe` |

GitHub Actions 在 `main` 推送或 PR 时执行测试；只有 `v2025-*` 标签触发发布构建。当前没有推送发布标签，旧上游版本号不代表本维护版已发布。

设备 helper 源码与说明见 [tools/mtk_direct](tools/mtk_direct/README.md)。后续同步上游应按提交审查，再验证 2025 款；不将上游的 2026 款测试结论作为本设备的实测结论。
