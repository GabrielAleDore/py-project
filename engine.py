"""
engine.py
---------
Motor de Conciliação Financeira Avançado.
Suporta:
  1. Match Exato (1-para-1): Mesma data ou janela com valor idêntico.
  2. Match Aglutinado (N-para-1): Vários lançamentos do sistema que somam 1 valor bancário (Subset Sum otimizado).
  3. Detecção de Divergências de Valor: Variações de centavos, tarifas ou descontos (até limite configurado).
  4. Alertas Críticos de Anomalias: Transações de alto valor não conciliadas (ex: R$ 15.000+) para auditoria imediata.
"""

from __future__ import annotations

from datetime import timedelta
import itertools
from typing import Any

import pandas as pd


class ResultadoConciliacao(tuple):
    """
    Estrutura de resultado compatível tanto com desempacotamento de 4 itens:
        df_conc, df_sobra_banco, df_sobra_sistema, df_div = conciliar_extratos_avancado(...)
    quanto com acesso por atributos:
        resultado.df_criticos
        resultado.metricas
        resultado.df_conc
    """

    def __new__(
        cls,
        df_conc: pd.DataFrame,
        df_sobra_banco: pd.DataFrame,
        df_sobra_sistema: pd.DataFrame,
        df_div: pd.DataFrame,
        df_criticos: pd.DataFrame | None = None,
        metricas: dict[str, Any] | None = None,
    ):
        return super().__new__(cls, (df_conc, df_sobra_banco, df_sobra_sistema, df_div))

    def __init__(
        self,
        df_conc: pd.DataFrame,
        df_sobra_banco: pd.DataFrame,
        df_sobra_sistema: pd.DataFrame,
        df_div: pd.DataFrame,
        df_criticos: pd.DataFrame | None = None,
        metricas: dict[str, Any] | None = None,
    ):
        self.df_conc = df_conc
        self.df_sobra_banco = df_sobra_banco
        self.df_sobra_sistema = df_sobra_sistema
        self.df_div = df_div
        self.df_criticos = df_criticos if df_criticos is not None else pd.DataFrame()
        self.metricas = metricas if metricas is not None else {}


def _buscar_subset_sum_otimizado(candidatos: list[tuple[int, float]], alvo: float, max_itens: int = 8) -> list[int] | None:
    """
    Encontra um subconjunto de candidatos cuja soma é igual a 'alvo' com poda imediata.
    candidatos: lista de (indice, valor_absoluto)
    alvo: valor absoluto procurado
    """
    alvo_arredondado = round(alvo, 2)
    n = len(candidatos)

    # Ordena candidatos por valor decrescente para maximizar podas rápidas
    candidatos_ord = sorted(candidatos, key=lambda x: -x[1])

    def _backtrack(inicio: int, soma_acumulada: float, indices_usados: list[int]) -> list[int] | None:
        if round(soma_acumulada, 2) == alvo_arredondado and len(indices_usados) >= 2:
            return indices_usados
        if len(indices_usados) >= max_itens or inicio >= n:
            return None

        for i in range(inicio, n):
            idx, val = candidatos_ord[i]
            nova_soma = round(soma_acumulada + val, 2)
            if nova_soma > alvo_arredondado + 0.001:
                # Poda: como todos os valores são positivos, não há como atingir o alvo continuando nesta ramificação
                continue
            res = _backtrack(i + 1, nova_soma, indices_usados + [idx])
            if res is not None:
                return res
        return None

    return _backtrack(0, 0.0, [])


