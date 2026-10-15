"""Teste de página do Resultado Orçamentário (08/10/2026).

Usa as bases reais já importadas (Dotação Anual, Execução Mensal, cadastros de Contratos Contínuos e de
Bolsas e Auxílios, Liquidação por Competência), como `tests/test_cadastros_layout_page.py` — pulado se a
Dotação ou a Execução Mensal não tiverem sido importadas. A persistência da página (seleção de células e
despesas manuais) vai para `tmp_path`, via monkeypatch de `DIRETORIO_PADRAO`: o teste nunca grava em
`data/resultado_orcamentario/`. A regra da conta tem testes próprios (`tests/test_resultado_orcamentario.py`);
aqui só se confere que a tela abre, grava a seleção e inclui uma despesa manual.

A seleção de células usa uma caixa de marcar por célula (`ro_cel_<exercício>_<índice>`), agrupadas por
Ação com "Marcar todas" (`ro_todas_<exercício>_<ação>`) — layout de 08/10/2026.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import resultado_orcamentario_cadastro as cadastro
from tests._apptest import TEMPO_LIMITE_APPTEST, aquecer_pagina

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGINA = PROJECT_ROOT / "app_pages" / "resultado_orcamentario.py"
MANIFESTOS = (
    PROJECT_ROOT / "data" / "manifestos" / "dotacao_anual_atual.json",
    PROJECT_ROOT / "data" / "manifestos" / "execucao_mensal_atual.json",
)

pytestmark = pytest.mark.skipif(
    not all(caminho.exists() for caminho in MANIFESTOS),
    reason="Dotação Anual ou Execução Mensal não importadas neste ambiente.",
)


@pytest.fixture(scope="module", autouse=True)
def _aquecer() -> None:
    # 1ª carga lê as bases reais (lenta a frio): aquece uma vez, fora dos testes cronometrados
    if PAGINA.exists():
        aquecer_pagina(str(PAGINA))


@pytest.fixture
def diretorio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cadastro, "DIRETORIO_PADRAO", tmp_path)
    return tmp_path


def _abrir() -> AppTest:
    app = AppTest.from_file(str(PAGINA), default_timeout=TEMPO_LIMITE_APPTEST)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _textos(app: AppTest) -> str:
    blocos = [*app.markdown, *app.caption, *app.info, *app.warning, *app.error, *app.success]
    return "\n".join(str(bloco.value) for bloco in blocos)


def _exercicio(app: AppTest) -> int:
    return int(app.selectbox(key="ro_exercicio").value)


def test_pagina_abre_sem_excecao(diretorio: Path) -> None:
    app = _abrir()
    assert not app.exception
    assert any(titulo.value == "Resultado Orçamentário" for titulo in app.title)


def test_secao_sobra_prevista_de_empenho_com_botao_de_download(diretorio: Path) -> None:
    """15/10/2026: a seção 7 mostra o resumo da sobra prevista e oferece o Excel; independe das células marcadas."""

    app = _abrir()
    assert any(sub.value == "7. Sobra prevista de empenho" for sub in app.subheader)
    textos = _textos(app)
    assert "NE(s) com sobra prevista" in textos or "Indisponível: a projeção pela execução" in textos
    if "Indisponível: a projeção pela execução" not in textos:
        # com a projeção montada: resumo com a linha TOTAL e o botão do relatório
        assert any(
            "TOTAL" in df.value.astype(str).to_numpy().ravel().tolist() for df in app.dataframe
            if "Sobra prevista (R$)" in df.value.columns
        )
        assert any(botao.key == "ro_baixar_sobra" for botao in app.get("download_button"))


def _html(app: AppTest) -> str:
    return "\n".join(str(elemento.proto.body) for elemento in app.get("html"))


def test_cartoes_e_composicao_no_criterio_executado_projetado(diretorio: Path) -> None:
    """15/10/2026: o resultado mede o executado e o projetado a realizar; a anulação sugerida deixou de ser receita. Com
    todas as células marcadas nenhuma NE de Contratos/Bolsas fica fora da conta."""

    app = _abrir()
    exercicio = _exercicio(app)
    for botao in [b for b in app.button if b.key and b.key.startswith(f"ro_todas_{exercicio}_")]:
        app.button(key=botao.key).click().run()
        assert not app.exception, [e.value for e in app.exception]
    html = _html(app)
    if "Indisponível: a projeção pela execução" in _textos(app):
        pytest.skip("Projeção pela execução indisponível neste ambiente")
    assert "(−) Executado nas células" in html and "(−) Projetado a realizar" in html
    assert "Executado nas células selecionadas" in html and "Projetado a realizar até dezembro" in html
    assert "Total executado" in html and "Total projetado" in html
    assert "Anulação sugerida" not in html and "(−) Necessidade" not in html
    assert not any("sem empenho nas células marcadas" in a.value for a in app.warning)


def test_ne_fora_das_celulas_marcadas_e_avisada_com_valor(diretorio: Path) -> None:
    """Marcada só a primeira célula, as NEs de Contratos/Bolsas que estão em outras células saem da conta e são avisadas."""

    app = _abrir()
    exercicio = _exercicio(app)
    app.checkbox(key=f"ro_cel_{exercicio}_0").check().run()
    assert not app.exception, [e.value for e in app.exception]
    if "Indisponível: a projeção pela execução" in _textos(app):
        pytest.skip("Projeção pela execução indisponível neste ambiente")
    assert any("sem empenho nas células marcadas ficam fora da conta" in a.value for a in app.warning)


def test_sem_selecao_mostra_mensagem(diretorio: Path) -> None:
    app = _abrir()
    assert "Nenhuma célula selecionada" in _textos(app)


def test_salvar_selecao_grava_arquivo(diretorio: Path) -> None:
    app = _abrir()
    exercicio = _exercicio(app)
    app.checkbox(key=f"ro_cel_{exercicio}_0").check().run()
    assert not app.exception, [e.value for e in app.exception]
    assert "Alterações não salvas" in _textos(app)
    app.button(key="ro_salvar_selecao").click().run()
    assert not app.exception, [e.value for e in app.exception]

    arquivo = diretorio / str(exercicio) / "celulas.json"
    assert arquivo.exists()
    assert len(json.loads(arquivo.read_text(encoding="utf-8"))["celulas"]) == 1


def test_marcar_todas_e_filtro_de_selecionadas(diretorio: Path) -> None:
    app = _abrir()
    exercicio = _exercicio(app)
    botao = next(b for b in app.button if b.key and b.key.startswith(f"ro_todas_{exercicio}_"))
    acao = botao.key.removeprefix(f"ro_todas_{exercicio}_")
    botao.click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert app.button(key=f"ro_todas_{exercicio}_{acao}").label == "Desmarcar todas"
    # o filtro esconde as outras ações, mas a seleção feita continua valendo
    app.checkbox(key="ro_so_selecionadas").check().run()
    assert not app.exception, [e.value for e in app.exception]
    chaves_todas = {b.key for b in app.button if b.key and b.key.startswith(f"ro_todas_{exercicio}_")}
    assert chaves_todas == {f"ro_todas_{exercicio}_{acao}"}


def test_filtro_so_selecionadas_sobrevive_a_atualizacao(diretorio: Path) -> None:
    app = _abrir()
    assert app.checkbox(key="ro_so_selecionadas").value is False
    app.checkbox(key="ro_so_selecionadas").check().run()
    assert not app.exception, [e.value for e in app.exception]
    assert json.loads((diretorio / "preferencias.json").read_text(encoding="utf-8"))["so_selecionadas"] is True
    # atualizar a página = sessão nova
    nova = _abrir()
    assert nova.checkbox(key="ro_so_selecionadas").value is True
    nova.checkbox(key="ro_so_selecionadas").uncheck().run()
    assert _abrir().checkbox(key="ro_so_selecionadas").value is False


def test_celulas_recolhidas_por_padrao(diretorio: Path) -> None:
    app = _abrir()
    rotulos = {"Ver células", "Ver célula"}
    expansores = [e for e in app.expander if e.label in rotulos]
    assert expansores and not any(e.proto.expanded for e in expansores)


def test_incluir_despesa_manual(diretorio: Path) -> None:
    app = _abrir()
    exercicio = _exercicio(app)
    app.text_input(key="ro_despesa_descricao").input("Teste")
    app.number_input(key="ro_despesa_valor").set_value(100.0)
    app.button(key="FormSubmitter:ro_nova_despesa-Incluir").click().run()
    assert not app.exception, [e.value for e in app.exception]

    arquivo = diretorio / str(exercicio) / "despesas_manuais.json"
    assert arquivo.exists()
    despesas = json.loads(arquivo.read_text(encoding="utf-8"))["despesas"]
    assert len(despesas) == 1
    assert despesas[0]["descricao"] == "Teste"
    assert despesas[0]["valor"] == 100.0

    # lista em linhas, com Editar/Excluir por despesa (layout do protótipo, 08/10/2026)
    assert any(bloco.value == "Teste" for bloco in app.markdown)
    assert app.button(key=f"ro_editar_{despesas[0]['id']}") is not None
    assert app.button(key=f"ro_excluir_{despesas[0]['id']}") is not None


def test_menu_tem_pagina(diretorio: Path) -> None:
    texto = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    assert '"app_pages/resultado_orcamentario.py"' in texto
    assert 'title="Resultado Orçamentário"' in texto

    # mesmo padrão de `tests/test_home_page.py`: abre o app pelo menu e troca para a página
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TEMPO_LIMITE_APPTEST)
    app.run()
    app.switch_page("app_pages/resultado_orcamentario.py")
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert any(titulo.value == "Resultado Orçamentário" for titulo in app.title)


def test_historico_sem_selecao_nao_grava_e_avisa(diretorio: Path) -> None:
    app = _abrir()
    assert any("Histórico do resultado" in s.value for s in app.subheader)
    assert "Ainda não há fotografias" in _textos(app)
    assert not list(diretorio.glob("*/historico/*.json"))


def test_historico_grava_fotografia_so_com_selecao_salva(diretorio: Path) -> None:
    app = _abrir()
    exercicio = _exercicio(app)
    # marcar sem salvar: a seleção em edição não vira história
    app.checkbox(key=f"ro_cel_{exercicio}_0").check().run()
    assert not app.exception, [e.value for e in app.exception]
    assert not list(diretorio.glob("*/historico/*.json"))
    # salvar: a próxima execução grava a fotografia do dia
    app.button(key="ro_salvar_selecao").click().run()
    assert not app.exception, [e.value for e in app.exception]
    arquivos = list((diretorio / str(exercicio) / "historico").glob("*.json"))
    assert len(arquivos) == 1
    foto = json.loads(arquivos[0].read_text(encoding="utf-8"))
    assert foto["exercicio"] == exercicio and foto["celulas_marcadas"] == 1
    assert "Ainda não há fotografias" not in _textos(app)
    assert "Há só uma fotografia" in _textos(app)


def test_historico_arquivo_corrompido_avisa_e_nao_sobrescreve(diretorio: Path) -> None:
    app = _abrir()
    exercicio = _exercicio(app)
    pasta = diretorio / str(exercicio) / "historico"
    pasta.mkdir(parents=True)
    (pasta / "2026-01-01.json").write_text("{quebrado", encoding="utf-8")
    app.checkbox(key=f"ro_cel_{exercicio}_0").check().run()
    app.button(key="ro_salvar_selecao").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert "O histórico não pôde ser lido" in "\n".join(str(e.value) for e in app.error)
    assert (pasta / "2026-01-01.json").read_text(encoding="utf-8") == "{quebrado"
    assert len(list(pasta.glob("*.json"))) == 1


def test_historico_com_duas_fotografias_mostra_o_que_levou_a_alteracao(diretorio: Path) -> None:
    from src import resultado_orcamentario_historico as historico_ro

    app = _abrir()
    exercicio = _exercicio(app)
    antiga = historico_ro.Fotografia(
        data="2026-01-01", exercicio=exercicio, resultado=100.0, incompleto=False, dotacao=500.0,
        empenhado={"Contratos Contínuos": 250.0}, empenhado_total=250.0,
        necessidade={"Contratos Contínuos": 150.0}, celulas_marcadas=1,
    )
    historico_ro.registrar(antiga, diretorio)
    app.checkbox(key=f"ro_cel_{exercicio}_0").check().run()
    app.button(key="ro_salvar_selecao").click().run()
    assert not app.exception, [e.value for e in app.exception]
    seletor = app.selectbox(key="ro_historico_periodo")
    assert seletor.value.startswith("2026-01-01 → ")
    assert "Variação do resultado" in _textos(app) or "não é calculável" in _textos(app)


def _semear_fotografia_antiga(diretorio: Path, exercicio: int, detalhe) -> None:
    from src import resultado_orcamentario_historico as historico_ro

    historico_ro.registrar(
        historico_ro.Fotografia(
            data="2026-01-01", exercicio=exercicio, resultado=100.0, incompleto=False, dotacao=500.0,
            empenhado={"Contratos Contínuos": 250.0}, empenhado_total=250.0,
            necessidade={"Contratos Contínuos": 150.0}, celulas_marcadas=0, dotacao_por_celula=detalhe,
        ),
        diretorio,
    )


def test_historico_sem_detalhe_por_celula_avisa_que_esta_indisponivel(diretorio: Path) -> None:
    app = _abrir()
    exercicio = _exercicio(app)
    _semear_fotografia_antiga(diretorio, exercicio, None)
    app.checkbox(key=f"ro_cel_{exercicio}_0").check().run()
    app.button(key="ro_salvar_selecao").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert "Detalhe da dotação por célula indisponível" in _textos(app)


def test_historico_com_detalhe_mostra_celula_marcada_que_moveu_a_dotacao(diretorio: Path) -> None:
    app = _abrir()
    exercicio = _exercicio(app)
    _semear_fotografia_antiga(diretorio, exercicio, {})  # detalhe existe, mas nenhuma célula estava marcada
    app.checkbox(key=f"ro_cel_{exercicio}_0").check().run()
    app.button(key="ro_salvar_selecao").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert "Células que moveram a dotação" in _textos(app)
    fotos = list((diretorio / str(exercicio) / "historico").glob("*.json"))
    hoje = next(json.loads(f.read_text(encoding="utf-8")) for f in fotos if f.stem != "2026-01-01")
    assert len(hoje["dotacao_por_celula"]) == 1  # a célula marcada, com a chave dos 7 códigos


# ------------------------------------------------------------ outras despesas, uma a uma (15/10/2026)
OUTRAS = "Outras despesas previstas"


def _incluir_despesa(app: AppTest, valor: float = 100.0, descricao: str = "Reagentes") -> None:
    app.text_input(key="ro_despesa_descricao").input(descricao)
    app.number_input(key="ro_despesa_valor").set_value(valor)
    app.button(key="FormSubmitter:ro_nova_despesa-Incluir").click().run()
    assert not app.exception, [e.value for e in app.exception]


def _com_selecao_salva(app: AppTest) -> int:
    exercicio = _exercicio(app)
    app.checkbox(key=f"ro_cel_{exercicio}_0").check().run()
    app.button(key="ro_salvar_selecao").click().run()
    assert not app.exception, [e.value for e in app.exception]
    return exercicio


def _foto_do_dia(diretorio: Path, exercicio: int) -> dict:
    arquivos = list((diretorio / str(exercicio) / "historico").glob("*.json"))
    assert len(arquivos) == 1
    return json.loads(arquivos[0].read_text(encoding="utf-8"))


def _caixas_considerar(app: AppTest) -> list:
    return [c for c in app.checkbox if c.key and c.key.startswith("ro_considerar_")]


def test_cada_despesa_tem_a_sua_caixa_considerar_marcada_e_nao_ha_interruptor_do_grupo(diretorio: Path) -> None:
    app = _abrir()
    assert not [t for t in app.toggle if t.key == "ro_considerar_outras"]
    _incluir_despesa(app, 100.0, "Reagentes")
    _incluir_despesa(app, 50.0, "Bancadas")
    caixas = _caixas_considerar(app)
    assert len(caixas) == 2 and all(c.value is True for c in caixas)


def test_desmarcar_uma_despesa_tira_so_ela_da_conta_avisa_e_fica_gravado(diretorio: Path) -> None:
    app = _abrir()
    _incluir_despesa(app, 100.0, "Reagentes")
    _incluir_despesa(app, 50.0, "Bancadas")
    exercicio = _com_selecao_salva(app)
    ligado = _foto_do_dia(diretorio, exercicio)
    assert ligado["necessidade"][OUTRAS] == 150.0 and ligado["outras_despesas_consideradas"] is True

    despesas = cadastro.carregar_despesas(exercicio, diretorio)
    reagentes = next(d for d in despesas if d.descricao == "Reagentes")
    app.checkbox(key=f"ro_considerar_{reagentes.id}").uncheck().run()
    assert not app.exception, [e.value for e in app.exception]

    depois = {d.descricao: d for d in cadastro.carregar_despesas(exercicio, diretorio)}
    assert depois["Reagentes"].considerada is False and depois["Bancadas"].considerada is True  # gravado, só ela
    assert depois["Reagentes"].atualizado_em == reagentes.atualizado_em  # não é edição do cadastro
    assert "SEM 1 de 2 outras despesas previstas" in _textos(app)
    assert any(bloco.value == "Reagentes" for bloco in app.markdown)  # continua listada e editável
    foto = _foto_do_dia(diretorio, exercicio)
    assert foto["necessidade"][OUTRAS] == 50.0
    assert foto["outras_despesas_consideradas"] is False
    assert foto["outras_despesas_ignoradas_qtd"] == 1 and foto["outras_despesas_ignoradas_valor"] == 100.0
    if ligado["resultado"] is not None and foto["resultado"] is not None:
        assert foto["resultado"] - ligado["resultado"] == pytest.approx(100.0)  # só a despesa desmarcada deixou de pesar


def test_a_escolha_sobrevive_a_uma_nova_sessao_e_remarcar_volta_a_conta(diretorio: Path) -> None:
    app = _abrir()
    _incluir_despesa(app, 100.0)
    exercicio = _com_selecao_salva(app)
    despesa = cadastro.carregar_despesas(exercicio, diretorio)[0]
    app.checkbox(key=f"ro_considerar_{despesa.id}").uncheck().run()

    nova_sessao = _abrir()  # F5: sessão nova, a escolha vem do arquivo
    assert nova_sessao.checkbox(key=f"ro_considerar_{despesa.id}").value is False
    nova_sessao.checkbox(key=f"ro_considerar_{despesa.id}").check().run()
    assert not nova_sessao.exception, [e.value for e in nova_sessao.exception]
    religado = _foto_do_dia(diretorio, exercicio)
    assert religado["outras_despesas_consideradas"] is True and religado["necessidade"][OUTRAS] == 100.0
    assert religado["outras_despesas_ignoradas_qtd"] == 0


def test_tabela_do_historico_mostra_a_coluna_e_a_comparacao_avisa_a_virada(diretorio: Path) -> None:
    from src import resultado_orcamentario_historico as historico_ro

    app = _abrir()
    _incluir_despesa(app, 100.0)
    exercicio = _exercicio(app)
    historico_ro.registrar(
        historico_ro.Fotografia(
            data="2026-01-01", exercicio=exercicio, resultado=100.0, incompleto=False, dotacao=500.0,
            empenhado={"Contratos Contínuos": 250.0}, empenhado_total=250.0,
            necessidade={"Contratos Contínuos": 150.0, OUTRAS: 40.0}, celulas_marcadas=1,
            outras_despesas_consideradas=True,
        ),
        diretorio,
    )
    app.checkbox(key=f"ro_cel_{exercicio}_0").check().run()
    despesa = cadastro.carregar_despesas(exercicio, diretorio)[0]
    app.checkbox(key=f"ro_considerar_{despesa.id}").uncheck().run()
    app.button(key="ro_salvar_selecao").click().run()
    assert not app.exception, [e.value for e in app.exception]
    colunas = [c for df in app.dataframe for c in df.value.columns]
    assert "Outras despesas" in colunas
    assert "consideradas → 1 desconsiderada(s)" in _textos(app)


def test_com_todas_marcadas_a_conta_e_a_de_antes(diretorio: Path) -> None:
    app = _abrir()
    _incluir_despesa(app, 100.0)
    exercicio = _com_selecao_salva(app)
    assert _foto_do_dia(diretorio, exercicio)["necessidade"][OUTRAS] == 100.0
