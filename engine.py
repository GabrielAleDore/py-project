"""
engine.py
---------
Re-exportador para compatibilidade retroativa com reconciliation_engine.
"""

from reconciliation_engine import (
    ResultadoConciliacao,
    conciliar_extratos_avancado,
    _buscar_subset_sum_otimizado,
    _formatar_moeda,
)

__all__ = [
    "ResultadoConciliacao",
    "conciliar_extratos_avancado",
    "_buscar_subset_sum_otimizado",
    "_formatar_moeda",
]