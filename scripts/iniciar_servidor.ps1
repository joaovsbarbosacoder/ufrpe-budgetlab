Set-Location "C:\Projetos\ufrpe-budgetlab - Copia"
cmd /c '".\.venv\Scripts\streamlit.exe" run app.py --server.headless true --server.port 8501 > "scripts\streamlit_task.log" 2>&1'
