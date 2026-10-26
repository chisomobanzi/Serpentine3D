; Inno Setup script for Serpentine3D.
; Compile after the PyInstaller build:
;   ISCC.exe installer.iss

#define AppName "Serpentine3D"
#define AppVersion "0.12.2"
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
{ The "check for updates" task is applied to settings.json on every install,
  ticked or cleared - SignPath's terms require an opt-out at install time, not
  only a runtime setting. Ticking it again must also undo an earlier opt-out,
  so an existing file gets its check_updates value flipped in place; the rest
  of the file is left as it is. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  CfgDir, CfgPath: String;
  Json, Wanted, Other: AnsiString;
  P: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;
  CfgDir := ExpandConstant('{%USERPROFILE}') + '\.config\serpentine3d';
  CfgPath := CfgDir + '\settings.json';
  if WizardIsTaskSelected('updatecheck') then
  begin
    Wanted := '"check_updates": true';
    Other := '"check_updates": false';
  end else begin
    Wanted := '"check_updates": false';
    Other := '"check_updates": true';
  end;
  if FileExists(CfgPath) then
  begin
    if not LoadStringFromFile(CfgPath, Json) then
      Exit;
    P := Pos(Other, Json);
    if P > 0 then
      Json := Copy(Json, 1, P - 1) + Wanted + Copy(Json, P + Length(Other), MaxInt)
    else if (Pos('"check_updates"', Json) = 0) and
            (not WizardIsTaskSelected('updatecheck')) then
    begin
      P := Pos('{', Json);
      if P = 0 then
        Exit;
      Insert(#13#10 + '  ' + Wanted + ',', Json, P + 1);
    end else
      Exit;
    SaveStringToFile(CfgPath, Json, False);
  end
  else if not WizardIsTaskSelected('updatecheck') then
  begin
    ForceDirectories(CfgDir);
    SaveStringToFile(CfgPath,
      '{' + #13#10 + '  "check_updates": false' + #13#10 + '}' + #13#10,
      False);
  end;
end;
