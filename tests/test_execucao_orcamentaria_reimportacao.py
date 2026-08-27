"""Testes da reimportação pela interface — página "Atualizar Planilhas", card "Execução
Orçamentária (Execução Anual)" (movida de `app_pages/execucao_orcamentaria.py`, ver
`src/reimportacao_especificacoes.py`).

Constrói variantes do arquivo de referência (um exercício fechado alterado,
um exercício removido, o exercício corrente avançando) para exercitar os
três caminhos do gate de confirmação. Como a reimportação grava de verdade
em `data/manifestos/` e `data/raw/`, cada teste faz backup do estado atual
antes de rodar e restaura tudo em `tearDown` — mesmo que a asserção falhe.

"Atualizar Planilhas" tem mais de um `st.file_uploader` na mesma página (Execução, Dotação,
e as 4 bases sem reimportação versionada) — os testes selecionam o uploader certo pelo rótulo
"Nova extração (.xlsx)" (só as duas seções versionadas usam esse texto) e pela ORDEM de
renderização (Execução antes de Dotação na página, ver `app_pages/atualizar_planilhas.py`),
não por índice absoluto na lista de uploaders da página.

Timeout de `app.run()` em 60s (era 30s antes da consolidação): a página agora varre a pasta
de entrada compartilhada duas vezes por carregamento (uma por base versionada, Execução e
Dotação), não uma só — precisa de mais margem, não é um sinal de teste instável.

Constrói as variantes a partir de uma FIXTURE CONGELADA (2023-2026, `tests/fixtures/
execucao_anual_2026-08-13.xlsx`), não do arquivo realmente ativo em `data/raw/` — composição
por ano (ver `src/importacao_versionada.py`) significa que uma importação real parcial (ex.:
só o exercício corrente) pode ficar ativa por tempo indefinido, o que quebraria a construção
destas variantes se elas dependessem de o ativo ter todos os exercícios no momento em que os
testes rodarem (aconteceu de verdade nesta sessão). Cada teste importa essa fixture como
baseline conhecida no próprio `setUp` — o estado real do sistema antes do teste é salvo e
restaurado do mesmo jeito de sempre, então isso não deixa rastro.
"""

from __future__ import annotations

import io
import shutil
import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.importacao_execucao import Manifesto, importar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIRETORIO_RAW = PROJECT_ROOT / "data/raw"
DIRETORIO_ENTRADA = DIRETORIO_RAW / "_entrada"  # pasta compartilhada por todas as bases
DIRETORIO_MANIFESTOS = PROJECT_ROOT / "data/manifestos"
MANIFESTO_ATUAL = DIRETORIO_MANIFESTOS / "execucao_anual_atual.json"
CAMINHO_FIXTURE = PROJECT_ROOT / "tests/fixtures/execucao_anual_2026-08-13.xlsx"

COL_ANO = 36        # posição 0-indexada da coluna "ano" no arquivo bruto
COL_EMPENHADA = 37  # posição 0-indexada da coluna "empenhada"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _build_variant(
    caminho_base: Path,
    *,
    modificar_ano: int | None = None,
    delta: float | None = None,
    remover_ano: int | None = None,
) -> bytes:
    """Cópia do arquivo de referência com uma alteração pontual e controlada."""

    header = pd.read_excel(caminho_base, header=None, nrows=2, dtype=str)
    data = pd.read_excel(caminho_base, header=None, skiprows=2, dtype=str)

    if remover_ano is not None:
        data = data[data[COL_ANO] != str(remover_ano)].reset_index(drop=True)

    if modificar_ano is not None:
        indice = data.index[data[COL_ANO] == str(modificar_ano)][0]
        atual = float(data.at[indice, COL_EMPENHADA] or 0)
        data.at[indice, COL_EMPENHADA] = str(atual + delta)

    completo = pd.concat([header, data], ignore_index=True)
    buffer = io.BytesIO()
    completo.to_excel(buffer, header=False, index=False, engine="openpyxl")
    return buffer.getvalue()


