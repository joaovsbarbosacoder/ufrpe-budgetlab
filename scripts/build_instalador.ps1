# Gera o instalador Windows do UFRPE BudgetLab em dist\ (roda só na máquina de build).
#   .\scripts\build_instalador.ps1              -> dist\BudgetLab-Setup.exe (sem dados)
#   .\scripts\build_instalador.ps1 -ComDados    -> dist\BudgetLab-Setup-Completo.exe (com data\)
# Pré-requisitos: internet, Git, Python (mesma versão do projeto) e Inno Setup 6.
# Ver docs/superpowers/specs/2026-10-19-instalador-windows-design.md.
param([switch]$ComDados)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$iscc = @("$env:ProgramFiles\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 não encontrado. Instale-o (https://jrsoftware.org/isdl.php) e repita." }
if (-not (Test-Path ".git")) { throw "Execute dentro do repositório Git do projeto." }
$ramo = (git rev-parse --abbrev-ref HEAD).Trim()
if ($ramo -ne "master") { Write-Host "Aviso: build a partir do ramo '$ramo'; na 1ª abertura o sistema se atualizará para o master." -ForegroundColor Yellow }

$build = Join-Path $raiz "build_instalador"
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
New-Item -ItemType Directory $build | Out-Null

# 1. Python embeddable (mesma versão do ambiente de desenvolvimento) + pip + dependências
$versao = (python -c "import sys;print('%d.%d.%d' % sys.version_info[:3])").Trim()
$pyDir = Join-Path $build "python"
$zip = Join-Path $build "python-embed.zip"
Write-Host "Baixando Python $versao (embeddable)..."
Invoke-WebRequest "https://www.python.org/ftp/python/$versao/python-$versao-embed-amd64.zip" -OutFile $zip -UseBasicParsing
Expand-Archive $zip -DestinationPath $pyDir
Remove-Item $zip
$pth = Get-ChildItem $pyDir -Filter "python*._pth" | Select-Object -First 1
(Get-Content $pth.FullName) -replace '^#\s*import site', 'import site' | Set-Content $pth.FullName -Encoding ascii
$getpip = Join-Path $build "get-pip.py"
Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip -UseBasicParsing
& "$pyDir\python.exe" $getpip --no-warn-script-location
Remove-Item $getpip
Write-Host "Instalando dependências (requirements.txt)..."
& "$pyDir\python.exe" -m pip install --disable-pip-version-check --no-warn-script-location -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependências." }

# 2. Código versionado (sem dados, testes e rascunhos) + versao.txt
$appDir = Join-Path $build "app"
$excluir = @("data/", "tests/", "docs/superpowers/", "design_handoff_streamlit/", "installer/")
$arquivos = git ls-files | Where-Object { $f = $_; -not ($excluir | Where-Object { $f.StartsWith($_) }) }
foreach ($f in $arquivos) {
    $destino = Join-Path $appDir $f
    New-Item -ItemType Directory (Split-Path $destino) -Force | Out-Null
    Copy-Item $f $destino
}
$hashReq = (Get-FileHash "requirements.txt" -Algorithm SHA256).Hash.ToLower()
@{ commit = (git rev-parse HEAD).Trim(); requirements_sha256 = $hashReq; arquivos = @($arquivos) } |
    ConvertTo-Json -Compress | Set-Content (Join-Path $appDir "versao.txt") -Encoding utf8

# 3. Estrutura de dados\ (subpastas de data\) e compilação do instalador
$dirs = Get-ChildItem "data" -Directory | ForEach-Object { 'Name: "{app}\dados\' + $_.Name + '"' }
$dirs | Set-Content (Join-Path $build "dirs.iss") -Encoding utf8
$flag = if ($ComDados) { 1 } else { 0 }
& $iscc "/DRaiz=$raiz" "/DBuild=$build" "/DComDados=$flag" "installer\budgetlab.iss"
if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar o instalador." }
Get-ChildItem (Join-Path $raiz "dist") -Filter "BudgetLab-Setup*.exe" |
    ForEach-Object { "{0}  ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB) }
