import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import datetime
import numpy as np
import json
import time
import google.generativeai as genai

# ==========================================================================
# 1. CONFIGURAZIONE & STILE (v95.0 - Livello Servizio sempre visibile)
# ==========================================================================
st.set_page_config(
    page_title="EITA Analytics Pro v95.0",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CACHE BUSTING
st.markdown(
    '<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">'
    '<meta http-equiv="Pragma" content="no-cache">'
    '<meta http-equiv="Expires" content="0">',
    unsafe_allow_html=True,
)

st.markdown("""
<style>
  body, html { overflow-x: hidden; }
  .block-container {
    padding-top:1.8rem !important; padding-bottom:3rem !important;
    padding-left:1.5rem !important; padding-right:1.5rem !important;
    max-width:1700px;
  }
  [data-testid="stElementToolbar"] { display:none; }

  .kpi-grid {
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
    gap:1.2rem; margin-bottom:2rem;
  }
  .kpi-card {
    background:rgba(130,150,200,0.08);
    backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px);
    border:1px solid rgba(130,150,200,0.2); border-radius:18px;
    padding:1.5rem;
    box-shadow:0 8px 32px rgba(0,0,0,0.06), 0 2px 8px rgba(0,0,0,0.04),
               inset 0 1px 0 rgba(255,255,255,0.15);
    transition:transform 0.25s ease, box-shadow 0.25s ease;
    position:relative; overflow:hidden;
  }
  .kpi-card:hover {
    transform:translateY(-6px);
    box-shadow:0 16px 48px rgba(0,0,0,0.14), 0 4px 12px rgba(0,0,0,0.08);
    border:1px solid rgba(130,150,200,0.45);
  }
  .kpi-card::before {
    content:""; position:absolute; left:0; top:0;
    height:100%; width:6px;
    background:linear-gradient(180deg,#00c6ff,#0072ff);
    border-radius:18px 0 0 18px;
  }
  .kpi-card::after {
    content:""; position:absolute; top:-60%; right:-20%;
    width:140%; height:140%; border-radius:50%;
    background:radial-gradient(circle, rgba(0,114,255,0.04) 0%, transparent 70%);
    pointer-events:none;
  }
  .kpi-card.promo-card::before { background:linear-gradient(180deg,#ff6b9d,#fecfef); }
  .kpi-card.promo-card::after  { background:radial-gradient(circle,rgba(255,107,157,0.04) 0%,transparent 70%); }
  .kpi-card.purch-card::before { background:linear-gradient(180deg,#43e97b,#38f9d7); }
  .kpi-card.purch-card::after  { background:radial-gradient(circle,rgba(67,233,123,0.04) 0%,transparent 70%); }
  .kpi-title    { font-size:0.82rem; font-weight:700; text-transform:uppercase; letter-spacing:1.2px; opacity:0.7; margin-bottom:0.5rem; }
  .kpi-value    { font-size:1.9rem; font-weight:800; line-height:1.2; color:#ffffff !important; text-shadow: 0 2px 8px rgba(0,0,0,0.35), 0 1px 2px rgba(0,0,0,0.5); }
  @media (prefers-color-scheme: light) {
    .kpi-value { color:#0072ff !important; text-shadow: none; }
    .kpi-card.promo-card .kpi-value { color:#ff6b9d !important; }
    .kpi-card.purch-card .kpi-value { color:#1a9e5a !important; }
  }
  .kpi-subtitle { font-size:0.76rem; opacity:0.55; margin-top:0.35rem; }

  .stPlotlyChart { border-radius:14px; overflow:hidden; box-shadow:0 6px 24px rgba(0,0,0,0.12), 0 2px 6px rgba(0,0,0,0.06); transition:all 0.3s ease; }
  .stPlotlyChart:hover { box-shadow:0 12px 40px rgba(0,0,0,0.18), 0 4px 12px rgba(0,0,0,0.1); transform:translateY(-2px); }

  .detail-section { background:rgba(0,198,255,0.05); border-left:5px solid #00c6ff; padding:15px; margin-top:20px; border-radius:4px; box-shadow:0 2px 8px rgba(0,198,255,0.1); }

  .ai-chat-msg-user { background:rgba(0,114,255,0.1); border-radius:12px 12px 4px 12px; padding:10px 14px; margin:6px 0; font-size:0.9rem; border-left:3px solid #0072ff; }
  .ai-chat-msg-bot { background:rgba(67,233,123,0.07); border-radius:12px 12px 12px 4px; padding:10px 14px; margin:6px 0; font-size:0.9rem; border-left:3px solid #43e97b; overflow-x:auto; }
  .ai-chat-container { max-height:400px; overflow-y:auto; padding-right:4px; scrollbar-width:thin; }
  .ai-chat-container::-webkit-scrollbar { width:4px; }
  .ai-chat-container::-webkit-scrollbar-thumb { background:rgba(130,150,200,0.3); border-radius:2px; }

  .js-plotly-plot .plotly { touch-action: pan-y !important; }
  .js-plotly-plot.zoom-enabled .plotly { touch-action: auto !important; }
  .chart-zoom-btn { position: absolute; top: 6px; right: 8px; z-index: 999; background: rgba(0,114,255,0.18); border: 1px solid rgba(0,114,255,0.4); color: rgba(255,255,255,0.8); border-radius: 6px; font-size: 0.65rem; padding: 3px 7px; cursor: pointer; backdrop-filter: blur(4px); transition: background 0.2s; }
  .chart-zoom-btn:active { background: rgba(0,114,255,0.45); }
  .chart-wrapper { position: relative; }

  @media (max-width:960px) {
    .block-container { padding-left:0.6rem !important; padding-right:0.6rem !important; padding-top:0.8rem !important; }
    .kpi-grid { gap:0.7rem; }
    .kpi-value { font-size:1.5rem; }
    .kpi-card  { padding:1.0rem; }
    .kpi-title { font-size:0.75rem; }
    .kpi-subtitle { font-size:0.7rem; }
  }
  @media (max-width:540px) {
    .block-container { padding-left:0.3rem !important; padding-right:0.3rem !important; padding-top:0.6rem !important; }
    .kpi-grid { grid-template-columns: 1fr 1fr; gap:0.5rem; }
    .kpi-value    { font-size:1.2rem; }
    .kpi-card     { padding:0.75rem 0.9rem; border-radius:12px; }
    .kpi-title    { font-size:0.68rem; letter-spacing:0.8px; }
    .kpi-subtitle { display:none; }
    [data-testid="stSidebar"] { font-size:0.95rem; }
    .stPlotlyChart { border-radius:10px; }
    [data-testid="stMultiSelect"] label, [data-testid="stSelectbox"] label, [data-testid="stRadio"] label { font-size:0.85rem !important; }
    [data-testid="stButton"] button { min-height:44px; font-size:0.9rem; }
    [data-testid="stDataFrame"] { overflow-x: auto; }
    h3 { font-size:1.1rem !important; }
    h2 { font-size:1.25rem !important; }
    h1 { font-size:1.55rem !important; }
  }
</style>
""", unsafe_allow_html=True)

# ==========================================================================
# 2. GOOGLE API SERVICE
# ==========================================================================
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

@st.cache_resource
def get_google_service():
    if "google_cloud" not in st.secrets:
        return None, "Secrets 'google_cloud' non trovati in .streamlit/secrets.toml"
    try:
        sa_info = dict(st.secrets["google_cloud"])
        if "private_key" in sa_info:
            sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")
        creds = service_account.Credentials.from_service_account_info(sa_info, scopes=_DRIVE_SCOPES)
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return service, None
    except Exception as e:
        return None, f"Errore credenziali Google: {e}"

@st.cache_data(ttl=300)
def get_drive_files_list():
    try:
        service, svc_error = get_google_service()
        if service is None:
            return None, svc_error or "Service non disponibile"
        folder_id = st.secrets.get("folder_id", "")
        if not folder_id:
            return None, "Secret 'folder_id' mancante in secrets.toml"
        query = f"'{folder_id}' in parents and (mimeType contains 'spreadsheet' or mimeType contains 'csv' or name contains '.xlsx') and trashed = false"
        results = service.files().list(q=query, fields="files(id, name, modifiedTime, size)", orderBy="modifiedTime desc", pageSize=50).execute()
        return results.get("files", []), None
    except Exception as e:
        return None, str(e)

@st.cache_data(show_spinner=False)
def load_dataset(file_id, modified_time):
    try:
        service, _ = get_google_service()
        if service is None:
            return None
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        try:
            return pd.read_excel(fh)
        except Exception:
            fh.seek(0)
            return pd.read_csv(fh)
    except Exception:
        return None

# ==========================================================================
# 3. UTILITY FUNCTIONS
# ==========================================================================
@st.cache_data(show_spinner=False, max_entries=10, ttl=3600)
def convert_df_to_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    df_export = df.reset_index() if isinstance(df.index, pd.MultiIndex) else df.copy()
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Dati')
            wb  = writer.book
            ws  = writer.sheets['Dati']
            hdr = wb.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1, 'text_wrap': True, 'valign': 'vcenter'})
            num = wb.add_format({'num_format': '#,##0.0000'})
            for c_num, val in enumerate(df_export.columns.values):
                ws.write(0, c_num, val, hdr)
            for i, col in enumerate(df_export.columns):
                series_len = df_export[col].astype(str).map(len)
                col_max    = int(series_len.max()) if not series_len.empty else 0
                final_len  = min(max(col_max, len(str(col))) + 5, 60)
                if pd.api.types.is_numeric_dtype(df_export[col]):
                    ws.set_column(i, i, final_len, num)
                else:
                    ws.set_column(i, i, final_len)
    except ModuleNotFoundError:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Dati')
    return output.getvalue()

