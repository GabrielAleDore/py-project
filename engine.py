"""
engine.py
---------
Core reconciliation algorithm.

Matching strategy (applied in order, with diminishing tolerance):
  1. Exact Match   – same date + same value (to 2 decimal places)
  2. Sliding Window – same value, date within N days (configurable)
  3. Fuzzy Match   – same date ± N days, value within P% tolerance,
                     description similarity ≥ threshold (thefuzz)
  4. Unmatched     – transactions that could not be paired

All pairings are one-to-one: once a transaction is consumed it is
removed from the available pool.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

import pandas as pd
from thefuzz import fuzz

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

MatchKind = Literal["exact", "sliding_window", "fuzzy", "unmatched"]


@dataclass
class MatchResult:
    """
    Represents a single reconciliation outcome.
    Either bank_idx or system_idx may be None for unmatched rows.
    """

    kind: MatchKind
    bank_idx: int | None
    system_idx: int | None
    bank_date: object = None
    bank_desc: str = ""
    bank_value: float | None = None
    bank_doc: str | None = None
    system_date: object = None
    system_desc: str = ""
    system_value: float | None = None
    system_doc: str | None = None
    value_diff: float | None = None
    date_diff_days: int | None = None
    desc_similarity: int | None = None  # 0-100


@dataclass
class ReconciliationReport:
    matches: list[MatchResult] = field(default_factory=list)

    # ---------- summary helpers ----------

    @property
    def total_bank(self) -> int:
        return sum(1 for m in self.matches if m.bank_idx is not None)

    @property
    def total_system(self) -> int:
        return sum(1 for m in self.matches if m.system_idx is not None)

    @property
    def exact_count(self) -> int:
        return sum(1 for m in self.matches if m.kind == "exact")

    @property
    def sliding_count(self) -> int:
        return sum(1 for m in self.matches if m.kind == "sliding_window")

    @property
    def fuzzy_count(self) -> int:
        return sum(1 for m in self.matches if m.kind == "fuzzy")

    @property
    def unmatched_bank(self) -> int:
        return sum(
            1 for m in self.matches if m.kind == "unmatched" and m.bank_idx is not None
        )

    @property
    def unmatched_system(self) -> int:
        return sum(
            1 for m in self.matches if m.kind == "unmatched" and m.system_idx is not None
        )

    @property
    def matched_count(self) -> int:
        return self.exact_count + self.sliding_count + self.fuzzy_count

    @property
    def match_rate(self) -> float:
        total = self.total_bank
        if total == 0:
            return 0.0
        return round(self.matched_count / total * 100, 2)

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for m in self.matches:
            rows.append(
                {
                    "Tipo de Correspondência": _kind_label(m.kind),
                    "Data Banco": _fmt_date(m.bank_date),
                    "Descrição Banco": m.bank_desc,
                    "Valor Banco (R$)": m.bank_value,
                    "Doc Banco": m.bank_doc or "",
                    "Data Sistema": _fmt_date(m.system_date),
                    "Descrição Sistema": m.system_desc,
                    "Valor Sistema (R$)": m.system_value,
                    "Doc Sistema": m.system_doc or "",
                    "Diferença Valor (R$)": m.value_diff,
                    "Diferença Dias": m.date_diff_days,
                    "Similaridade Descrição (%)": m.desc_similarity,
                }
            )
        return pd.DataFrame(rows)


def _kind_label(kind: MatchKind) -> str:
    return {
        "exact": "✅ Exato",
        "sliding_window": "🔶 Janela Deslizante",
        "fuzzy": "🔵 Fuzzy",
        "unmatched": "❌ Sem Correspondência",
    }.get(kind, kind)


def _fmt_date(d: object) -> str:
    if d is None:
        return ""
    try:
        return d.strftime("%d/%m/%Y")  # type: ignore[union-attr]
    except Exception:
        return str(d)


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _values_close(v1: float | None, v2: float | None, pct_tol: float) -> bool:
    """Return True if two values are within pct_tol percent of each other."""
    if v1 is None or v2 is None:
        return False
    if v1 == 0 and v2 == 0:
        return True
    if v1 == 0 or v2 == 0:
        return abs(v1 - v2) < 0.01  # treat zero specially
    return abs(v1 - v2) / max(abs(v1), abs(v2)) <= pct_tol / 100


def _desc_similarity(d1: str, d2: str) -> int:
    """Compute token-set-ratio similarity between two description strings."""
    if not d1 and not d2:
        return 100
    if not d1 or not d2:
        return 0
    return fuzz.token_set_ratio(d1.lower(), d2.lower())


def _date_diff(d1: object, d2: object) -> int | None:
    """Return absolute day difference between two dates, or None if either is null."""
    if d1 is None or d2 is None:
        return None
    try:
        return abs((d1 - d2).days)  # type: ignore[operator]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core reconciliation engine
# ---------------------------------------------------------------------------

class ReconciliationEngine:
    """
    Performs multi-pass transaction matching between bank and system extracts.

    Parameters
    ----------
    window_days : int
        Maximum day offset allowed for sliding-window and fuzzy matches.
    value_pct_tol : float
        Maximum value difference (as % of larger value) for fuzzy matches.
    desc_threshold : int
        Minimum description similarity (0-100) required for fuzzy matches.
    """

    def __init__(
        self,
        window_days: int = 5,
        value_pct_tol: float = 0.5,
        desc_threshold: int = 60,
    ) -> None:
        self.window_days = window_days
        self.value_pct_tol = value_pct_tol
        self.desc_threshold = desc_threshold

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def reconcile(
        self,
        bank_df: pd.DataFrame,
        system_df: pd.DataFrame,
    ) -> ReconciliationReport:
        """
        Run the full reconciliation pipeline.

        Parameters
        ----------
        bank_df    : Normalised bank DataFrame (output of parsers.parse_bank_statement)
        system_df  : Normalised system DataFrame (output of parsers.parse_system_report)

        Returns
        -------
        ReconciliationReport
        """
        report = ReconciliationReport()

        # Work on copies with integer indices for easy removal
        bank = bank_df.copy().reset_index(drop=True)
        system = system_df.copy().reset_index(drop=True)

        available_bank = set(bank.index.tolist())
        available_sys = set(system.index.tolist())

        # ── Pass 1: Exact match (same date + same value) ──────────────
        logger.info("Pass 1: Exact match")
        matched_b, matched_s = self._exact_match(bank, system, available_bank, available_sys)
        for bi, si in zip(matched_b, matched_s):
            report.matches.append(self._build_result("exact", bank, system, bi, si))
        available_bank -= set(matched_b)
        available_sys -= set(matched_s)

        # ── Pass 2: Sliding-window match (same value, ±N days) ────────
        logger.info("Pass 2: Sliding-window match (window=%d days)", self.window_days)
        matched_b, matched_s = self._sliding_window_match(
            bank, system, available_bank, available_sys
        )
        for bi, si in zip(matched_b, matched_s):
            report.matches.append(self._build_result("sliding_window", bank, system, bi, si))
        available_bank -= set(matched_b)
        available_sys -= set(matched_s)

        # ── Pass 3: Fuzzy match ────────────────────────────────────────
        logger.info(
            "Pass 3: Fuzzy match (value_tol=%.1f%%, desc_threshold=%d)",
            self.value_pct_tol, self.desc_threshold,
        )
        matched_b, matched_s = self._fuzzy_match(
            bank, system, available_bank, available_sys
        )
        for bi, si in zip(matched_b, matched_s):
            report.matches.append(self._build_result("fuzzy", bank, system, bi, si))
        available_bank -= set(matched_b)
        available_sys -= set(matched_s)

        # ── Pass 4: Unmatched ──────────────────────────────────────────
        for bi in sorted(available_bank):
            report.matches.append(self._build_unmatched_bank(bank, bi))
        for si in sorted(available_sys):
            report.matches.append(self._build_unmatched_system(system, si))

        logger.info(
            "Reconciliation complete: %d exact, %d sliding, %d fuzzy, "
            "%d unmatched_bank, %d unmatched_system",
            report.exact_count,
            report.sliding_count,
            report.fuzzy_count,
            report.unmatched_bank,
            report.unmatched_system,
        )
        return report

    # ------------------------------------------------------------------
    # Pass 1 – Exact match
    # ------------------------------------------------------------------

    def _exact_match(
        self,
        bank: pd.DataFrame,
        system: pd.DataFrame,
        avail_b: set[int],
        avail_s: set[int],
    ) -> tuple[list[int], list[int]]:
        matched_b: list[int] = []
        matched_s: list[int] = []

        # Build lookup: (date_str, rounded_value) -> list of system indices
        sys_lookup: dict[tuple, list[int]] = {}
        for si in avail_s:
            row = system.loc[si]
            key = self._exact_key(row)
            if key:
                sys_lookup.setdefault(key, []).append(si)

        remaining_sys = set(avail_s)

        for bi in sorted(avail_b):
            row_b = bank.loc[bi]
            key = self._exact_key(row_b)
            if not key:
                continue
            candidates = [si for si in sys_lookup.get(key, []) if si in remaining_sys]
            if candidates:
                si = candidates[0]
                matched_b.append(bi)
                matched_s.append(si)
                remaining_sys.discard(si)

        return matched_b, matched_s

    def _exact_key(self, row: pd.Series) -> tuple | None:
        """Create a hashable key for exact matching."""
        date = row.get("date")
        value = row.get("value")
        if date is None or value is None:
            return None
        try:
            date_str = date.strftime("%Y-%m-%d")
        except Exception:
            return None
        return (date_str, round(float(value), 2))

    # ------------------------------------------------------------------
    # Pass 2 – Sliding-window match
    # ------------------------------------------------------------------

    def _sliding_window_match(
        self,
        bank: pd.DataFrame,
        system: pd.DataFrame,
        avail_b: set[int],
        avail_s: set[int],
    ) -> tuple[list[int], list[int]]:
        matched_b: list[int] = []
        matched_s: list[int] = []
        remaining_sys = set(avail_s)

        for bi in sorted(avail_b):
            row_b = bank.loc[bi]
            v_b = row_b.get("value")
            d_b = row_b.get("date")
            if v_b is None or d_b is None:
                continue

            best_si: int | None = None
            best_diff: int = self.window_days + 1

            for si in sorted(remaining_sys):
                row_s = system.loc[si]
                v_s = row_s.get("value")
                d_s = row_s.get("date")
                if v_s is None or d_s is None:
                    continue
                if round(float(v_b), 2) != round(float(v_s), 2):
                    continue
                diff = _date_diff(d_b, d_s)
                if diff is None:
                    continue
                if diff <= self.window_days and diff < best_diff:
                    best_diff = diff
                    best_si = si

            if best_si is not None:
                matched_b.append(bi)
                matched_s.append(best_si)
                remaining_sys.discard(best_si)

        return matched_b, matched_s

    # ------------------------------------------------------------------
    # Pass 3 – Fuzzy match
    # ------------------------------------------------------------------

    def _fuzzy_match(
        self,
        bank: pd.DataFrame,
        system: pd.DataFrame,
        avail_b: set[int],
        avail_s: set[int],
    ) -> tuple[list[int], list[int]]:
        """
        Score each (bank, system) candidate pair and greedily pick the
        best-scoring non-conflicting pairs.
        """
        matched_b: list[int] = []
        matched_s: list[int] = []
        remaining_sys = set(avail_s)

        # Build scored candidates
        scored: list[tuple[float, int, int]] = []  # (score, bi, si)
        for bi in sorted(avail_b):
            row_b = bank.loc[bi]
            v_b = row_b.get("value")
            d_b = row_b.get("date")
            desc_b = str(row_b.get("description") or "")
            if v_b is None:
                continue

            for si in sorted(avail_s):
                row_s = system.loc[si]
                v_s = row_s.get("value")
                d_s = row_s.get("date")
                desc_s = str(row_s.get("description") or "")
                if v_s is None:
                    continue

                # Value must be within tolerance
                if not _values_close(v_b, v_s, self.value_pct_tol):
                    continue

                # Date within window
                diff = _date_diff(d_b, d_s)
                if diff is None or diff > self.window_days:
                    continue

                # Description similarity
                sim = _desc_similarity(desc_b, desc_s)
                if sim < self.desc_threshold:
                    continue

                # Score: combine closeness of value, date and description
                val_score = 1 - abs(float(v_b) - float(v_s)) / max(abs(float(v_b)), abs(float(v_s)), 1)
                date_score = 1 - diff / (self.window_days + 1)
                desc_score = sim / 100
                score = val_score * 0.5 + date_score * 0.3 + desc_score * 0.2
                scored.append((score, bi, si))

        # Sort descending by score for greedy one-to-one assignment
        scored.sort(key=lambda x: -x[0])
        used_b: set[int] = set()
        used_s: set[int] = set()

        for score, bi, si in scored:
            if bi in used_b or si not in remaining_sys or si in used_s:
                continue
            matched_b.append(bi)
            matched_s.append(si)
            used_b.add(bi)
            used_s.add(si)
            remaining_sys.discard(si)

        return matched_b, matched_s

    # ------------------------------------------------------------------
    # MatchResult builders
    # ------------------------------------------------------------------

    def _build_result(
        self,
        kind: MatchKind,
        bank: pd.DataFrame,
        system: pd.DataFrame,
        bi: int,
        si: int,
    ) -> MatchResult:
        row_b = bank.loc[bi]
        row_s = system.loc[si]
        v_b = row_b.get("value")
        v_s = row_s.get("value")
        return MatchResult(
            kind=kind,
            bank_idx=bi,
            system_idx=si,
            bank_date=row_b.get("date"),
            bank_desc=str(row_b.get("description") or ""),
            bank_value=float(v_b) if v_b is not None else None,
            bank_doc=str(row_b.get("document") or "") or None,
            system_date=row_s.get("date"),
            system_desc=str(row_s.get("description") or ""),
            system_value=float(v_s) if v_s is not None else None,
            system_doc=str(row_s.get("document") or "") or None,
            value_diff=round(float(v_b) - float(v_s), 2) if (v_b is not None and v_s is not None) else None,
            date_diff_days=_date_diff(row_b.get("date"), row_s.get("date")),
            desc_similarity=_desc_similarity(
                str(row_b.get("description") or ""),
                str(row_s.get("description") or ""),
            ),
        )

    def _build_unmatched_bank(self, bank: pd.DataFrame, bi: int) -> MatchResult:
        row = bank.loc[bi]
        v = row.get("value")
        return MatchResult(
            kind="unmatched",
            bank_idx=bi,
            system_idx=None,
            bank_date=row.get("date"),
            bank_desc=str(row.get("description") or ""),
            bank_value=float(v) if v is not None else None,
            bank_doc=str(row.get("document") or "") or None,
        )

    def _build_unmatched_system(self, system: pd.DataFrame, si: int) -> MatchResult:
        row = system.loc[si]
        v = row.get("value")
        return MatchResult(
            kind="unmatched",
            bank_idx=None,
            system_idx=si,
            system_date=row.get("date"),
            system_desc=str(row.get("description") or ""),
            system_value=float(v) if v is not None else None,
            system_doc=str(row.get("document") or "") or None,
        )
