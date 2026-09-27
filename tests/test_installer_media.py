from pathlib import Path
import unittest


SCRIPT = (Path(__file__).resolve().parents[1] / "packaging/windows/ReShadowTower.iss").read_text()


class InstallerMediaTests(unittest.TestCase):
    def test_branded_images_and_existing_install_policy(self):
        self.assertIn("WizardImageFile={#SourcePath}wizard.bmp", SCRIPT)
        self.assertIn("WizardSmallImageFile={#SourcePath}wizard-small.bmp", SCRIPT)
        self.assertIn("DisableWelcomePage=no", SCRIPT)
        self.assertIn("PrivilegesRequired=lowest", SCRIPT)
        self.assertIn("DefaultDirName={localappdata}", SCRIPT)
        self.assertIn('Source: "{#PackageDir}\\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion', SCRIPT)
        self.assertNotIn("[Run]", SCRIPT)

    def test_audio_lifecycle_and_nonfatal_error(self):
        self.assertIn('Source: "{#PackageDir}\\payload\\assets\\setup\\music.wav"; Flags: dontcopy', SCRIPT)
        self.assertIn("ExtractTemporaryFile('music.wav')", SCRIPT)
        self.assertIn("SND_ASYNC or SND_NODEFAULT or SND_LOOP or SND_FILENAME", SCRIPT)
        self.assertIn("external 'PlaySoundW@winmm.dll stdcall'", SCRIPT)
        self.assertIn("MusicCheckBox.OnClick := @MusicClicked", SCRIPT)
        self.assertIn("MusicCheckBox.Parent := WizardForm;", SCRIPT)
        self.assertIn("if not MusicExtracted then", SCRIPT)
        self.assertIn("procedure DeinitializeSetup;\nbegin\n  StopMusic;", SCRIPT)
        self.assertIn("MusicStatus.Caption := 'Music could not be played; installation can continue.'", SCRIPT)
        self.assertIn("Log('Setup music playback failed.')", SCRIPT)


if __name__ == "__main__":
    unittest.main()