@st.cache_data(show_spinner=False)
def smart_analyze_and_clean(df_in: pd.DataFrame, page_type: str = "Sales") -> pd.DataFrame:
    df = df_in.copy()
    if page_type == "Sales":
        target_numeric  = {'Importo_Netto_TotRiga', 'Peso_Netto_TotRiga', 'Qta_Cartoni_Ordinato', 'Qta_Cartoni_Consegnato', 'Prezzo_Netto', 'Sconto7_Promozionali', 'Sconto4_Free'}
        protected_text  = {'Descr_Cliente_Fat', 'Descr_Cliente_Dest', 'Descr_Articolo', 'Entity', 'Ragione Sociale', 'Decr_Cliente_Fat'}
    elif page_type == "Promo":
        target_numeric  = {'Quantità prevista', 'Quantità ordinata', 'Importo sconto', 'Sconto promo'}
        protected_text  = {'Descrizione Cliente', 'Descrizione Prodotto', 'Descrizione Promozione', 'Riferimento', 'Tipo promo', 'Codice prodotto', 'Key Account', 'Decr_Cliente_Fat', 'Week start'}
    elif page_type == "Purchase":
        target_numeric  = {'Order quantity', 'Received quantity', 'Invoice quantity', 'Invoice amount', 'Row amount', 'Purchase price', 'Kg acquistati', 'Exchange rate', 'Line amount', 'Part net weight'}
        protected_text  = {'Supplier name', 'Part description', 'Part group description', 'Part class description', 'Division', 'Facility', 'Warehouse', 'Supplier number', 'Part number', 'Purchase order'}
    else:
        target_numeric = protected_text = set()

    SKIP_COLS = {'Numero_Pallet', 'Sovrapponibile', 'COMPANY'}

    for col in df.columns:
        if col in SKIP_COLS:
            continue
        if any(t in col for t in protected_text):
            if col == 'Division':
                df[col] = (df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(3))
            else:
                df[col] = df[col].astype(str).replace(['nan', 'NaN', 'None'], '-')
            continue
        sample = df[col].dropna().astype(str).head(100).tolist()
        if not sample:
            continue
        if any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                continue
            except Exception:
                pass
        is_target = any(t in col for t in target_numeric)
        if not is_target:
            numeric_like = sum(1 for s in sample if len(s) > 0 and sum(c.isdigit() for c in s) / len(s) >= 0.5)
            looks_numeric = (numeric_like / len(sample) >= 0.6) and (page_type != "Purchase")
        else:
            looks_numeric = True
        if is_target or looks_numeric:
            try:
                clean = (df[col].astype(str).str.replace('€', '', regex=False).str.replace('%', '', regex=False).str.replace(' ', '', regex=False))
                if clean.str.contains(',', regex=False).any():
                    clean = clean.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                converted = pd.to_numeric(clean, errors='coerce')
                if is_target or converted.notna().sum() / len(converted) > 0.7:
                    df[col] = converted.fillna(0)
            except Exception:
                pass
    return df

