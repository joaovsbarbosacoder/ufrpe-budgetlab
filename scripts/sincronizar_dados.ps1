<#
.SYNOPSIS
  Liga as pastas de decisões do usuário (data\...) a uma pasta sincronizada (Google Drive em modo espelho, OneDrive...),
  para que vários dispositivos compartilhem os mesmos dados sem passar pelo Git.

.DESCRIPTION
  Para cada pasta da lista, `data\<pasta>` vira uma JUNÇÃO (atalho de diretório do Windows) para
  `<PastaCompartilhada>\ufrpe-budgetlab-dados\<pasta>`. O sistema não muda nada: continua lendo e gravando em `data\...`.

  Sem `-Aplicar` o script só MOSTRA o que faria (ensaio). Nada é apagado ou sobrescrito:
    * pasta local com dados e pasta compartilhada vazia: copia, confere, guarda a original em
      `data\_antes_da_sincronizacao\<pasta>` e só então cria a junção;
    * pasta local com dados E pasta compartilhada com dados: RECUSA (conflito) — junte as duas à mão;
    * junção já correta: não faz nada (pode rodar de novo).

  Roda em cada dispositivo, apontando para a MESMA pasta compartilhada. Precisa ser executado numa instalação em disco
  local (NTFS); não funciona dentro de uma unidade virtual do Google Drive (G:\Outros computadores\...).

  NÃO entram: planilhas brutas (data\raw), cache (data\processed) e bancos SQLite (TEDs, Captação) — sincronizar arquivo de
  banco por serviço de nuvem pode corromper. Duas máquinas editando o MESMO arquivo ao mesmo tempo: vale a última gravação
  e o serviço pode criar uma "cópia em conflito" (o sistema ignora essa cópia). Os eventos (um JSON por evento) não conflitam.

.PARAMETER PastaCompartilhada
  Pasta local sincronizada, ex.: C:\Users\fulano\Google Drive\UFRPE.

.PARAMETER RaizProjeto
  Raiz do projeto (padrão: a pasta acima de `scripts`).

.PARAMETER Aplicar
  Executa de verdade. Sem ele, é só ensaio.

.EXAMPLE
  .\scripts\sincronizar_dados.ps1 -PastaCompartilhada "C:\Users\fulano\Google Drive\UFRPE"
  .\scripts\sincronizar_dados.ps1 -PastaCompartilhada "C:\Users\fulano\Google Drive\UFRPE" -Aplicar
#>
param(
    [Parameter(Mandatory = $true)][string]$PastaCompartilhada,
    [string]$RaizProjeto = (Split-Path $PSScriptRoot -Parent),
    [switch]$Aplicar
)

$ErrorActionPreference = "Stop"

# Decisões do usuário (cadastros e escolhas gravadas pelo app). Edite aqui para incluir ou tirar pastas.
$pastas = @(
    "resultado_orcamentario",
    "projecao_execucao",
    "projecao_execucao_bolsas",
    "preferencias",
    "limite_empenho",
    "conciliacao_decisoes",
    "contratos_continuos",
    "bolsas_auxilios"
)

function Test-Juncao([string]$caminho) {
    if (-not (Test-Path -LiteralPath $caminho)) { return $false }
    $item = Get-Item -LiteralPath $caminho -Force
    return [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

function Get-Arquivos([string]$caminho) {
    if (-not (Test-Path -LiteralPath $caminho)) { return @() }
    return @(Get-ChildItem -LiteralPath $caminho -Recurse -File -Force)
}

# Dados "de verdade": tudo que não é só o marcador .gitkeep
function Get-ArquivosDeDados([string]$caminho) {
    return @(Get-Arquivos $caminho | Where-Object { $_.Name -ne ".gitkeep" })
}

$dados = Join-Path $RaizProjeto "data"
if (-not (Test-Path -LiteralPath $dados)) { throw "Pasta de dados não encontrada: $dados" }
if (-not (Test-Path -LiteralPath $PastaCompartilhada)) { throw "Pasta compartilhada não encontrada: $PastaCompartilhada" }
$destinoRaiz = Join-Path (Resolve-Path -LiteralPath $PastaCompartilhada).Path "ufrpe-budgetlab-dados"
$guarda = Join-Path $dados "_antes_da_sincronizacao"

Write-Host ""
Write-Host ("Modo: " + $(if ($Aplicar) { "APLICAR" } else { "ENSAIO (nada será alterado; use -Aplicar)" }))
Write-Host "Dados locais:      $dados"
Write-Host "Pasta compartilhada: $destinoRaiz"
Write-Host ""

$resumo = @()
foreach ($nome in $pastas) {
    $local = Join-Path $dados $nome
    $remoto = Join-Path $destinoRaiz $nome

    if (Test-Juncao $local) {
        $alvo = (Get-Item -LiteralPath $local -Force).Target
        if ($alvo -and ((@($alvo)[0]).TrimEnd("\") -ieq $remoto.TrimEnd("\"))) {
            $resumo += "[ok]        $nome (já sincronizada)"
        } else {
            $resumo += "[ATENÇÃO]  $nome já é uma junção para outro lugar ($alvo); nada feito"
        }
        continue
    }

    $locaisComDados = Get-ArquivosDeDados $local
    $remotosComDados = Get-ArquivosDeDados $remoto

    if ($locaisComDados.Count -gt 0 -and $remotosComDados.Count -gt 0) {
        $resumo += "[CONFLITO]  $nome tem dados aqui ($($locaisComDados.Count) arquivo(s)) e na pasta compartilhada ($($remotosComDados.Count)); junte à mão e rode de novo"
        continue
    }

    $acao = if ($locaisComDados.Count -gt 0) { "copiar $($locaisComDados.Count) arquivo(s) para a pasta compartilhada e ligar" }
            elseif ($remotosComDados.Count -gt 0) { "usar os $($remotosComDados.Count) arquivo(s) da pasta compartilhada e ligar" }
            else { "ligar (pasta vazia)" }

    if (-not $Aplicar) {
        $resumo += "[ensaio]    $nome : $acao"
        continue
    }

    New-Item -ItemType Directory -Force -Path $remoto | Out-Null
    if (Test-Path -LiteralPath $local) {
        if ($locaisComDados.Count -gt 0) {
            Copy-Item -Path (Join-Path $local "*") -Destination $remoto -Recurse -Force
            # confere antes de mexer na original: mesmos arquivos, mesmos tamanhos
            foreach ($arquivo in (Get-Arquivos $local)) {
                $relativo = $arquivo.FullName.Substring($local.Length).TrimStart("\")
                $copia = Join-Path $remoto $relativo
                if (-not (Test-Path -LiteralPath $copia) -or ((Get-Item -LiteralPath $copia).Length -ne $arquivo.Length)) {
                    throw "Cópia de '$relativo' não confere; nada foi alterado em $local"
                }
            }
        }
        New-Item -ItemType Directory -Force -Path $guarda | Out-Null
        $carimbo = Get-Date -Format "yyyyMMdd-HHmmss"
        Move-Item -LiteralPath $local -Destination (Join-Path $guarda "$nome-$carimbo")
    }
    New-Item -ItemType Junction -Path $local -Target $remoto | Out-Null
    $resumo += "[feito]     $nome : $acao"
}

$resumo | ForEach-Object { Write-Host $_ }
Write-Host ""
if ($Aplicar) {
    Write-Host "As pastas originais ficaram em $guarda (pode apagar depois de conferir)."
    Write-Host "Reinicie o sistema para ele reler os dados."
}
