#define ReleaseVersion ReadIni(AddBackslash(SourcePath) + "release.ini", "app", "version", "")

[Setup]
AppId={{C31233B7-C2D6-48F1-A7B8-BAB49A20193E}
AppName=墨序
AppVersion={#ReleaseVersion}
AppPublisher=UserWZ08
AppPublisherURL=https://github.com/UserWZ08/moxu
AppSupportURL=https://github.com/UserWZ08/moxu/issues
AppUpdatesURL=https://github.com/UserWZ08/moxu/releases
DefaultDirName={localappdata}\Programs\NeighbourPrint
DefaultGroupName=墨序
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..
OutputBaseFilename=墨序-安装包-{#ReleaseVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\MoXu.exe
SetupIconFile=assets\moxu.ico
DisableProgramGroupPage=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "程序-{#ReleaseVersion}\MoXu\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "使用说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "P0-P1修复记录.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "验证记录.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "维护说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "本次更新与打印原理.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "0.8.2更新说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "打印机配置示例.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

Source: "只读打印诊断.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "运行只读诊断.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "Run-Diagnostics.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "PrintDiagnostics.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "打印首选项故障说明.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{userprograms}\邻里快印.lnk"
Type: files; Name: "{userdesktop}\邻里快印.lnk"
Type: files; Name: "{app}\NeighbourPrint.exe"
Type: files; Name: "{app}\modules\light-background.enabled"
Type: files; Name: "{app}\_internal\assets\light-background.enabled"

[Icons]
Name: "{userprograms}\墨序"; Filename: "{app}\MoXu.exe"; IconFilename: "{app}\_internal\assets\moxu.ico"
Name: "{userdesktop}\墨序"; Filename: "{app}\MoXu.exe"; IconFilename: "{app}\_internal\assets\moxu.ico"; Tasks: desktopicon

Name: "{userprograms}\墨序只读打印诊断"; Filename: "{app}\运行只读诊断.cmd"

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; Flags: unchecked

[Run]
Filename: "{app}\MoXu.exe"; Description: "启动墨序"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command, ProgramPath: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    ProgramPath := ExpandConstant('{app}\MoXu.exe');
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'MoXu.UserWZ08', Command) then
      if (CompareText(Trim(Command), '"' + ProgramPath + '" --startup') = 0) or
         (CompareText(Trim(Command), ProgramPath + ' --startup') = 0) then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'MoXu.UserWZ08');
  end;
end;
