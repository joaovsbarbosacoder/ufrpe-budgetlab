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
ArchitecturesAllowed=x64compatible
UninstallDisplayName=UFRPE BudgetLab

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Dirs]
Name: "{app}\dados"
#include AddBackslash(Build) + "dirs.iss"

[Files]
Source: "{#Build}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Build}\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion
#ifdef ComDados
; Nunca sobrescreve dado que o usuário já tenha em dados\.
Source: "{#Raiz}\data\*"; DestDir: "{app}\dados"; Flags: recursesubdirs createallsubdirs onlyifdoesntexist
#endif

[Icons]
Name: "{userprograms}\UFRPE BudgetLab"; Filename: "{app}\python\python.exe"; Parameters: "-m scripts.instalador.iniciar"; WorkingDir: "{app}\app"
Name: "{userdesktop}\UFRPE BudgetLab"; Filename: "{app}\python\python.exe"; Parameters: "-m scripts.instalador.iniciar"; WorkingDir: "{app}\app"

[Run]
; app\data -> dados (junção): os módulos continuam lendo "data/..." sem alteração.
Filename: "cmd.exe"; Parameters: "/c if not exist ""{app}\app\data"" mklink /J ""{app}\app\data"" ""{app}\dados"""; Flags: runhidden
Filename: "{app}\python\python.exe"; Parameters: "-m scripts.instalador.iniciar"; WorkingDir: "{app}\app"; Description: "Abrir o UFRPE BudgetLab agora"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Remove a junção (rmdir não segue o link) ANTES de qualquer remoção recursiva de app\.
Filename: "cmd.exe"; Parameters: "/c rmdir ""{app}\app\data"""; RunOnceId: "RemoverJuncaoData"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dados: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dados := ExpandConstant('{app}\dados');
    if DirExists(Dados) then
      if MsgBox('Remover também as bases de dados em:' + #13#10 + Dados + #13#10#13#10 +
                'Escolha "Não" para manter seus dados (recomendado).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dados, True, True, True);
  end;
end;
