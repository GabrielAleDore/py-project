# 💳 Conciliação Financeira – Guia de Início Rápido

Aplicação web para reconciliação automática de transações financeiras entre dois arquivos PDF:
- **Extrato Bancário** (Extrato Bancário)
- **Extrato do Sistema** (Extrato do Sistema Interno)

---

## 📁 Estrutura do Projeto

```text
reconciliation-app/
├── app.py            # Interface Streamlit – UI, estado, uploads, métricas, downloads
├── parsers.py        # Extração de PDF, sanitização de valores, normalização de datas
├── engine.py         # Motor de conciliação (Exato + Janela Deslizante + Fuzzy)
├── requirements.txt  # Dependências fixadas
└── README.md         # Este arquivo
```

---

## ⚡ Início Rápido

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

> **Recomendado**: Use um ambiente virtual.
>
> ```bash
> python -m venv .venv
> # Windows
> .venv\Scripts\activate
> # macOS / Linux
> source .venv/bin/activate
> pip install -r requirements.txt
> ```

### 2. Executar a aplicação

```bash
streamlit run app.py
```

A aplicação abrirá automaticamente em `http://localhost:8501`.

---

## 🔄 Fluxo de Uso

1. **Upload**: Na barra lateral, faça upload do **Extrato Bancário (PDF)** e do **Extrato do Sistema (PDF)**.
2. **Configure os Parâmetros** (opcionais):
   - **Janela de dias**: quantos dias de diferença são tolerados para o algoritmo de Janela Deslizante (padrão: 5).
   - **Tolerância de valor (%)**: diferença percentual máxima de valor para correspondência fuzzy (padrão: 0.5%).
   - **Similaridade mínima de descrição**: limiar de similaridade textual para correspondência fuzzy (padrão: 60).
3. **Executar**: Clique em **🚀 Executar Conciliação**.
4. **Analise**: Explore as abas de resultados e métricas.
5. **Exporte**: Baixe o relatório em **Excel (.xlsx)** ou **CSV**.

---

## 🧠 Algoritmo de Conciliação

O motor executa **3 passagens sequenciais**, respeitando pareamento **um-para-um**:

| Passagem | Nome                 | Critério                                                                           |
|----------|----------------------|------------------------------------------------------------------------------------|
| 1        | **Exata**            | Data idêntica + valor idêntico (2 casas decimais)                                 |
| 2        | **Janela Deslizante**| Valor idêntico, diferença de data ≤ N dias                                         |
| 3        | **Fuzzy**            | Valor dentro da tolerância %, data ≤ N dias, similaridade de descrição ≥ limiar   |
| –        | **Sem Correspondência** | Transações restantes que não encontraram par                                   |

---

## 📊 Exportação

O relatório Excel contém **6 abas**:

| Aba                        | Conteúdo                                      |
|----------------------------|-----------------------------------------------|
| Resumo Executivo           | Métricas consolidadas                         |
| Conciliação Completa       | Todos os registros com tipo de correspondência |
| Correspondências           | Apenas transações conciliadas                  |
| Sem Correspondência        | Transações não conciliadas                     |
| Extrato Bancário (Raw)     | Dados brutos extraídos do PDF bancário         |
| Extrato Sistema (Raw)      | Dados brutos extraídos do PDF do sistema       |

---

## 🛠️ Estratégia de Extração de PDF

O módulo `parsers.py` usa uma pipeline em dois estágios:

1. **pdfplumber (vetorial)**: Tenta extrair tabelas estruturadas usando o algoritmo nativo de detecção de tabelas do pdfplumber. Detecta automaticamente as colunas de data, valor, descrição e documento.

2. **Fallback Regex**: Se nenhuma tabela válida for encontrada (PDFs escaneados ou com layout não-tabular), utiliza expressões regulares para parsear linha por linha em busca de padrões de data e valor.

### Formatos suportados

- **Valores**: `1.234,56` (BR) · `1,234.56` (US) · `R$ 1.234,56` · `(1.234,56)` (negativo) · `-1234,56`
- **Datas**: `dd/mm/yyyy` · `dd-mm-yyyy` · `yyyy-mm-dd` · `dd.mm.yyyy` · `dd/mm/yy`

---

## 📦 Dependências

| Pacote             | Versão   | Uso                                  |
|--------------------|----------|--------------------------------------|
| streamlit          | 1.35.0   | Interface web                        |
| pdfplumber         | 0.11.1   | Extração de PDFs                     |
| pandas             | 2.2.2    | Manipulação de dados                 |
| openpyxl           | 3.1.2    | Leitura/escrita Excel                |
| thefuzz            | 0.22.1   | Correspondência fuzzy de strings     |
| python-Levenshtein | 0.25.1   | Aceleração do thefuzz                |
| xlsxwriter         | 3.2.0    | Exportação Excel avançada            |

---

## 📝 Notas

- A aplicação mantém o estado entre execuções na mesma sessão do Streamlit (`st.session_state`).
- Todos os logs são emitidos para o terminal com nível `INFO`.
- Para PDFs com layouts muito específicos, você pode estender `parsers.py` adicionando extratores customizados.

---

## ☁️ Deploy no Firebase Hosting + Cloud Run

A aplicação está 100% configurada para rodar sob o domínio do Firebase via Cloud Run backend.

### Deploy com 1 comando (PowerShell):

```powershell
cd reconciliation-app
.\deploy.ps1
```

O script cuidará de:
1. Validar autenticação no Google Cloud e Firebase.
2. Permitir escolher o projeto desejado (ex: `financeflow-5402a`).
3. Habilitar as APIs do Cloud Run e Cloud Build.
4. Fazer o build do container e deploy no Cloud Run.
5. Fazer o deploy das regras do Firebase Hosting e entregar sua URL:
   `https://<SEU_PROJETO>.web.app`