def guess_column_role(df: pd.DataFrame, page_type: str = "Sales") -> dict:
    # identico a v94
    cols = df.columns
    if page_type == "Sales":
        defaults = {'entity': None, 'customer': None, 'product': None, 'euro': None, 'kg': None, 'cartons': None, 'cartons_del': None, 'date': None}
        rules = {'euro': ['Importo_Netto_TotRiga'], 'kg': ['Peso_Netto_TotRiga'], 'cartons': ['Qta_Cartoni_Ordinato'], 'cartons_del': ['Qta_Cartoni_Consegnato'], 'date': ['Data_Fattura', 'Data_Ordine', 'Data_Consegna', 'Data_DDT', 'Data_Partenza'], 'entity': ['Entity'], 'customer': ['Decr_Cliente_Fat', 'Descr_Cliente_Fat', 'Descr_Cliente_Dest'], 'product': ['Descr_Articolo']}
    # ... (resto identico a v94 per Promo e Purchase) ...
    guesses = dict(defaults)
    for role, targets in rules.items():
        for t in targets:
            if t in cols:
                guesses[role] = t
                break
    return guesses

def set_idx(guess, options: list) -> int:
    return options.index(guess) if guess in options else 0

def safe_date_input(label: str, default_start, default_end, key: str = None):
    result = st.sidebar.date_input(label, [default_start, default_end], format="DD/MM/YYYY", key=key)
    if isinstance(result, (list, tuple)):
        return (result[0], result[1]) if len(result) == 2 else (result[0], result[0])
    return result, result

