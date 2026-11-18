; Instalador de Windows (Inno Setup 6) para ComprobantesSRI.
;
; Empaqueta la carpeta onedir que genera PyInstaller (dist\ComprobantesSRI) en
; un único ComprobantesSRI-Setup.exe. Así el usuario no tiene que descomprimir
; nada: si se abre el .exe desde dentro de un zip, Windows copia solo el .exe a
; una carpeta temporal y falta _internal\python312.dll («Failed to load Python DLL»).
;
; Se instala por usuario (%LOCALAPPDATA%\Programs\ComprobantesSRI), sin pedir
; permisos de administrador. Los datos de la app viven aparte
; (%LOCALAPPDATA%\ComprobantesSRI) y NO se borran al desinstalar.
;
; Compilar (desde la raíz del repo, después de PyInstaller):
;   iscc /DAppVersion=1.0.0 instalador\ComprobantesSRI.iss
; Resultado: dist\ComprobantesSRI-Setup.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Comprobantes SRI"
#define AppExe "ComprobantesSRI.exe"

[Setup]
; AppId identifica la app para actualizar/desinstalar: NO cambiarlo nunca.
AppId={{6C3D441B-3746-41F7-A947-8D6197619B3D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=KUYACODE
DefaultDirName={autopf}\ComprobantesSRI
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
; Instalación por usuario: no pide administrador ({autopf} = %LOCALAPPDATA%\Programs).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=ComprobantesSRI-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Si la app está abierta al actualizar, se ofrece cerrarla.
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Al actualizar, se limpia _internal para no dejar librerías de la versión anterior.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\ComprobantesSRI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
