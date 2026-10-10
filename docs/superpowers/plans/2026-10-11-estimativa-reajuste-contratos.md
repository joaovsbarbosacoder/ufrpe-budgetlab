# Estimativa de reajuste de contratos — plano

**Spec:** `docs/superpowers/specs/2026-10-11-estimativa-reajuste-contratos-design.md`. Branch `feat/estimativa-reajuste-contratos`.
Execução nativa, TDD; testes sem rede (cliente BCB injetável). `pytest -n 4` no máximo.

## Tarefas

1. **`src/indices_economicos.py`** (+ `tests/test_indices_economicos.py`): `ErroIndiceEconomico`; `SERIES_BCB = {"IPCA": 433, "INPC": 188, "IGPM": 189}`;
   `variacoes_bcb(indice, inicio, fim, *, buscar=None) -> dict[tuple[int,int], float]` (buscar injetável; falha → erro);
   `acumulado_12m(variacoes, ano, mes) -> tuple[float|None, str]` (12 meses anteriores; origem `oficial` | `oficial_ultimo` | `ausente`).
2. **`src/estimativa_reajuste.py`** (+ `tests/test_estimativa_reajuste.py`): `datas_base`, `percentual_do_ciclo`,
   `estimar_contrato`, `resumo_por_contrato`, `aditivo_previsto_do_ciclo`; valores esperados calculados à mão.
3. **Cadastro**: três campos em `CAMPOS_IDENTIDADE` (+ teste no `test_contratos_continuos_cadastro.py`).
4. **`src/ui_reajuste.py`** + chamada em `app_pages/contratos_continuos.py` (+ teste AppTest): matriz, resumo, edição, promoção, Excel.
5. **Documentação e regressão**: README, suíte completa, commit.

Cada tarefa termina com testes verdes e commit (`Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`).
