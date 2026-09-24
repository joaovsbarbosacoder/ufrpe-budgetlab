"""
Testes de "TED sem código SIAFI" (Execução Anual, briefing seção 7).

O SIAFI compõe a chave do TED, então a linha não pode ser gravada. Mas um TED real sem SIAFI (ex.:
"Termo em cadastramento", visto na extração de 17/09/2026) NÃO é rodapé: gera alerta, e valores não
nulos da linha são citados para nada sumir em silêncio. Linhas sem TED (rodapé de verdade) continuam
rejeitadas com o motivo antigo, sem alerta.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.teds_alertas import (
    TIPO_TED_SEM_SIAFI,
    gerar_alertas_ted_sem_siafi,
)
from src.teds_importacao_simec import ler_execucao_anual_simec
from src.teds_lotes import importar_execucao_anual
from src.teds_schema import conectar

_TOTAIS = [
    "Total NC Descentralização (R$)", "Total NC Devolução (R$)", "Total Descentralizado (R$)",
    "Total PF Repasse", "Total PF Devolução", "Total Repassado",
]


def _linha(ted=17352.0, siafi="1ABDKU", valores=(1000.0, 100.0, 900.0, 800.0, 50.0, 750.0), estado="Termo em Execução"):
    return {
        "Ano de emissão": 2026.0, "Descrição do Termo": "Termo", "Estado Atual": estado,
        "Fim da Vigência": "31/12/2027", "Início da Vigência": "01/01/2026", "SIAFI": siafi, "TED": ted,
        "UG Descentralizadora": 153165.0, **dict(zip(_TOTAIS, valores)),
    }


def _df(*linhas):
    return pd.DataFrame(list(linhas))


class LeituraTests(unittest.TestCase):
    def test_ted_sem_siafi_tem_motivo_proprio_e_carrega_o_numero_do_ted(self):
        leitura = ler_execucao_anual_simec(_df(
            _linha(),
            _linha(ted=16811.0, siafi=np.nan, valores=(0.0,) * 6, estado="Termo em cadastramento"),
        ))
        self.assertEqual(len(leitura.registros), 1)
        (rejeitada,) = leitura.rejeitadas
        self.assertEqual(rejeitada.ted, "16811")
        self.assertIn("TED 16811 sem código SIAFI", rejeitada.motivo)
        self.assertIn("Termo em cadastramento", rejeitada.motivo)
        self.assertIn("todos os valores da linha são zero", rejeitada.motivo)
        self.assertNotIn("rodapé", rejeitada.motivo)  # não é mais chamado de rodapé

    def test_valores_nao_nulos_da_linha_sao_citados_e_nunca_descartados_em_silencio(self):
        leitura = ler_execucao_anual_simec(_df(
            _linha(ted=16811.0, siafi=np.nan, valores=(500.0, 0.0, 500.0, 0.0, 0.0, 0.0)),
        ))
        (rejeitada,) = leitura.rejeitadas
        self.assertIn("valores não nulos na linha", rejeitada.motivo)
        self.assertIn("total_nc_descentralizacao = 500", rejeitada.motivo)
        self.assertIn("total_descentralizado = 500", rejeitada.motivo)
        self.assertNotIn("total_nc_devolucao", rejeitada.motivo)

    def test_linha_sem_ted_continua_sendo_rodape_sem_alerta(self):
        leitura = ler_execucao_anual_simec(_df(_linha(), _linha(ted=np.nan, siafi=np.nan)))
        (rejeitada,) = leitura.rejeitadas
        self.assertIsNone(rejeitada.ted)
        self.assertIn("possível linha de rodapé", rejeitada.motivo)

    def test_siafi_sem_ted_tambem_continua_como_antes(self):
        leitura = ler_execucao_anual_simec(_df(_linha(), _linha(ted=np.nan, siafi="1ABDKU")))
        (rejeitada,) = leitura.rejeitadas
        self.assertIsNone(rejeitada.ted)

    def test_o_rodape_continua_sendo_capturado_com_um_ted_sem_siafi_no_arquivo(self):
        df = _df(_linha(), _linha(ted=16811.0, siafi=np.nan, valores=(0.0,) * 6))
        df.loc[len(df)] = {c: np.nan for c in df.columns} | dict(zip(_TOTAIS, (1000.0, 100.0, 900.0, 800.0, 50.0, 750.0)))
        leitura = ler_execucao_anual_simec(df)
        self.assertEqual(len(leitura.rejeitadas), 2)  # o TED sem SIAFI + o rodapé
        self.assertIsNotNone(leitura.rodape)


class AlertaTests(unittest.TestCase):
    def test_gera_um_alerta_por_ted_com_o_motivo_e_a_consequencia(self):
        (alerta,) = gerar_alertas_ted_sem_siafi([("16811", "TED 16811 sem código SIAFI; todos os valores da linha são zero")])
        self.assertEqual((alerta.tipo, alerta.gravidade, alerta.documento), (TIPO_TED_SEM_SIAFI, "media", "ted:16811"))
        self.assertIn("NÃO foi importada", alerta.descricao)
        self.assertIn("fora de todos os totais", alerta.descricao)

    def test_mesmo_ted_repetido_gera_um_so(self):
        linha = ("16811", "TED 16811 sem código SIAFI")
        self.assertEqual(len(gerar_alertas_ted_sem_siafi([linha, linha])), 1)


class ImportacaoTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def _abertos(self):
        return self.conn.execute(
            "SELECT documento, gravidade FROM alerta WHERE tipo = ? AND status != 'resolvido'", (TIPO_TED_SEM_SIAFI,)
        ).fetchall()

    def test_importar_gera_o_alerta_e_o_ted_fica_fora_dos_totais(self):
        df = _df(_linha(), _linha(ted=16811.0, siafi=np.nan, valores=(0.0,) * 6, estado="Termo em cadastramento"))
        resultado = importar_execucao_anual(self.conn, df, "ea.xlsx", b"ea")
        self.assertEqual(resultado.inseridos, 1)
        self.assertEqual(self._abertos(), [("ted:16811", "media")])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ted").fetchone()[0], 1)  # 16811 não entrou
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM execucao_anual").fetchone()[0], 1)

    def test_reimportar_nao_duplica_e_extracao_nova_com_o_mesmo_ted_tambem_nao(self):
        df = _df(_linha(), _linha(ted=16811.0, siafi=np.nan, valores=(0.0,) * 6))
        importar_execucao_anual(self.conn, df, "ea.xlsx", b"ea")
        importar_execucao_anual(self.conn, df, "ea.xlsx", b"ea")  # mesmo arquivo: no-op
        importar_execucao_anual(self.conn, df, "ea2.xlsx", b"ea2")  # extração nova, mesma situação
        self.assertEqual(len(self._abertos()), 1)

    def test_o_alerta_nao_fecha_sozinho_quando_o_siafi_chega(self):
        importar_execucao_anual(
            self.conn, _df(_linha(), _linha(ted=16811.0, siafi=np.nan, valores=(0.0,) * 6)), "ea.xlsx", b"ea"
        )
        importar_execucao_anual(
            self.conn, _df(_linha(), _linha(ted=16811.0, siafi="1ABEXY", valores=(0.0,) * 6)), "ea2.xlsx", b"ea2"
        )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ted").fetchone()[0], 2)  # agora entrou
        self.assertEqual(self._abertos(), [("ted:16811", "media")])  # só uma pessoa resolve

    def test_arquivo_sem_ted_sem_siafi_nao_gera_alerta(self):
        importar_execucao_anual(self.conn, _df(_linha(), _linha(ted=np.nan, siafi=np.nan)), "ea.xlsx", b"ea")
        self.assertEqual(self._abertos(), [])


if __name__ == "__main__":
    unittest.main()
