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
  MusicExtracted: Boolean;

procedure StopMusic;
begin
  StopPlaySound(0, 0, 0);
end;

procedure MusicFailed(const Detail: String);
begin
  StopMusic;
  MusicCheckBox.Caption := 'Music unavailable (setup can continue)';
  MusicCheckBox.Enabled := False;
  Log(Detail);
end;

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
      MusicFailed('Setup music playback failed.');
  except
    MusicFailed('Setup music extraction or playback failed: ' + GetExceptionMessage);
  end;
end;

procedure MusicClicked(Sender: TObject);
begin
  if MusicCheckBox.Checked then
    StartMusic
  else
    StopMusic;
end;

{ Keep the mute control accessible on every wizard page. }
procedure InitializeMusic;
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

  StartMusic;
end;
