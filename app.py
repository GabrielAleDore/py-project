"""
app.py
------
Streamlit UI for the Financial PDF Reconciliation tool.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

import pandas as pd
import streamlit as st

from engine import ReconciliationEngine
from parsers import parse_bank_statement, parse_system_report

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Conciliação Financeira",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS – premium dark-glassmorphism theme
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Root & Body ─────────────────────────────────────── */
:root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-glass: rgba(255,255,255,0.04);
    --bg-glass-hover: rgba(255,255,255,0.08);
    --border: rgba(255,255,255,0.08);
    --border-accent: rgba(99,179,237,0.4);
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --accent-blue: #58a6ff;
    --accent-green: #3fb950;
    --accent-orange: #d29922;
    --accent-red: #f85149;
    --accent-purple: #bc8cff;
    --accent-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    --success-gradient: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
    --warning-gradient: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    --card-shadow: 0 8px 32px rgba(0,0,0,0.37);
}

html, body, [class*="st-"], .stApp {
    font-family: 'Inter', sans-serif !important;
    background-color: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}

/* ── Sidebar ─────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] * {
    color: var(--text-primary) !important;
}

/* ── Header strip ────────────────────────────────────── */
.app-header {
    background: var(--accent-gradient);
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 24px;
    box-shadow: var(--card-shadow);
    position: relative;
    overflow: hidden;
}
.app-header::before {
    content: '';
    position: absolute;
    top: -40%;
    right: -10%;
    width: 300px;
    height: 300px;
    background: rgba(255,255,255,0.05);
    border-radius: 50%;
}
.app-header h1 {
    font-size: 2rem;
    font-weight: 800;
    color: #fff !important;
    margin: 0;
    letter-spacing: -0.5px;
}
.app-header p {
    color: rgba(255,255,255,0.75) !important;
    margin: 6px 0 0;
    font-size: 0.95rem;
}

/* ── Metric cards ────────────────────────────────────── */
.metric-card {
    background: var(--bg-glass);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 24px;
    backdrop-filter: blur(12px);
    transition: all 0.25s ease;
    box-shadow: var(--card-shadow);
}
.metric-card:hover {
    background: var(--bg-glass-hover);
    border-color: var(--border-accent);
    transform: translateY(-2px);
}
.metric-card .label {
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-secondary);
    margin-bottom: 8px;
}
.metric-card .value {
    font-size: 2rem;
    font-weight: 800;
    line-height: 1;
}
.metric-card .sub {
    font-size: 0.78rem;
    color: var(--text-secondary);
    margin-top: 6px;
}
.val-green  { color: var(--accent-green)  !important; }
.val-orange { color: var(--accent-orange) !important; }
.val-blue   { color: var(--accent-blue)   !important; }
.val-red    { color: var(--accent-red)    !important; }
.val-purple { color: var(--accent-purple) !important; }
.val-white  { color: var(--text-primary)  !important; }

/* ── Progress bar override ───────────────────────────── */
.stProgress > div > div > div > div {
    background: var(--accent-gradient) !important;
}

/* ── File uploader ───────────────────────────────────── */
[data-testid="stFileUploader"] {
    background: var(--bg-glass) !important;
    border: 1px dashed var(--border-accent) !important;
    border-radius: 12px !important;
    transition: all 0.2s ease !important;
}
[data-testid="stFileUploader"]:hover {
    background: var(--bg-glass-hover) !important;
    border-color: var(--accent-blue) !important;
}

/* ── Buttons ─────────────────────────────────────────── */
.stButton > button {
    background: var(--accent-gradient) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 10px 28px !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 4px 15px rgba(102,126,234,0.35) !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(102,126,234,0.5) !important;
}
.stButton > button:active {
    transform: translateY(0) !important;
}

/* ── Download button ─────────────────────────────────── */
[data-testid="stDownloadButton"] > button {
    background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%) !important;
    box-shadow: 0 4px 15px rgba(17,153,142,0.35) !important;
}
[data-testid="stDownloadButton"] > button:hover {
    box-shadow: 0 6px 20px rgba(17,153,142,0.5) !important;
}

/* ── Dataframe / table ───────────────────────────────── */
[data-testid="stDataFrame"] {
    background: var(--bg-secondary) !important;
    border-radius: 12px !important;
    border: 1px solid var(--border) !important;
    overflow: hidden !important;
}

/* ── Slider, select, number_input ───────────────────── */
.stSlider [data-baseweb="slider"] {
    padding-top: 4px;
}
.stSelectbox [data-baseweb="select"] > div,
.stNumberInput input {
    background: var(--bg-glass) !important;
    border-color: var(--border) !important;
    color: var(--text-primary) !important;
    border-radius: 8px !important;
}

/* ── Tabs ────────────────────────────────────────────── */
[data-baseweb="tab-list"] {
    background: var(--bg-secondary) !important;
    border-radius: 10px !important;
    padding: 4px !important;
    gap: 4px !important;
    border: 1px solid var(--border) !important;
}
[data-baseweb="tab"] {
    border-radius: 8px !important;
    font-weight: 500 !important;
    color: var(--text-secondary) !important;
}
[aria-selected="true"][data-baseweb="tab"] {
    background: var(--accent-gradient) !important;
    color: #fff !important;
}

/* ── Expander ────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: var(--bg-glass) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}

/* ── Alert / info boxes ──────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
}

/* ── Section divider ─────────────────────────────────── */
.section-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text-primary);
    margin: 24px 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 8px;
}

/* ── Badge tags ──────────────────────────────────────── */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.04em;
}
.badge-green  { background: rgba(63,185,80,0.15); color: #3fb950; border: 1px solid rgba(63,185,80,0.3); }
.badge-orange { background: rgba(210,153,34,0.15); color: #d29922; border: 1px solid rgba(210,153,34,0.3); }
.badge-blue   { background: rgba(88,166,255,0.15); color: #58a6ff; border: 1px solid rgba(88,166,255,0.3); }
.badge-red    { background: rgba(248,81,73,0.15); color: #f85149; border: 1px solid rgba(248,81,73,0.3); }

/* ── Scrollbar ───────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border-accent); border-radius: 3px; }

/* ── Spinner ─────────────────────────────────────────── */
.stSpinner { color: var(--accent-blue) !important; }
</style>
"""


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _init_state() -> None:
    defaults: dict[str, Any] = {
        "bank_df": None,
        "system_df": None,
        "report": None,
        "result_df": None,
        "elapsed": None,
        "bank_filename": "",
        "system_filename": "",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _get_sample_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retorna dados fictícios realistas para demonstrar todos os casos de conciliação."""
    bank_data = [
        {"date": pd.Timestamp("2024-05-10"), "description": "PIX RECEBIDO - CLIENTE JOAO SILVA", "value": 1500.00, "doc": "00142"},
        {"date": pd.Timestamp("2024-05-12"), "description": "TED RECEBIDA EMPRESA ALFA LTDA", "value": 3450.80, "doc": "98231"},
        {"date": pd.Timestamp("2024-05-14"), "description": "PGTO FORNECEDOR ABC SERVICOS", "value": -890.00, "doc": "55210"},
        {"date": pd.Timestamp("2024-05-15"), "description": "PIX ENVIADO - ALUGUEL SALA 302", "value": -2200.00, "doc": "88123"},
        {"date": pd.Timestamp("2024-05-18"), "description": "TARIFA PACOTE SERVICOS BANCARIOS", "value": -59.90, "doc": "00000"},
        {"date": pd.Timestamp("2024-05-20"), "description": "RECEBIMENTO CARTAO CREDITO REDE", "value": 4120.50, "doc": "77100"},
    ]
    system_data = [
        {"date": pd.Timestamp("2024-05-10"), "description": "Venda #1042 - Joao Silva (PIX)", "value": 1500.00, "doc": "00142"},
        {"date": pd.Timestamp("2024-05-10"), "description": "Faturamento NF 892 Alfa Ltda", "value": 3450.80, "doc": "NF-892"},
        {"date": pd.Timestamp("2024-05-13"), "description": "Fornec ABC Servicos Manutencao", "value": -895.00, "doc": "55210"},
        {"date": pd.Timestamp("2024-05-15"), "description": "Aluguel Predio Comercial Sala 302", "value": -2200.00, "doc": "88123"},
        {"date": pd.Timestamp("2024-05-22"), "description": "Venda Pendente #1099 - Maria Souza", "value": 720.00, "doc": "NF-1099"},
        {"date": pd.Timestamp("2024-05-20"), "description": "Fechamento Lote Cartoes Credito", "value": 4120.50, "doc": "LOTE-77"},
    ]
    return pd.DataFrame(bank_data), pd.DataFrame(system_data)


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _to_excel_bytes(report_df: pd.DataFrame, bank_df: pd.DataFrame, system_df: pd.DataFrame) -> bytes:
    """Export the reconciliation report + raw data to a multi-sheet Excel file."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        # Sheet 1 – Summary
        _write_summary_sheet(writer, report_df)
        # Sheet 2 – Full reconciliation
        report_df.to_excel(writer, sheet_name="Conciliação Completa", index=False)
        # Sheet 3 – Matched only
        matched = report_df[~report_df["Tipo de Correspondência"].str.contains("Sem Correspondência")]
        matched.to_excel(writer, sheet_name="Correspondências", index=False)
        # Sheet 4 – Unmatched only
        unmatched = report_df[report_df["Tipo de Correspondência"].str.contains("Sem Correspondência")]
        unmatched.to_excel(writer, sheet_name="Sem Correspondência", index=False)
        # Sheet 5 – Raw bank
        bank_df.to_excel(writer, sheet_name="Extrato Bancário (Raw)", index=False)
        # Sheet 6 – Raw system
        system_df.to_excel(writer, sheet_name="Extrato Sistema (Raw)", index=False)

        _apply_excel_styles(writer)
    buf.seek(0)
    return buf.read()


def _write_summary_sheet(writer: pd.ExcelWriter, df: pd.DataFrame) -> None:
    wb = writer.book
    ws = wb.add_worksheet("Resumo Executivo")
    writer.sheets["Resumo Executivo"] = ws

    title_fmt = wb.add_format({"bold": True, "font_size": 16, "font_color": "#667eea"})
    header_fmt = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#667eea", "border": 1})
    cell_fmt = wb.add_format({"border": 1})

    ws.write("A1", "📊 Resumo da Conciliação Financeira", title_fmt)
    ws.set_column("A:B", 35)

    total = len(df)
    matched = df[~df["Tipo de Correspondência"].str.contains("Sem Correspondência")]
    unmatched = df[df["Tipo de Correspondência"].str.contains("Sem Correspondência")]
    exact = df[df["Tipo de Correspondência"].str.contains("Exato")]
    sliding = df[df["Tipo de Correspondência"].str.contains("Janela")]
    fuzzy = df[df["Tipo de Correspondência"].str.contains("Fuzzy")]
    rate = round(len(matched) / max(total, 1) * 100, 2)

    rows = [
        ("Métrica", "Valor"),
        ("Total de Registros", total),
        ("Correspondências Exatas", len(exact)),
        ("Correspondências Janela Deslizante", len(sliding)),
        ("Correspondências Fuzzy", len(fuzzy)),
        ("Total Correspondências", len(matched)),
        ("Sem Correspondência", len(unmatched)),
        ("Taxa de Conciliação (%)", rate),
    ]
    for i, (k, v) in enumerate(rows, start=3):
        fmt = header_fmt if i == 3 else cell_fmt
        ws.write(i, 0, k, fmt)
        ws.write(i, 1, v, fmt)


def _apply_excel_styles(writer: pd.ExcelWriter) -> None:
    wb = writer.book
    header_fmt = wb.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#667eea",
        "border": 1,
        "align": "center",
        "valign": "vcenter",
    })
    for sheet_name in ["Conciliação Completa", "Correspondências", "Sem Correspondência"]:
        if sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            ws.set_row(0, 22, header_fmt)
            ws.set_column("A:M", 22)


