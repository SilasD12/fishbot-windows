; Inno Setup script for Fishbot.
;
; Produces a per-user installer (no admin required) that:
;   * installs into %LOCALAPPDATA%\Programs\Fishbot
;   * registers an entry in Settings > Apps & features
;   * creates Start Menu and (optional) Desktop shortcuts
;   * seeds %APPDATA%\Fishbot\config.toml on first install only
;   * removes everything cleanly on uninstall
;
; The installer touches no autostart keys, no scheduled tasks, no services,
; no firewall rules, and no PATH entries. It writes only to the per-user
; install dir and the user-config dir under %APPDATA%.

#define AppName       "Fishbot"
#define AppVersion    "1.0.0"
#define AppPublisher  "Silas Daley"
#define AppExeName    "fishbot-gui.exe"

[Setup]
AppId={{8F9C5D02-7E4A-4B6F-9F8E-1A3B5C7D9E2F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL=https://github.com/silasdaley
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=fishbot-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
ChangesAssociations=no
ChangesEnvironment=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; GUI bundle goes to {app}; CLI goes to {app}\fishbot. Both are flat
; PyInstaller --onedir outputs.
Source: "..\dist\fishbot-gui\*"; DestDir: "{app}";          Flags: recursesubdirs ignoreversion
Source: "..\dist\fishbot\*";     DestDir: "{app}\fishbot";  Flags: recursesubdirs ignoreversion

; Seed the user's config on first install only. Editing the file later
; survives subsequent reinstalls.
Source: "..\config.toml";        DestDir: "{userappdata}\{#AppName}"; \
    DestName: "config.toml"; Flags: onlyifdoesntexist

[Icons]
Name: "{userprograms}\{#AppName}";          Filename: "{app}\{#AppExeName}"
Name: "{userprograms}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}";           Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Cleans up runtime data (logs, debug frames). The user's edited config
; under %APPDATA%\Fishbot is intentionally NOT deleted here so that
; reinstall preserves their settings. To remove it manually, delete:
;   %APPDATA%\Fishbot
Type: filesandordirs; Name: "{localappdata}\{#AppName}"
