"""
parsers.py
----------
Módulo especializado na extração de extratos bancários (Santander Empresas)
e relatórios de sistemas ERP internos a partir de PDFs.

Suporta extração tabular precisa e fallbacks resilientes para linhas de texto.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any

import pandas as pd
import pdfplumber


def limpar_valor_monetario(valor_str: Any) -> float:
    """
    Converte uma string monetária (padrão brasileiro ou bancário) em float.
    - Débitos ('D', prefixo/sufixo '-', ou entre parênteses) tornam-se negativos.
    - Créditos ('C', prefixo '+', ou números positivos) tornam-se positivos.
    """
    if valor_str is None:
        return 0.0
    s = str(valor_str).strip()
    if not s or s in ("-", "–", "N/A", "n/a", "", "None"):
        return 0.0

    eh_debito = False

    # Detecção de débitos: sufixo/prefixo D, -, ou formato contábil (valor)
    if s.startswith("(") and s.endswith(")"):
        eh_debito = True
        s = s[1:-1].strip()
    elif s.endswith("D") or s.endswith("d") or s.startswith("-") or s.endswith("-"):
        eh_debito = True
    elif s.endswith("C") or s.endswith("c") or s.startswith("+") or s.endswith("+"):
        eh_debito = False

    # Remove símbolos de moeda, letras D/C e espaços
    num = re.sub(r"[^\d,\.]", "", s)
    if not num:
        return 0.0

    # Normalização de separador decimal e milhar
    if "," in num and "." in num:
        # Formato brasileiro comum: 1.234,56
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            # Formato americano: 1,234.56
            num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", ".")

    try:
        val = float(num)
        return -abs(val) if eh_debito else abs(val)
    except ValueError:
        return 0.0


def converter_data(data_str: Any) -> datetime.date | None:
    """
    Converte formatos variados de data (DD/MM/YY, DD/MM/YYYY, etc.) em datetime.date.
    Converte anos de 2 dígitos (< 100) para o século 2000.
    """
    if not data_str:
        return None
    s = str(data_str).strip()
    m = re.search(r"\b(\d{2})[/.-](\d{2})[/.-](\d{2,4})\b", s)
    if not m:
        return None
    d, m_mes, a = m.groups()
    ano = int(a)
    if ano < 100:
        ano += 2000
    try:
        return datetime(ano, int(m_mes), int(d)).date()
    except ValueError:
        return None


def _get_pdf_source(file_input: Any) -> Any:
    """Garante que a entrada para o pdfplumber seja um stream ou arquivo válido."""
    if isinstance(file_input, bytes):
        return io.BytesIO(file_input)
    if hasattr(file_input, "getvalue"):
        return io.BytesIO(file_input.getvalue())
    if hasattr(file_input, "seek"):
        file_input.seek(0)
    return file_input


def extrair_sistema(file_input: Any) -> pd.DataFrame:
    """
    Extrai transações do relatório do ERP (Extrato do Sistema).
    Formato esperado: Data (DD/MM/YY) | Descrição | Valor (ex: 970,00 D / 350.000,00 C) | Saldo
    """
    transacoes = []
    # Expressão regular com separadores tipo pipe '|'
    regex_linha_pipe = re.compile(
        r"(\d{2}/\d{2}/\d{2,4})\s*\|\s*(.*?)\s*\|\s*([\d\.,]+)\s*([DCdc])(?:\s*\|\s*(-?[\d\.,]+))?"
    )
    # Expressão de fallback para separação tabular por múltiplos espaços
    regex_linha_espaco = re.compile(
        r"(\d{2}/\d{2}/\d{2,4})\s{2,}(.+?)\s{2,}([\d\.,]+)\s*([DCdc])(?:\s{2,}(-?[\d\.,]+))?"
    )

    src = _get_pdf_source(file_input)
    with pdfplumber.open(src) as pdf:
        for page in pdf.pages:
            texto = page.extract_text(layout=False) or ""
            linhas = texto.split("\n")
            for linha in linhas:
                linha = linha.strip()
                if not linha:
                    continue

                m = regex_linha_pipe.search(linha)
                if not m:
                    m = regex_linha_espaco.search(linha)

                if m:
                    dt_str, desc, valor_str, dc = m.group(1), m.group(2), m.group(3), m.group(4)
                    dt = converter_data(dt_str)
                    val = limpar_valor_monetario(f"{valor_str} {dc}")
                    desc_limpa = re.sub(r"\s+", " ", desc).strip(" |")

                    # Ignora linhas de saldo anterior, saldo do período ou totalizadores
                    if any(ign in desc_limpa.upper() for ign in ["SALDO ANTERIOR", "TOTAL GERAL", "SALDO ATUAL"]):
                        continue

                    if dt and val != 0.0:
                        transacoes.append({
                            "data": dt,
                            "descricao": desc_limpa,
                            "valor": round(val, 2),
                            "origem": "SISTEMA",
                        })

    df = pd.DataFrame(transacoes)
    if df.empty:
        return pd.DataFrame(columns=["data", "descricao", "valor", "origem"])
    return df.sort_values(by=["data", "valor"]).reset_index(drop=True)


def extrair_santander(file_input: Any) -> pd.DataFrame:
    """
    Extrai transações do Extrato Santander Empresas.
    Lê tabelas estruturadas (Data | Descrição | Documento | Valor | Saldo)
    com fallback resiliente para análise linha a linha de texto.
    """
    transacoes = []
    src = _get_pdf_source(file_input)

    with pdfplumber.open(src) as pdf:
        for page in pdf.pages:
            tabela_processada = False
            tabelas = page.extract_tables() or []

            for tabela in tabelas:
                if not tabela:
                    continue
                for row in tabela:
                    cols = [str(c).strip() for c in row if c is not None and str(c).strip()]
                    if len(cols) >= 3:
                        dt = converter_data(cols[0])
                        if not dt:
                            continue

                        desc = cols[1].replace("\n", " ").strip()
                        desc_upper = desc.upper()
                        if any(ign in desc_upper for ign in ["SALDO", "TOTAL", "EXTRATO", "CONTA CORRENTE", "DOCUMENTO"]):
                            continue

                        # Procura o valor monetário nas colunas numéricas
                        val = None
                        for candidate_idx in [-2, -1, 2, 3]:
                            if abs(candidate_idx) <= len(cols):
                                candidate_val = limpar_valor_monetario(cols[candidate_idx])
                                if candidate_val != 0.0:
                                    val = candidate_val
                                    break

                        if dt and val is not None and val != 0.0:
                            transacoes.append({
                                "data": dt,
                                "descricao": re.sub(r"\s+", " ", desc).strip(),
                                "valor": round(val, 2),
                                "origem": "BANCO",
                            })
                            tabela_processada = True

            # Fallback por linhas de texto caso a tabela nativa não tenha detectado linhas
            if not tabela_processada:
                texto = page.extract_text() or ""
                regex_santander_linha = re.compile(
                    r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?[\d\.,]+(?:\s*[DC]|-)?)\s+(-?[\d\.,]+)?$"
                )
                for linha in texto.split("\n"):
                    linha = linha.strip()
                    m = regex_santander_linha.search(linha)
                    if m:
                        dt = converter_data(m.group(1))
                        desc = m.group(2).strip()
                        if any(ign in desc.upper() for ign in ["SALDO", "TOTAL", "RENDIMENTO", "APLICACAO"]):
                            continue
                        val = limpar_valor_monetario(m.group(3))
                        if dt and val != 0.0:
                            transacoes.append({
                                "data": dt,
                                "descricao": re.sub(r"\s+", " ", desc).strip(),
                                "valor": round(val, 2),
                                "origem": "BANCO",
                            })

    df = pd.DataFrame(transacoes)
    if df.empty:
        return pd.DataFrame(columns=["data", "descricao", "valor", "origem"])
    return df.sort_values(by=["data", "valor"]).reset_index(drop=True)


# Aliases para compatibilidade
parse_bank_statement = extrair_santander
parse_system_report = extrair_sistema