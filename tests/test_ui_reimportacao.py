"""Testes de `src/ui_reimportacao._efetivar_reimportacao` — gravação do arquivo de origem em
`data/raw/` ao confirmar uma reimportação. Diretórios temporários; o `st` do módulo é
substituído por um mock (a função só usa `st.success`/`st.rerun`/`st.session_state`).

Caso real de 28/09/2026: o navegador salvou um download novo com o nome "(8).xlsx", já usado
pela extração de 22/09, e a reimportação sobrescreveu esse arquivo original — a extração de
22/09 deixou de ser reproduzível a partir de `data/raw/`.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.importacao_versionada import Manifesto, nome_ponteiro
from src.ui_reimportacao import EspecificacaoReimportacao, _efetivar_reimportacao

NOME = "BI CPOC - EXEC. DESPESAS - Por Ano (8).xlsx"
BASE = "execucao_mensal"


class EfetivarReimportacaoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        raiz = Path(self._tmp.name)
        self.spec = EspecificacaoReimportacao(
            prefixo_estado="teste",
            diretorio_dados_brutos=raiz / "raw",
            diretorio_manifestos=raiz / "manifestos",
            medidas=("empenhada",),
            importar=mock.Mock(),
            linhas_resumo=lambda _m: "",
        )
        self.spec.diretorio_dados_brutos.mkdir()
        self.spec.diretorio_manifestos.mkdir()
        patcher = mock.patch("src.ui_reimportacao.st")
        self.st = patcher.start()
        self.st.session_state = {}
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _staging(self, conteudo: bytes) -> Path:
        self.spec.diretorio_staging.mkdir(parents=True, exist_ok=True)
        caminho = self.spec.diretorio_staging / NOME
        caminho.write_bytes(conteudo)
        return caminho

    @staticmethod
    def _manifesto(conteudo: bytes) -> Manifesto:
        return Manifesto(
            base=BASE, arquivo=NOME, sha256=hashlib.sha256(conteudo).hexdigest(),
            data_extracao="2026-09-28T10:14:27", importado_em="2026-09-28T10:14:30-03:00",
            anos=[2026], totais={"empenhada": 1.0}, totais_por_ano={"2026": {"empenhada": 1.0}},
            contagens={"linhas": 1},
        )

    def _manifesto_gravado(self) -> dict:
        return json.loads((self.spec.diretorio_manifestos / nome_ponteiro(BASE)).read_text(encoding="utf-8"))

    def test_nome_ja_usado_com_conteudo_diferente_preserva_o_original(self):
        original = self.spec.diretorio_dados_brutos / NOME
        original.write_bytes(b"extracao de 22/09")
        manifesto = self._manifesto(b"extracao de 28/09")

        _efetivar_reimportacao(self.spec, self._staging(b"extracao de 28/09"), manifesto, "geracao")

        self.assertEqual(original.read_bytes(), b"extracao de 22/09")  # nada sobrescrito
        gravado = self._manifesto_gravado()
        self.assertNotEqual(gravado["arquivo"], NOME)
        novo = self.spec.diretorio_dados_brutos / gravado["arquivo"]
        self.assertEqual(novo.read_bytes(), b"extracao de 28/09")
        self.assertEqual(hashlib.sha256(novo.read_bytes()).hexdigest(), gravado["sha256"])

    def test_mesmo_conteudo_reaproveita_o_arquivo_sem_copia(self):
        original = self.spec.diretorio_dados_brutos / NOME
        original.write_bytes(b"mesma extracao")
        staging = self._staging(b"mesma extracao")

        _efetivar_reimportacao(self.spec, staging, self._manifesto(b"mesma extracao"), "geracao")

        self.assertEqual(self._manifesto_gravado()["arquivo"], NOME)
        self.assertEqual(sorted(p.name for p in self.spec.diretorio_dados_brutos.glob("*.xlsx")), [NOME])
        self.assertFalse(staging.exists())

    def test_nome_livre_mantem_o_nome_do_upload(self):
        _efetivar_reimportacao(self.spec, self._staging(b"primeira"), self._manifesto(b"primeira"), "geracao")
        self.assertEqual(self._manifesto_gravado()["arquivo"], NOME)
        self.assertEqual((self.spec.diretorio_dados_brutos / NOME).read_bytes(), b"primeira")


if __name__ == "__main__":
    unittest.main()