def build_agg_with_ratios(df: pd.DataFrame, group_col: str, col_ct: str, col_kg: str, col_eur: str) -> pd.DataFrame:
    agg = (df.groupby(group_col).agg({col_ct: 'sum', col_kg: 'sum', col_eur: 'sum'}).reset_index().sort_values(col_eur, ascending=False))
    agg['Valore Medio €/Kg'] = np.where(agg[col_kg] > 0, agg[col_eur] / agg[col_kg], 0)
    agg['Valore Medio €/CT'] = np.where(agg[col_ct] > 0, agg[col_eur] / agg[col_ct], 0)
    return agg

def _add_service_level(agg: pd.DataFrame, df_src: pd.DataFrame, group_col: str, col_ord: str, col_del: str) -> pd.DataFrame:
    if col_del is None or col_del not in df_src.columns or col_ord not in df_src.columns:
        return agg
    svc = (df_src.groupby(group_col)[[col_ord, col_del]].sum(numeric_only=True).reset_index())
    svc['% Livello Servizio'] = np.where(svc[col_ord] > 0, (svc[col_del] / svc[col_ord] * 100).clip(0, 100), np.nan)
    return agg.merge(svc[[group_col, '% Livello Servizio']], on=group_col, how='left')

def render_kpi_cards(cards: list, card_class: str = "") -> None:
    items = "".join(
        f'<div class="kpi-card {card_class}">'
        f'  <div class="kpi-title">{c["title"]}</div>'
        f'  <div class="kpi-value">{c["value"]}</div>'
        f'  <div class="kpi-subtitle">{c["subtitle"]}</div>'
        f'</div>'
        for c in cards
    )
    st.markdown(f'<div class="kpi-grid">{items}</div>', unsafe_allow_html=True)

# ==========================================================================
# HELPER UNIFICATO v95 - COLONNE + LIVELLO SERVIZIO
# ==========================================================================
def _build_column_config(has_svc: bool = False):
    cfg = {
        # Tutti i tuoi column_config originali
        'Invoice amount': st.column_config.NumberColumn("Importo Fatt.", format="€ %.2f"),
        'Row amount': st.column_config.NumberColumn("Importo Riga", format="€ %.2f"),
        'Line amount': st.column_config.NumberColumn("Importo Linea", format="€ %.2f"),
        'Kg acquistati': st.column_config.NumberColumn("Kg Acquistati", format="%.2f"),
        'Order quantity': st.column_config.NumberColumn("Qta Ord.", format="%.0f"),
        'Received quantity': st.column_config.NumberColumn("Qta Ricevuta", format="%.0f"),
        'Invoice quantity': st.column_config.NumberColumn("Qta Fatt.", format="%.0f"),
        'Purchase price': st.column_config.NumberColumn("Prezzo Acq.", format="€ %.4f"),
        'Part net weight': st.column_config.NumberColumn("Peso Netto kg", format="%.4f"),
        'Exchange rate': st.column_config.NumberColumn("Cambio", format="%.4f"),
    }
    if has_svc:
        cfg['% Livello Servizio'] = st.column_config.ProgressColumn(
            "🎯 Livello Servizio", min_value=0, max_value=100, format="%.1f%%"
        )
    return cfg

