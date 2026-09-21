"""
parsers.py
----------
Handles PDF extraction for Bank Statements (Extrato Bancário) and
Internal System Reports (Extrato do Sistema).

Strategy:
  1. Try pdfplumber vector table extraction (most accurate for digital PDFs).
  2. Fallback to regex-based line parsing for scanned / inconsistent layouts.
"""

from __future__ import annotations

import re
import logging
from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd
import pdfplumber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

# Date formats tried in order during normalisation
_DATE_FORMATS = [
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d/%m/%y",
    "%d-%m-%y",
    "%m/%d/%Y",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d %B %Y",
]

# Regex that captures Brazilian-style numbers: 1.234,56 or 1234.56 or 1234,56
_VALUE_RE = re.compile(
    r"[-–]?\s*R?\$?\s*([\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)"
)

# Date pattern: dd/mm/yyyy or similar separators
_DATE_RE = re.compile(
    r"\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})\b"
)

# Minimum columns a row must have to be considered a transaction row
_MIN_COLS = 3


# ---------------------------------------------------------------------------
# Public sanitisers
# ---------------------------------------------------------------------------

def sanitize_value(raw: Any) -> float | None:
    """
    Convert a raw cell / string value into a Python float.

    Handles:
     - Brazilian format  : "1.234,56"  -> 1234.56
     - US format         : "1,234.56"  -> 1234.56
     - Plain integer     : "1234"      -> 1234.0
     - Negative prefix   : "(1.234,56)" or "-1.234,56"
     - Currency prefix   : "R$ 1.234,56"
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in ("-", "–", "N/A", "n/a", ""):
        return None

    # Detect parenthetical negatives
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if text.startswith("-") or text.startswith("–"):
        negative = True
        text = text.lstrip("-–").strip()

    # Strip currency symbols
    text = re.sub(r"[R$\s]", "", text)

    # Determine decimal separator by checking last separator character
    # Brazilian: dots as thousands, comma as decimal -> "1.234,56"
    # US:        commas as thousands, dot as decimal -> "1,234.56"
    if "," in text and "." in text:
        last_comma = text.rfind(",")
        last_dot = text.rfind(".")
        if last_comma > last_dot:
            # Brazilian format
            text = text.replace(".", "").replace(",", ".")
        else:
            # US format
            text = text.replace(",", "")
    elif "," in text:
        # Could be "1234,56" (BR) or "1,234" (US without decimals)
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    # else: plain dot-decimal, leave as is

    try:
        value = float(text)
        return -value if negative else value
    except ValueError:
        logger.debug("Could not convert '%s' to float", raw)
        return None


def normalize_date(raw: Any) -> datetime | None:
    """
    Parse a raw date string into a timezone-naive datetime.
    Tries every format in _DATE_FORMATS.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    # Normalise separators to /
    text_norm = re.sub(r"[-\.]", "/", text)

    for fmt in _DATE_FORMATS:
        fmt_norm = re.sub(r"[-\.]", "/", fmt)
        try:
            return datetime.strptime(text_norm, fmt_norm)
        except ValueError:
            pass
    logger.debug("Could not parse date '%s'", raw)
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_header_name(name: Any) -> str:
    if name is None:
        return ""
    return re.sub(r"\s+", " ", str(name)).strip().lower()


def _find_column(columns: list[str], candidates: list[str]) -> str | None:
    """Return the first column name that fuzzy-matches any of the candidates."""
    col_lower = {c: c.lower() for c in columns}
    for candidate in candidates:
        cand_lower = candidate.lower()
        for col, cl in col_lower.items():
            if cand_lower in cl or cl in cand_lower:
                return col
    return None


