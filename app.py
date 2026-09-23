"""
app.py
------
Interface Web Streamlit para Conciliação Financeira Avançada:
Extrato Santander Empresas vs Extrato do Sistema ERP.

Suporta:
- Extração precisa de PDFs tabulares e com pipes
- Match Exato (1-para-1) e Aglutinado (N-para-1 / Subset Sum)
- Detecção de Divergências de Valor (centavos, tarifas, juros)
- Alertas de Anomalias Críticas (transações de alto valor não conciliadas)
- Exportação em Excel multi-aba estilizado e CSV
"""

from __future__ import annotations

import io
import logging
import time
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from engine import conciliar_extratos_avancado
from parsers import extrair_santander, extrair_sistema

# ---------------------------------------------------------------------------
# Configurações do Streamlit e Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Conciliação Financeira | Santander & ERP",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Estilos CSS - Tema Dark Glassmorphism Premium
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

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
    --card-shadow: 0 8px 32px rgba(0,0,0,0.37);
}

html, body, [class*="st-"], .stApp {
    font-family: 'Inter', sans-serif !important;
    background-color: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}

[data-testid="stSidebar"] {
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] * {
    color: var(--text-primary) !important;
}

.app-header {
    background: var(--accent-gradient);
    border-radius: 16px;
    padding: 24px 32px;
    margin-bottom: 24px;
    box-shadow: var(--card-shadow);
    position: relative;
    overflow: hidden;
}
.app-header h1 {
    font-size: 1.85rem;
    font-weight: 800;
    color: #fff !important;
    margin: 0;
    letter-spacing: -0.5px;
}
.app-header p {
    color: rgba(255,255,255,0.85) !important;
    margin: 6px 0 0;
    font-size: 0.95rem;
}

.metric-card {
    background: var(--bg-glass);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 16px 20px;
    backdrop-filter: blur(12px);
    transition: all 0.25s ease;
    box-shadow: var(--card-shadow);
    min-height: 105px;
}
.metric-card:hover {
    background: var(--bg-glass-hover);
    border-color: var(--border-accent);
    transform: translateY(-2px);
}
.metric-card .label {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-secondary);
    margin-bottom: 6px;
}
.metric-card .value {
    font-size: 1.75rem;
    font-weight: 800;
    line-height: 1.1;
}
.metric-card .sub {
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-top: 4px;
}
.val-green  { color: var(--accent-green)  !important; }
.val-orange { color: var(--accent-orange) !important; }
.val-blue   { color: var(--accent-blue)   !important; }
.val-red    { color: var(--accent-red)    !important; }
.val-purple { color: var(--accent-purple) !important; }

[data-testid="stDataFrame"] {
    background: var(--bg-secondary) !important;
    border-radius: 12px !important;
    border: 1px solid var(--border) !important;
}

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

.section-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text-primary);
    margin: 20px 0 12px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 8px;
}