def conciliar_extratos_avancado(
    df_banco: pd.DataFrame,
    df_sistema: pd.DataFrame,
    janela_dias: int = 3,
    limite_divergencia: float = 100.0,
    limiar_alto_valor: float = 5000.0,
) -> ResultadoConciliacao:
    """
    Executa a conciliação avançada entre extrato bancário e extrato do sistema.

    Parâmetros:
      - df_banco: DataFrame com colunas ['data', 'descricao', 'valor']
      - df_sistema: DataFrame com colunas ['data', 'descricao', 'valor']
      - janela_dias: Tolerância em dias para match de datas
      - limite_divergencia: Valor máximo de diferença monetária para classificar como divergência
      - limiar_alto_valor: Valor a partir do qual sobras não conciliadas viram alertas críticos
    """
    if df_banco.empty or df_sistema.empty:
        df_empty_conc = pd.DataFrame(columns=[
            "data_banco", "desc_banco", "data_sistema", "desc_sistema",
            "valor_banco", "valor_sistema", "diferenca", "tipo_match"
        ])
        df_empty_sobra = pd.DataFrame(columns=["data", "descricao", "valor"])
        df_empty_div = pd.DataFrame(columns=[
            "data_banco", "desc_banco", "valor_banco",
            "data_sistema", "desc_sistema", "valor_sistema", "diferenca"
        ])
        df_empty_crit = pd.DataFrame(columns=["origem", "data", "descricao", "valor", "motivo", "severidade"])
        return ResultadoConciliacao(
            df_empty_conc,
            df_banco if not df_banco.empty else df_empty_sobra,
            df_sistema if not df_sistema.empty else df_empty_sobra,
            df_empty_div,
            df_empty_crit,
            {"total_banco": len(df_banco), "total_sistema": len(df_sistema), "taxa_conciliacao": 0.0}
        )

    banco = df_banco.copy().reset_index(drop=True)
    sistema = df_sistema.copy().reset_index(drop=True)

    banco["valor"] = banco["valor"].round(2)
    sistema["valor"] = sistema["valor"].round(2)

    conciliados = []

    # -------------------------------------------------------------------------
    # 1. MATCH EXATO 1-PARA-1
    # Prioriza: mesma data exata (0 dias), depois ±1 dia, até ±janela_dias
    # -------------------------------------------------------------------------
    for delta in range(0, janela_dias + 1):
        for idx_b in list(banco.index):
            if idx_b not in banco.index:
                continue
            b = banco.loc[idx_b]

            d_min = b["data"] - timedelta(days=delta)
            d_max = b["data"] + timedelta(days=delta)

            matches = sistema[
                (sistema["data"] >= d_min) &
                (sistema["data"] <= d_max) &
                (sistema["valor"] == b["valor"])
            ]

            if not matches.empty:
                # Escolhe o que tiver a menor diferença de dias
                best_match_idx = None
                menor_diff = 999
                for s_idx, s_row in matches.iterrows():
                    diff_dias = abs((b["data"] - s_row["data"]).days)
                    if diff_dias < menor_diff:
                        menor_diff = diff_dias
                        best_match_idx = s_idx

                if best_match_idx is not None:
                    s_match = matches.loc[best_match_idx]
                    conciliados.append({
                        "data_banco": b["data"],
                        "desc_banco": b["descricao"],
                        "data_sistema": s_match["data"],
                        "desc_sistema": s_match["descricao"],
                        "valor_banco": b["valor"],
                        "valor_sistema": s_match["valor"],
                        "diferenca": 0.0,
                        "tipo_match": "Exato (1-para-1)",
                    })
                    banco.drop(idx_b, inplace=True)
                    sistema.drop(best_match_idx, inplace=True)

    # -------------------------------------------------------------------------
    # 2. MATCH N-PARA-1 (Aglutinação / Subset Sum)
    # Vários lançamentos do sistema que somam exatamente 1 valor do banco
    # -------------------------------------------------------------------------
    for idx_b in list(banco.index):
        if idx_b not in banco.index:
            continue
        b = banco.loc[idx_b]

        d_min = b["data"] - timedelta(days=janela_dias + 1)
        d_max = b["data"] + timedelta(days=janela_dias)

        # Candidatos do sistema dentro da janela com o mesmo sinal e cujo valor absoluto <= valor do banco
        candidatos = sistema[
            (sistema["data"] >= d_min) &
            (sistema["data"] <= d_max) &
            ((sistema["valor"] * b["valor"]) > 0) &
            (sistema["valor"].abs() <= abs(b["valor"]) + 0.01)
        ]

        if len(candidatos) < 2:
            continue

        candidatos_lista = [(int(idx), float(abs(row["valor"]))) for idx, row in candidatos.iterrows()]
        alvo_abs = float(abs(b["valor"]))

        comb_indices = _buscar_subset_sum_otimizado(candidatos_lista, alvo_abs, max_itens=8)

        if comb_indices:
            sub_df = sistema.loc[comb_indices]
            soma_sistema = round(float(sub_df["valor"].sum()), 2)
            conciliados.append({
                "data_banco": b["data"],
                "desc_banco": b["descricao"],
                "data_sistema": ", ".join(sub_df["data"].astype(str).unique()),
                "desc_sistema": " | ".join(sub_df["descricao"].tolist()),
                "valor_banco": b["valor"],
                "valor_sistema": soma_sistema,
                "diferenca": round(b["valor"] - soma_sistema, 2),
                "tipo_match": f"Aglutinado ({len(comb_indices)} para 1)",
            })
            banco.drop(idx_b, inplace=True)
            sistema.drop(comb_indices, inplace=True)

    # -------------------------------------------------------------------------
    # 3. DETECÇÃO DE DIVERGÊNCIAS DE VALOR (Tolerâncias / Centavos / Juros)
    # -------------------------------------------------------------------------
    divergencias = []
    for idx_b, b in banco.iterrows():
        d_min = b["data"] - timedelta(days=janela_dias)
        d_max = b["data"] + timedelta(days=janela_dias)

        candidatos = sistema[
            (sistema["data"] >= d_min) &
            (sistema["data"] <= d_max) &
            ((sistema["valor"] * b["valor"]) > 0)
        ]

        for idx_s, s in candidatos.iterrows():
            diferenca = round(abs(b["valor"] - s["valor"]), 2)
            if 0 < diferenca <= limite_divergencia:
                divergencias.append({
                    "data_banco": b["data"],
                    "desc_banco": b["descricao"],
                    "valor_banco": b["valor"],
                    "data_sistema": s["data"],
                    "desc_sistema": s["descricao"],
                    "valor_sistema": s["valor"],
                    "diferenca": round(b["valor"] - s["valor"], 2),
                    "diferenca_abs": diferenca,
                })

    df_div = pd.DataFrame(divergencias)
    if not df_div.empty:
        df_div = df_div.sort_values(by="diferenca_abs").reset_index(drop=True)

    # -------------------------------------------------------------------------
    # 4. DETECÇÃO DE ALERTAS CRÍTICOS (ALTO VALOR NÃO CONCILIADO)
    # -------------------------------------------------------------------------
    alertas_criticos = []

    # Sobras do banco com alto valor
    for _, b in banco.iterrows():
        if abs(b["valor"]) >= limiar_alto_valor:
            alertas_criticos.append({
                "origem": "BANCO (Santander)",
                "data": b["data"],
                "descricao": b["descricao"],
                "valor": b["valor"],
                "motivo": f"Transação de alto valor ({_formatar_moeda(b['valor'])}) presente no banco sem lançamento no ERP",
                "severidade": "CRÍTICO",
            })

    # Sobras do sistema com alto valor
    for _, s in sistema.iterrows():
        if abs(s["valor"]) >= limiar_alto_valor:
            alertas_criticos.append({
                "origem": "SISTEMA (ERP)",
                "data": s["data"],
                "descricao": s["descricao"],
                "valor": s["valor"],
                "motivo": f"Lançamento de alto valor ({_formatar_moeda(s['valor'])}) registrado no ERP sem compensação bancária",
                "severidade": "CRÍTICO",
            })

    df_criticos = pd.DataFrame(alertas_criticos)
    if not df_criticos.empty:
        df_criticos = df_criticos.sort_values(by="valor", key=abs, ascending=False).reset_index(drop=True)
    else:
        df_criticos = pd.DataFrame(columns=["origem", "data", "descricao", "valor", "motivo", "severidade"])

    df_conc = pd.DataFrame(conciliados)
    if df_conc.empty:
        df_conc = pd.DataFrame(columns=[
            "data_banco", "desc_banco", "data_sistema", "desc_sistema",
            "valor_banco", "valor_sistema", "diferenca", "tipo_match"
        ])

    df_sobra_banco = banco[["data", "descricao", "valor"]].reset_index(drop=True)
    df_sobra_sistema = sistema[["data", "descricao", "valor"]].reset_index(drop=True)

    # Métricas consolidadas
    total_banco = len(df_banco)
    total_sistema = len(df_sistema)
    total_conciliados = len(df_conc)
    exatos_count = sum(1 for m in conciliados if "Exato" in m["tipo_match"])
    aglutinados_count = sum(1 for m in conciliados if "Aglutinado" in m["tipo_match"])

    metricas = {
        "total_banco": total_banco,
        "total_sistema": total_sistema,
        "total_conciliados": total_conciliados,
        "exatos_count": exatos_count,
        "aglutinados_count": aglutinados_count,
        "sobra_banco_count": len(df_sobra_banco),
        "sobra_sistema_count": len(df_sobra_sistema),
        "divergencias_count": len(df_div),
        "criticos_count": len(df_criticos),
        "taxa_conciliacao": round(total_conciliados / max(total_banco, 1) * 100, 2),
        "valor_total_banco": round(float(df_banco["valor"].sum()), 2),
        "valor_total_sistema": round(float(df_sistema["valor"].sum()), 2),
        "valor_conciliado": round(float(df_conc["valor_banco"].sum()), 2) if not df_conc.empty else 0.0,
    }

    return ResultadoConciliacao(
        df_conc=df_conc,
        df_sobra_banco=df_sobra_banco,
        df_sobra_sistema=df_sobra_sistema,
        df_div=df_div,
        df_criticos=df_criticos,
        metricas=metricas,
    )


def _formatar_moeda(valor: float) -> str:
    """Formata valor em Real brasileiro: R$ 1.234,56 ou R$ -1.234,56."""
    s = f"{valor:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")