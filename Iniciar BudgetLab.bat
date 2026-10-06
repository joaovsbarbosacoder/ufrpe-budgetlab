@echo off
rem Atalho de duplo clique: atualiza o codigo pelo GitHub e inicia o UFRPE BudgetLab.
rem Ver scripts\atualizar_e_iniciar.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\atualizar_e_iniciar.ps1" %*
if errorlevel 1 pause