@unittest.skipUnless(CAMINHO_FIXTURE.exists(), f"Fixture ausente em {CAMINHO_FIXTURE}")
class ReimportacaoPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.variant_retroativo = _build_variant(CAMINHO_FIXTURE, modificar_ano=2023, delta=100_000.0)
        cls.variant_removido = _build_variant(CAMINHO_FIXTURE, remover_ano=2023)
        cls.variant_avanco = _build_variant(CAMINHO_FIXTURE, modificar_ano=2026, delta=100_000.0)

    def setUp(self) -> None:
        self._manifesto_backup = MANIFESTO_ATUAL.read_bytes() if MANIFESTO_ATUAL.exists() else None
        self._raw_antes = set(DIRETORIO_RAW.glob("*.xlsx"))
        self._manifestos_antes = set(DIRETORIO_MANIFESTOS.glob("execucao_anual_*.json"))
        self._importar_baseline()
        # estado logo após a baseline — é contra isso que as asserções de "nada foi gravado"
        # comparam durante o teste (não contra o backup pré-teste: setUp já muda o ponteiro
        # ao importar a baseline, então comparar com o backup original sempre acusaria
        # diferença, mesmo quando o teste não gravou nada por conta própria).
        self._manifesto_baseline = MANIFESTO_ATUAL.read_bytes()

    def _importar_baseline(self) -> None:
        # baseline conhecida (2023-2026) antes de cada teste — não depende de o que já estava
        # ativo (ver docstring do módulo).
        caminho = DIRETORIO_RAW / CAMINHO_FIXTURE.name
        caminho.write_bytes(CAMINHO_FIXTURE.read_bytes())
        resultado = importar(caminho)
        assert resultado.ok, resultado.validacao.erros

    def tearDown(self) -> None:
        if self._manifesto_backup is not None:
            MANIFESTO_ATUAL.write_bytes(self._manifesto_backup)
        else:
            MANIFESTO_ATUAL.unlink(missing_ok=True)
        for novo in set(DIRETORIO_RAW.glob("*.xlsx")) - self._raw_antes:
            novo.unlink(missing_ok=True)
        for novo in set(DIRETORIO_MANIFESTOS.glob("execucao_anual_*.json")) - self._manifestos_antes:
            novo.unlink(missing_ok=True)
        staging = DIRETORIO_RAW / "_staging"
        if staging.exists():
            shutil.rmtree(staging)

    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/atualizar_planilhas.py")
        app.run(timeout=60)
        return app

    def _upload(self, app: AppTest, content: bytes, filename: str) -> None:
        # primeiro uploader com esse rótulo é o da Execução Anual (card renderizado antes do
        # de Dotação — ver docstring do módulo).
        uploader = next(u for u in app.file_uploader if u.label == "Nova extração (.xlsx)")
        uploader.set_value((filename, content, XLSX_MIME))
        app.run(timeout=60)

    def test_retroactive_change_shows_gate_and_blocks_commit_by_default(self) -> None:
        app = self._open_page()
        self._upload(app, self.variant_retroativo, "variant_retroativo.xlsx")

        self.assertEqual(len(app.exception), 0)
        textos = [item.value for item in app.markdown]
        self.assertTrue(any("Exercícios com valores alterados retroativamente" in t for t in textos))
        self.assertTrue(any("2023" in t and "→" in t for t in textos))

        confirmar = next(b for b in app.button if b.label == "Confirmar substituição")
        self.assertTrue(confirmar.disabled)
        self.assertFalse(any(b.label == "Confirmar importação" for b in app.button))

        checkbox = next(c for c in app.checkbox if "confirmo a atualização" in c.label)
        self.assertFalse(checkbox.value)

        # nada deve ter sido gravado só de mostrar a prévia
        self.assertEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_baseline)

    def test_retroactive_change_commits_once_explicitly_confirmed(self) -> None:
        app = self._open_page()
        self._upload(app, self.variant_retroativo, "variant_retroativo.xlsx")

        checkbox = next(c for c in app.checkbox if "confirmo a atualização" in c.label)
        checkbox.check()
        app.run(timeout=60)

        confirmar = next(b for b in app.button if b.label == "Confirmar substituição")
        self.assertFalse(confirmar.disabled)
        confirmar.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertNotEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)
        manifesto_novo = Manifesto.atual()
        self.assertEqual(manifesto_novo.totais_por_ano["2023"]["empenhada"], 762_555_916.88)
        self.assertTrue((DIRETORIO_RAW / manifesto_novo.arquivo).exists())

    def test_removed_exercise_is_informational_and_does_not_block(self) -> None:
        # composição por ano (pedido explícito do usuário): um exercício ausente da extração
        # nova não é mais motivo de gate — só aparece como informação, e o botão "Confirmar
        # importação" (sempre exigido no upload manual, mesmo sem gate) vem habilitado direto.
        app = self._open_page()
        self._upload(app, self.variant_removido, "variant_removido.xlsx")

        self.assertEqual(len(app.exception), 0)
        textos = [item.value for item in app.markdown]
        self.assertTrue(any("não incluídos nesta extração" in t and "2023" in t for t in textos))
        self.assertFalse(any(b.label == "Confirmar substituição" for b in app.button))

        confirmar = next(b for b in app.button if b.label == "Confirmar importação")
        self.assertFalse(confirmar.disabled)
        confirmar.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertNotEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)
        manifesto_novo = Manifesto.atual()
        self.assertNotIn(2023, manifesto_novo.anos)  # não veio NESTA extração

    def test_ongoing_exercise_advance_commits_without_gate(self) -> None:
        app = self._open_page()
        self._upload(app, self.variant_avanco, "variant_avanco.xlsx")

        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any(b.label == "Confirmar substituição" for b in app.button))
        confirmar = next(b for b in app.button if b.label == "Confirmar importação")
        self.assertFalse(confirmar.disabled)

        confirmar.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertNotEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)
        manifesto_novo = Manifesto.atual()
        self.assertEqual(manifesto_novo.arquivo, "variant_avanco.xlsx")
        self.assertEqual(manifesto_novo.totais_por_ano["2026"]["empenhada"], 754_791_351.80)
        self.assertTrue((DIRETORIO_RAW / "variant_avanco.xlsx").exists())

    def test_uploading_identical_file_reports_nothing_to_save(self) -> None:
        manifesto_atual = Manifesto.atual()
        caminho_ativo = DIRETORIO_RAW / manifesto_atual.arquivo
        conteudo_identico = caminho_ativo.read_bytes()

        app = self._open_page()
        self._upload(app, conteudo_identico, manifesto_atual.arquivo)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any("Arquivo idêntico à extração atual" in item.value for item in app.info)
        )
        self.assertFalse(any(b.label in ("Confirmar importação", "Confirmar substituição") for b in app.button))
        self.assertEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_baseline)

    def test_invalid_extraction_is_blocked_and_reports_errors(self) -> None:
        # Linha sem NE CCor -> erro estrutural determinístico em validar(),
        # independente de magnitudes financeiras.
        caminho_ativo = DIRETORIO_RAW / Manifesto.atual().arquivo
        header = pd.read_excel(caminho_ativo, header=None, nrows=2, dtype=str)
        data = pd.read_excel(caminho_ativo, header=None, skiprows=2, dtype=str)
        COL_NE_CCOR = 34
        data.at[0, COL_NE_CCOR] = ""
        completo = pd.concat([header, data], ignore_index=True)
        buffer = io.BytesIO()
        completo.to_excel(buffer, header=False, index=False, engine="openpyxl")

        app = self._open_page()
        self._upload(app, buffer.getvalue(), "variant_invalido.xlsx")

        self.assertEqual(len(app.exception), 0)
        textos_erro = [item.value for item in app.error]
        self.assertTrue(any("bloqueada" in t for t in textos_erro))
        self.assertFalse(any(b.label in ("Confirmar importação", "Confirmar substituição") for b in app.button))
        self.assertEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_baseline)


