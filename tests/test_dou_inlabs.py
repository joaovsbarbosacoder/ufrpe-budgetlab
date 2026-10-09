"""Testes de src/dou_inlabs.py — leitura dos XML do INLABS, filtro por termos e download.

A fixture `tests/fixtures/dou_inlabs_sintetico.xml` é SINTÉTICA (formato do INLABS, conteúdo
inventado): três matérias — um extrato de contrato da UFRPE (nome por extenso + UASG 153165),
uma portaria da SOF que cita só a UO 26248 (e traz um atributo e um filho de `<body>` fora do
esquema), e um aviso da UFPE com armadilhas (UASG 1531650, "ufrpex", data inválida).
Nenhum teste acessa a rede nem usa credencial real.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd
import requests

from src.dou_inlabs import (
    ARQUIVO_MANIFESTO,
    COLUNAS,
    COOKIE_SESSAO,
    TERMOS_UFRPE_PADRAO,
    VARIAVEL_EMAIL,
    VARIAVEL_SENHA,
    ClienteInlabs,
    ErroInlabs,
    baixar_dia,
    credenciais_do_ambiente,
    filtrar_por_termos,
    ARQUIVO_TERMOS,
    arquivos_baixados,
    atualizar,
    carregar_termos,
    salvar_termos,
    dias_baixados,
    dias_pendentes,
    ler_e_filtrar_zip,
    ler_xml,
    ler_zip,
    limpar_termos,
    main,
    normalizar_texto,
)

FIXTURE = Path(__file__).parent / "fixtures" / "dou_inlabs_sintetico.xml"


def _zip(diretorio: Path, nome: str = "2026-10-08-DO3.zip") -> Path:
    caminho = diretorio / nome
    with zipfile.ZipFile(caminho, "w") as arquivo:
        arquivo.writestr("materias/sintetico.xml", FIXTURE.read_bytes())
        arquivo.writestr("materias/imagem.jpg", b"\xff\xd8 nao-xml")
    return caminho


def _resposta(status: int, conteudo: bytes = b"") -> mock.Mock:
    resposta = mock.Mock()
    resposta.status_code = status
    resposta.content = conteudo
    return resposta


class LeituraXmlTest(unittest.TestCase):
    def setUp(self):
        self.registros = ler_xml(FIXTURE.read_bytes(), "a.zip", "m.xml")

    def test_le_todas_as_materias_com_origem(self):
        self.assertEqual([r["id"] for r in self.registros], ["40000001", "40000002", "40000003"])
        self.assertTrue(all(r["arquivo_origem"] == "a.zip" and r["membro_origem"] == "m.xml" for r in self.registros))
        self.assertEqual(set(self.registros[0]), set(COLUNAS))

    def test_campos_conhecidos(self):
        r = self.registros[0]
        self.assertEqual(r["pub_name"], "DO3")
        self.assertEqual(r["art_type"], "Extrato de Contrato")
        self.assertEqual(r["identifica"], "EXTRATO DE CONTRATO Nº 12/2026 - UASG 153165")
        self.assertIn("R$ 1.234.567,89", r["texto"])  # texto original, com HTML, intacto
        self.assertIn('<p class="assina">', r["texto"])
        self.assertNotIn("&amp;", r["pdf_page"])  # entidade XML resolvida
        self.assertIn("&jornal=530", r["pdf_page"])

    def test_ids_sao_texto_com_zeros_preservados(self):
        self.assertEqual(self.registros[0]["id_materia"], "0000001")
        self.assertIsInstance(self.registros[0]["id"], str)

    def test_vazio_diferente_de_ausente(self):
        r = self.registros[0]
        self.assertEqual(r["data"], "")  # elemento presente sem conteúdo
        self.assertEqual(r["ementa"], "")
        sem_corpo = ler_xml(b'<xml><article id="9" pubDate="01/01/2026"/></xml>')[0]
        self.assertIsNone(sem_corpo["ementa"])  # elemento ausente
        self.assertIsNone(sem_corpo["name"])

    def test_extras_preservados(self):
        r = self.registros[1]
        self.assertEqual(r["atributos_extras"], {"atributoNovo": "valor-preservado"})
        self.assertEqual(r["corpo_extras"], {"Anexo": "conteúdo fora do esquema"})

    def test_data_publicacao(self):
        self.assertEqual(self.registros[0]["data_publicacao"], date(2026, 10, 8))
        self.assertIsNone(self.registros[2]["data_publicacao"])
        self.assertEqual(self.registros[2]["pub_date"], "data-invalida")  # original mantido

    def test_article_como_raiz(self):
        registros = ler_xml(b'<article id="7" pubName="DO1"><body><Ementa>x</Ementa></body></article>')
        self.assertEqual([(r["id"], r["ementa"]) for r in registros], [("7", "x")])

    def test_xml_invalido(self):
        with self.assertRaisesRegex(ErroInlabs, "XML inválido em z.zip:m.xml"):
            ler_xml(b"<xml><article>", "z.zip", "m.xml")


class LeituraZipTest(unittest.TestCase):
    def test_le_xml_do_zip_sem_alterar_o_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _zip(Path(tmp))
            antes = hashlib.sha256(caminho.read_bytes()).hexdigest()
            df = ler_zip(caminho)
            self.assertEqual(hashlib.sha256(caminho.read_bytes()).hexdigest(), antes)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [caminho.name])  # nada extraído
        self.assertEqual(len(df), 3)  # o .jpg é ignorado
        self.assertEqual(list(df.columns), COLUNAS)
        self.assertEqual(set(df["arquivo_origem"]), {"2026-10-08-DO3.zip"})
        self.assertEqual(set(df["membro_origem"]), {"materias/sintetico.xml"})


class FiltroTest(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame(ler_xml(FIXTURE.read_bytes()), columns=COLUNAS)

    def test_normalizar_texto(self):
        self.assertEqual(normalizar_texto("<p>LICITAÇÃO&nbsp;  Pública</p>"), "licitacao publica")
        self.assertEqual(normalizar_texto(None), "")

    def test_termos_padrao(self):
        achadas = filtrar_por_termos(self.df)
        self.assertEqual(list(achadas["id"]), ["40000001", "40000002"])
        self.assertEqual(
            achadas.iloc[0]["termos_encontrados"],
            ("Universidade Federal Rural de Pernambuco", "153165"),
        )
        self.assertEqual(achadas.iloc[1]["termos_encontrados"], ("26248",))

    def test_sem_acento_e_sem_caixa(self):
        com = filtrar_por_termos(self.df, ["licitação"])
        sem = filtrar_por_termos(self.df, ["LICITACAO"])
        self.assertEqual(list(com["id"]), ["40000003"])
        self.assertEqual(list(sem["id"]), ["40000003"])

    def test_nao_casa_dentro_de_outro_codigo_ou_palavra(self):
        self.assertEqual(list(filtrar_por_termos(self.df, ["153165"])["id"]), ["40000001"])  # não 1531650
        self.assertEqual(list(filtrar_por_termos(self.df, ["26248"])["id"]), ["40000002"])  # não 262480
        self.assertTrue(filtrar_por_termos(self.df, ["UFRPE"]).empty)  # não "ufrpex"
        # UFPE ("Universidade Federal de Pernambuco") não é confundida com a UFRPE
        self.assertNotIn("40000003", list(filtrar_por_termos(self.df)["id"]))

    def test_entrada_nao_modificada(self):
        antes = self.df.copy()
        filtrar_por_termos(self.df)
        pd.testing.assert_frame_equal(self.df, antes)

    def test_df_vazio_e_termo_vazio(self):
        vazio = filtrar_por_termos(pd.DataFrame(columns=COLUNAS))
        self.assertTrue(vazio.empty)
        self.assertIn("termos_encontrados", vazio.columns)
        with self.assertRaises(ValueError):
            filtrar_por_termos(self.df, ["  "])

    def test_codigos_padrao_sao_texto(self):
        self.assertTrue(all(isinstance(t, str) for t in TERMOS_UFRPE_PADRAO))


#: nenhum teste lê o registro real do Windows (a máquina de desenvolvimento tem credenciais de verdade).
SEM_REGISTRO = mock.patch("src.dou_inlabs._variavel_do_usuario_windows", return_value="")


class RefinarTest(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame(ler_xml(FIXTURE.read_bytes()), columns=COLUNAS)

    def test_refinar_exige_os_dois_grupos(self):
        achadas = filtrar_por_termos(self.df, TERMOS_UFRPE_PADRAO, ["limpeza"])
        self.assertEqual(list(achadas["id"]), ["40000001"])
        self.assertEqual(
            achadas.iloc[0]["termos_encontrados"],
            ("Universidade Federal Rural de Pernambuco", "153165", "limpeza"),
        )

    def test_refinar_aceita_qualquer_termo_do_grupo(self):
        achadas = filtrar_por_termos(self.df, TERMOS_UFRPE_PADRAO, ["crédito suplementar", "limpeza"])
        self.assertEqual(list(achadas["id"]), ["40000001", "40000002"])

    def test_termo_de_refinar_sozinho_nao_basta(self):
        # "licitação" só aparece no aviso da UFPE, que não cita a UFRPE
        self.assertTrue(filtrar_por_termos(self.df, TERMOS_UFRPE_PADRAO, ["licitação"]).empty)

    def test_refinar_vazio_equivale_ao_filtro_simples(self):
        pd.testing.assert_frame_equal(filtrar_por_termos(self.df, refinar=()), filtrar_por_termos(self.df))

    def test_zip_com_refinar(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _zip(Path(tmp))
            esperado = filtrar_por_termos(ler_zip(caminho), TERMOS_UFRPE_PADRAO, ["limpeza"]).reset_index(drop=True)
            obtido = ler_e_filtrar_zip(caminho, TERMOS_UFRPE_PADRAO, ["limpeza"])
            pd.testing.assert_frame_equal(obtido, esperado, check_dtype=False)


class TermosSalvosTest(unittest.TestCase):
    def test_sem_arquivo_usa_padroes(self):
        with tempfile.TemporaryDirectory() as tmp:
            salvos = carregar_termos(tmp)
        self.assertEqual((salvos.termos, salvos.refinar, salvos.aviso), (TERMOS_UFRPE_PADRAO, (), None))

    def test_salvar_e_carregar(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp) / "dou"  # criada na primeira gravação
            salvar_termos(["UFRPE", " ufrpe ", "0153"], ["pregão", ""], pasta)
            salvos = carregar_termos(pasta)
            dados = json.loads((pasta / ARQUIVO_TERMOS).read_text(encoding="utf-8"))
            self.assertFalse(list(pasta.glob("*.tmp")))
        self.assertEqual(salvos.termos, ("UFRPE", "0153"))  # zero à esquerda preservado
        self.assertEqual(salvos.refinar, ("pregão",))
        self.assertIsNone(salvos.aviso)
        self.assertIn("atualizado_em", dados)

    def test_lista_vazia_e_respeitada(self):
        with tempfile.TemporaryDirectory() as tmp:
            salvar_termos([], [], tmp)
            self.assertEqual(carregar_termos(tmp).termos, ())

    def test_arquivo_invalido_volta_aos_padroes_com_aviso_sem_apagar(self):
        for conteudo in ("{quebrado", '{"refinar": []}', '{"termos": "UFRPE"}', '{"termos": [1, 2]}', "[]"):
            with self.subTest(conteudo=conteudo), tempfile.TemporaryDirectory() as tmp:
                caminho = Path(tmp) / ARQUIVO_TERMOS
                caminho.write_text(conteudo, encoding="utf-8")
                salvos = carregar_termos(tmp)
                self.assertEqual(salvos.termos, TERMOS_UFRPE_PADRAO)
                self.assertIn("usando os padrões", salvos.aviso)
                self.assertEqual(caminho.read_text(encoding="utf-8"), conteudo)


class CredenciaisTest(unittest.TestCase):
    def test_ausentes(self):
        with mock.patch.dict("os.environ", {}, clear=True), SEM_REGISTRO:
            with self.assertRaisesRegex(ErroInlabs, VARIAVEL_SENHA):
                credenciais_do_ambiente()

    def test_presentes(self):
        with mock.patch.dict("os.environ", {VARIAVEL_EMAIL: " a@b.br ", VARIAVEL_SENHA: "s3nha"}, clear=True),              SEM_REGISTRO as registro:
            self.assertEqual(credenciais_do_ambiente(), ("a@b.br", "s3nha"))
            registro.assert_not_called()  # ambiente do processo tem prioridade

    def test_perfil_do_windows_quando_falta_no_ambiente(self):
        valores = {VARIAVEL_EMAIL: "reg@b.br", VARIAVEL_SENHA: "s3nha-reg"}
        with mock.patch.dict("os.environ", {}, clear=True),              mock.patch("src.dou_inlabs._variavel_do_usuario_windows", side_effect=lambda n: valores[n]):
            self.assertEqual(credenciais_do_ambiente(), ("reg@b.br", "s3nha-reg"))

    def test_leitura_do_registro_ausente_ou_fora_do_windows(self):
        from src.dou_inlabs import _variavel_do_usuario_windows
        self.assertEqual(_variavel_do_usuario_windows("BUDGETLAB_VARIAVEL_QUE_NAO_EXISTE"), "")
        with mock.patch("sys.platform", "linux"):
            self.assertEqual(_variavel_do_usuario_windows(VARIAVEL_SENHA), "")


class ClienteTest(unittest.TestCase):
    def _cliente(self):
        sessao = mock.Mock(spec=requests.Session)
        sessao.cookies = requests.cookies.RequestsCookieJar()
        return ClienteInlabs(sessao), sessao

    def test_login_ok(self):
        cliente, sessao = self._cliente()
        sessao.post.side_effect = lambda *a, **k: sessao.cookies.set(COOKIE_SESSAO, "abc")
        cliente.autenticar("a@b.br", "segredo-123")
        self.assertEqual(sessao.post.call_args.kwargs["data"], {"email": "a@b.br", "password": "segredo-123"})

    def test_login_recusado_nao_expoe_senha(self):
        cliente, sessao = self._cliente()
        with self.assertRaises(ErroInlabs) as ctx:
            cliente.autenticar("a@b.br", "segredo-123")
        self.assertNotIn("segredo-123", str(ctx.exception))

    def test_falha_de_conexao_nao_expoe_senha(self):
        cliente, sessao = self._cliente()
        sessao.post.side_effect = requests.ConnectionError("password=segredo-123")
        with self.assertRaises(ErroInlabs) as ctx:
            cliente.autenticar("a@b.br", "segredo-123")
        self.assertNotIn("segredo-123", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)

    PAGINA_DIA = (
        '<a href="logout.php">Sair</a>'
        '<a title="Baixar Arquivo" href="?p=2026-10-08&dl=2026-10-08-DO1.zip">DO1</a>'
        '<a title="Baixar Arquivo" href="?p=2026-10-08&dl=2026-10-08-DO1.zip">DO1 (repetido)</a>'
        '<a title="Baixar Arquivo" href="?p=2026-10-08&dl=2026-10-08-DO1E.zip">extra</a>'
        '<a title="Baixar Arquivo" href="?p=2026-10-08&dl=2026_10_08_ASSINADO_do1.pdf">pdf</a>'
        '<a href="?p=2026-10-07&dl=2026-10-07-DO3.zip">outro dia</a>'
    )

    def _texto(self, status: int, texto: str) -> mock.Mock:
        resposta = _resposta(status)
        resposta.text = texto
        return resposta

    def test_listar_arquivos_do_dia(self):
        cliente, sessao = self._cliente()
        sessao.get.return_value = self._texto(200, self.PAGINA_DIA)
        self.assertEqual(cliente.listar_arquivos(date(2026, 10, 8)), ["2026-10-08-DO1.zip", "2026-10-08-DO1E.zip"])
        self.assertTrue(sessao.get.call_args.args[0].endswith("index.php?p=2026-10-08"))

    def test_dia_sem_edicao_lista_vazia(self):
        cliente, sessao = self._cliente()
        sessao.get.return_value = self._texto(200, '<a href="logout.php">Sair</a> calendário sem arquivos')
        self.assertEqual(cliente.listar_arquivos(date(2026, 10, 3)), [])

    def test_sessao_inativa(self):
        cliente, sessao = self._cliente()
        sessao.get.return_value = self._texto(200, '<form action="logar.php"><input name="password"></form>')
        with self.assertRaisesRegex(ErroInlabs, "Sessão do INLABS não está ativa"):
            cliente.listar_arquivos(date(2026, 10, 8))

    def test_baixar_arquivo(self):
        cliente, sessao = self._cliente()
        sessao.get.return_value = _resposta(200, b"PKconteudo")
        self.assertEqual(cliente.baixar_arquivo(date(2026, 10, 8), "2026-10-08-DO1.zip"), b"PKconteudo")
        self.assertIn("p=2026-10-08&dl=2026-10-08-DO1.zip", sessao.get.call_args.args[0])
        self.assertIn("origem", sessao.get.call_args.kwargs["headers"])

    def test_html_no_lugar_do_zip(self):
        cliente, sessao = self._cliente()
        sessao.get.return_value = _resposta(200, b"<html>login</html>")
        with self.assertRaisesRegex(ErroInlabs, "não devolveu um ZIP"):
            cliente.baixar_arquivo(date(2026, 10, 8), "2026-10-08-DO1.zip")

    def test_status_inesperado(self):
        cliente, sessao = self._cliente()
        sessao.get.return_value = _resposta(500)
        with self.assertRaisesRegex(ErroInlabs, "500"):
            cliente.baixar_arquivo(date(2026, 10, 8), "2026-10-08-DO1.zip")

    def test_falha_de_conexao(self):
        cliente, sessao = self._cliente()
        sessao.get.side_effect = requests.ConnectionError("x")
        with self.assertRaisesRegex(ErroInlabs, "Falha de conexão ao listar 2026-10-08"):
            cliente.listar_arquivos(date(2026, 10, 8))


class BaixarDiaTest(unittest.TestCase):
    def _cliente(self, conteudos: dict[str, bytes]):
        return _baixar_falso({date(2026, 10, 8): conteudos})

    def test_grava_zips_e_manifesto(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminhos = baixar_dia(self._cliente({"DO1": b"PK1", "DO3": b"PK3"}), date(2026, 10, 8), tmp)
            pasta = Path(tmp) / "2026-10-08"
            self.assertEqual([c.name for c in caminhos], ["2026-10-08-DO1.zip", "2026-10-08-DO3.zip"])
            self.assertEqual((pasta / "2026-10-08-DO1.zip").read_bytes(), b"PK1")
            manifesto = json.loads((pasta / ARQUIVO_MANIFESTO).read_text(encoding="utf-8"))
            self.assertEqual(manifesto["data_publicacao"], "2026-10-08")
            self.assertEqual([a["secao"] for a in manifesto["arquivos"]], ["DO1", "DO3"])
            self.assertEqual(manifesto["arquivos"][0]["sha256"], hashlib.sha256(b"PK1").hexdigest())
            self.assertEqual(manifesto["arquivos"][0]["bytes"], 3)
            self.assertFalse(list(pasta.glob("*.parcial")))

    def test_nunca_sobrescreve_zip_existente(self):
        with tempfile.TemporaryDirectory() as tmp:
            dia = date(2026, 10, 8)
            baixar_dia(self._cliente({"DO1": b"PK-v1"}), dia, tmp)
            baixar_dia(self._cliente({"DO1": b"PK-v1"}), dia, tmp)  # idêntico: reaproveitado
            caminhos = baixar_dia(self._cliente({"DO1": b"PK-v2"}), dia, tmp)  # republicado
            pasta = Path(tmp) / "2026-10-08"
            self.assertEqual((pasta / "2026-10-08-DO1.zip").read_bytes(), b"PK-v1")
            self.assertEqual(caminhos[0].read_bytes(), b"PK-v2")
            self.assertNotEqual(caminhos[0].name, "2026-10-08-DO1.zip")
            manifesto = json.loads((pasta / ARQUIVO_MANIFESTO).read_text(encoding="utf-8"))
            self.assertEqual(len(manifesto["arquivos"]), 2)


class LerEFiltrarZipTest(unittest.TestCase):
    def test_equivale_a_ler_e_depois_filtrar(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _zip(Path(tmp))
            for termos in (TERMOS_UFRPE_PADRAO, ("licitação",), ("inexistente",)):
                esperado = filtrar_por_termos(ler_zip(caminho), termos).reset_index(drop=True)
                obtido = ler_e_filtrar_zip(caminho, termos)
                pd.testing.assert_frame_equal(obtido, esperado, check_dtype=False)


class LimparTermosTest(unittest.TestCase):
    def test_remove_vazios_espacos_e_repetidos(self):
        self.assertEqual(
            limpar_termos([" UFRPE ", "", "  ", "ufrpe", "Licitação", "LICITACAO", "153165"]),
            ("UFRPE", "Licitação", "153165"),
        )


def _baixar_falso(conteudos_por_dia: dict[date, dict[str, bytes]], falha_em: date | None = None):
    """Cliente sem rede: `conteudos_por_dia[dia][secao]` é o ZIP publicado; dia ausente = sem edição."""
    cliente = mock.Mock(spec=ClienteInlabs)

    def listar_arquivos(dia):
        if dia == falha_em:
            raise ErroInlabs("sem rede")
        return [f"{dia.isoformat()}-{secao}.zip" for secao in conteudos_por_dia.get(dia, {})]

    def baixar_arquivo(dia, nome):
        secao = nome.removeprefix(f"{dia.isoformat()}-").removesuffix(".zip")
        return conteudos_por_dia[dia][secao]

    cliente.listar_arquivos.side_effect = listar_arquivos
    cliente.baixar_arquivo.side_effect = baixar_arquivo
    return cliente


class AtualizacaoIncrementalTest(unittest.TestCase):
    HOJE = date(2026, 10, 8)

    def test_primeira_vez_consulta_ultimos_dias(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(dias_pendentes(self.HOJE, tmp, dias_iniciais=3), [date(2026, 10, 6), date(2026, 10, 7), self.HOJE])

    def test_continua_do_dia_seguinte_ao_ultimo(self):
        with tempfile.TemporaryDirectory() as tmp:
            atualizar(_baixar_falso({}), date(2026, 10, 5), tmp)
            pendentes = dias_pendentes(self.HOJE, tmp)
            self.assertEqual(pendentes[0], date(2026, 10, 6))
            self.assertEqual(pendentes[-1], self.HOJE)

    def test_ja_atualizado_reconsulta_hoje(self):
        with tempfile.TemporaryDirectory() as tmp:
            atualizar(_baixar_falso({}), self.HOJE, tmp)
            self.assertEqual(dias_pendentes(self.HOJE, tmp), [self.HOJE])

    def test_limite_por_atualizacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            pendentes = dias_pendentes(self.HOJE, tmp, dias_iniciais=40, limite=30)
            self.assertEqual(len(pendentes), 30)
            self.assertEqual(pendentes[0], self.HOJE - timedelta(days=39))  # os mais antigos primeiro

    def test_dia_sem_publicacao_fica_registrado(self):
        with tempfile.TemporaryDirectory() as tmp:
            resumo = atualizar(_baixar_falso({self.HOJE: {"DO1": b"PK1"}}), self.HOJE, tmp)
            self.assertIsNone(resumo.erro)
            self.assertEqual(len(resumo.dias_consultados), 7)
            self.assertEqual(len(resumo.dias_sem_publicacao), 6)
            self.assertEqual([c.name for c in resumo.arquivos], ["2026-10-08-DO1.zip"])
            baixados = dias_baixados(tmp)
            self.assertEqual(len(baixados), 7)
            self.assertEqual(baixados[date(2026, 10, 2)]["arquivos"], [])
            self.assertIn("verificado_em", baixados[date(2026, 10, 2)])

    def test_erro_interrompe_e_preserva_o_que_ja_baixou(self):
        with tempfile.TemporaryDirectory() as tmp:
            falha = date(2026, 10, 5)
            progresso = mock.Mock()
            resumo = atualizar(_baixar_falso({date(2026, 10, 3): {"DO3": b"PK3"}}, falha), self.HOJE, tmp, progresso)
            self.assertEqual(resumo.erro, "sem rede")
            self.assertEqual(resumo.dias_consultados, [date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4)])
            self.assertEqual(resumo.restantes, 4)  # 05/10 a 08/10
            self.assertEqual(dias_pendentes(self.HOJE, tmp)[0], falha)  # recomeça de onde parou
            self.assertEqual(progresso.call_count, 4)

    def test_restantes_alem_do_limite(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "2026-08-01").mkdir()
            Path(tmp, "2026-08-01", ARQUIVO_MANIFESTO).write_text('{"arquivos": []}', encoding="utf-8")
            resumo = atualizar(_baixar_falso({}), self.HOJE, tmp)
            self.assertEqual(len(resumo.dias_consultados), 30)
            self.assertEqual(resumo.restantes, 68 - 30)  # 02/08 a 08/10 = 68 dias

    def test_arquivos_baixados_por_periodo(self):
        with tempfile.TemporaryDirectory() as tmp:
            conteudos = {date(2026, 10, 7): {"DO1": b"PK7"}, self.HOJE: {"DO3": b"PK8"}}
            atualizar(_baixar_falso(conteudos), self.HOJE, tmp)
            Path(tmp, "2026-10-08", "solto.zip").write_bytes(b"PK")  # fora do manifesto: ignorado
            Path(tmp, "nao-e-data").mkdir()
            todos = arquivos_baixados(tmp)
            self.assertEqual([c.name for c, _ in todos], ["2026-10-07-DO1.zip", "2026-10-08-DO3.zip"])
            self.assertEqual(todos[0][1], hashlib.sha256(b"PK7").hexdigest())
            self.assertEqual([c.name for c, _ in arquivos_baixados(tmp, inicio=self.HOJE)], ["2026-10-08-DO3.zip"])
            self.assertEqual(arquivos_baixados(tmp, fim=date(2026, 10, 6)), [])

    def test_diretorio_inexistente(self):
        self.assertEqual(dias_baixados("nao/existe/dou"), {})


class LinhaDeComandoTest(unittest.TestCase):
    def test_sem_credenciais_retorna_erro(self):
        with mock.patch.dict("os.environ", {}, clear=True), SEM_REGISTRO, mock.patch("sys.stderr"):
            self.assertEqual(main(["2026-10-08"]), 1)

    def test_fluxo_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_ = _zip(Path(tmp))
            with mock.patch.dict("os.environ", {VARIAVEL_EMAIL: "a@b.br", VARIAVEL_SENHA: "segredo-123"}), \
                 mock.patch.object(ClienteInlabs, "autenticar"), \
                 mock.patch("src.dou_inlabs.baixar_dia", return_value=[zip_]), \
                 mock.patch("builtins.print") as impressao:
                self.assertEqual(main(["2026-10-08", "--diretorio", tmp]), 0)
            saida = "\n".join(str(c.args[0]) for c in impressao.call_args_list)
            self.assertIn("3 matéria(s), 2 com os termos", saida)
            self.assertNotIn("segredo-123", saida)


if __name__ == "__main__":
    unittest.main()