def _to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------

def render_header() -> None:
    st.markdown("""
    <div class="app-header">
        <h1>💳 Conciliação Financeira</h1>
        <p>Reconciliação automática entre Extrato Bancário e Extrato do Sistema</p>
    </div>
    """, unsafe_allow_html=True)


def render_metric_card(label: str, value: str, sub: str, color_class: str) -> str:
    return f"""
    <div class="metric-card">
        <div class="label">{label}</div>
        <div class="value {color_class}">{value}</div>
        <div class="sub">{sub}</div>
    </div>
    """


def render_metrics(report: Any) -> None:
    st.markdown('<div class="section-title">📊 Métricas da Conciliação</div>', unsafe_allow_html=True)

    cols = st.columns(6)
    cards = [
        ("Taxa de Conciliação", f"{report.match_rate}%", f"{report.matched_count} de {report.total_bank} lançamentos", "val-green"),
        ("Correspondências Exatas", str(report.exact_count), "Mesma data e valor", "val-blue"),
        ("Janela Deslizante", str(report.sliding_count), f"Mesmo valor ±{st.session_state.get('window_days', 5)} dias", "val-orange"),
        ("Correspondências Fuzzy", str(report.fuzzy_count), "Valor aprox. + similaridade", "val-purple"),
        ("Sem Corr. Banco", str(report.unmatched_bank), "Apenas no extrato bancário", "val-red"),
        ("Sem Corr. Sistema", str(report.unmatched_system), "Apenas no sistema", "val-red"),
    ]

    for col, (label, value, sub, color) in zip(cols, cards):
        with col:
            st.markdown(render_metric_card(label, value, sub, color), unsafe_allow_html=True)

    # Match-rate progress bar
    st.markdown("<br>", unsafe_allow_html=True)
    col_prog, col_text = st.columns([4, 1])
    with col_prog:
        st.progress(report.match_rate / 100)
    with col_text:
        st.markdown(
            f"<p style='color:#8b949e;font-size:0.85rem;margin-top:6px;'>{report.match_rate}% conciliado</p>",
            unsafe_allow_html=True,
        )


