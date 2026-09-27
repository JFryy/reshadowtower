#ifndef PackageDir
  #error PackageDir must be provided with /DPackageDir
#endif
#ifndef AppVersion
  #error AppVersion must be provided with /DAppVersion
#endif
#ifndef OutputDir
  #error OutputDir must be provided with /DOutputDir
#endif

[Setup]
AppId={{A1CBBAC5-46DD-46B0-83E8-079D87D4DDE1}
AppName=ReShadowTower
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\ReShadowTower\{#AppVersion}
DefaultGroupName=ReShadowTower
UsePreviousAppDir=no
DisableDirPage=yes
RestartApplications=no
OutputDir={#OutputDir}
OutputBaseFilename=ReShadowTower-{#AppVersion}-windows-x64-setup
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\ReShadowTower.exe

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\ReShadowTower"; Filename: "{app}\ReShadowTower.exe"
