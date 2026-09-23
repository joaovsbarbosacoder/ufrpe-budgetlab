Set-Location (Split-Path -Parent $PSScriptRoot)
# Usa o .venv do projeto quando ele funciona nesta máquina (um .venv copiado de outro
# computador existe mas aponta para um Python inexistente); senão cai no Python do sistema.
$python = ".\.venv\Scripts\python.exe"
$venvOk = $false
if (Test-Path $python) { try { & $python -c "import streamlit" 2>$null; $venvOk = ($LASTEXITCODE -eq 0) } catch { $venvOk = $false } }
if ($venvOk) {
    cmd /c '".\.venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --server.port 8501 > "scripts\streamlit_task.log" 2>&1'
} else {
    cmd /c 'python -m streamlit run app.py --server.headless true --server.port 8501 > "scripts\streamlit_task.log" 2>&1'
}