def render_sidebar() -> dict:
    """Render the sidebar controls and return configuration dict."""
    with st.sidebar:
        st.markdown("## ⚙️ Configurações")
        st.markdown("---")

        st.markdown("### 📁 Upload de Arquivos")
        bank_file = st.file_uploader(
            "Extrato Bancário (PDF)",
            type=["pdf"],
            key="bank_upload",
            help="Faça upload do PDF do extrato bancário",
        )
        system_file = st.file_uploader(
            "Extrato do Sistema (PDF)",
            type=["pdf"],
            key="system_upload",
            help="Faça upload do PDF do extrato do sistema",
        )

        st.markdown("---")
        st.markdown("### 🔧 Parâmetros do Motor")

        window_days = st.slider(
            "Janela de dias (Sliding Window)",
            min_value=0,
            max_value=30,
            value=5,
            step=1,
            key="window_days",
            help="Número máximo de dias de diferença para correspondência por janela deslizante",
        )
        value_pct_tol = st.slider(
            "Tolerância de valor (%)",
            min_value=0.0,
            max_value=10.0,
            value=0.5,
            step=0.1,
            key="value_pct_tol",
            help="Tolerância percentual de diferença de valor para correspondência fuzzy",
        )
        desc_threshold = st.slider(
            "Similaridade mínima de descrição",
            min_value=0,
            max_value=100,
            value=60,
            step=5,
            key="desc_threshold",
            help="Limiar de similaridade textual (0-100) para correspondência fuzzy",
        )

        st.markdown("---")
        run_btn = st.button("🚀 Executar Conciliação", use_container_width=True)
        demo_btn = st.button("🧪 Carregar Dados de Exemplo", use_container_width=True, help="Testa o app imediatamente com transações simuladas")

        st.markdown("---")
        st.markdown(
            "<p style='color:#8b949e;font-size:0.75rem;text-align:center;'>"
            "Conciliação Financeira v1.0<br>Powered by pdfplumber + thefuzz"
            "</p>",
            unsafe_allow_html=True,
        )

    return {
        "bank_file": bank_file,
        "system_file": system_file,
        "window_days": window_days,
        "value_pct_tol": value_pct_tol,
        "desc_threshold": desc_threshold,
        "run": run_btn,
        "demo": demo_btn,
    }


