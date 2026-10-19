# Obtém o runtime oficial do Electron (win32-x64) com o SHA-256 conferido.
# Usado por scripts\build_instalador.ps1 e pelos testes de electron\lib.test.js.
#   . .\scripts\electron_runtime.ps1
#   Obter-Electron -Destino build_instalador\electron
# Sem Node/npm: só o .zip pronto da release oficial (github.com/electron/electron/releases).

$ElectronVersao = "v44.9.0"

function Obter-Electron {
    param(
        [Parameter(Mandatory)][string]$Destino,
        [string]$ShaEsperado = ""   # só para teste de adulteração; padrão: SHASUMS256.txt da release
    )
    $ErrorActionPreference = "Stop"
    $raiz = Split-Path -Parent $PSScriptRoot
    $cache = Join-Path $raiz "build_instalador\cache"
    New-Item -ItemType Directory $cache -Force | Out-Null
    $nome = "electron-$ElectronVersao-win32-x64.zip"
    $base = "https://github.com/electron/electron/releases/download/$ElectronVersao"
    $zip = Join-Path $cache $nome

    if (-not $ShaEsperado) {
        $sums = (Invoke-WebRequest "$base/SHASUMS256.txt" -UseBasicParsing).Content
        if ($sums -is [byte[]]) { $sums = [System.Text.Encoding]::UTF8.GetString($sums) }
        $linha = ($sums -split "`n" | Where-Object { $_ -match [regex]::Escape($nome) } | Select-Object -First 1)
        if (-not $linha) { throw "SHASUMS256.txt não lista $nome." }
        $ShaEsperado = ($linha.Trim() -split "\s+")[0]
    }
    if (-not (Test-Path $zip)) {
        Write-Host "Baixando $nome..."
        Invoke-WebRequest "$base/$nome" -OutFile $zip -UseBasicParsing
    }
    $sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if ($sha -ne $ShaEsperado.ToLower()) {
        Remove-Item $zip -Force
        throw "SHA-256 do Electron diverge do publicado (esperado $ShaEsperado, obtido $sha). Download descartado."
    }
    if (Test-Path $Destino) { Remove-Item $Destino -Recurse -Force }
    Expand-Archive $zip -DestinationPath $Destino
    Rename-Item (Join-Path $Destino "electron.exe") "UFRPE BudgetLab.exe"
    Write-Host "Electron $ElectronVersao pronto em $Destino (SHA-256 conferido)."
}
