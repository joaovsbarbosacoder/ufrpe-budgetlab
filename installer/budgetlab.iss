; Instalador do UFRPE BudgetLab (Inno Setup 6). Gerado por scripts\build_instalador.ps1,
; que define Raiz (raiz do repositório), Build (pasta montada) e, só na variante completa, ComDados.
; Ver docs/superpowers/specs/2026-10-19-instalador-windows-design.md.
#ifdef ComDados
  #define Saida "BudgetLab-Setup-Completo"
#else
  #define Saida "BudgetLab-Setup"
#endif

[Setup]
AppId={{7B6D2C1E-4F3A-4C57-9A0E-5B1F2D8C9E41}
AppName=UFRPE BudgetLab
AppVersion=1.0
AppPublisher=UFRPE
DefaultDirName={localappdata}\UFRPE BudgetLab
DefaultGroupName=UFRPE BudgetLab
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#Raiz}\dist
OutputBaseFilename={#Saida}
Compression=lzma2
SolidCompression=yes
LZMANumBlockThreads=8
ArchitecturesAllowed=x64compatible
UninstallDisplayName=UFRPE BudgetLab

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Dirs]
Name: "{app}\dados"; Flags: uninsneveruninstall
Name: "{app}\log"
#include AddBackslash(Build) + "dirs.iss"

[Files]
Source: "{#Build}\python\*"; DestDir: "{app}\python"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Build}\electron\*"; DestDir: "{app}\electron"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Build}\app\*"; DestDir: "{app}\app"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion
#ifdef ComDados
; Nunca sobrescreve dado que o usuário já tenha em dados\. uninsneveruninstall: o desinstalador
; do Inno apagaria os arquivos que instalou; os dados só saem se o usuário confirmar no diálogo.
Source: "{#Raiz}\data\*"; DestDir: "{app}\dados"; Flags: recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall
#endif

[Icons]
Name: "{userprograms}\UFRPE BudgetLab"; Filename: "{app}\electron\UFRPE BudgetLab.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\UFRPE BudgetLab"; Filename: "{app}\electron\UFRPE BudgetLab.exe"; WorkingDir: "{app}"

[Run]
; app\data -> dados (junção): os módulos continuam lendo "data/..." sem alteração.
Filename: "cmd.exe"; Parameters: "/c if not exist ""{app}\app\data"" mklink /J ""{app}\app\data"" ""{app}\dados"""; Flags: runhidden
Filename: "{app}\electron\UFRPE BudgetLab.exe"; WorkingDir: "{app}"; Description: "Abrir o UFRPE BudgetLab agora"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Fecha o app (e o servidor filho) antes de remover arquivos.
Filename: "taskkill.exe"; Parameters: "/IM ""UFRPE BudgetLab.exe"" /T /F"; RunOnceId: "FecharApp"; Flags: runhidden
; Remove a junção (rmdir não segue o link) ANTES de qualquer remoção recursiva de app\.
Filename: "cmd.exe"; Parameters: "/c rmdir ""{app}\app\data"""; RunOnceId: "RemoverJuncaoData"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\electron"
Type: filesandordirs; Name: "{app}\log"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dados: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dados := ExpandConstant('{app}\dados');
    if DirExists(Dados) and not UninstallSilent then
      if MsgBox('Remover também as bases de dados em:' + #13#10 + Dados + #13#10#13#10 +
                'Escolha "Não" para manter seus dados (recomendado).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dados, True, True, True);
  end;
end;
