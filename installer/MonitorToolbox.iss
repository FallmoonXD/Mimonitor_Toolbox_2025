; MonitorToolbox Inno Setup 安装器
; 本地构建: build_installer.bat（先产出 standalone 目录再编译）
; CI 构建: ISCC /DMyAppVersion=<tag> installer\MonitorToolbox.iss

#ifndef MyAppVersion
#define MyAppVersion "0.0.0-dev"
#endif

#define MyAppName "红米 G Pro 27U 2025 Toolbox"
#define MyAppExeName "MonitorToolbox2025.exe"

[Setup]
AppId={{458301FA-5E7A-48F9-8DAB-405FF76F8103}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=FallmoonXD (based on YiHoooong/Mimonitor_Toolbox)
DefaultDirName={autopf}\MonitorToolbox2025
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName}
OutputDir=..\dist-installer
OutputBaseFilename=MonitorToolbox2025-Setup
SetupIconFile=..\assets\app\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
; 中文语言包 vendored 自 jrsoftware/issrc（choco 的 Inno Setup 6 不自带）
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist-nuitka-standalone\monitor_controller.dist\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