def render_results(report_df: pd.DataFrame, report: Any, elapsed: float) -> None:
    """Render all result tabs."""

    # ── Metrics ──────────────────────────────────────────────────────────
    render_metrics(report)

    st.markdown(
        f"<p style='color:#8b949e;font-size:0.82rem;'>⏱️ Conciliação concluída em {elapsed:.2f}s</p>",
        unsafe_allow_html=True,
    )

    # ── Tabs ──────────────────────────────────────────────────────────────
    tab_all, tab_matched, tab_unmatched, tab_raw = st.tabs(
        ["📋 Todos os Registros", "✅ Correspondências", "❌ Sem Correspondência", "🔍 Dados Brutos"]
    )

    with tab_all:
        _render_full_table(report_df)

    with tab_matched:
        matched = report_df[~report_df["Tipo de Correspondência"].str.contains("Sem Correspondência")]
        _render_full_table(matched, empty_msg="Nenhuma correspondência encontrada.")

    with tab_unmatched:
        unmatched = report_df[report_df["Tipo de Correspondência"].str.contains("Sem Correspondência")]
        if unmatched.empty:
            st.success("🎉 Todos os lançamentos foram conciliados!")
        else:
            st.warning(f"⚠️ {len(unmatched)} lançamentos sem correspondência")
            _render_full_table(unmatched)

    with tab_raw:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**📄 Extrato Bancário Processado**")
            st.dataframe(st.session_state.bank_df, use_container_width=True, height=400)
        with col2:
            st.markdown("**🖥️ Extrato do Sistema Processado**")
            st.dataframe(st.session_state.system_df, use_container_width=True, height=400)

    # ── Downloads ─────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">⬇️ Exportar Resultados</div>', unsafe_allow_html=True)
    col_xl, col_csv, _ = st.columns([1, 1, 2])

    with col_xl:
        excel_bytes = _to_excel_bytes(
            report_df,
            st.session_state.bank_df,
            st.session_state.system_df,
        )
        st.download_button(
            label="📥 Exportar Excel (.xlsx)",
            data=excel_bytes,
            file_name="conciliacao_financeira.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with col_csv:
        csv_bytes = _to_csv_bytes(report_df)
        st.download_button(
            label="📄 Exportar CSV",
            data=csv_bytes,
            file_name="conciliacao_financeira.csv",
            mime="text/csv",
            use_container_width=True,
        )


def _render_full_table(df: pd.DataFrame, empty_msg: str = "Nenhum dado disponível.") -> None:
    if df.empty:
        st.info(empty_msg)
        return

    # Color-code the "Tipo de Correspondência" column with pandas Styler
    def style_kind(val: str) -> str:
        if "Exato" in val:
            return "color: #3fb950; font-weight: 600;"
        if "Janela" in val:
            return "color: #d29922; font-weight: 600;"
        if "Fuzzy" in val:
            return "color: #58a6ff; font-weight: 600;"
        if "Sem Correspondência" in val:
            return "color: #f85149; font-weight: 600;"
        return ""

    style_func = getattr(df.style, "map", getattr(df.style, "applymap", None))
    styled = style_func(style_kind, subset=["Tipo de Correspondência"])
    st.dataframe(styled, use_container_width=True, height=500)


def render_empty_state() -> bool:
    """Render the landing / upload-prompt state. Retorna True se o usuario clicou no botao de demo."""
    st.markdown("""
    <div style="
        text-align: center;
        padding: 50px 40px 30px;
        background: rgba(255,255,255,0.03);
        border: 1px dashed rgba(255,255,255,0.1);
        border-radius: 20px;
        margin: 30px 0;
    ">
        <div style="font-size:3.5rem; margin-bottom:12px;">📂</div>
        <h2 style="color:#e6edf3; font-weight:700; margin:0;">Pronto para Conciliar</h2>
        <p style="color:#8b949e; margin-top:8px; font-size:0.95rem;">
            Faça upload dos arquivos PDF na barra lateral e clique em<br>
            <strong style="color:#58a6ff;">🚀 Executar Conciliação</strong> para começar, ou experimente a demonstração.
        </p>
        <br>
        <div style="display:flex; justify-content:center; gap:24px; flex-wrap:wrap; margin-top:8px;">
            <div style="background:rgba(99,179,237,0.08);border:1px solid rgba(99,179,237,0.2);border-radius:12px;padding:16px 24px;">
                <div style="font-size:1.5rem;">🏦</div>
                <div style="color:#8b949e;font-size:0.8rem;margin-top:4px;">Extrato Bancário</div>
            </div>
            <div style="font-size:1.8rem;display:flex;align-items:center;color:#667eea;">⟷</div>
            <div style="background:rgba(99,179,237,0.08);border:1px solid rgba(99,179,237,0.2);border-radius:12px;padding:16px 24px;">
                <div style="font-size:1.5rem;">🖥️</div>
                <div style="color:#8b949e;font-size:0.8rem;margin-top:4px;">Extrato do Sistema</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 2, 1])
    demo_clicked = False
    with c2:
        if st.button("🧪 Carregar Demonstração com Valores Fictícios", type="primary", use_container_width=True):
            demo_clicked = True

    # Feature cards
    st.markdown('<div class="section-title">✨ Recursos</div>', unsafe_allow_html=True)
    f1, f2, f3, f4 = st.columns(4)
    features = [
        ("✅", "Correspondência Exata", "Data + valor 100% idênticos"),
        ("🔶", "Janela Deslizante", "Mesmo valor em janela de N dias"),
        ("🔵", "Correspondência Fuzzy", "Valor aprox. + similaridade textual"),
        ("📥", "Exportação Rich", "Excel multi-aba + CSV"),
    ]
    for col, (icon, title, desc) in zip([f1, f2, f3, f4], features):
        with col:
            st.markdown(f"""
            <div class="metric-card" style="text-align:center;">
                <div style="font-size:2rem;">{icon}</div>
                <div style="font-weight:700;margin:8px 0 4px;font-size:0.9rem;">{title}</div>
                <div class="sub">{desc}</div>
            </div>
            """, unsafe_allow_html=True)

    return demo_clicked


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main() -> None:
    _init_state()
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    render_header()

    config = render_sidebar()

    # ── Run reconciliation ─────────────────────────────────────────────
    if config["run"]:
        bank_file = config["bank_file"]
        system_file = config["system_file"]

        if not bank_file or not system_file:
            st.error("⚠️ Por favor, faça upload dos dois arquivos PDF antes de executar.")
            st.stop()

        with st.spinner("⚙️ Processando arquivos PDF..."):
            bank_bytes = bank_file.read()
            system_bytes = system_file.read()

            try:
                bank_df = parse_bank_statement(bank_bytes)
                system_df = parse_system_report(system_bytes)
            except Exception as exc:
                st.error(f"❌ Erro ao processar os PDFs: {exc}")
                logger.exception("PDF parsing error")
                st.stop()

        if bank_df.empty and system_df.empty:
            st.error(
                "❌ Não foi possível extrair transações de nenhum dos PDFs. "
                "Verifique se os arquivos são extratos financeiros válidos."
            )
            st.stop()

        if bank_df.empty:
            st.warning("⚠️ Nenhuma transação extraída do Extrato Bancário.")
        if system_df.empty:
            st.warning("⚠️ Nenhuma transação extraída do Extrato do Sistema.")

        with st.spinner("🔄 Executando algoritmo de conciliação..."):
            engine = ReconciliationEngine(
                window_days=config["window_days"],
                value_pct_tol=config["value_pct_tol"],
                desc_threshold=config["desc_threshold"],
            )
            t0 = time.perf_counter()
            report = engine.reconcile(bank_df, system_df)
            elapsed = time.perf_counter() - t0

        result_df = report.to_dataframe()

        # Persist to session state
        st.session_state.bank_df = bank_df
        st.session_state.system_df = system_df
        st.session_state.report = report
        st.session_state.result_df = result_df
        st.session_state.elapsed = elapsed
        st.session_state.bank_filename = bank_file.name
        st.session_state.system_filename = system_file.name

        st.success(f"✅ Conciliação concluída! {report.match_rate}% de taxa de conciliação.")

    elif config["demo"]:
        with st.spinner("🔄 Carregando dados fictícios de demonstração..."):
            bank_df, system_df = _get_sample_data()
            engine = ReconciliationEngine(
                window_days=config["window_days"],
                value_pct_tol=config["value_pct_tol"],
                desc_threshold=config["desc_threshold"],
            )
            t0 = time.perf_counter()
            report = engine.reconcile(bank_df, system_df)
            elapsed = time.perf_counter() - t0

            st.session_state.bank_df = bank_df
            st.session_state.system_df = system_df
            st.session_state.report = report
            st.session_state.result_df = report.to_dataframe()
            st.session_state.elapsed = elapsed
            st.session_state.bank_filename = "Extrato_Bancario_Exemplo.pdf"
            st.session_state.system_filename = "Extrato_Sistema_Exemplo.pdf"
            st.success(f"✅ Exemplo carregado! Taxa de conciliação: {report.match_rate}%")

    # ── Render results or empty state ──────────────────────────────────
    if st.session_state.report is not None:
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            st.info(f"🏦 **Banco:** {st.session_state.bank_filename}  |  {len(st.session_state.bank_df)} transações")
        with c2:
            st.info(f"🖥️ **Sistema:** {st.session_state.system_filename}  |  {len(st.session_state.system_df)} transações")
        with c3:
            if st.button("🔄 Nova Consulta", use_container_width=True):
                st.session_state.report = None
                st.session_state.result_df = None
                st.rerun()

        render_results(
            st.session_state.result_df,
            st.session_state.report,
            st.session_state.elapsed,
        )
    else:
        empty_demo = render_empty_state()
        if empty_demo:
            with st.spinner("🔄 Carregando dados fictícios de demonstração..."):
                bank_df, system_df = _get_sample_data()
                engine = ReconciliationEngine(
                    window_days=config["window_days"],
                    value_pct_tol=config["value_pct_tol"],
                    desc_threshold=config["desc_threshold"],
                )
                t0 = time.perf_counter()
                report = engine.reconcile(bank_df, system_df)
                elapsed = time.perf_counter() - t0

                st.session_state.bank_df = bank_df
                st.session_state.system_df = system_df
                st.session_state.report = report
                st.session_state.result_df = report.to_dataframe()
                st.session_state.elapsed = elapsed
                st.session_state.bank_filename = "Extrato_Bancario_Exemplo.pdf"
                st.session_state.system_filename = "Extrato_Sistema_Exemplo.pdf"
                st.rerun()


if __name__ == "__main__":
    main()