def _build_dataframe_from_table(rows: list[list], header_row_idx: int = 0) -> pd.DataFrame | None:
    """
    Given a list of raw rows from pdfplumber, try to construct a DataFrame
    with a meaningful header row.
    """
    if not rows or len(rows) < 2:
        return None

    header = [_clean_header_name(c) for c in rows[header_row_idx]]
    data = rows[header_row_idx + 1 :]
    df = pd.DataFrame(data, columns=header if len(header) == len(rows[0]) else None)
    # Drop fully-empty rows
    df.dropna(how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------------
# Vector table extractor (pdfplumber)
# ---------------------------------------------------------------------------

def _extract_tables_pdfplumber(pdf_bytes: bytes) -> list[pd.DataFrame]:
    """
    Use pdfplumber's table-finding algorithm to extract all tables from all
    pages of the PDF.  Returns a list of DataFrames (one per table found).
    """
    dfs: list[pd.DataFrame] = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    df = _build_dataframe_from_table(table)
                    if df is not None and not df.empty:
                        dfs.append(df)
    except Exception as exc:
        logger.warning("pdfplumber table extraction failed: %s", exc)
    return dfs


def _extract_text_pdfplumber(pdf_bytes: bytes) -> str:
    """Extract raw text from all pages."""
    parts: list[str] = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                parts.append(text)
    except Exception as exc:
        logger.warning("pdfplumber text extraction failed: %s", exc)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Regex-based fallback line parser
# ---------------------------------------------------------------------------

def _parse_lines_regex(text: str) -> pd.DataFrame | None:
    """
    Attempt to extract transactions from raw text using regex.
    Each line must contain at least one date-like token and one numeric value.

    Returns a DataFrame with columns: [date_raw, description, value_raw]
    """
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        dates = _DATE_RE.findall(line)
        if not dates:
            continue

        # Find all numeric values in the line
        values = []
        for match in _VALUE_RE.finditer(line):
            val = sanitize_value(match.group(0))
            if val is not None:
                values.append((match.start(), val))

        if not values:
            continue

        date_raw = dates[0]
        # Remove the date from the line to get description + value
        desc_line = _DATE_RE.sub("", line, count=1).strip()
        # The last numeric value is usually the transaction amount
        _, value_raw = values[-1]

        # Description: everything before the last numeric pattern
        last_val_match = list(_VALUE_RE.finditer(desc_line))
        if last_val_match:
            desc = desc_line[: last_val_match[-1].start()].strip(" ,;-")
        else:
            desc = desc_line

        records.append(
            {
                "date_raw": date_raw,
                "description": desc,
                "value_raw": value_raw,
            }
        )

    if not records:
        return None
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Column auto-detection & normalisation
# ---------------------------------------------------------------------------

_DATE_CANDIDATES = [
    "data", "date", "dt", "data lançamento", "data mov", "data transação",
    "competência", "vencimento", "data pagamento", "data pg",
]
_VALUE_CANDIDATES = [
    "valor", "value", "amount", "vlr", "total", "débito", "crédito",
    "debit", "credit", "montante", "r$", "vl movimento",
]
_DESC_CANDIDATES = [
    "descrição", "description", "histórico", "históric", "memo",
    "lançamento", "complemento", "detalhamento", "hist", "obs",
]
_DOC_CANDIDATES = [
    "documento", "doc", "número", "num", "nsu", "id", "referência",
    "cod", "código", "ref",
]


def _auto_detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """
    Attempt to auto-detect which DataFrame columns correspond to
    date / value / description / document.
    """
    cols = list(df.columns)
    return {
        "date": _find_column(cols, _DATE_CANDIDATES),
        "value": _find_column(cols, _VALUE_CANDIDATES),
        "description": _find_column(cols, _DESC_CANDIDATES),
        "document": _find_column(cols, _DOC_CANDIDATES),
    }


def _normalise_extracted_df(
    df: pd.DataFrame,
    mapping: dict[str, str | None],
    source_label: str,
) -> pd.DataFrame:
    """
    Build a standardised transaction DataFrame from a raw extracted df.
    Output columns: [date, description, value, document, source, date_raw, value_raw]
    """
    result = pd.DataFrame()

    # Date
    date_col = mapping.get("date")
    if date_col and date_col in df.columns:
        result["date_raw"] = df[date_col].astype(str)
        result["date"] = df[date_col].apply(normalize_date)
    else:
        result["date_raw"] = None
        result["date"] = None

    # Description
    desc_col = mapping.get("description")
    if desc_col and desc_col in df.columns:
        result["description"] = df[desc_col].astype(str).str.strip()
    else:
        # Fallback: concatenate all non-date, non-value columns
        other_cols = [
            c for c in df.columns
            if c not in (mapping.get("date"), mapping.get("value"), mapping.get("document"))
        ]
        if other_cols:
            result["description"] = df[other_cols].astype(str).agg(" | ".join, axis=1).str.strip()
        else:
            result["description"] = ""

    # Value
    val_col = mapping.get("value")
    if val_col and val_col in df.columns:
        result["value_raw"] = df[val_col].astype(str)
        result["value"] = df[val_col].apply(sanitize_value)
    else:
        result["value_raw"] = None
        result["value"] = None

    # Document / Reference
    doc_col = mapping.get("document")
    if doc_col and doc_col in df.columns:
        result["document"] = df[doc_col].astype(str).str.strip()
    else:
        result["document"] = None

    # Source label
    result["source"] = source_label

    # Drop rows without both date AND value
    result = result[result["date"].notna() | result["value"].notna()].copy()
    result.reset_index(drop=True, inplace=True)
    return result


# ---------------------------------------------------------------------------
# Main public parsing functions
# ---------------------------------------------------------------------------

def parse_bank_statement(pdf_bytes: bytes) -> pd.DataFrame:
    """
    Parse a Bank Statement PDF (Extrato Bancário).

    Returns a standardised DataFrame with columns:
      [date, description, value, document, source, date_raw, value_raw]
    """
    return _parse_pdf(pdf_bytes, source_label="bank")


def parse_system_report(pdf_bytes: bytes) -> pd.DataFrame:
    """
    Parse an Internal System Report PDF (Extrato do Sistema).

    Returns the same standardised schema as parse_bank_statement.
    """
    return _parse_pdf(pdf_bytes, source_label="system")


def _parse_pdf(pdf_bytes: bytes, source_label: str) -> pd.DataFrame:
    """
    Unified PDF parsing pipeline:
      1. Try pdfplumber table extraction
      2. If no tables found or too few rows, fall back to regex line parsing
    """
    # --- Attempt 1: vector table extraction ---
    tables = _extract_tables_pdfplumber(pdf_bytes)
    candidate_dfs: list[pd.DataFrame] = []

    for raw_df in tables:
        if raw_df.empty or len(raw_df) < 2:
            continue
        mapping = _auto_detect_columns(raw_df)
        # Accept table only if we found at least date OR value columns
        if mapping["date"] or mapping["value"]:
            norm_df = _normalise_extracted_df(raw_df, mapping, source_label)
            if not norm_df.empty:
                candidate_dfs.append(norm_df)

    if candidate_dfs:
        combined = pd.concat(candidate_dfs, ignore_index=True)
        combined = combined[combined["value"].notna()].reset_index(drop=True)
        if not combined.empty:
            logger.info(
                "[%s] Extracted %d rows via pdfplumber table extractor",
                source_label, len(combined),
            )
            return combined

    # --- Attempt 2: regex line parser ---
    logger.info("[%s] Falling back to regex line parser", source_label)
    text = _extract_text_pdfplumber(pdf_bytes)
    regex_df = _parse_lines_regex(text)

    if regex_df is None or regex_df.empty:
        logger.warning("[%s] No transactions found in PDF", source_label)
        return _empty_standard_df(source_label)

    # regex_df already has: date_raw, description, value_raw (numeric)
    result = pd.DataFrame()
    result["date_raw"] = regex_df["date_raw"]
    result["date"] = regex_df["date_raw"].apply(normalize_date)
    result["description"] = regex_df["description"]
    result["value_raw"] = regex_df["value_raw"].astype(str)
    result["value"] = regex_df["value_raw"]
    result["document"] = None
    result["source"] = source_label

    result = result[result["value"].notna()].reset_index(drop=True)
    logger.info(
        "[%s] Extracted %d rows via regex parser",
        source_label, len(result),
    )
    return result


def _empty_standard_df(source_label: str) -> pd.DataFrame:
    return pd.DataFrame(
        columns=["date", "description", "value", "document", "source", "date_raw", "value_raw"]
    ).assign(source=source_label)
