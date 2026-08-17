; Inno Setup script for Serpentine3D.
; Compile after the PyInstaller build:
;   ISCC.exe installer.iss

#define AppName "Serpentine3D"
#define AppVersion "0.7.0"
#define AppPublisher "Chisomo Banzi"
#define AppURL "https://github.com/chisomobanzi/Serpentine3D"

[Setup]
AppId={{7E1D0A4C-52F3-4B7E-9C0D-2B54E6A9D311}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\serp3d.exe
LicenseFile=..\..\LICENSE
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=Serpentine3D-Setup-x86_64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; \
  GroupDescription: "Additional icons:"; Flags: unchecked
Name: "updatecheck"; Description: "Check GitHub for &updates on startup"; \
  GroupDescription: "Options:"

[Files]
Source: "dist\serp3d\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\serp3d.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\serp3d.exe"; \
  Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.serp\OpenWithProgids"; \
  ValueType: string; ValueName: "Serpentine3D.Document"; ValueData: ""; \
  Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Serpentine3D.Document"; \
  ValueType: string; ValueName: ""; ValueData: "Serpentine3D model"; \
  Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Serpentine3D.Document\DefaultIcon"; \
  ValueType: string; ValueName: ""; ValueData: "{app}\serp3d.exe,0"
Root: HKA; Subkey: "Software\Classes\Serpentine3D.Document\shell\open\command"; \
  ValueType: string; ValueName: ""; ValueData: """{app}\serp3d.exe"" ""%1"""

[Run]
Filename: "{app}\serp3d.exe"; Description: "Launch {#AppName}"; \
  Flags: nowait postinstall skipifsilent

[Code]
{ Clearing the "check for updates" task writes a minimal settings.json so the
  launch-time check is off from first run - SignPath's terms require an opt-out
  at install time, not only a runtime setting. An existing settings file is
  never touched: whatever the user already chose in the app wins. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  CfgDir, CfgPath: String;
begin
  if (CurStep = ssPostInstall) and (not WizardIsTaskSelected('updatecheck')) then
  begin
    CfgDir := ExpandConstant('{%USERPROFILE}') + '\.config\serpentine3d';
    CfgPath := CfgDir + '\settings.json';
    if not FileExists(CfgPath) then
    begin
      ForceDirectories(CfgDir);
      SaveStringToFile(CfgPath,
        '{' + #13#10 + '  "check_updates": false' + #13#10 + '}' + #13#10,
        False);
    end;
  end;
end;