.alert-banner {
    background: rgba(248,81,73,0.12);
    border: 1px solid rgba(248,81,73,0.4);
    border-radius: 12px;
    padding: 14px 18px;
    margin-bottom: 18px;
    display: flex;
    align-items: center;
    gap: 12px;
}
</style>
"""

# ---------------------------------------------------------------------------
# Gerenciamento de Estado
# ---------------------------------------------------------------------------
def _init_state() -> None:
    defaults: dict[str, Any] = {
        "df_banco": None,
        "df_sistema": None,
        "resultado": None,
        "elapsed": None,
        "banco_filename": "",
        "sistema_filename": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _get_sample_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retorna dados de exemplo baseados no layout do Santander Empresas e do ERP Sistema."""
    banco_data = [
        {"data": date(2024, 5, 10), "descricao": "PIX TRANSF CLIENTE ALFA COMERCIO", "valor": 1500.00, "origem": "BANCO"},
        {"data": date(2024, 5, 11), "descricao": "PAGAMENTO LOTE FORNECEDORES - PIX", "valor": -1500.00, "origem": "BANCO"},
        {"data": date(2024, 5, 13), "descricao": "TARIFA CONECTIVIDADE BANCARIA", "valor": -59.90, "origem": "BANCO"},
        {"data": date(2024, 5, 15), "descricao": "TED RECEBIDA - OPERACAO FINANCEIRA", "valor": 15283.00, "origem": "BANCO"},
        {"data": date(2024, 5, 17), "descricao": "PAGAMENTO CLARO TELEFONIA EMPRESAS", "valor": -354.80, "origem": "BANCO"},
        {"data": date(2024, 5, 20), "descricao": "DEPOSITO CARTAO DE CREDITO REDE", "valor": 4120.50, "origem": "BANCO"},
    ]

    sistema_data = [
        {"data": date(2024, 5, 10), "descricao": "Venda #892 - Alfa Comercio Ltda", "valor": 1500.00, "origem": "SISTEMA"},
        {"data": date(2024, 5, 11), "descricao": "NF 1042 - Papelaria e Escritorio", "valor": -700.00, "origem": "SISTEMA"},
        {"data": date(2024, 5, 11), "descricao": "NF 1043 - Material de Limpeza", "valor": -800.00, "origem": "SISTEMA"},
        {"data": date(2024, 5, 17), "descricao": "Fatura 998 - Telefonia Claro", "valor": -350.00, "origem": "SISTEMA"},
        {"data": date(2024, 5, 20), "descricao": "Fechamento Cartoes Rede Lote 44", "valor": 4120.50, "origem": "SISTEMA"},
        {"data": date(2024, 5, 22), "descricao": "LANCAMENTO APORTE CAPITAL SOCIAL", "valor": 15000.00, "origem": "SISTEMA"},
    ]

    return pd.DataFrame(banco_data), pd.DataFrame(sistema_data)


