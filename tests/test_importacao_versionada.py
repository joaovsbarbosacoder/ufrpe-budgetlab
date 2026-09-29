"""Testes do núcleo genérico de importação versionada (src/importacao_versionada.py).

Não repete a suíte de `test_execucao_anual.py` (que continua sendo o contrato de regressão
da Execução Anual através de `src/importacao_execucao.py`). Aqui: o comportamento genérico em
si — `comparar`/`exige_confirmacao` com medidas fictícias, tolerância a valores nulos, e a
compatibilidade de `Manifesto.carregar()` com o formato antigo de manifesto (campos de
contagem soltos), que é o ponto mais frágil da extração porque manifestos reais já gravados
em disco usam esse formato.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.importacao_execucao import Manifesto as ManifestoExecucao
from src import importacao_dotacao, importacao_execucao, importacao_execucao_mensal
from src.importacao_versionada import (
    ArquivoHistoricoAusente,
    Manifesto,
    comparar,
    destino_sem_sobrescrever,
    exige_confirmacao,
    manifestos_por_ano,
    nome_ponteiro,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFESTO_REAL_COMMITADO = PROJECT_ROOT / "data" / "manifestos" / "execucao_anual_atual.json"
# Cópia congelada do manifesto real como estava no formato antigo (campos de contagem soltos),
# antes da reimportação que trocou o ponteiro atual para a extração com "Núm. Processo" — o
# ponteiro atual não serve mais como fixture do formato antigo porque toda gravação nova
# (inclusive reimportações de rotina) já usa o formato novo (`contagens` aninhado).
MANIFESTO_FORMATO_ANTIGO = PROJECT_ROOT / "tests" / "fixtures" / "execucao_anual_manifesto_formato_antigo.json"


def _manifesto(sha: str, medidas_por_ano: dict, base: str = "teste") -> Manifesto:
    anos = sorted(int(a) for a in medidas_por_ano)
    medidas = {chave for valores in medidas_por_ano.values() for chave in valores}
    totais = {
        m: round(sum(v[m] for v in medidas_por_ano.values() if v.get(m) is not None), 2)
        for m in medidas
    }
    return Manifesto(
        base=base,
        arquivo="x.xlsx",
        sha256=sha,
        data_extracao="2026-08-11T10:00:00",
        importado_em="2026-08-11T10:00:00",
        anos=anos,
        totais=totais,
        totais_por_ano={str(a): v for a, v in medidas_por_ano.items()},
        contagens={"linhas_fake": 10},
    )


class ManifestoFormatoAntigoTests(unittest.TestCase):
    """O ponto mais frágil do plano: carregar manifesto real já commitado, sem editá-lo."""

    @unittest.skipUnless(
        MANIFESTO_FORMATO_ANTIGO.exists(), f"Fixture ausente em {MANIFESTO_FORMATO_ANTIGO}"
    )
    def test_carrega_manifesto_real_commitado_no_formato_antigo(self) -> None:
        manifesto = Manifesto.carregar(MANIFESTO_FORMATO_ANTIGO)

        self.assertEqual(manifesto.base, "execucao_anual")
        self.assertEqual(manifesto.sha256[:8], "7d09c278")
        self.assertEqual(manifesto.anos, [2023, 2024, 2025, 2026])
        # campos de contagem soltos no JSON (formato antigo) precisam continuar acessíveis
        # pelos mesmos nomes de atributo de sempre, lendo por baixo de `contagens`.
        self.assertEqual(manifesto.linhas, 7779)
        self.assertEqual(manifesto.linhas_empenho, 4092)
        self.assertEqual(manifesto.linhas_item_execucao, 3687)
        self.assertEqual(manifesto.notas_empenho_distintas, 3700)
        self.assertEqual(
            manifesto.contagens,
            {
                "linhas": 7779,
                "linhas_empenho": 4092,
                "linhas_item_execucao": 3687,
                "notas_empenho_distintas": 3700,
            },
        )
        self.assertAlmostEqual(manifesto.totais["empenhada"], 3232327499.34, places=2)

    @unittest.skipUnless(
        MANIFESTO_REAL_COMMITADO.exists(), f"Manifesto ausente em {MANIFESTO_REAL_COMMITADO}"
    )
    def test_manifesto_atual_da_execucao_le_o_mesmo_arquivo_sem_erro(self) -> None:
        # A mesma leitura, mas pelo caminho real que a página usa: ManifestoExecucao.atual()
        # -> Manifesto.atual(base="execucao_anual") -> carregar(). O ponteiro atual já está no
        # formato novo (ver MANIFESTO_FORMATO_ANTIGO acima para o teste de formato legado);
        # aqui só confere que a leitura do ponteiro real não quebra e traz dados plausíveis.
        manifesto = ManifestoExecucao.atual()

        self.assertIsNotNone(manifesto)
        self.assertIsNotNone(manifesto.linhas)
        self.assertGreater(manifesto.linhas, 0)

    def test_construcao_direta_com_campos_soltos_continua_funcionando(self) -> None:
        # Mesmo estilo de chamada que TestDelta._manifesto() usa em test_execucao_anual.py —
        # não pode quebrar, porque aquele teste não pode ser editado.
        manifesto = Manifesto(
            base="execucao_anual",
            arquivo="x.xlsx",
            sha256="a" * 64,
            data_extracao="2026-08-11T10:00:00",
            importado_em="2026-08-11T10:00:00",
            linhas=10,
            linhas_empenho=6,
            linhas_item_execucao=4,
            notas_empenho_distintas=6,
            anos=[2025],
            totais={"empenhada": 1.0},
            totais_por_ano={"2025": {"empenhada": 1.0}},
        )
        self.assertEqual(manifesto.linhas, 10)
        self.assertEqual(manifesto.contagens, {
            "linhas": 10, "linhas_empenho": 6, "linhas_item_execucao": 4, "notas_empenho_distintas": 6,
        })

    def test_argumento_desconhecido_ainda_e_rejeitado(self) -> None:
        with self.assertRaises(TypeError):
            Manifesto(
                base="x", arquivo="x.xlsx", sha256="a" * 64,
                data_extracao="2026-01-01T00:00:00", importado_em="2026-01-01T00:00:00",
                anos=[2025], totais={}, totais_por_ano={},
                campo_que_nao_existe=123,
            )


class ManifestoRoundTripTests(unittest.TestCase):
    """gerar → salvar → carregar → comparar, no formato NOVO (contagens aninhado).

    Complementa test_execucao_anual.py::test_manifesto_carrega_igual_ao_que_foi_salvo, que
    já cobre sha256/totais/data_extracao mas não `contagens`/`.linhas` — e não prova que o
    manifesto escrito por uma importação de verdade grava no formato novo, não no antigo.
    """

    def test_round_trip_preserva_contagens_e_todos_os_campos(self) -> None:
        original = _manifesto(
            "d0d0" * 16,
            {2025: {"indicador": 100.0}, 2026: {"indicador": 50.0}},
            base="teste_round_trip",
        )
        with tempfile.TemporaryDirectory() as tmp:
            caminho = original.salvar(Path(tmp))
            recarregado = Manifesto.carregar(caminho)

            self.assertEqual(recarregado.base, original.base)
            self.assertEqual(recarregado.sha256, original.sha256)
            self.assertEqual(recarregado.data_extracao, original.data_extracao)
            self.assertEqual(recarregado.anos, original.anos)
            self.assertEqual(recarregado.totais, original.totais)
            self.assertEqual(recarregado.totais_por_ano, original.totais_por_ano)
            self.assertEqual(recarregado.contagens, original.contagens)
            self.assertEqual(recarregado.linhas, None)  # esta base fictícia não tem "linhas"

            # o JSON gravado tem que estar no formato NOVO: "contagens" aninhado, nunca
            # campos soltos de contagem no nível raiz.
            bruto = json.loads(caminho.read_text(encoding="utf-8"))
            self.assertIn("contagens", bruto)
            for campo_legado in ("linhas", "linhas_empenho", "linhas_item_execucao", "notas_empenho_distintas"):
                self.assertNotIn(campo_legado, bruto)

    def test_round_trip_de_uma_importacao_real_grava_formato_novo(self) -> None:
        # Prova o caminho de ponta a ponta que a interface usa de verdade: importar() ->
        # gerar_manifesto() -> Manifesto.salvar() -> disco -> Manifesto.atual() -> .linhas.
        from src.importacao_execucao import importar

        caminho_base = Path("data/raw/BI CPOC - EXEC. DESPESAS - Por Ano - com processo.xlsx")
        if not caminho_base.exists():
            self.skipTest(f"Base ausente em {caminho_base}")

        with tempfile.TemporaryDirectory() as tmp:
            resultado = importar(caminho_base, tmp)
            bruto = json.loads(resultado.caminho_manifesto.read_text(encoding="utf-8"))
            self.assertIn("contagens", bruto)
            self.assertNotIn("linhas", bruto)  # não mais solto no nível raiz

            recarregado = ManifestoExecucao.atual(tmp)
            self.assertEqual(recarregado.linhas, resultado.manifesto.linhas)
            self.assertEqual(recarregado.linhas_empenho, resultado.manifesto.linhas_empenho)


class NomePonteiroTests(unittest.TestCase):
    def test_nome_ponteiro_e_parametrizado_por_base(self) -> None:
        self.assertEqual(nome_ponteiro("execucao_anual"), "execucao_anual_atual.json")
        self.assertEqual(nome_ponteiro("dotacao_anual"), "dotacao_anual_atual.json")


class CompararGenericoTests(unittest.TestCase):
    """Mesmo comportamento de tests/test_execucao_anual.py::TestDelta, mas com medidas
    fictícias — prova que `comparar()` não depende mais de nada específico da Execução."""

    def test_primeira_importacao(self) -> None:
        d = comparar(
            None, _manifesto("a" * 64, {2025: {"indicador": 1.0}}), medidas=["indicador"]
        )
        self.assertFalse(d.houve_anterior)

    def test_avanco_do_periodo_corrente_nao_e_retroativo(self) -> None:
        antes = _manifesto("c" * 64, {
            2025: {"indicador": 100.0},
            2026: {"indicador": 50.0},
        })
        depois = _manifesto("d" * 64, {
            2025: {"indicador": 100.0},
            2026: {"indicador": 70.0},
        })
        d = comparar(antes, depois, medidas=["indicador"])
        self.assertEqual(list(d.anos_alterados), [2026])
        self.assertEqual(d.anos_retroativos, [])
        self.assertEqual(d.alertas, [])

    def test_mudanca_retroativa_preenche_anos_retroativos(self) -> None:
        antes = _manifesto("e" * 64, {
            2024: {"indicador": 100.0},
            2025: {"indicador": 100.0},
        })
        depois = _manifesto("f" * 64, {
            2024: {"indicador": 95.0},
            2025: {"indicador": 100.0},
        })
        d = comparar(antes, depois, medidas=["indicador"])
        self.assertEqual(d.anos_retroativos, [2024])
        self.assertTrue(any("retroativ" in a for a in d.alertas))

    def test_valor_nulo_para_numero_e_tratado_como_mudanca(self) -> None:
        antes = _manifesto("1" * 64, {2025: {"indicador": None}})
        depois = _manifesto("2" * 64, {2025: {"indicador": 10.0}})
        d = comparar(antes, depois, medidas=["indicador"])
        self.assertIn(2025, d.anos_alterados)
        self.assertIsNone(d.anos_alterados[2025]["indicador"]["antes"])
        self.assertEqual(d.anos_alterados[2025]["indicador"]["depois"], 10.0)
        self.assertIsNone(d.anos_alterados[2025]["indicador"]["diferenca"])

    def test_valor_nulo_para_nulo_nao_e_mudanca(self) -> None:
        antes = _manifesto("3" * 64, {2025: {"indicador": None}})
        depois = _manifesto("4" * 64, {2025: {"indicador": None}})
        d = comparar(antes, depois, medidas=["indicador"])
        self.assertNotIn(2025, d.anos_alterados)

    def test_resumo_texto_nao_quebra_com_diferenca_nula(self) -> None:
        antes = _manifesto("5" * 64, {2025: {"indicador": None}})
        depois = _manifesto("6" * 64, {2025: {"indicador": 10.0}})
        d = comparar(antes, depois, medidas=["indicador"])
        linhas = d.resumo_texto()
        self.assertTrue(any("2025" in linha for linha in linhas))


class ExigeConfirmacaoTests(unittest.TestCase):
    def test_sem_retroatividade_nem_remocao_nao_exige_gate(self) -> None:
        antes = _manifesto("7" * 64, {2026: {"indicador": 50.0}})
        depois = _manifesto("8" * 64, {2026: {"indicador": 70.0}})
        d = comparar(antes, depois, medidas=["indicador"])
        self.assertIsNone(exige_confirmacao(d))

    def test_retroatividade_exige_gate(self) -> None:
        antes = _manifesto("9" * 64, {2024: {"indicador": 100.0}, 2025: {"indicador": 100.0}})
        depois = _manifesto("A" * 64, {2024: {"indicador": 95.0}, 2025: {"indicador": 100.0}})
        d = comparar(antes, depois, medidas=["indicador"])
        motivo = exige_confirmacao(d)
        self.assertIsNotNone(motivo)
        self.assertEqual(motivo.anos_retroativos, [2024])

    def test_ano_ausente_da_extracao_nova_nao_exige_gate(self) -> None:
        # composição por ano (pedido explícito do usuário): um exercício ausente da extração
        # nova não é motivo de bloqueio — ele continua disponível com o último dado importado
        # (ver `manifestos_por_ano`/`carregar_atual`), não é "perdido" como na substituição
        # total antiga.
        antes = _manifesto("B" * 64, {
            2023: {"indicador": 10.0}, 2024: {"indicador": 10.0},
        })
        depois = _manifesto("C" * 64, {2024: {"indicador": 10.0}})
        d = comparar(antes, depois, medidas=["indicador"])
        self.assertEqual(d.anos_removidos, [2023])  # ainda informativo no Delta
        self.assertIsNone(exige_confirmacao(d))  # mas não gera mais gate


def _manifesto_gravavel(
    sha: str, anos: list[int], importado_em: str, base: str = "teste_composicao"
) -> Manifesto:
    """Igual a `_manifesto`, mas com `importado_em` variável (`_manifesto` fixa sempre o mesmo
    valor, insuficiente pra testar a ordem cronológica que `manifestos_por_ano` resolve)."""
    return Manifesto(
        base=base,
        arquivo=f"{sha}.xlsx",
        sha256=sha,
        data_extracao=importado_em,
        importado_em=importado_em,
        anos=anos,
        totais={},
        totais_por_ano={str(a): {} for a in anos},
    )


class ManifestosPorAnoTests(unittest.TestCase):
    """`manifestos_por_ano` — base de "composição por ano" (ver docstring do módulo): resolve,
    por ano, qual foi o manifesto mais recente (por `importado_em`) que o trouxe."""

    def test_sem_nenhuma_importacao_devolve_vazio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(manifestos_por_ano("base_inexistente", Path(tmp)), {})

    def test_uma_unica_importacao_e_dona_de_todos_os_seus_anos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            m1 = _manifesto_gravavel("1" * 64, [2024, 2025, 2026], "2026-08-01T10:00:00")
            m1.salvar(diretorio)

            resultado = manifestos_por_ano("teste_composicao", diretorio)
            self.assertEqual(set(resultado), {2024, 2025, 2026})
            self.assertTrue(all(m.sha256 == m1.sha256 for m in resultado.values()))

    def test_importacao_parcial_mais_recente_assume_so_os_anos_que_traz(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            m1 = _manifesto_gravavel("1" * 64, [2023, 2024, 2025], "2026-08-01T10:00:00")
            m1.salvar(diretorio)
            m2 = _manifesto_gravavel("2" * 64, [2026], "2026-08-26T10:00:00")
            m2.salvar(diretorio)

            resultado = manifestos_por_ano("teste_composicao", diretorio)
            self.assertEqual(set(resultado), {2023, 2024, 2025, 2026})
            # 2023-2025 continuam com o manifesto antigo — não desapareceram nem foram
            # sobrescritos por uma importação que nunca os trouxe.
            self.assertEqual(resultado[2023].sha256, m1.sha256)
            self.assertEqual(resultado[2024].sha256, m1.sha256)
            self.assertEqual(resultado[2025].sha256, m1.sha256)
            self.assertEqual(resultado[2026].sha256, m2.sha256)

    def test_ano_sobreposto_fica_com_o_manifesto_mais_recente(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            m1 = _manifesto_gravavel("1" * 64, [2025, 2026], "2026-08-01T10:00:00")
            m1.salvar(diretorio)
            # correção retroativa de 2025, publicada depois — mesmo critério de
            # `comparar`/`exige_confirmacao`: importação mais recente vence.
            m2 = _manifesto_gravavel("2" * 64, [2025], "2026-08-26T10:00:00")
            m2.salvar(diretorio)

            resultado = manifestos_por_ano("teste_composicao", diretorio)
            self.assertEqual(resultado[2025].sha256, m2.sha256)
            self.assertEqual(resultado[2026].sha256, m1.sha256)


class ArquivoHistoricoAusenteTests(unittest.TestCase):
    """Ano histórico cujo arquivo de origem sumiu: erro explícito (nunca ano omitido em
    silêncio) e `situacao_historico` somente leitura — nas três bases com composição por ano
    (Execução Anual, Dotação Anual, Execução Mensal). Manifestos fictícios: nenhum xlsx real
    é lido, porque a checagem de existência acontece antes de qualquer leitura."""

    MODULOS = {
        "execucao_anual": importacao_execucao,
        "dotacao_anual": importacao_dotacao,
        "execucao_mensal": importacao_execucao_mensal,
    }

    def _manifesto(self, base: str, sha: str, arquivo: str, anos: list[int]) -> Manifesto:
        return Manifesto(
            base=base, arquivo=arquivo, sha256=sha * 64,
            data_extracao="2026-08-11T10:00:00", importado_em="2026-08-11T10:00:00",
            anos=anos, totais={}, totais_por_ano={}, contagens={},
        )

    def test_carregar_atual_levanta_erro_nomeando_anos_e_arquivo(self) -> None:
        for base, modulo in self.MODULOS.items():
            with self.subTest(base=base), tempfile.TemporaryDirectory() as tmp:
                raiz = Path(tmp)
                raw, manifestos = raiz / "raw", raiz / "manifestos"
                raw.mkdir()
                self._manifesto(base, "a", "historico.xlsx", [2023, 2024]).salvar(manifestos)
                (raw / "corrente.xlsx").write_bytes(b"nao e um xlsx")
                m2 = self._manifesto(base, "b", "corrente.xlsx", [2026])
                m2.importado_em = "2026-09-01T10:00:00"
                m2.salvar(manifestos)

                with self.assertRaises(ArquivoHistoricoAusente) as ctx:
                    modulo.carregar_atual(raw, manifestos)
                mensagem = str(ctx.exception)
                self.assertIn("2023, 2024", mensagem)
                self.assertIn("historico.xlsx", mensagem)
                self.assertNotIn("corrente.xlsx", mensagem)
                self.assertIsInstance(ctx.exception, FileNotFoundError)

    def test_situacao_historico_marca_presenca_por_exercicio_e_nao_grava(self) -> None:
        for base, modulo in self.MODULOS.items():
            with self.subTest(base=base), tempfile.TemporaryDirectory() as tmp:
                raiz = Path(tmp)
                raw, manifestos = raiz / "raw", raiz / "manifestos"
                raw.mkdir()
                self._manifesto(base, "a", "historico.xlsx", [2024]).salvar(manifestos)
                m2 = self._manifesto(base, "b", "corrente.xlsx", [2026])
                m2.importado_em = "2026-09-01T10:00:00"
                m2.salvar(manifestos)
                (raw / "corrente.xlsx").write_bytes(b"x")
                antes = sorted(p.name for p in manifestos.iterdir())

                situacao = modulo.situacao_historico(raw, manifestos)

                self.assertEqual(situacao["exercicio"].tolist(), [2024, 2026])
                self.assertEqual(situacao["arquivo_presente"].tolist(), [False, True])
                self.assertEqual(sorted(p.name for p in manifestos.iterdir()), antes)

    def test_sem_manifesto_carregar_atual_devolve_none_e_situacao_vazia(self) -> None:
        for base, modulo in self.MODULOS.items():
            with self.subTest(base=base), tempfile.TemporaryDirectory() as tmp:
                self.assertIsNone(modulo.carregar_atual(tmp, tmp))
                self.assertTrue(modulo.situacao_historico(tmp, tmp).empty)


class DestinoSemSobrescreverTests(unittest.TestCase):
    """Caso real de 28/09/2026: o navegador reaproveitou o nome "(8).xlsx" num download novo,
    e a reimportação sobrescreveu o arquivo de origem da extração de 22/09 em data/raw/."""

    NOME = "BI CPOC - EXEC. DESPESAS - Por Ano (8).xlsx"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _sha(conteudo: bytes) -> str:
        import hashlib
        return hashlib.sha256(conteudo).hexdigest()

    def test_nome_livre_usa_o_proprio_nome(self):
        destino, ja_existe = destino_sem_sobrescrever(self.diretorio, self.NOME, self._sha(b"novo"))
        self.assertEqual(destino, self.diretorio / self.NOME)
        self.assertFalse(ja_existe)

    def test_mesmo_nome_e_mesmo_conteudo_reaproveita_o_arquivo(self):
        (self.diretorio / self.NOME).write_bytes(b"igual")
        destino, ja_existe = destino_sem_sobrescrever(self.diretorio, self.NOME, self._sha(b"igual"))
        self.assertEqual(destino, self.diretorio / self.NOME)
        self.assertTrue(ja_existe)

    def test_mesmo_nome_com_conteudo_diferente_ganha_nome_unico(self):
        (self.diretorio / self.NOME).write_bytes(b"extracao de 22/09")
        sha_novo = self._sha(b"extracao de 28/09")
        destino, ja_existe = destino_sem_sobrescrever(self.diretorio, self.NOME, sha_novo)
        self.assertEqual(destino.name, f"BI CPOC - EXEC. DESPESAS - Por Ano (8)__{sha_novo[:8]}.xlsx")
        self.assertFalse(ja_existe)
        self.assertEqual((self.diretorio / self.NOME).read_bytes(), b"extracao de 22/09")

    def test_nome_unico_ja_existente_com_mesmo_conteudo_e_reaproveitado(self):
        sha_novo = self._sha(b"extracao de 28/09")
        (self.diretorio / self.NOME).write_bytes(b"extracao de 22/09")
        unico = self.diretorio / f"BI CPOC - EXEC. DESPESAS - Por Ano (8)__{sha_novo[:8]}.xlsx"
        unico.write_bytes(b"extracao de 28/09")
        destino, ja_existe = destino_sem_sobrescrever(self.diretorio, self.NOME, sha_novo)
        self.assertEqual(destino, unico)
        self.assertTrue(ja_existe)

    def test_colisao_improvavel_do_prefixo_usa_o_hash_inteiro(self):
        sha_novo = self._sha(b"extracao de 28/09")
        (self.diretorio / self.NOME).write_bytes(b"extracao de 22/09")
        (self.diretorio / f"BI CPOC - EXEC. DESPESAS - Por Ano (8)__{sha_novo[:8]}.xlsx").write_bytes(b"outro")
        destino, ja_existe = destino_sem_sobrescrever(self.diretorio, self.NOME, sha_novo)
        self.assertEqual(destino.name, f"BI CPOC - EXEC. DESPESAS - Por Ano (8)__{sha_novo}.xlsx")
        self.assertFalse(ja_existe)


if __name__ == "__main__":
    unittest.main(verbosity=2)