@unittest.skipUnless(CAMINHO_FIXTURE.exists(), f"Fixture ausente em {CAMINHO_FIXTURE}")
class PastaDeEntradaTests(unittest.TestCase):
    """Detecção automática de arquivo em `data/raw/_entrada/` — pasta única, compartilhada com
    a Dotação Anual (ver docstring de `src/ui_reimportacao.py`); mesmo pipeline de
    validação/gate do upload manual, só a origem do arquivo candidato muda (ver
    `_render_pasta_de_entrada`)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.variant_retroativo = _build_variant(CAMINHO_FIXTURE, modificar_ano=2023, delta=100_000.0)
        cls.variant_avanco = _build_variant(CAMINHO_FIXTURE, modificar_ano=2026, delta=100_000.0)

    def setUp(self) -> None:
        self._manifesto_backup = MANIFESTO_ATUAL.read_bytes() if MANIFESTO_ATUAL.exists() else None
        self._raw_antes = set(DIRETORIO_RAW.glob("*.xlsx"))
        self._manifestos_antes = set(DIRETORIO_MANIFESTOS.glob("execucao_anual_*.json"))
        if DIRETORIO_ENTRADA.exists():
            shutil.rmtree(DIRETORIO_ENTRADA)
        self._importar_baseline()
        # estado logo após a baseline — é contra isso que as asserções de "nada foi gravado"
        # comparam durante o teste (não contra o backup pré-teste: setUp já muda o ponteiro
        # ao importar a baseline, então comparar com o backup original sempre acusaria
        # diferença, mesmo quando o teste não gravou nada por conta própria).
        self._manifesto_baseline = MANIFESTO_ATUAL.read_bytes()

    def _importar_baseline(self) -> None:
        # mesma baseline conhecida de ReimportacaoPageTests — ver docstring do módulo.
        caminho = DIRETORIO_RAW / CAMINHO_FIXTURE.name
        caminho.write_bytes(CAMINHO_FIXTURE.read_bytes())
        resultado = importar(caminho)
        assert resultado.ok, resultado.validacao.erros

    def tearDown(self) -> None:
        if self._manifesto_backup is not None:
            MANIFESTO_ATUAL.write_bytes(self._manifesto_backup)
        else:
            MANIFESTO_ATUAL.unlink(missing_ok=True)
        for novo in set(DIRETORIO_RAW.glob("*.xlsx")) - self._raw_antes:
            novo.unlink(missing_ok=True)
        for novo in set(DIRETORIO_MANIFESTOS.glob("execucao_anual_*.json")) - self._manifestos_antes:
            novo.unlink(missing_ok=True)
        for pasta in (DIRETORIO_RAW / "_staging", DIRETORIO_ENTRADA):
            if pasta.exists():
                shutil.rmtree(pasta)

    def _colocar_na_entrada(self, conteudo: bytes, filename: str) -> None:
        DIRETORIO_ENTRADA.mkdir(parents=True, exist_ok=True)
        (DIRETORIO_ENTRADA / filename).write_bytes(conteudo)

    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/atualizar_planilhas.py")
        app.run(timeout=60)
        return app

    def test_arquivo_seguro_e_aplicado_automaticamente_sem_clique(self) -> None:
        self._colocar_na_entrada(self.variant_avanco, "variant_avanco.xlsx")

        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any(b.label == "Confirmar importação" for b in app.button))
        self.assertFalse(any(b.label == "Confirmar substituição" for b in app.button))
        self.assertNotEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)
        manifesto_novo = Manifesto.atual()
        self.assertEqual(manifesto_novo.arquivo, "variant_avanco.xlsx")
        self.assertEqual(manifesto_novo.totais_por_ano["2026"]["empenhada"], 754_791_351.80)
        # arquivo consumido da pasta de entrada, não deixado para trás
        self.assertFalse((DIRETORIO_ENTRADA / "variant_avanco.xlsx").exists())
        self.assertTrue((DIRETORIO_RAW / "variant_avanco.xlsx").exists())

    def test_arquivo_retroativo_exige_confirmacao_e_fica_parado_na_entrada(self) -> None:
        self._colocar_na_entrada(self.variant_retroativo, "variant_retroativo.xlsx")

        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        confirmar = next(b for b in app.button if b.label == "Confirmar substituição")
        self.assertTrue(confirmar.disabled)
        self.assertEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_baseline)
        # nada foi movido até a confirmação
        self.assertTrue((DIRETORIO_ENTRADA / "variant_retroativo.xlsx").exists())

        checkbox = next(c for c in app.checkbox if "confirmo a atualização" in c.label)
        checkbox.check()
        app.run(timeout=60)
        confirmar = next(b for b in app.button if b.label == "Confirmar substituição")
        confirmar.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertNotEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)
        self.assertFalse((DIRETORIO_ENTRADA / "variant_retroativo.xlsx").exists())
        self.assertTrue((DIRETORIO_RAW / "variant_retroativo.xlsx").exists())

    def test_mais_de_um_arquivo_na_entrada_nao_processa_nada(self) -> None:
        self._colocar_na_entrada(self.variant_avanco, "a.xlsx")
        self._colocar_na_entrada(self.variant_retroativo, "b.xlsx")

        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Há 2 arquivos" in item.value for item in app.warning))
        self.assertEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_baseline)
        self.assertTrue((DIRETORIO_ENTRADA / "a.xlsx").exists())
        self.assertTrue((DIRETORIO_ENTRADA / "b.xlsx").exists())

    def test_arquivo_de_outra_base_na_pasta_compartilhada_e_ignorado(self) -> None:
        # importado aqui, não no topo do arquivo, para deixar explícito que é só usado por
        # este teste específico (constrói uma extração sintética de Dotação Anual válida, só
        # para provar que a Execução Anual não a reconhece como sua).
        from tests.test_dotacao_orcamentaria_reimportacao import _two_years, _workbook_bytes

        arquivo_dotacao = _workbook_bytes(_two_years(1000, 2000))
        self._colocar_na_entrada(arquivo_dotacao, "dotacao_alheia.xlsx")
        self._colocar_na_entrada(self.variant_avanco, "variant_avanco.xlsx")

        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        # só o arquivo reconhecido como Execução Anual é processado — o de Dotação não conta
        # para a checagem de "mais de um arquivo", nem trava nada. Não dá mais pra afirmar
        # "nenhum botão de confirmação em lugar nenhum da página": a partir de "Atualizar
        # Planilhas" (ver módulo), o card de Dotação Anual TAMBÉM varre a mesma pasta de
        # entrada compartilhada e pode legitimamente reconhecer "dotacao_alheia.xlsx" como sua
        # própria extração pendente de confirmação — isso é o comportamento correto do card de
        # Dotação, não um vazamento do teste da Execução. O que importa aqui (que o arquivo da
        # Execução foi processado sozinho, sem travar em nenhum gate) já fica provado pelas
        # asserções de manifesto abaixo.
        self.assertFalse(any("Há" in item.value and "arquivos" in item.value for item in app.warning))
        self.assertNotEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)
        manifesto_novo = Manifesto.atual()
        self.assertEqual(manifesto_novo.arquivo, "variant_avanco.xlsx")
        # o arquivo alheio nunca é tocado — nem movido, nem apagado.
        self.assertTrue((DIRETORIO_ENTRADA / "dotacao_alheia.xlsx").exists())
        self.assertFalse((DIRETORIO_ENTRADA / "variant_avanco.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