# ---------------------------------------------------------------------------
# Exportação em Excel Multi-Aba
# ---------------------------------------------------------------------------
def _to_excel_bytes(
    resultado: Any,
    df_banco: pd.DataFrame,
    df_sistema: pd.DataFrame
) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        wb = writer.book

        # Formatações
        header_fmt = wb.add_format({
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#2563eb",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })
        crit_header_fmt = wb.add_format({
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#dc2626",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })
        money_fmt = wb.add_format({"num_format": "R$ #,##0.00", "border": 1})
        date_fmt = wb.add_format({"num_format": "dd/mm/yyyy", "border": 1, "align": "center"})
        cell_fmt = wb.add_format({"border": 1})

        # 1. Resumo Executivo
        ws_resumo = wb.add_worksheet("Resumo Executivo")
        ws_resumo.write("A1", "📊 Relatório Consolidado de Conciliação Financeira", wb.add_format({"bold": True, "font_size": 14, "font_color": "#2563eb"}))
        m = resultado.metricas
        kpis = [
            ("Métrica", "Valor"),
            ("Taxa de Conciliação (%)", f"{m.get('taxa_conciliacao', 0)}%"),
            ("Lançamentos Conciliados (Total)", m.get("total_conciliados", 0)),
            ("  - Correspondências Exatas (1-para-1)", m.get("exatos_count", 0)),
            ("  - Correspondências Aglutinadas (N-para-1)", m.get("aglutinados_count", 0)),
            ("Divergências de Valor Detectadas", m.get("divergencias_count", 0)),
            ("Alertas Críticos de Alto Valor", m.get("criticos_count", 0)),
            ("Transações Sobrando no Banco", m.get("sobra_banco_count", 0)),
            ("Transações Sobrando no ERP", m.get("sobra_sistema_count", 0)),
            ("Valor Total Santander (R$)", m.get("valor_total_banco", 0)),
            ("Valor Total ERP Sistema (R$)", m.get("valor_total_sistema", 0)),
        ]
        ws_resumo.set_column("A:A", 40)
        ws_resumo.set_column("B:B", 20)
        for i, (k, v) in enumerate(kpis, start=3):
            fmt = header_fmt if i == 3 else cell_fmt
            ws_resumo.write(i, 0, k, fmt)
            ws_resumo.write(i, 1, v, fmt)

        # 2. Conciliados
        resultado.df_conc.to_excel(writer, sheet_name="Conciliados", index=False)
        # 3. Alertas Críticos
        if not resultado.df_criticos.empty:
            resultado.df_criticos.to_excel(writer, sheet_name="Alertas Críticos", index=False)
        # 4. Divergências de Valor
        if not resultado.df_div.empty:
            resultado.df_div.to_excel(writer, sheet_name="Divergências Valor", index=False)
        # 5. Sobras Banco
        resultado.df_sobra_banco.to_excel(writer, sheet_name="Sobras Banco", index=False)
        # 6. Sobras Sistema
        resultado.df_sobra_sistema.to_excel(writer, sheet_name="Sobras Sistema", index=False)
        # 7. Dados Brutos Banco
        df_banco.to_excel(writer, sheet_name="Santander (Raw)", index=False)
        # 8. Dados Brutos Sistema
        df_sistema.to_excel(writer, sheet_name="ERP Sistema (Raw)", index=False)

    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Componentes Visuais
# ---------------------------------------------------------------------------
def render_header() -> None:
    st.markdown("""
    <div class="app-header">
        <h1>💳 Conciliação Financeira Especializada</h1>
        <p>Motor de alta precisão para Extrato Santander Empresas e Relatórios ERP com suporte a Aglutinação N-para-1</p>
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


def render_metrics(metricas: dict[str, Any]) -> None:
    st.markdown('<div class="section-title">📊 Painel Consolidado de Conciliação</div>', unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    cards = [
        ("Taxa de Match", f"{metricas.get('taxa_conciliacao', 0)}%", f"{metricas.get('total_conciliados', 0)} de {metricas.get('total_banco', 0)} banco", "val-green"),
        ("Exatos (1-para-1)", str(metricas.get("exatos_count", 0)), "Mesma data/janela e valor", "val-blue"),
        ("Aglutinados (N-1)", str(metricas.get("aglutinados_count", 0)), "Soma do ERP = 1 Banco", "val-purple"),
        ("Alertas Críticos", str(metricas.get("criticos_count", 0)), "Alto valor sem match", "val-red" if metricas.get("criticos_count", 0) > 0 else "val-green"),
        ("Divergências", str(metricas.get("divergencias_count", 0)), "Centavos ou taxas", "val-orange"),
        ("Sobras Totais", str(metricas.get("sobra_banco_count", 0) + metricas.get("sobra_sistema_count", 0)), f"{metricas.get('sobra_banco_count', 0)} bco | {metricas.get('sobra_sistema_count', 0)} erp", "val-red"),
    ]

    for col, (label, value, sub, color) in zip([c1, c2, c3, c4, c5, c6], cards):
        with col:
            st.markdown(render_metric_card(label, value, sub, color), unsafe_allow_html=True)


def _render_styled_table(df: pd.DataFrame, empty_msg: str = "Nenhum registro encontrado.") -> None:
    if df.empty:
        st.info(empty_msg)
        return

    df_display = df.copy()

    # Formatação amigável de datas e valores monetários para exibição
    for col in df_display.columns:
        if "data" in col.lower():
            df_display[col] = df_display[col].apply(lambda x: x.strftime("%d/%m/%Y") if hasattr(x, "strftime") else str(x) if pd.notna(x) else "")
        elif "valor" in col.lower() or "diferenca" in col.lower():
            df_display[col] = df_display[col].apply(
                lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if isinstance(v, (int, float)) and pd.notna(v) else v
            )

    st.dataframe(df_display, use_container_width=True, height=450)


# ---------------------------------------------------------------------------
# Sidebar de Configuração
# ---------------------------------------------------------------------------
def render_sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.markdown("## ⚙️ Painel de Controle")
        st.markdown("---")

        st.markdown("### 📁 Upload dos Extratos (PDF)")
        banco_file = st.file_uploader(
            "Extrato Bancário (Santander)",
            type=["pdf"],
            key="banco_upload",
            help="PDF oficial do extrato de conta corrente Santander Empresas",
        )
        sistema_file = st.file_uploader(
            "Extrato do Sistema (ERP)",
            type=["pdf"],
            key="sistema_upload",
            help="Relatório emitido pelo ERP contendo colunas com formato pipe | ou espaçado",
        )

        st.markdown("---")
        st.markdown("### 🔧 Parâmetros de Conciliação")

        janela_dias = st.slider(
            "Janela de Tolerância (Dias)",
            min_value=0,
            max_value=15,
            value=3,
            step=1,
            help="Diferença máxima de dias permitida entre data do banco e data do sistema",
        )

        limite_divergencia = st.number_input(
            "Tolerância para Divergência (R$)",
            min_value=1.0,
            max_value=1000.0,
            value=100.0,
            step=10.0,
            help="Diferenças de até este valor serão destacadas como divergências de centavos/taxas",
        )

        limiar_alto_valor = st.number_input(
            "Limiar para Alertas Críticos (R$)",
            min_value=500.0,
            max_value=50000.0,
            value=5000.0,
            step=500.0,
            help="Lançamentos não conciliados com valor absoluto igual ou superior a este valor disparam Alerta Crítico",
        )

        st.markdown("---")
        run_btn = st.button("🚀 Executar Conciliação", type="primary", use_container_width=True)
        demo_btn = st.button("🧪 Carregar Dados de Demonstração", use_container_width=True, help="Testa com exemplos de Match Exato, N-para-1 e Alertas Críticos")

        st.markdown("---")
        st.markdown(
            "<p style='color:#8b949e;font-size:0.75rem;text-align:center;'>"
            "Conciliação Financeira v2.0<br>Santander Tabular & ERP Regex Pipeline"
            "</p>",
            unsafe_allow_html=True,
        )

    return {
        "banco_file": banco_file,
        "sistema_file": sistema_file,
        "janela_dias": janela_dias,
        "limite_divergencia": limite_divergencia,
        "limiar_alto_valor": limiar_alto_valor,
        "run": run_btn,
        "demo": demo_btn,
    }


# ---------------------------------------------------------------------------
# Exibição dos Resultados
# ---------------------------------------------------------------------------
def render_results(resultado: Any, elapsed: float) -> None:
    render_metrics(resultado.metricas)

    st.markdown(
        f"<p style='color:#8b949e;font-size:0.82rem;'>⏱️ Processamento concluído em {elapsed:.2f}s</p>",
        unsafe_allow_html=True,
    )

    # Alerta em banner caso existam alertas críticos
    if not resultado.df_criticos.empty:
        qtd_crit = len(resultado.df_criticos)
        st.markdown(f"""
        <div class="alert-banner">
            <span style="font-size:1.6rem;">🚨</span>
            <div>
                <strong style="color:#f85149;font-size:0.95rem;">{qtd_crit} Alerta(s) Crítico(s) Detectado(s)!</strong><br>
                <span style="color:#e6edf3;font-size:0.85rem;">Existem lançamentos de alto valor pendentes de conciliação. Verifique a aba <strong>Alertas Críticos</strong>.</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Abas principais
    t_conc, t_criticos, t_div, t_sobra_bco, t_sobra_sis, t_raw = st.tabs([
        "✅ Conciliados (1-1 e N-1)",
        f"🚨 Alertas Críticos ({len(resultado.df_criticos)})",
        f"🟡 Divergências de Valor ({len(resultado.df_div)})",
        f"🏦 Sobras Santander ({len(resultado.df_sobra_banco)})",
        f"🖥️ Sobras ERP Sistema ({len(resultado.df_sobra_sistema)})",
        "🔍 Dados Brutos Extraídos",
    ])

    with t_conc:
        st.markdown("##### 📌 Transações Conciliadas com Sucesso")
        _render_styled_table(
            resultado.df_conc,
            empty_msg="Nenhuma transação conciliada com os parâmetros atuais.",
        )

    with t_criticos:
        st.markdown("##### 🚨 Transações Relevantes de Alto Valor Sem Conciliação")
        st.caption("Lançamentos com valor superior ao limiar configurado que requerem auditoria manual prioritária.")
        _render_styled_table(
            resultado.df_criticos,
            empty_msg="Nenhum alerta crítico detectado! Todas as transações de alto valor foram conciliadas.",
        )

    with t_div:
        st.markdown("##### 🟡 Variações de Valor Próximo (Centavos / Tarifas / Descontos)")
        st.caption("Lançamentos com datas próximas e valores ligeiramente divergentes (possíveis juros, tarifas bancárias ou erros de digitação).")
        _render_styled_table(
            resultado.df_div,
            empty_msg="Nenhuma divergência de centavos ou taxas detectada.",
        )

    with t_sobra_bco:
        st.markdown("##### 🏦 Lançamentos Santander Sem Par no ERP")
        _render_styled_table(
            resultado.df_sobra_banco,
            empty_msg="Parabéns! Todas as transações do Santander foram conciliadas.",
        )

    with t_sobra_sis:
        st.markdown("##### 🖥️ Lançamentos do ERP Sem Compensação no Santander")
        _render_styled_table(
            resultado.df_sobra_sistema,
            empty_msg="Parabéns! Todas as transações do ERP foram conciliadas.",
        )

    with t_raw:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**📄 Santander Processado ({len(st.session_state.df_banco)} itens)**")
            _render_styled_table(st.session_state.df_banco)
        with c2:
            st.markdown(f"**🖥️ ERP Sistema Processado ({len(st.session_state.df_sistema)} itens)**")
            _render_styled_table(st.session_state.df_sistema)

    # Seção de Exportação
    st.markdown('<div class="section-title">⬇️ Exportar Relatório Consolidado</div>', unsafe_allow_html=True)
    c_btn1, c_btn2, _ = st.columns([1, 1, 2])

    with c_btn1:
        excel_data = _to_excel_bytes(
            resultado,
            st.session_state.df_banco,
            st.session_state.df_sistema,
        )
        st.download_button(
            label="📥 Baixar Excel Completo (.xlsx)",
            data=excel_data,
            file_name=f"conciliacao_santander_erp_{date.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with c_btn2:
        csv_data = resultado.df_conc.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            label="📄 Baixar Conciliados em CSV",
            data=csv_data,
            file_name=f"conciliados_{date.today().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )


def render_empty_state() -> bool:
    st.markdown("""
    <div style="
        text-align: center;
        padding: 48px 32px 30px;
        background: rgba(255,255,255,0.03);
        border: 1px dashed rgba(255,255,255,0.12);
        border-radius: 20px;
        margin: 24px 0;
    ">
        <div style="font-size:3.2rem; margin-bottom:12px;">📑</div>
        <h2 style="color:#e6edf3; font-weight:700; margin:0;">Pronto para Conciliar os Extratos</h2>
        <p style="color:#8b949e; margin-top:8px; font-size:0.95rem; max-width:600px; margin-left:auto; margin-right:auto;">
            Faça upload do <strong>Extrato Santander Empresas</strong> e do <strong>Extrato do ERP</strong> na barra lateral ou experimente a demonstração interativa.
        </p>
        <div style="display:flex; justify-content:center; gap:20px; flex-wrap:wrap; margin-top:20px;">
            <div style="background:rgba(99,179,237,0.08);border:1px solid rgba(99,179,237,0.2);border-radius:12px;padding:12px 20px;">
                <div style="font-size:1.3rem;">🏦</div>
                <div style="color:#8b949e;font-size:0.8rem;margin-top:4px;">Santander Empresas</div>
            </div>
            <div style="font-size:1.6rem;display:flex;align-items:center;color:#667eea;">⟷</div>
            <div style="background:rgba(99,179,237,0.08);border:1px solid rgba(99,179,237,0.2);border-radius:12px;padding:12px 20px;">
                <div style="font-size:1.3rem;">🖥️</div>
                <div style="color:#8b949e;font-size:0.8rem;margin-top:4px;">Relatório do Sistema ERP</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    _, c2, _ = st.columns([1, 2, 1])
    with c2:
        return st.button("🧪 Carregar Demonstração com Valores Fictícios", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Função Principal
# ---------------------------------------------------------------------------
def main() -> None:
    _init_state()
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    render_header()

    cfg = render_sidebar()

    # 1. Execução via Upload
    if cfg["run"]:
        banco_file = cfg["banco_file"]
        sistema_file = cfg["sistema_file"]

        if not banco_file or not sistema_file:
            st.error("⚠️ Por favor, faça upload de ambos os arquivos PDF antes de executar.")
            st.stop()

        with st.spinner("⚙️ Extraindo dados dos arquivos PDF..."):
            try:
                df_banco = extrair_santander(banco_file)
                df_sistema = extrair_sistema(sistema_file)
            except Exception as exc:
                st.error(f"❌ Erro ao extrair os arquivos PDF: {exc}")
                logger.exception("PDF extraction error")
                st.stop()

        if df_banco.empty and df_sistema.empty:
            st.error("❌ Nenhuma transação pôde ser identificada nos arquivos enviados. Verifique os formatos dos PDFs.")
            st.stop()

        if df_banco.empty:
            st.warning("⚠️ Nenhuma transação válida identificada no extrato Santander.")
        if df_sistema.empty:
            st.warning("⚠️ Nenhuma transação válida identificada no extrato do ERP.")

        with st.spinner("🔄 Executando motor de conciliação e análise de anomalias..."):
            t0 = time.perf_counter()
            resultado = conciliar_extratos_avancado(
                df_banco=df_banco,
                df_sistema=df_sistema,
                janela_dias=cfg["janela_dias"],
                limite_divergencia=cfg["limite_divergencia"],
                limiar_alto_valor=cfg["limiar_alto_valor"],
            )
            elapsed = time.perf_counter() - t0

        st.session_state.df_banco = df_banco
        st.session_state.df_sistema = df_sistema
        st.session_state.resultado = resultado
        st.session_state.elapsed = elapsed
        st.session_state.banco_filename = banco_file.name
        st.session_state.sistema_filename = sistema_file.name

        st.success(f"✅ Conciliação finalizada! Taxa de conciliação: {resultado.metricas.get('taxa_conciliacao', 0)}%")

    # 2. Execução via Demonstração
    elif cfg["demo"]:
        with st.spinner("🔄 Carregando transações simuladas..."):
            df_banco, df_sistema = _get_sample_data()
            t0 = time.perf_counter()
            resultado = conciliar_extratos_avancado(
                df_banco=df_banco,
                df_sistema=df_sistema,
                janela_dias=cfg["janela_dias"],
                limite_divergencia=cfg["limite_divergencia"],
                limiar_alto_valor=cfg["limiar_alto_valor"],
            )
            elapsed = time.perf_counter() - t0

            st.session_state.df_banco = df_banco
            st.session_state.df_sistema = df_sistema
            st.session_state.resultado = resultado
            st.session_state.elapsed = elapsed
            st.session_state.banco_filename = "Extrato_Santander_Exemplo.pdf"
            st.session_state.sistema_filename = "Extrato_ERP_Exemplo.pdf"
            st.success(f"✅ Demonstração carregada com sucesso! Taxa: {resultado.metricas.get('taxa_conciliacao', 0)}%")

    # 3. Renderização dos Resultados ou Estado Inicial
    if st.session_state.resultado is not None:
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            st.info(f"🏦 **Santander:** {st.session_state.banco_filename} ({len(st.session_state.df_banco)} itens)")
        with c2:
            st.info(f"🖥️ **ERP Sistema:** {st.session_state.sistema_filename} ({len(st.session_state.df_sistema)} itens)")
        with c3:
            if st.button("🔄 Nova Conciliação", use_container_width=True):
                st.session_state.resultado = None
                st.session_state.df_banco = None
                st.session_state.df_sistema = None
                st.rerun()

        render_results(st.session_state.resultado, st.session_state.elapsed)
    else:
        demo_clicked = render_empty_state()
        if demo_clicked:
            with st.spinner("🔄 Carregando demonstração..."):
                df_banco, df_sistema = _get_sample_data()
                t0 = time.perf_counter()
                resultado = conciliar_extratos_avancado(
                    df_banco=df_banco,
                    df_sistema=df_sistema,
                    janela_dias=cfg["janela_dias"],
                    limite_divergencia=cfg["limite_divergencia"],
                    limiar_alto_valor=cfg["limiar_alto_valor"],
                )
                elapsed = time.perf_counter() - t0

                st.session_state.df_banco = df_banco
                st.session_state.df_sistema = df_sistema
                st.session_state.resultado = resultado
                st.session_state.elapsed = elapsed
                st.session_state.banco_filename = "Extrato_Santander_Exemplo.pdf"
                st.session_state.sistema_filename = "Extrato_ERP_Exemplo.pdf"
                st.rerun()


if __name__ == "__main__":
    main()