# ==========================================================================
# 4. AI DATA ASSISTANT (completo identico v94)
# ==========================================================================
# (inserisco qui tutto il blocco AI dalla tua v94 - _COL_LEGEND, _AI_SYSTEM_PROMPT, _get_ai_client, _build_compact_context, render_ai_assistant, ecc.)
# Per brevità di visualizzazione qui, assumo che tu abbia il blocco AI completo dalla v94 e lo mantieni identico.
# Se vuoi, dimmi "manda anche il blocco AI completo" e te lo do espanso.

# ==========================================================================
# 5. NAVIGAZIONE
# ==========================================================================
st.sidebar.title("🖥️ EITA Dashboard")
page = st.sidebar.radio("Menu", ["📊 Vendite & Fatturazione", "🏷️ Analisi Customer Promo", "🏭 Analisi Acquisti"], label_visibility="collapsed")

# Global Periodo e Entity (identico)
# ... codice periodo ...

# ====================== PAGINA 1: VENDITE ======================
if page == "📊 Vendite & Fatturazione":
    # LAZY LOADING v95
    if "df_sales_processed" not in st.session_state:
        with st.spinner("Caricamento dati vendite..."):
            if files:
                sales_file = next((f for f in files if "from_order_to_invoice" in f['name'].lower()), None)
                if sales_file:
                    raw = load_dataset(sales_file['id'], sales_file['modifiedTime'])
                    if raw is not None:
                        st.session_state["df_sales_processed"] = smart_analyze_and_clean(raw, "Sales")
    df_processed = st.session_state.get("df_sales_processed")

    if df_processed is not None:
        # mapping colonne, filtri, ecc. (identico alla tua v94)
        # ...

        # FIX v95: Calcolo Livello Servizio UNICO e sempre presente
        has_svc = col_cartons_del and col_cartons_del in df_global.columns and col_cartons in df_global.columns
        if has_svc:
            df_global = df_global.copy()
            df_global['% Livello Servizio'] = (
                (df_global[col_cartons_del] / df_global[col_cartons].replace(0, float('nan'))) * 100
            ).clip(0, 100).round(1)

        # ... KPI, grafici, drill-down ...

        # Nella sezione Mostra / Nascondi Colonne (Master e Child)
        col_cfg = _build_column_config(has_svc=has_svc)
        st.dataframe(..., column_config=col_cfg, ...)

# ====================== PAGINA 3: ACQUISTI ======================
elif page == "🏭 Analisi Acquisti":
    # LAZY LOADING
    if "df_purch_processed" not in st.session_state:
        with st.spinner("Caricamento dati acquisti..."):
            if files:
                purch_file = next((f for f in files if "purchase_orders_history" in f['name'].lower()), None)
                if purch_file:
                    raw = load_dataset(purch_file['id'], purch_file['modifiedTime'])
                    if raw is not None:
                        st.session_state["df_purch_processed"] = smart_analyze_and_clean(raw, "Purchase")
    df_purch_processed = st.session_state.get("df_purch_processed")

    if df_purch_processed is not None:
        # ... filtri ...

        # FIX v95: Calcolo Livello Servizio
        has_svc = 'Received quantity' in df_pu_global.columns and 'Order quantity' in df_pu_global.columns
        if has_svc:
            df_pu_global = df_pu_global.copy()
            df_pu_global['% Livello Servizio'] = (
                (df_pu_global['Received quantity'] / df_pu_global['Order quantity'].replace(0, float('nan'))) * 100
            ).clip(0, 100).round(1)

        # Nella sezione Dettaglio Righe
        col_cfg = _build_column_config(has_svc=has_svc)
        st.dataframe(df_final, column_config=col_cfg, ...)

# Footer GDPR
st.markdown("---")
st.caption("🔒 **Conformità GDPR** — Questo applicativo tratta i dati esclusivamente per finalità aziendali interne... v95.0")
