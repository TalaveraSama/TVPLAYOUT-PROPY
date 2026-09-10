; ============================================================================
; TVPlayout PRO V24.0.2.39 — Instalador completo para Windows
;
; Genera UN SOLO Setup_TVPlayoutPRO_V24.0.2.39.exe que instala:
;   • TVPlayoutPRO.exe  (aplicación PySide6 + PyAV congelada, carpeta _internal)
;   • ffmpeg.exe, ffprobe.exe y mpv.exe en la RAÍZ del programa
;   • Opcional: NDI Runtime x64 y VLC (se empaquetan si están en vendor\)
;   • Opcional: regla de firewall para el descubrimiento NDI/mDNS (UDP 5353)
;
; Instalación por usuario (sin UAC) en %LOCALAPPDATA%\Programs\TVPlayoutPRO:
; la aplicación guarda base de datos, logs, miniaturas y cache JUNTO AL EXE,
; por lo que necesita una carpeta con permisos de escritura (Program Files
; no los daría sin administrador).
;
; Compilar con Inno Setup 6:  installer\BUILD_INSTALLER.bat lo llama solo.
; ============================================================================

#define MyAppName "TVPlayout PRO"
#define MyAppVersion "V24.0.2.39"
#define MyAppPublisher "TVPlayout PRO"
#define MyAppExeName "TVPlayoutPRO.exe"
#define MyAppId "{7A4C2E90-3B1D-4F5A-8C2E-9D0B1A2C3E4F}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\TVPlayoutPRO
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Instalación por usuario: sin UAC y con permisos de escritura para la BD.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
WizardResizable=yes
OutputDir=..\dist
OutputBaseFilename=Setup_TVPlayoutPRO_{#MyAppVersion}
SetupLogging=yes
UninstallDisplayName={#MyAppName} {#MyAppVersion}
#if FileExists("..\assets\logo.ico")
SetupIconFile=..\assets\logo.ico
#endif

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el &escritorio"; GroupDescription: "Accesos directos:"
Name: "ndi"; Description: "Instalar NDI Runtime x64 (necesario para la salida NDI; pide permiso de administrador)"; GroupDescription: "Componentes opcionales:"; Flags: checkedonce
Name: "vlc"; Description: "Instalar VLC (reproductor de vistas previas y monitor de programa)"; GroupDescription: "Componentes opcionales:"
Name: "firewall"; Description: "Permitir NDI en el firewall de Windows (regla mDNS UDP 5353; pide permiso de administrador)"; GroupDescription: "Componentes opcionales:"

[Files]
; Aplicación completa (exe + _internal + ffmpeg/ffprobe/mpv en la raíz)
Source: "..\dist\TVPlayoutPRO\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Instaladores opcionales: solo se empaquetan si existen en vendor\
Source: "..\vendor\ndi-runtime.exe"; DestDir: "{tmp}"; Flags: skipifsourcedoesntexist
Source: "..\vendor\vlc-setup.exe"; DestDir: "{tmp}"; Flags: skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; NDI Runtime (silencioso, elevado por UAC porque el instalador es por usuario)
Filename: "{tmp}\ndi-runtime.exe"; Parameters: "/S"; Flags: runas runhidden waituntilterminated; Tasks: ndi; Check: NdiInstallerPresent
; VLC (silencioso, elevado por UAC)
Filename: "{tmp}\vlc-setup.exe"; Parameters: "/S"; Flags: runas runhidden waituntilterminated; Tasks: vlc; Check: VlcInstallerPresent
; Regla de firewall para el descubrimiento NDI (mDNS)
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""TVPlayout PRO NDI"" dir=in action=allow protocol=UDP localport=5353 program=""{app}\{#MyAppExeName}"""; Flags: runas runhidden waituntilterminated; Tasks: firewall
; Ejecutar la aplicación al terminar
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Quitar la regla de firewall si se llegó a crear (mejor esfuerzo).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""TVPlayout PRO NDI"""; Flags: runhidden; RunOnceId: "DelFirewallRule"

[UninstallDelete]
; La base de datos, logs, cache y miniaturas creadas en uso NO se borran:
; son datos del usuario. Se listan aquí solo si el usuario las pide borrar
; manualmente tras desinstalar.

[Code]
function NdiInstallerPresent(): Boolean;
begin
  Result := FileExists(ExpandConstant('{tmp}\ndi-runtime.exe'));
end;

function VlcInstallerPresent(): Boolean;
begin
  Result := FileExists(ExpandConstant('{tmp}\vlc-setup.exe'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    Log('TVPlayout PRO instalado en ' + ExpandConstant('{app}'));
end;
