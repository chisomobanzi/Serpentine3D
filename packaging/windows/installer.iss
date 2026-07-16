; Inno Setup script for Serpentine3D.
; Compile after the PyInstaller build:
;   ISCC.exe installer.iss

#define AppName "Serpentine3D"
#define AppVersion "0.3.1"
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
