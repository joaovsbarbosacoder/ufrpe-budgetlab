# Atualiza o código pelo GitHub e inicia o UFRPE BudgetLab (uso em um único computador).
#
# Chamado pelo atalho "Iniciar BudgetLab.bat" na raiz do projeto. Etapas:
#   1. git pull --ff-only no branch atual. Sem internet, com alterações locais conflitantes
#      ou com histórico divergente, o Git recusa a atualização sem tocar em nada; o script
#      só avisa e segue com a versão já instalada. Nunca usa reset, stash ou checkout.
#   2. Garante o .venv e reinstala as dependências somente quando o requirements.txt mudou
#      (hash gravado em .venv\requirements.sha256).
#   3. Se o sistema já estiver aberto na porta, só abre o navegador; senão inicia o
#      Streamlit nesta janela (fechar a janela encerra o sistema) e abre o navegador.
#
# Os dados locais em data/ (cadastros, bancos SQLite, planilhas importadas) não são
# versionados e não são alterados por este script.
param(
    [int]$Porta = 8501,
    [switch]$SemNavegador
)

Set-Location (Split-Path -Parent $PSScriptRoot)
$Host.UI.RawUI.WindowTitle = "UFRPE BudgetLab"
$url = "http://localhost:$Porta"

function Escrever([string]$texto, [string]$cor = "Gray") { Write-Host $texto -ForegroundColor $cor }

function Sistema-Aberto {
    try {
        $r = Invoke-WebRequest -Uri "$url/_stcore/health" -UseBasicParsing -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

# --- 1. Atualização do código ---------------------------------------------------------
Escrever "== UFRPE BudgetLab ==" "Cyan"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Escrever "Aviso: Git não encontrado; seguindo sem atualizar." "Yellow"
} elseif (-not (Test-Path ".git")) {
    Escrever "Aviso: esta pasta não é um repositório Git; seguindo sem atualizar." "Yellow"
} else {
    $env:GIT_TERMINAL_PROMPT = "0"
    $antes = (cmd /c "git rev-parse HEAD 2>nul")
    Escrever "Verificando atualizações..."
    $saida = (cmd /c "git pull --ff-only 2>&1") -join "`n"
    if ($LASTEXITCODE -ne 0) {
        Escrever "Aviso: não foi possível atualizar. O sistema será aberto na versão já instalada." "Yellow"
        Escrever "Motivo informado pelo Git:" "Yellow"
        Escrever $saida "DarkYellow"
    } else {
        $depois = (cmd /c "git rev-parse HEAD 2>nul")
        if ($antes -eq $depois) {
            Escrever "Sistema já está na versão mais recente." "Green"
        } else {
            Escrever "Sistema atualizado:" "Green"
            cmd /c "git log --oneline $antes..$depois"
        }
    }
}

# --- 2. Ambiente Python ---------------------------------------------------------------
$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path ".venv")) {
    Escrever "Criando ambiente Python (.venv) — somente na primeira execução..."
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
    else { Escrever "Erro: Python não encontrado. Instale o Python 3.10 ou superior." "Red"; exit 1 }
}
cmd /c "`"$python`" -c `"pass`" >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Escrever "Erro: o ambiente .venv existe mas não funciona neste computador (provavelmente copiado de outra máquina)." "Red"
    Escrever "Apague a pasta .venv e execute o atalho novamente." "Red"
    exit 1
}

$hashAtual = (Get-FileHash "requirements.txt" -Algorithm SHA256).Hash
$arquivoHash = ".venv\requirements.sha256"
$hashGravado = if (Test-Path $arquivoHash) { (Get-Content $arquivoHash -Raw).Trim() } else { "" }
cmd /c "`"$python`" -c `"import streamlit`" >nul 2>&1"
$streamlitOk = ($LASTEXITCODE -eq 0)
if ($hashAtual -ne $hashGravado -or -not $streamlitOk) {
    Escrever "Instalando/atualizando dependências (requirements.txt)..."
    & $python -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -eq 0) {
        Set-Content -Path $arquivoHash -Value $hashAtual -Encoding ascii
    } elseif ($streamlitOk) {
        Escrever "Aviso: falha ao instalar dependências (sem internet?). Abrindo com as já instaladas." "Yellow"
    } else {
        Escrever "Erro: não foi possível instalar as dependências e o sistema não pode abrir." "Red"
        exit 1
    }
}

# --- 3. Inicialização -----------------------------------------------------------------
if (Sistema-Aberto) {
    Escrever "O sistema já está aberto em $url." "Green"
    if (-not $SemNavegador) { Start-Process $url }
    exit 0
}

if (-not $SemNavegador) {
    # Abre o navegador assim que o servidor responder (até ~90 s).
    Start-Job -ArgumentList $url -ScriptBlock {
        param($u)
        for ($i = 0; $i -lt 90; $i++) {
            try {
                $r = Invoke-WebRequest -Uri "$u/_stcore/health" -UseBasicParsing -TimeoutSec 2
                if ($r.StatusCode -eq 200) { Start-Process $u; return }
            } catch { }
            Start-Sleep -Seconds 1
        }
    } | Out-Null
}

Escrever "Iniciando o sistema em $url — mantenha esta janela aberta; fechá-la encerra o sistema." "Cyan"
& $python -m streamlit run app.py --server.headless true --server.port $Porta
exit $LASTEXITCODE
