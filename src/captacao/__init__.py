"""Captação de Demandas para a Proposta Orçamentária (modelo `captacao-demandas`).

Camadas separadas (ver `docs/PROJETO.md` do pacote de origem, seção 9.3):

- `schema.py`: DDL e conexão SQLite (`data/captacao/captacao.db`);
- `regras.py`: regras de negócio puras (RN-01..RN-05, fases do ciclo, transições), sem
  acesso a banco nem à interface;
- `servicos.py`: operações transacionais sobre o banco (criar rascunho, enviar), que
  aplicam as regras e gravam o histórico de situação.
"""
