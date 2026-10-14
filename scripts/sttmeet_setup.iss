; STTMeet Windows installer (Inno Setup 6)
; Compiled by scripts/build_windows.ps1 -> installer_output\sttmeet_setup.exe
;
; Defines (overridable via ISCC /D...):
;   MyAppVersion   e.g. 1.0.0 (SemVer, shown in UI)
;   MyFileVersion  e.g. 1.0.0.0 (Windows VERSIONINFO)
;   RepoRoot       absolute path to repo root

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef MyFileVersion
  #define MyFileVersion "1.0.0.0"
#endif
#ifndef RepoRoot
  #define RepoRoot ".."
#endif

#define MyAppName "STTMeet"
#define MyAppPublisher "STTMeet"
#define MyAppExeName "sttmeet.exe"
#define MyAppDir "runtime"
#define MyAppURL "https://github.com/Deen/STTMeet"
#define MyAppGuid "{1A09380E-45A5-476C-B4C0-C7DD58234A7C}"

[Setup]
AppId={{1A09380E-45A5-476C-B4C0-C7DD58234A7C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
VersionInfoVersion={#MyFileVersion}
VersionInfoProductVersion={#MyFileVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile={#RepoRoot}\LICENSE
OutputDir={#RepoRoot}\installer_output
OutputBaseFilename=sttmeet_setup
SetupIconFile={#RepoRoot}\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppDir}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#RepoRoot}\sttmeet.dist\*"; DestDir: "{app}\{#MyAppDir}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoRoot}\vendor\ffmpeg\bin\ffmpeg.exe"; DestDir: "{app}\{#MyAppDir}\ffmpeg"; Flags: ignoreversion
Source: "{#RepoRoot}\vendor\ffmpeg\bin\ffprobe.exe"; DestDir: "{app}\{#MyAppDir}\ffmpeg"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppDir}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppDir}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppDir}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\{#MyAppDir}\ffmpeg"

[Code]
var
  MaintPage: TInputOptionWizardPage;
  AlreadyInstalled: Boolean;

function UninstallRegKey: String;
begin
  { Same GUID as AppId; Chr(123/125) = braces so the preprocessor does not treat them as constants }
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    Chr(123) + '1A09380E-45A5-476C-B4C0-C7DD58234A7C' + Chr(125) + '_is1';
end;

function GetUninstallerPath: String;
var
  Key: String;
begin
  Result := '';
  Key := UninstallRegKey;
  if RegQueryStringValue(HKLM, Key, 'UninstallString', Result) then
    Exit;
  if RegQueryStringValue(HKCU, Key, 'UninstallString', Result) then
    Exit;
  if IsWin64 then
  begin
    if RegQueryStringValue(HKLM64, Key, 'UninstallString', Result) then
      Exit;
    if RegQueryStringValue(HKLM32, Key, 'UninstallString', Result) then
      Exit;
  end;
end;

function LocalAppDataDir: String;
begin
  Result := ExpandConstant('{localappdata}\STTMeet');
end;

function DataDirEmpty: Boolean;
var
  FindRec: TFindRec;
  Path: String;
begin
  Result := True;
  Path := LocalAppDataDir;
  if DirExists(Path) then
  begin
    if FindFirst(Path + '\*', FindRec) then
    begin
      try
        Result := (FindRec.Name = '.') or (FindRec.Name = '..');
      finally
        FindClose(FindRec);
      end;
    end;
  end;
end;

procedure InitializeWizard;
begin
  AlreadyInstalled := GetUninstallerPath() <> '';
  if AlreadyInstalled then
  begin
    MaintPage := CreateInputOptionPage(
      wpWelcome,
      'Welcome to the STTMeet Setup Wizard',
      'Select whether you want to repair or remove STTMeet.',
      'Choose an option below, then click Next.',
      True,
      False
    );
    MaintPage.Add('Repair STTMeet');
    MaintPage.Add('Remove STTMeet');
    MaintPage.Values[0] := True;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (MaintPage <> nil) and (PageID = MaintPage.ID) then
    Result := not AlreadyInstalled;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  UninstPath: String;
  ResultCode: Integer;
begin
  Result := True;
  if (MaintPage = nil) or (CurPageID <> MaintPage.ID) then
    Exit;

  if MaintPage.Values[0] then
  begin
    { Repair - continue with normal install/upgrade }
    Result := True;
    Exit;
  end;

  if MaintPage.Values[1] then
  begin
    UninstPath := RemoveQuotes(GetUninstallerPath());
    if UninstPath = '' then
    begin
      MsgBox('Could not find the STTMeet uninstaller.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not Exec(UninstPath, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode) then
    begin
      MsgBox(FmtMessage(SetupMessage(msgUninstallOpenError), [UninstPath]), mbError, MB_OK);
      Result := False;
      Exit;
    end;
    { Exit this setup; the uninstaller UI takes over }
    Abort;
  end;

  Result := False;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Prompt before removing user data (API key, cache, logs). Never silently delete. }
  if CurUninstallStep = usPostUninstall then
  begin
    if DirExists(LocalAppDataDir) and not DataDirEmpty then
    begin
      if MsgBox('Remove STTMeet application data as well?' + #13#10 + #13#10 +
                LocalAppDataDir + #13#10 + #13#10 +
                'This deletes your API key, cached chunks and logs.' + #13#10 +
                'Choose No to keep the files for a later reinstall.',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(LocalAppDataDir, True, True, True);
    end;
  end;
end;