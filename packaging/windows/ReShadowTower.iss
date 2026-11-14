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
DefaultDirName={localappdata}\Programs\ReShadowTower
DefaultGroupName=ReShadowTower
UsePreviousAppDir=yes
DisableDirPage=no
DisableWelcomePage=no
WizardImageFile={#SourcePath}wizard.bmp
WizardSmallImageFile={#SourcePath}wizard-small.bmp
RestartApplications=no
OutputDir={#OutputDir}
OutputBaseFilename=ReShadowTower-{#AppVersion}-windows-x64-setup
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\{#AppVersion}\ReShadowTower.exe

[Files]
Source: "{#PackageDir}\payload\assets\setup\music.wav"; Flags: dontcopy
; Versioned subfolders: the bootstrap rejects payload files left over from an older release.
Source: "{#PackageDir}\*"; DestDir: "{app}\{#AppVersion}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\ReShadowTower"; Filename: "{app}\{#AppVersion}\ReShadowTower.exe"

[Code]
#include "setup_music.iss"

procedure InitializeWizard;
begin
  InitializeMusic;
  { Older releases recorded <folder>\<version> as the install folder; offer <folder> instead. }
  if FileExists(AddBackslash(WizardForm.DirEdit.Text) + 'ReShadowTower.exe') then
    WizardForm.DirEdit.Text := ExtractFileDir(RemoveBackslash(WizardForm.DirEdit.Text));
end;

procedure DeinitializeSetup;
begin
  StopMusic;
end;
