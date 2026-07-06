#define AppName "Scan Backup Manager"
#define AppVersion "1.0.0"

[Setup]
AppId={{D629F4A3-29C8-46DD-A8F2-2D54A8B4F18A}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\ScanBackupManager
PrivilegesRequired=admin
OutputBaseFilename=ScanBackupManager-Setup
Compression=lzma2
SolidCompression=yes

[Files]
Source: "..\dist\ScanBackupManager.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\ScanBackupService.exe"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "{app}\ScanBackupService.exe"; Parameters: "--startup delayed install"; StatusMsg: "Đăng ký dịch vụ sao lưu..."; Flags: runhidden
Filename: "{sys}\sc.exe"; Parameters: "config ScanBackupService obj= ""{code:GetServiceUser}"" password= ""{code:GetServicePassword}"""; StatusMsg: "Cấu hình tài khoản dịch vụ..."; Flags: runhidden
Filename: "{sys}\sc.exe"; Parameters: "start ScanBackupService"; StatusMsg: "Khởi động dịch vụ sao lưu..."; Flags: runhidden

[UninstallRun]
Filename: "{app}\ScanBackupService.exe"; Parameters: "stop"; Flags: runhidden; RunOnceId: "StopService"
Filename: "{app}\ScanBackupService.exe"; Parameters: "remove"; Flags: runhidden; RunOnceId: "RemoveService"

[Icons]
Name: "{autoprograms}\Scan Backup Manager"; Filename: "{app}\ScanBackupManager.exe"

[Code]
var
  ServiceAccountPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  ServiceAccountPage := CreateInputQueryPage(
    wpSelectDir,
    'Tài khoản dịch vụ Windows',
    'Nhập tài khoản có quyền đọc thư mục chia sẻ máy trạm và ghi kho sao lưu.',
    'Ví dụ: DOMAIN\svc_scanbackup. Thông tin được Windows Service Control Manager lưu bảo mật.'
  );
  ServiceAccountPage.Add('Tài khoản:', False);
  ServiceAccountPage.Add('Mật khẩu:', True);
end;

function GetServiceUser(Param: String): String;
begin
  Result := ServiceAccountPage.Values[0];
end;

function GetServicePassword(Param: String): String;
begin
  Result := ServiceAccountPage.Values[1];
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ServiceAccountPage.ID then
  begin
    if (Trim(ServiceAccountPage.Values[0]) = '') or
       (ServiceAccountPage.Values[1] = '') then
    begin
      MsgBox('Cần nhập tài khoản và mật khẩu dịch vụ.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
