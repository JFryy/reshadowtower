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
UninstallDisplayIcon={app}\ReShadowTower.exe

[Files]
Source: "{#PackageDir}\payload\assets\setup\music.wav"; Flags: dontcopy
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\ReShadowTower"; Filename: "{app}\ReShadowTower.exe"

[Code]
const
  SND_ASYNC = $0001;
  SND_NODEFAULT = $0002;
  SND_LOOP = $0008;
  SND_FILENAME = $00020000;

function PlaySoundW(pszSound: String; hmod: Integer; fdwSound: Integer): Boolean;
  external 'PlaySoundW@winmm.dll stdcall';
function StopPlaySound(pszSound: Integer; hmod: Integer; fdwSound: Integer): Boolean;
  external 'PlaySoundW@winmm.dll stdcall';

var
  MusicCheckBox: TNewCheckBox;
  MusicStatus: TNewStaticText;
  MusicExtracted: Boolean;

{ Stop playback before changing tracks or closing Setup. }
procedure StopMusic;
begin
  StopPlaySound(0, 0, 0);
end;

{ Start the bundled track without blocking the installer; report failures in the wizard. }
procedure StartMusic;
begin
  try
    if not MusicExtracted then
    begin
      ExtractTemporaryFile('music.wav');
      MusicExtracted := True;
    end;
    if not PlaySoundW(ExpandConstant('{tmp}\music.wav'), 0,
      SND_ASYNC or SND_NODEFAULT or SND_LOOP or SND_FILENAME) then
    begin
      MusicStatus.Caption := 'Music could not be played; installation can continue.';
      MusicCheckBox.Caption := 'Music unavailable (installation can continue)';
      MusicCheckBox.Enabled := False;
      Log('Setup music playback failed.');
    end;
  except
    MusicStatus.Caption := 'Music could not be played; installation can continue.';
    MusicCheckBox.Caption := 'Music unavailable (installation can continue)';
    MusicCheckBox.Enabled := False;
    Log('Setup music extraction or playback failed: ' + GetExceptionMessage);
  end;
end;

{ Toggle music without affecting installation. }
procedure MusicClicked(Sender: TObject);
begin
  if MusicCheckBox.Checked then
    StartMusic
  else
    StopMusic;
end;

{ Keep the mute control accessible on every wizard page. }
procedure InitializeWizard;
begin
  MusicCheckBox := TNewCheckBox.Create(WizardForm);
  MusicCheckBox.Parent := WizardForm;
  MusicCheckBox.Left := ScaleX(16);
  MusicCheckBox.Top := WizardForm.CancelButton.Top;
  MusicCheckBox.Width := WizardForm.BackButton.Left - ScaleX(24);
  MusicCheckBox.Height := ScaleY(20);
  MusicCheckBox.Caption := 'Play setup music';
  MusicCheckBox.Checked := True;
  MusicCheckBox.OnClick := @MusicClicked;

  MusicStatus := TNewStaticText.Create(WizardForm);
  MusicStatus.Parent := WizardForm.WelcomePage;
  MusicStatus.Left := WizardForm.WelcomeLabel2.Left;
  MusicStatus.Top := WizardForm.WelcomePage.Height - ScaleY(40);
  MusicStatus.Width := WizardForm.WelcomeLabel2.Width;
  MusicStatus.Height := ScaleY(30);
  StartMusic;
end;

{ Stop the loop on cancellation and successful completion alike. }
procedure DeinitializeSetup;
begin
  StopMusic;
end;
