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
; Dados em pasta REAL (app\data): uma junção para outra pasta falha com WinError 448 quando o
; Python é iniciado pelo Electron (proteção do Windows contra junções não confiáveis).
Name: "{app}\app\data"; Flags: uninsneveruninstall
Name: "{app}\log"
#include AddBackslash(Build) + "dirs.iss"

[Files]
Source: "{#Build}\python\*"; DestDir: "{app}\python"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Build}\electron\*"; DestDir: "{app}\electron"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Build}\app\*"; DestDir: "{app}\app"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion
#ifdef ComDados
; Nunca sobrescreve dado que o usuário já tenha em app\data. uninsneveruninstall: o desinstalador
; do Inno apagaria os arquivos que instalou; os dados só saem se o usuário confirmar no diálogo.
Source: "{#Raiz}\data\*"; DestDir: "{app}\app\data"; Flags: recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall
#endif

[Icons]
Name: "{userprograms}\UFRPE BudgetLab"; Filename: "{app}\electron\UFRPE BudgetLab.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\UFRPE BudgetLab"; Filename: "{app}\electron\UFRPE BudgetLab.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\electron\UFRPE BudgetLab.exe"; WorkingDir: "{app}"; Description: "Abrir o UFRPE BudgetLab agora"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Fecha o app (e o servidor filho) antes de remover arquivos.
Filename: "taskkill.exe"; Parameters: "/IM ""UFRPE BudgetLab.exe"" /T /F"; RunOnceId: "FecharApp"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\electron"
Type: filesandordirs; Name: "{app}\log"

[Code]
// Versão anterior: app\data era uma junção para dados\ (falha com o Electron) e o registro de
// desinstalação dela remove app\ recursivamente. Instalar por cima manteria essa regra (e
// apagaria os dados ao desinstalar), então o instalador recusa e pede para desinstalar a
// versão antiga antes (isso preserva dados\, que esta versão migra para app\data).
function EhJuncao(Caminho: String): Boolean;
var
  R: TFindRec;
begin
  Result := False;
  if FindFirst(Caminho, R) then
  try
    Result := (R.Attributes and $400) <> 0;  // FILE_ATTRIBUTE_REPARSE_POINT
  finally
    FindClose(R);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if EhJuncao(ExpandConstant('{app}\app\data')) then
    Result := 'Há uma versão anterior do UFRPE BudgetLab nesta pasta.' + #13#10#13#10 +
              'Desinstale-a antes (Configurações > Aplicativos > UFRPE BudgetLab) e execute este ' +
              'instalador de novo. Seus dados são mantidos e esta versão os aproveita.';
end;

// Dados da versão anterior (dados\ ao lado de app\): move para app\data, sem perder nada.
procedure MigrarDadosAntigos;
var
  Novo, Antigo: String;
begin
  Novo := ExpandConstant('{app}\app\data');
  Antigo := ExpandConstant('{app}\dados');
  if DirExists(Antigo) and not DirExists(Novo) then
  begin
    ForceDirectories(ExpandConstant('{app}\app'));
    if not RenameFile(Antigo, Novo) then
      MsgBox('Não foi possível mover ' + Antigo + ' para ' + Novo + '.' + #13#10 +
             'Seus dados continuam em ' + Antigo + '.', mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    MigrarDadosAntigos;
end;

// Remove tudo de app\ MENOS a pasta data (que só sai se o usuário confirmar).
procedure LimparCodigo;
var
  Raiz: String;
  R: TFindRec;
begin
  Raiz := ExpandConstant('{app}\app');
  if FindFirst(Raiz + '\*', R) then
  try
    repeat
      if (R.Name <> '.') and (R.Name <> '..') and (CompareText(R.Name, 'data') <> 0) then
      begin
        if (R.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          DelTree(Raiz + '\' + R.Name, True, True, True)
        else
          DeleteFile(Raiz + '\' + R.Name);
      end;
    until not FindNext(R);
  finally
    FindClose(R);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dados: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    LimparCodigo;
    Dados := ExpandConstant('{app}\app\data');
    if DirExists(Dados) and not UninstallSilent then
      if MsgBox('Remover também as bases de dados em:' + #13#10 + Dados + #13#10#13#10 +
                'Escolha "Não" para manter seus dados (recomendado).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dados, True, True, True);
    RemoveDir(ExpandConstant('{app}\app'));
  end;
end;
