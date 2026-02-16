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
import base64
import re
import time
import google.generativeai as genai

# ==========================================================================
# 1. CONFIGURAZIONE & STILE (v85.0 - Top Fornitori: subplots side-by-side (€|Kg) no overlap; P1 layout: col_r Esplosione + full-width drill-down; titolo📊 P1; CSS h1 mobile; tabelle full-width: contesto AI caricato prima di render_ai_assistant, df unico globale)
# ==========================================================================
st.set_page_config(
    page_title="EITA Analytics Pro v85.0",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── CACHE BUSTING — previene rendering stale su Chrome mobile/Android ────────
# Inietta header HTTP no-cache + meta pragma via custom HTML.
# Streamlit non espone st.response_headers, quindi usiamo il meta tag HTML
# che istruisce browser e proxy a non servire versioni cached della pagina.
st.markdown(
    '<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">'
    '<meta http-equiv="Pragma" content="no-cache">'
    '<meta http-equiv="Expires" content="0">',
    unsafe_allow_html=True,
)

st.markdown("""
<style>
  /* ---- LAYOUT ---- */
  body, html { overflow-x: hidden; }   /* previene scroll orizzontale su mobile */
  .block-container {
    padding-top:1.8rem !important; padding-bottom:3rem !important;
    padding-left:1.5rem !important; padding-right:1.5rem !important;
    max-width:1700px;
  }
  [data-testid="stElementToolbar"] { display:none; }

  /* ---- KPI GRID ---- */
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
  .kpi-title    { font-size:0.82rem; font-weight:700; text-transform:uppercase;
                  letter-spacing:1.2px; opacity:0.7; margin-bottom:0.5rem; }
  .kpi-value    { font-size:1.9rem; font-weight:800; line-height:1.2;
                  color:#ffffff !important;
                  text-shadow: 0 2px 8px rgba(0,0,0,0.35), 0 1px 2px rgba(0,0,0,0.5); }
  /* Tema chiaro: il valore usa il colore accent (stesso della barra sinistra) invece di bianco */
  @media (prefers-color-scheme: light) {
    .kpi-value { color:#0072ff !important; text-shadow: none; }
    .kpi-card.promo-card .kpi-value { color:#ff6b9d !important; }
    .kpi-card.purch-card .kpi-value { color:#1a9e5a !important; }
  }
  .kpi-subtitle { font-size:0.76rem; opacity:0.55; margin-top:0.35rem; }

  /* ---- CHARTS ---- */
  .stPlotlyChart {
    border-radius:14px; overflow:hidden;
    box-shadow:0 6px 24px rgba(0,0,0,0.12), 0 2px 6px rgba(0,0,0,0.06);
    transition:all 0.3s ease;
  }
  .stPlotlyChart:hover {
    box-shadow:0 12px 40px rgba(0,0,0,0.18), 0 4px 12px rgba(0,0,0,0.1);
    transform:translateY(-2px);
  }

  /* ---- DETAIL SECTION ---- */
  .detail-section {
    background:rgba(0,198,255,0.05);
    border-left:5px solid #00c6ff;
    padding:15px; margin-top:20px; border-radius:4px;
    box-shadow:0 2px 8px rgba(0,198,255,0.1);
  }

  /* ---- AI CHAT ---- */
  .ai-chat-msg-user {
    background:rgba(0,114,255,0.1); border-radius:12px 12px 4px 12px;
    padding:10px 14px; margin:6px 0; font-size:0.9rem;
    border-left:3px solid #0072ff;
  }
  .ai-chat-msg-bot {
    background:rgba(67,233,123,0.07); border-radius:12px 12px 12px 4px;
    padding:10px 14px; margin:6px 0; font-size:0.9rem;
    border-left:3px solid #43e97b; overflow-x:auto;
  }
  .ai-chat-container {
    max-height:400px; overflow-y:auto;
    padding-right:4px; scrollbar-width:thin;
  }
  .ai-chat-container::-webkit-scrollbar { width:4px; }
  .ai-chat-container::-webkit-scrollbar-thumb {
    background:rgba(130,150,200,0.3); border-radius:2px;
  }

  /* ---- GRAFICI: blocca zoom accidentale su mobile ---- */
  /* di default i grafici non zoomano al touch — si attiva via pulsante JS */
  .js-plotly-plot .plotly {
    touch-action: pan-y !important;
  }
  .js-plotly-plot.zoom-enabled .plotly {
    touch-action: auto !important;
  }
  /* Pulsante zoom mobile */
  .chart-zoom-btn {
    position: absolute; top: 6px; right: 8px; z-index: 999;
    background: rgba(0,114,255,0.18); border: 1px solid rgba(0,114,255,0.4);
    color: rgba(255,255,255,0.8); border-radius: 6px;
    font-size: 0.65rem; padding: 3px 7px; cursor: pointer;
    backdrop-filter: blur(4px);
    transition: background 0.2s;
  }
  .chart-zoom-btn:active { background: rgba(0,114,255,0.45); }
  .chart-wrapper { position: relative; }

  /* ---- RESPONSIVE: tablet ---- */
  @media (max-width:960px) {
    .block-container {
      padding-left:0.6rem !important;
      padding-right:0.6rem !important;
      padding-top:0.8rem !important;
    }
    .kpi-grid { gap:0.7rem; }
    .kpi-value { font-size:1.5rem; }
    .kpi-card  { padding:1.0rem; }
    .kpi-title { font-size:0.75rem; }
    .kpi-subtitle { font-size:0.7rem; }
  }
  /* ---- RESPONSIVE: smartphone ---- */
  @media (max-width:540px) {
    .block-container {
      padding-left:0.3rem !important;
      padding-right:0.3rem !important;
      padding-top:0.6rem !important;
    }
    .kpi-grid {
      grid-template-columns: 1fr 1fr;
      gap:0.5rem;
    }
    .kpi-value    { font-size:1.2rem; }
    .kpi-card     { padding:0.75rem 0.9rem; border-radius:12px; }
    .kpi-title    { font-size:0.68rem; letter-spacing:0.8px; }
    .kpi-subtitle { display:none; }        /* nasconde subtitle su schermi piccoli */
    /* Sidebar testo più grande su mobile */
    [data-testid="stSidebar"] { font-size:0.95rem; }
    /* Grafici full-width su mobile */
    .stPlotlyChart { border-radius:10px; }
    /* Form e filtri */
    [data-testid="stMultiSelect"] label,
    [data-testid="stSelectbox"] label,
    [data-testid="stRadio"] label { font-size:0.85rem !important; }
    /* Bottoni più grandi per il touch */
    [data-testid="stButton"] button { min-height:44px; font-size:0.9rem; }
    /* Tabelle scroll orizzontale */
    [data-testid="stDataFrame"] { overflow-x: auto; }
    /* Subheader più compatti */
    h3 { font-size:1.1rem !important; }
    h2 { font-size:1.25rem !important; }
    h1 { font-size:1.55rem !important; }  /* titolo pagina su mobile */
  }
</style>
<!-- zoom gestito via Plotly config -->
""", unsafe_allow_html=True)


# ==========================================================================
# 2. GOOGLE API SERVICE
# ==========================================================================

# Scopes obbligatori per Google Drive API
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


@st.cache_resource
def get_google_service():
    """
    Singleton Google Drive service.

    FIX #1 - scopes mancanti: senza scopes= le credenziali non ottengono token
              validi per Drive → 'Service unavailable' o 403.
    FIX #2 - private_key \n: Streamlit Cloud TOML serializza i newline come
              stringa '\\n' (due caratteri). La chiave privata RSA richiede
              veri newline altrimenti il parsing PEM fallisce silenziosamente.
    FIX #3 - cache_discovery=False: in ambienti serverless Streamlit Cloud
              la discovery endpoint può rispondere 404 → errore a cascata.
    FIX #4 - errore non più silente: l'eccezione viene restituita come
              secondo elemento della tupla così l'utente vede il vero messaggio.
    """
    if "google_cloud" not in st.secrets:
        return None, "Secrets 'google_cloud' non trovati in .streamlit/secrets.toml"

    try:
        # dict() necessario per poter modificare il mapping (Streamlit restituisce
        # un oggetto immutabile di tipo AttrDict)
        sa_info = dict(st.secrets["google_cloud"])

        # FIX #2: ripristina i newline reali nel private_key
        if "private_key" in sa_info:
            sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")

        # FIX #1: scopes espliciti per Drive read-only
        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=_DRIVE_SCOPES
        )

        # FIX #3: evita chiamata al discovery endpoint (instabile su Streamlit Cloud)
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return service, None

    except Exception as e:
        return None, f"Errore credenziali Google: {e}"


@st.cache_data(ttl=300)
def get_drive_files_list():
    """Lista file Drive — ritorna solo dati serializzabili (no service object)."""
    try:
        service, svc_error = get_google_service()
        if service is None:
            return None, svc_error or "Service non disponibile"

        folder_id = st.secrets.get("folder_id", "")
        if not folder_id:
            return None, "Secret 'folder_id' mancante in secrets.toml"

        query = (
            f"'{folder_id}' in parents and "
            "(mimeType contains 'spreadsheet' or mimeType contains 'csv' "
            "or name contains '.xlsx') and trashed = false"
        )
        results = service.files().list(
            q=query,
            fields="files(id, name, modifiedTime, size)",
            orderBy="modifiedTime desc",
            pageSize=50
        ).execute()
        return results.get("files", []), None

    except Exception as e:
        return None, str(e)


@st.cache_data(show_spinner=False)
def load_dataset(file_id, modified_time):
    """Download + parse del file Drive. Cache basata su (id, modifiedTime)."""
    try:
        service, _ = get_google_service()   # FIX: unpack tupla (service, error)
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

def convert_df_to_excel(df: pd.DataFrame) -> bytes:
    """Esporta un DataFrame in formato .xlsx con formattazione base."""
    output = io.BytesIO()
    df_export = df.reset_index() if isinstance(df.index, pd.MultiIndex) else df.copy()

    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Dati')
            wb  = writer.book
            ws  = writer.sheets['Dati']
            hdr = wb.add_format({'bold': True, 'bg_color': '#f0f0f0',
                                 'border': 1, 'text_wrap': True, 'valign': 'vcenter'})
            num = wb.add_format({'num_format': '#,##0.0000'})
            for c_num, val in enumerate(df_export.columns.values):
                ws.write(0, c_num, val, hdr)
            for i, col in enumerate(df_export.columns):
                # FIX: .max() su serie vuota o tutto-NaN restituisce NaN → TypeError
                # Soluzione: usare pd.Series.max() con default 0 via fillna
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


# OTTIMIZZAZIONE: smart_analyze_and_clean cachata → non rielaborata se
# lo stesso DataFrame grezzo viene richiesto due volte (es. Sales in Promo page).
@st.cache_data(show_spinner=False)
def smart_analyze_and_clean(df_in: pd.DataFrame, page_type: str = "Sales") -> pd.DataFrame:
    """Pulisce e tipizza automaticamente le colonne del DataFrame."""
    df = df_in.copy()

    if page_type == "Sales":
        target_numeric  = {'Importo_Netto_TotRiga', 'Peso_Netto_TotRiga',
                           'Qta_Cartoni_Ordinato', 'Prezzo_Netto',
                           'Sconto7_Promozionali', 'Sconto4_Free'}
        protected_text  = {'Descr_Cliente_Fat', 'Descr_Cliente_Dest', 'Descr_Articolo',
                           'Entity', 'Ragione Sociale', 'Decr_Cliente_Fat'}
    elif page_type == "Promo":
        target_numeric  = {'Quantità prevista', 'Quantità ordinata',
                           'Importo sconto', 'Sconto promo'}
        protected_text  = {'Descrizione Cliente', 'Descrizione Prodotto',
                           'Descrizione Promozione', 'Riferimento', 'Tipo promo',
                           'Codice prodotto', 'Key Account', 'Decr_Cliente_Fat', 'Week start'}
    elif page_type == "Purchase":
        target_numeric  = {'Order quantity', 'Received quantity', 'Invoice quantity',
                           'Invoice amount', 'Row amount', 'Purchase price',
                           'Kg acquistati', 'Exchange rate', 'Line amount', 'Part net weight'}
        protected_text  = {'Supplier name', 'Part description', 'Part group description',
                           'Part class description', 'Division', 'Facility', 'Warehouse',
                           'Supplier number', 'Part number', 'Purchase order'}
    else:
        target_numeric = protected_text = set()

    SKIP_COLS = {'Numero_Pallet', 'Sovrapponibile', 'COMPANY'}

    for col in df.columns:
        if col in SKIP_COLS:
            continue

        if any(t in col for t in protected_text):
            # FIX: zfill applicato SOLO alla colonna esatta 'Division',
            # non a qualsiasi colonna che contiene la parola (es. "Sub-Division")
            if col == 'Division':
                df[col] = (df[col].astype(str)
                               .str.replace(r'\.0$', '', regex=True)
                               .str.zfill(3))
            else:
                df[col] = df[col].astype(str).replace(['nan', 'NaN', 'None'], '-')
            continue

        sample = df[col].dropna().astype(str).head(100).tolist()
        if not sample:
            continue

        # Rilevamento date
        if any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                continue
            except Exception:
                pass

        is_target = any(t in col for t in target_numeric)

        # FIX: euristica numerica conservativa + guard per Purchase
        if not is_target:
            numeric_like = sum(
                1 for s in sample
                if len(s) > 0 and sum(c.isdigit() for c in s) / len(s) >= 0.5
            )
            # guard page_type != "Purchase": evita conversione numerica su codici fornitore/part number
            looks_numeric = (numeric_like / len(sample) >= 0.6) and (page_type != "Purchase")
        else:
            looks_numeric = True

        if is_target or looks_numeric:
            try:
                clean = (df[col].astype(str)
                                .str.replace('€', '', regex=False)
                                .str.replace('%', '', regex=False)
                                .str.replace(' ', '', regex=False))
                if clean.str.contains(',', regex=False).any():
                    clean = (clean.str.replace('.', '', regex=False)
                                  .str.replace(',', '.', regex=False))
                converted = pd.to_numeric(clean, errors='coerce')
                if is_target or converted.notna().sum() / len(converted) > 0.7:
                    df[col] = converted.fillna(0)
            except Exception:
                pass
    return df


def guess_column_role(df: pd.DataFrame, page_type: str = "Sales") -> dict:
    """Mappa automatica ruolo → nome colonna tramite golden rules."""
    cols = df.columns

    if page_type == "Sales":
        defaults = {'entity': None, 'customer': None, 'product': None,
                    'euro': None, 'kg': None, 'cartons': None, 'date': None}
        rules = {
            'euro':     ['Importo_Netto_TotRiga'],
            'kg':       ['Peso_Netto_TotRiga'],
            'cartons':  ['Qta_Cartoni_Ordinato'],
            'date':     ['Data_Fattura', 'Data_Ordine', 'Data_Consegna', 'Data_DDT', 'Data_Partenza'],
            'entity':   ['Entity'],
            'customer': ['Decr_Cliente_Fat', 'Descr_Cliente_Fat', 'Descr_Cliente_Dest'],
            'product':  ['Descr_Articolo'],
        }
    elif page_type == "Promo":
        defaults = {'promo_id': None, 'promo_desc': None, 'customer': None,
                    'product': None, 'qty_forecast': None, 'qty_actual': None,
                    'start_date': None, 'status': None, 'division': None,
                    'type': None, 'week_start': None}
        rules = {
            'promo_id':    ['Numero Promozione'],
            'promo_desc':  ['Descrizione Promozione', 'Riferimento'],
            'customer':    ['Descrizione Cliente'],
            'product':     ['Descrizione Prodotto'],
            'qty_forecast':['Quantità prevista'],
            'qty_actual':  ['Quantità ordinata'],
            'start_date':  ['Sell in da'],
            'status':      ['Stato'],
            'division':    ['Division'],
            'type':        ['Tipo promo'],
            'week_start':  ['Week start'],
        }
    elif page_type == "Purchase":
        defaults = {'supplier': None, 'order_date': None, 'amount': None,
                    'kg': None, 'division': None, 'status': None,
                    'product': None, 'category': None, 'price': None, 'row_amount': None}
        rules = {
            'supplier':   ['Supplier name', 'Supplier number'],
            'order_date': ['Invoice date', 'Date of receipt', 'Purchase order date'],
            'amount':     ['Invoice amount', 'Row amount'],
            'kg':         ['Kg acquistati'],
            'division':   ['Division'],
            'status':     ['Highest status', 'Lowest status'],
            'product':    ['Part description', 'Part number'],
            'category':   ['Part group description', 'Part group'],
            'price':      ['Purchase price'],
            'row_amount': ['Row amount'],
        }
    else:
        return {}

    guesses = dict(defaults)
    for role, targets in rules.items():
        for t in targets:
            if t in cols:
                guesses[role] = t
                break
    return guesses


def set_idx(guess, options: list) -> int:
    """Restituisce l'indice di guess in options, oppure 0."""
    return options.index(guess) if guess in options else 0


def safe_date_input(label: str, default_start, default_end, key: str = None):
    """
    Wrapper date_input robusto: gestisce selezione di un solo giorno
    (Streamlit restituisce tuple a 1 elemento → ValueError).
    """
    result = st.sidebar.date_input(
        label, [default_start, default_end], format="DD/MM/YYYY", key=key
    )
    if isinstance(result, (list, tuple)):
        return (result[0], result[1]) if len(result) == 2 else (result[0], result[0])
    return result, result


# OTTIMIZZAZIONE: helper riutilizzabile per calcolo master/detail aggregation
def build_agg_with_ratios(df: pd.DataFrame, group_col: str,
                          col_ct: str, col_kg: str, col_eur: str) -> pd.DataFrame:
    """Raggruppa, aggrega e calcola i ratio €/Kg e €/CT."""
    agg = (df.groupby(group_col)
             .agg({col_ct: 'sum', col_kg: 'sum', col_eur: 'sum'})
             .reset_index()
             .sort_values(col_eur, ascending=False))
    agg['Valore Medio €/Kg'] = np.where(agg[col_kg] > 0,    agg[col_eur] / agg[col_kg],    0)
    agg['Valore Medio €/CT'] = np.where(agg[col_ct] > 0,    agg[col_eur] / agg[col_ct],    0)
    return agg


# OTTIMIZZAZIONE: helper per HTML KPI card grid
def render_kpi_cards(cards: list, card_class: str = "") -> None:
    """
    Renderizza le KPI card.
    cards = [{'title': str, 'value': str, 'subtitle': str}, ...]
    """
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
# ==========================================================================
# 4. AI DATA ASSISTANT (Gemini)
# ==========================================================================

# Legenda colonne per l'AI (usata nel system prompt e nei tooltip)
_COL_LEGEND = {
    "Supplier number":       "Codice del fornitore",
    "Supplier name":         "Nome del fornitore",
    "Division":              "Divisione aziendale (entità / società)",
    "Purchase order":        "Numero d'ordine di acquisto del sistema",
    "Purchase order date":   "Data dell'ordine di acquisto del sistema",
    "Purchase line":         "Quante linee di prodotto (prodotti diversi) nell'ordine",
    "Lowest status":         "Numero che identifica lo stato dell'ordine nell'ERP (min)",
    "Highest status":        "Numero che identifica lo stato dell'ordine nell'ERP (max)",
    "Facility":              "Codice del sito produttivo di destinazione",
    "Warehouse":             "Codice del magazzino di arrivo merce",
    "Part number":           "Codice prodotto",
    "Part description":      "Descrizione prodotto",
    "Part group":            "Codice del gruppo di acquisto",
    "Part group description":"Descrizione del gruppo di acquisto",
    "Part class":            "Codice sottocategoria del gruppo di acquisto",
    "Part class description":"Descrizione sottocategoria del gruppo di acquisto",
    "Part net weight":       "Peso del singolo cartone in kg",
    "Order quantity":        "Quantità ordinata",
    "Delivery date":         "Data di consegna richiesta",
    "ibourt":                "Se = 1, presente numero contratto in ibourr",
    "ibourr":                "Numero del contratto di acquisto",
    "Purchase price":        "Costo di acquisto dell'articolo (€/kg)",
    "Row amount":            "Importo stimato della riga al momento dell'ordine",
    "Supplier delivery number":"Numero di consegna del fornitore",
    "Received quantity":     "Quantità di merce effettivamente ricevuta",
    "Date of receipt":       "Data effettiva di ricevimento merce",
    "Invoice number":        "Numero fattura",
    "Invoice date":          "Data fattura",
    "Invoice quantity":      "Quantità di merce effettivamente fatturata",
    "Invoice amount":        "Totale importo fatturato (dato certo e definitivo)",
    "Invoice currency":      "Valuta usata nella fattura",
    "Exchange rate":         "Tasso di cambio applicato",
    "Line amount":           "Importo totale linea",
    "Line amount internal":  "Importo totale linea con dati interni",
    "G/L Account":           "Conto contabile",
    "Cost Center":           "Centro di costo",
    "Utente inserimento":    "Utente che ha inserito l'ordine",
    "Utente ultima modifica":"Utente che ha modificato per ultimo l'ordine",
    "Sett. Riferimento Data ordine":   "Settimana dell'anno della data ordine",
    "Sett. Riferimento Data consegna": "Settimana dell'anno della data consegna",
    "Mese Riferimento Data ordine":    "Mese dell'anno della data ordine",
    "Mese Riferimento Data consegna":  "Mese dell'anno della data consegna",
    "Kg acquistati":         "Kg acquistati = Line amount / Purchase price",
}

# ==========================================================================
# AI: SISTEMA UNIFICATO GROQ (primario) + GEMINI (fallback opzionale)
#
# GROQ — piano gratuito generoso, nessuna carta di credito:
#   • llama-3.3-70b-versatile: 30 RPM, 1.000 RPD, 6.000 TPM
#   • llama-3.1-8b-instant:    30 RPM, 14.400 RPD, 20.000 TPM (più veloce)
#   • Whisper nativo per trascrizione vocale
#   Registrazione: https://console.groq.com → "Create API Key"
#   Secret Streamlit: groq_api_key = "gsk_..."
#
# GEMINI (fallback) — se hai billing attivo su Google AI Studio:
#   Secret Streamlit: gemini_api_key = "AIza..."
# ==========================================================================

_AI_SYSTEM_PROMPT = """Sei un assistente esperto di Business Intelligence per EITA, azienda alimentare italiana.
Rispondi in italiano, in modo diretto, assertivo e professionale.

════════════════════════════════════════════════════════════
MAPPA DATI — FOGLIO From_order_to_invoice (Pagina Vendite)
════════════════════════════════════════════════════════════
Ogni domanda sulle vendite si basa su questo foglio. Ecco il significato esatto di ogni colonna:

IDENTIFICAZIONE:
  Entity               = Entità/divisione aziendale (es. EITA) — il contesto è già filtrato per entità
  Anno_Ordine          = Anno di emissione ordine
  Tipo_Ordine          = Codice tipo ordine (sistema ERP)
  Stato_riga_ordine    = Codice stato di preparazione ordine
  Numero_Ordine        = Numero ordine sistema
  Numero_Ordine_Cliente= Numero ordine del cliente

DATE (usa Data_Fattura come data principale; fallback: Data_Ordine, Data_Consegna, Data_DDT):
  Data_Ordine          = Data inserimento ordine
  Data_Ordine_Cliente  = Data emissione ordine cliente
  Data_DDT             = Data DDT
  Data_Consegna        = Data consegna
  Data_Partenza        = Data partenza
  Data_Fattura         = Data fattura
  Numero_DDT           = Numero DDT sistema
  Numero_DDT_esterno   = Numero DDT del vettore
  Numero_Fattura       = Numero fattura

CLIENTE (per domande su chi ha comprato):
  Cod_Cliente_Fat      = Codice cliente di fatturazione
  Decr_Cliente_Fat     = Ragione sociale cliente fatturazione → LA COLONNA CLIENTE PRINCIPALE
  Cod_Cliente_Dest     = Codice destinazione merce
  Descr_Cliente_Dest   = Nome luogo destinazione merce
  Città_Dest           = Città di consegna
  Stato_Dest           = Stato di consegna

PRODOTTO (per domande su quale prodotto):
  Cod_Articolo         = Codice prodotto
  Descr_Articolo       = Descrizione prodotto → LA COLONNA PRODOTTO PRINCIPALE

QUANTITÀ:
  Qta_Cartoni_Ordinato   = Cartoni ordinati → usato come CT nelle tabelle
  Qta_Cartoni_Consegnato = Cartoni consegnati
  Qta_Cartoni_Fatturato  = Cartoni fatturati
  Qta_residua            = Quantità residua

PESO:
  Peso_Netto           = Peso netto singola riga
  Peso_Lordo           = Peso lordo singola riga
  Peso_Netto_TotRiga   = Kg netti totali riga → LA COLONNA KG PRINCIPALE per analisi volumi

VALORI ECONOMICI:
  Valuta_Ordine        = Valuta ordine
  Prezzo_Netto         = Prezzo netto unitario
  Prezzo_Lordo         = Prezzo lordo unitario
  Importo_Netto_TotRiga= Fatturato netto € riga → LA COLONNA FATTURATO € PRINCIPALE

SCONTI (per classificare le vendite):
  Sconto1_Canale       = Sconto contrattuale 1 (non usato per classificazione promo)
  Sconto2_Canale       = Sconto contrattuale 2 (non usato per classificazione promo)
  Sconto3_Canale       = Sconto contrattuale 3 (non usato per classificazione promo)
  Sconto5_Logistici    = Sconto logistico (non usato per classificazione promo)
  Sconto6_Canvass      = Sconto temporaneo (non usato per classificazione promo)
  Sconto4_Free         = Sconto promozionale libero → USATO per classificare promo
  Sconto7_Promozionali = Sconto promozionale concordato → USATO per classificare promo

  REGOLA CLASSIFICAZIONE (si applica SOLO a Sconto4_Free e Sconto7_Promozionali):
    • Vendita Normale = Sconto7=0 E Sconto4=0 (o vuoti/NaN)
    • In Promozione   = Sconto7>0 OPPURE Sconto4>0 (qualsiasi valore, ESCLUSI 99 e 100)
    • Omaggio         = Sconto7=99 o 100  OPPURE  Sconto4=99 o 100

LOGISTICA:
  Cod_Plant, Plant     = Sito produttivo / entità legale
  Key_Account          = Account di riferimento commerciale
  Key_Account_Region   = Stato di competenza key account
  Incoterm             = Incoterm ordine
  Vettore              = Nome vettore di trasporto
  Cod_Container        = Codice container
  Magazzino_Partenza   = Magazzino di partenza merce
  Resp                 = Responsabile inserimento ordine
  Numero_Pallet        = Numero pallet
  Sovrapponibile       = Pallet sovrapponibile (1=sì, 0=no)

RIFERIMENTI TEMPORALI AGGREGATI:
  Sett. Riferimento Data ordine   = Settimana dell'anno dell'ordine
  Sett. Riferimento Data consegna = Settimana dell'anno della consegna
  Mese Riferimento Data ordine    = Mese dell'ordine
  Mese Riferimento Data consegna  = Mese della consegna
  Anno data consegna              = Anno consegna
  Anno data ordine                = Anno ordine
  Anno data fattura               = Anno fattura
  Anno data ordine Semplice       = Anno ordine (duplicato con formula diversa)

════════════════════════════════════════════════════════════
STRUTTURA DEL CONTESTO AI
════════════════════════════════════════════════════════════
Il contesto viene aggiornato ad ogni render e contiene sezioni pre-calcolate:

  TOTALI COMPLESSIVI: somme esatte di Importo_Netto_TotRiga (€) e Peso_Netto_TotRiga (Kg)
  TOP 15 per CLIENTE: aggregazione per Decr_Cliente_Fat, ordinata per € decrescenti
  TOP 15 per PRODOTTO: aggregazione per Descr_Articolo, ordinata per € decrescenti
  TOP 10 CLIENTI + PRODOTTO PRINCIPALE: tabella pre-calcolata con rank, cliente,
    fatturato totale €, prodotto principale, fatturato prodotto principale €
  TOP/BOTTOM CLIENTI per PRODOTTO: per ogni prodotto, i 5 clienti con più/meno acquisti
  TOP/BOTTOM PRODOTTI per CLIENTE: per ogni cliente, i 5 prodotti con più/meno acquisti
  TREND MENSILE: aggregazione mensile per Peso_Netto_TotRiga e Importo_Netto_TotRiga
  ANALISI PROMO vs NORMALE: tabelle per cliente e prodotto con Kg promo/normale/omaggio e %
  CROSS PROMO per PRODOTTO×CLIENTE: % promo su Kg per ogni combinazione prodotto-cliente

════════════════════════════════════════════════════════════
REGOLE DI RISPOSTA — OBBLIGATORIE
════════════════════════════════════════════════════════════
1. DATI ESATTI: tutti i valori nel contesto sono calcolati dal database, non stime.
   Citali con certezza assoluta, senza disclaimer ("circa", "presumibilmente", ecc.).

2. PERIODO: il contesto indica esplicitamente il periodo analizzato (es. 01/01/2026–31/01/2026).
   Rispondi con certezza sull'anno/periodo senza aggiungere "non so se è 2026".

3. NIENTE FRASI DI CAUTELA. Non scrivere mai:
   "non sono sicuro" / "potrebbe essere" / "non possiamo confermare" /
   "se i dati fossero disponibili" / "presumibilmente" / "stimo" / "circa"

4. NO RIPETIZIONI: scrivi ogni concetto una sola volta. Concludi dopo l'ultima info utile.

5. TOP N CLIENTI → usa SEMPRE la tabella "TOP 10 CLIENTI + PRODOTTO PRINCIPALE".
   Quella tabella contiene già: rank, Decr_Cliente_Fat, Importo_Netto_TotRiga,
   prodotto principale (Descr_Articolo con più fatturato), fatturato prodotto principale.
   Non sintetizzare da altre sezioni — leggi quella tabella verbatim.

6. TOP N PRODOTTI/FORNITORI → leggi la tabella TOP 15 per PRODOTTO/FORNITORE.

7. "Chi ha comprato di PIÙ X?" → leggi riga "↑ TOP" sotto il prodotto X in TOP/BOTTOM CLIENTI.
8. "Chi ha comprato di MENO X?" → leggi riga "↓ BOTTOM" sotto il prodotto X.
9. "Cosa ha comprato di più/meno il cliente Y?" → leggi TOP/BOTTOM PRODOTTI per CLIENTE.
10. "Trend/andamento" → leggi TREND MENSILE.
11. Cita i valori con unità: "€ 1.234.567" oppure "1.234 Kg" (formato italiano con punto migliaia).
12. Usa tabelle Markdown solo per confronti multi-riga. Ogni colonna della tabella deve
    corrispondere a una colonna LETTA dal contesto, non calcolata autonomamente dall'AI.

ANALISI PROMO:
13. Per "% promo per cliente/prodotto" → leggi ANALISI PROMO vs NORMALE, colonna % Promo(Kg).
    La % è calcolata su Peso_Netto_TotRiga (Kg), identica al grafico donut della dashboard.
14. Per "chi ha comprato X più in promo?" → leggi CROSS PROMO per PRODOTTO×CLIENTE,
    trova prodotto X, ordina per % Promo(Kg) decrescente.
15. Gli Sconti da 1 a 6 (Canale, Logistici, Canvass) NON determinano se una vendita è promo.
    Solo Sconto4_Free e Sconto7_Promozionali classificano promo/normale/omaggio.

LIMITI:
16. Se il dato richiesto non è nel contesto → dì "Dato non disponibile nel contesto attuale"
    e suggerisci di usare i filtri della dashboard.
17. NON inventare valori. NON costruire tabelle con colonne non presenti nel contesto.
18. NON creare colonne calcolate autonomamente nelle tabelle (es. % variazione, medie
    non presenti nel contesto). Riporta solo i valori già calcolati nel contesto.
"""

# ---------------------------------------------------------------------------
# Limiti free tier (fonte: documentazione ufficiale Feb 2026)
# ---------------------------------------------------------------------------
_GROQ_FREE_RPM = 30
_GROQ_FREE_TPD = 500_000    # stima conservativa (varia per modello)
_GROQ_MODELS   = [
    "llama-3.3-70b-versatile",  # migliore qualità, 1.000 RPD
    "llama-3.1-8b-instant",     # più veloce, 14.400 RPD (fallback quota)
]


def _get_ai_client():
    """
    Restituisce (client, provider, model_name, error, diag).
    NESSUNA chiamata di rete qui — solo lettura secrets e import.
    La verifica reale avviene in _call_ai_groq / _call_ai.
    Priorità: Groq → Gemini.
    """
    diag = []

    # ---------------------------------------------------------------
    # Helper: legge un secret dal top-level O da una sezione annidata.
    # NECESSARIO perché in TOML le chiavi scritte DOPO [google_cloud]
    # finiscono annidate in quella sezione, non al top level.
    # Es: st.secrets["groq_api_key"] → KeyError
    #     st.secrets["google_cloud"]["groq_api_key"] → OK
    # ---------------------------------------------------------------
    def _read_secret(key: str) -> str:
        """Cerca `key` al top-level e in tutte le sezioni annidate."""
        # 1. Top level
        val = st.secrets.get(key, "")
        if val:
            return val
        # 2. Sezioni annidate (google_cloud, ecc.)
        for section_key in st.secrets:
            try:
                section = st.secrets[section_key]
                if hasattr(section, "get"):
                    val = section.get(key, "")
                    if val:
                        return val
            except Exception:
                continue
        return ""

    # --- GROQ (primario, gratuito) ---
    groq_key = _read_secret("groq_api_key")
    groq_key_location = "top-level"
    if not groq_key:
        groq_key_location = "non trovato"
        diag.append("groq_api_key: ❌ non trovato nei Secrets (né top-level né sezioni annidate)")
        diag.append("  SOLUZIONE: nel file Secrets, metti groq_api_key PRIMA di [google_cloud]")
    else:
        # Determina dove è stato trovato
        if st.secrets.get("groq_api_key", ""):
            groq_key_location = "top-level ✅"
        else:
            groq_key_location = "in sezione annidata ⚠️ (meglio spostarlo prima di [google_cloud])"
        diag.append(f"groq_api_key: trovato — posizione: {groq_key_location}")
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            diag.append("Groq SDK: importato e inizializzato ✅")
            diag.append(f"Modello: {_GROQ_MODELS[0]}")
            return client, "groq", _GROQ_MODELS[0], None, "\n".join(diag)
        except ImportError:
            diag.append("❌ Pacchetto 'groq' NON installato nell'ambiente Streamlit")
            diag.append("  → Verifica requirements.txt → fai Manage App → Reboot app")
        except Exception as e:
            diag.append(f"❌ Groq init error: {type(e).__name__}: {e}")

    # --- GEMINI (fallback) ---
    gemini_key = _read_secret("gemini_api_key")
    if gemini_key:
        diag.append(f"gemini_api_key: trovato — uso come fallback")
        try:
            genai.configure(api_key=gemini_key)
            for mname in ["gemini-2.0-flash-lite", "gemini-2.5-flash"]:
                try:
                    m = genai.GenerativeModel(
                        model_name=mname,
                        system_instruction=_AI_SYSTEM_PROMPT,
                        generation_config=genai.GenerationConfig(
                            temperature=0.1, top_p=0.85, max_output_tokens=4096
                        ),
                    )
                    diag.append(f"Gemini {mname}: OK ✅")
                    return m, "gemini", mname, None, "\n".join(diag)
                except Exception as em:
                    diag.append(f"  Gemini {mname}: {type(em).__name__}: {em}")
                    continue
        except Exception as e:
            diag.append(f"❌ Gemini config error: {e}")
    else:
        diag.append("gemini_api_key: non trovato")

    return None, None, None, (
        "Nessuna API configurata.\n\n"
        "Aggiungi nei Secrets Streamlit (PRIMA di [google_cloud]):\n"
        'groq_api_key = "gsk_..."'
    ), "\n".join(diag)


# ---------------------------------------------------------------------------
# Config Plotly: scrollZoom=False blocca il mouse wheel su desktop.
# Per il pinch-to-zoom su mobile la soluzione AFFIDABILE è fixedrange=True
# negli assi del layout — impedisce zoom nel motore Plotly stesso.
# ---------------------------------------------------------------------------
_PLOTLY_CONFIG = {
    "scrollZoom":             False,
    "doubleClick":            "reset",
    "displayModeBar":         "hover",
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
    "responsive":             True,
    "displaylogo":            False,
}


def _plot(fig, key: str = None, allow_zoom: bool = None) -> None:
    """
    Wrapper st.plotly_chart con gestione zoom mobile.

    Modalità SCROLL (default, zoom OFF):
      config staticPlot=True → Plotly non cattura NESSUN evento touch
      → il browser riceve tutti gli eventi → la pagina scrolla normalmente.
      Il grafico è visibile ma non interattivo.

    Modalità ZOOM (zoom ON via toggle sidebar):
      staticPlot=False → interazione normale (zoom, pan, hover).
      fixedrange rimosso → pinch-to-zoom funziona.
    """
    if allow_zoom is None:
        allow_zoom = st.session_state.get("chart_zoom_enabled", False)

    if allow_zoom:
        # Zoom ON: interattività completa
        cfg = dict(_PLOTLY_CONFIG)
        cfg["staticPlot"] = False
    else:
        # Zoom OFF: grafico statico → scroll pagina funziona su mobile
        cfg = {
            "staticPlot":  True,   # nessun evento catturato da Plotly
            "responsive":  True,
            "displaylogo": False,
        }

    st.plotly_chart(
        fig,
        config=cfg,
        key=key,
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Mapping colonne per dataset: client → colonne cliente, amount → importo, ecc.
# Usato da _build_compact_context per creare aggregazioni reali.
# ---------------------------------------------------------------------------
# ==========================================================================
# COSTANTI PROMO — usate dal grafico E dal contesto AI
# ==========================================================================
_COL_S7 = 'Sconto7_Promozionali'   # colonna sconto promozionale
_COL_S4 = 'Sconto4_Free'           # colonna sconto free (omaggio)
_COL_KG = 'Peso_Netto_TotRiga'     # colonna Kg
_COL_EU = 'Importo_Netto_TotRiga'  # colonna € netti
_COL_CT = 'Qta_Cartoni_Ordinato'   # colonna cartoni
_COL_AT = 'Descr_Articolo'         # colonna articolo
_COL_CL = 'Decr_Cliente_Fat'       # colonna cliente fatturazione
# Ordine di preferenza per il rilevamento colonna data nel file From_order_to_invoice:
# Data_Fattura → Data_Ordine → Data_Consegna → Data_DDT → Data_Partenza → Data_Documento
_COL_DT_FALLBACKS = [
    'Data_Fattura', 'Data_Ordine', 'Data_Consegna',
    'Data_DDT', 'Data_Partenza', 'Data_Documento', 'Data', 'Date'
]

# ── Legenda COMPLETA colonne From_order_to_invoice ──────────────────────
# Fonte: documentazione interna EITA (fornita dall'utente)
_SALES_COL_LEGEND = {
    "Entity":                   "Entità aziendale (es. EITA) — FILTRO PRINCIPALE per isolare i dati EITA",
    "Data_Documento":           "Data del documento (fattura/ordine) — usata per il filtro periodo",
    "Numero_Documento":         "Numero progressivo del documento",
    "Tipo_Documento":           "Tipo documento (es. Fattura, Nota Credito)",
    "Codice_Cliente_Fat":       "Codice identificativo del cliente di fatturazione",
    "Decr_Cliente_Fat":         "Nome/ragione sociale del cliente di fatturazione (colonna CLIENTE)",
    "Codice_Cliente_Dest":      "Codice identificativo del cliente di destinazione merce",
    "Descr_Cliente_Dest":       "Nome/ragione sociale del cliente destinatario merce",
    "Codice_Articolo":          "Codice prodotto interno",
    "Descr_Articolo":           "Descrizione prodotto (colonna PRODOTTO per analisi)",
    "Qta_Cartoni_Ordinato":     "Quantità in cartoni ordinata",
    "Peso_Netto_TotRiga":       "Peso netto totale della riga in kg (METRICA PRINCIPALE per analisi Kg)",
    "Importo_Netto_TotRiga":    "Importo netto totale della riga in € (METRICA PRINCIPALE per fatturato)",
    "Prezzo_Netto":             "Prezzo netto unitario del prodotto (€/unità)",
    "Sconto7_Promozionali":     "Sconto promozionale: >0 = vendita promo; 99/100 = omaggio; 0 = normale",
    "Sconto4_Free":             "Sconto free (omaggio): >0 = vendita promo; 99/100 = omaggio; 0 = normale",
    "Numero_Pallet":            "Numero pallet (logistica, non usato per analisi commerciali)",
    "COMPANY":                  "Campo tecnico ERP — non usato per analisi (usa Entity invece)",
}


def _classifica_vendita(df: "pd.DataFrame") -> "pd.Series":
    """
    Regole ufficiali (applicate identicamente da grafico e AI):
    - s7=0 E s4=0 (o null/NaN) → 'Vendita Normale'
    - s7=99 O s7=100 O s4=99 O s4=100 → 'Omaggio'
    - qualsiasi altro valore >0 in s7 O s4 → 'In Promozione'
    Ritorna una Series con le stesse categories per ogni riga del df.
    """
    s7 = df[_COL_S7].fillna(0) if _COL_S7 in df.columns else pd.Series(0, index=df.index)
    s4 = df[_COL_S4].fillna(0) if _COL_S4 in df.columns else pd.Series(0, index=df.index)
    is_omaggio = s7.isin([99, 100]) | s4.isin([99, 100])
    is_promo   = (~is_omaggio) & ((s7 > 0) | (s4 > 0))
    tipo = pd.Series('Vendita Normale', index=df.index, dtype='object')
    tipo[is_promo]   = 'In Promozione'
    tipo[is_omaggio] = 'Omaggio'
    return tipo


def _filtra_vendite_periodo(df_sales: "pd.DataFrame", g_start, g_end,
                             entity: str = None) -> "pd.DataFrame":
    """
    Filtra df_sales per periodo G_START/G_END e opzionalmente per entity.
    Aggiunge colonna '__tipo__' con _classifica_vendita().
    Restituisce il df filtrato pronto per grafico E contesto AI.
    """
    df = df_sales.copy()
    # Filtro data — usa la lista completa di fallback per trovare la colonna giusta
    col_dt = next((c for c in _COL_DT_FALLBACKS if c in df.columns
                   and pd.api.types.is_datetime64_any_dtype(df[c])), None)
    if col_dt is None:
        # Ultimo tentativo: cerca qualsiasi colonna datetime nel df
        col_dt = next((c for c in df.columns
                       if pd.api.types.is_datetime64_any_dtype(df[c])), None)
    if col_dt:
        df = df[(df[col_dt].dt.date >= g_start) & (df[col_dt].dt.date <= g_end)]
    # Filtro entity
    if entity:
        ent_col = next((c for c in ['Entity', 'Società', 'Company', 'Division', 'Azienda']
                        if c in df.columns), None)
        if ent_col:
            df = df[df[ent_col].astype(str) == entity]
    # Classificazione
    df = df.copy()
    df['__tipo__'] = _classifica_vendita(df)
    return df


_CTX_COL_MAPS = {
    # Dataset Vendite
    "vendite": {
        "cliente":  ["Decr_Cliente_Fat", "Descr_Cliente_Fat", "Descr_Cliente_Dest", "Cliente"],
        "prodotto": ["Descr_Articolo", "Prodotto", "Articolo"],
        "importo":  ["Importo_Netto_TotRiga", "Euro", "Fatturato", "Netto"],
        "kg":       ["Peso_Netto_TotRiga", "Kg", "Peso"],
        "entita":   ["Entity", "Società", "Division"],
        "data":     ["Data_Fattura", "Data_Ordine", "Data_Consegna", "Data_DDT", "Data_Documento", "Data", "Date"],
    },
    # Dataset Promozioni
    "promo": {
        "prodotto": ["Descr_Articolo", "Prodotto"],
        "cliente":  ["Decr_Cliente_Fat", "Descr_Cliente_Fat", "Cliente"],
        "importo":  ["Importo_Netto_TotRiga", "Euro"],
        "qty":      ["Qta_Cartoni_Ordinato", "Quantità"],
        "data":     ["Data_Fattura", "Data_Ordine", "Data_Consegna", "Data_DDT", "Data_Documento", "Data"],
    },
    # Dataset Acquisti
    "acquisti": {
        "fornitore": ["Supplier name", "Supplier number"],
        "prodotto":  ["Part description", "Part group description", "Part number"],
        "importo":   ["Invoice amount", "Line amount", "Row amount"],
        "kg":        ["Kg acquistati", "Part net weight"],
        "data":      ["Invoice date", "Delivery date", "Date of receipt"],
    },
}


def _detect_dataset_type(label: str, cols: list) -> str:
    """Rileva il tipo di dataset dal label e dalle colonne presenti."""
    label_lower = label.lower()
    if any(k in label_lower for k in ["acquist", "purchase", "supplier"]):
        return "acquisti"
    if any(k in label_lower for k in ["promo", "iniziativ"]):
        return "promo"
    if any(k in label_lower for k in ["vendit", "fattur", "sales"]):
        return "vendite"
    # Fallback: deduci dalle colonne
    cols_lower = [c.lower() for c in cols]
    if any("supplier" in c or "invoice" in c for c in cols_lower):
        return "acquisti"
    if "sconto7" in " ".join(cols_lower) or "promo" in " ".join(cols_lower):
        return "promo"
    return "vendite"


def _first_col(df: pd.DataFrame, candidates: list):
    """Ritorna la prima colonna candidata presente nel df, o None."""
    return next((c for c in candidates if c in df.columns), None)


def _fmt_num(val) -> str:
    """
    Formatta numero con separatori italiani COMPLETI.
    Numeri interi: 1.234.567  (nessuna abbreviazione → AI non dice "non sono sicuro")
    Numeri decimali: 1.234.567,89
    NON usare K/M: l'AI le interpreta come approssimazioni e si cautela.
    """
    try:
        v = float(val)
        if v == int(v) and abs(v) >= 1:
            # Numero intero: formato con punto come separatore migliaia
            return f"{int(v):,}".replace(",", ".")
        else:
            # Decimale: 2 cifre, punto migliaia, virgola decimale
            formatted = f"{v:,.2f}"
            # Converti da formato inglese (1,234.56) a italiano (1.234,56)
            formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
            return formatted
    except Exception:
        return str(val)


def _agg_table(df: pd.DataFrame, group_col: str, value_cols: list,
               top_n: int = 15, label: str = "") -> str:
    """
    Crea una tabella aggregata (group_col × SUM di value_cols).
    Ritorna stringa Markdown pronta per il context AI.
    """
    if df is None or df.empty:
        return ""
    present = [c for c in value_cols if c in df.columns]
    if not present or group_col not in df.columns:
        return ""
    try:
        agg = (df.groupby(group_col, observed=True)[present]
                 .sum(numeric_only=True)
                 .reset_index()
                 .sort_values(present[0], ascending=False)
                 .head(top_n))
        if agg.empty:
            return ""
        lines = [f"\nTOP {top_n} per {label or group_col}:"]
        header = f"{'Voce':<35} | " + " | ".join(f"{c:>14}" for c in present)
        lines.append(header)
        lines.append("-" * len(header))
        for _, row in agg.iterrows():
            voce = str(row[group_col])[:34]
            vals = " | ".join(f"{_fmt_num(row[c]):>14}" for c in present)
            lines.append(f"{voce:<35} | {vals}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Errore aggregazione {group_col}: {e}]"


def _monthly_trend(df: pd.DataFrame, date_col: str, value_cols: list) -> str:
    """Crea trend mensile aggregato (ultimi 24 mesi)."""
    if df is None or df.empty:
        return ""
    present = [c for c in value_cols if c in df.columns]
    if not present or date_col not in df.columns:
        return ""
    try:
        tmp = df.assign(__mese__=pd.to_datetime(df[date_col], errors="coerce").dt.to_period("M"))
        tmp = tmp.dropna(subset=["__mese__"])
        agg = (tmp.groupby("__mese__", observed=True)[present]
                  .sum(numeric_only=True)
                  .reset_index()
                  .sort_values("__mese__")
                  .tail(24))
        if agg.empty:
            return ""
        lines = ["\nTREND MENSILE (ultimi 24 mesi):"]
        header = f"{'Mese':<12} | " + " | ".join(f"{c:>14}" for c in present)
        lines.append(header)
        lines.append("-" * len(header))
        for _, row in agg.iterrows():
            vals = " | ".join(f"{_fmt_num(row[c]):>14}" for c in present)
            lines.append(f"{str(row['__mese__']):<12} | {vals}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Errore trend: {e}]"


@st.cache_data(show_spinner=False, ttl=120)
def _build_compact_context(context_df: pd.DataFrame, context_label: str) -> str:
    """
    Contesto INTELLIGENTE con aggregazioni reali per rispondere a domande come:
    - Top 5 clienti per fatturato → gruppo per cliente, somma importo
    - Fornitore con più spesa → gruppo per fornitore, somma invoice
    - Trend mensile → raggruppamento per mese
    - Qual è il prodotto più venduto → gruppo per prodotto, somma kg/qty

    Formato testo compatto (~600-1200 token) con tabelle Markdown leggibili dall'AI.
    """
    if context_df is None or context_df.empty:
        return ""

    df   = context_df
    n    = len(df)
    cols = df.columns.tolist()
    dset = _detect_dataset_type(context_label, cols)
    cmap = _CTX_COL_MAPS.get(dset, {})

    parts = []
    parts.append(f"\n\n{'='*60}")
    parts.append(f"DATASET: {context_label} | Righe: {n:,} | Tipo: {dset.upper()}")
    parts.append("⚡ TUTTI I VALORI SONO ESATTI — calcolati dal database, nessuna stima")
    # Estrai il periodo dal label se presente (formato "Vendite EITA | Periodo: DD/MM/YYYY – DD/MM/YYYY")
    if "Periodo:" in context_label:
        parts.append(f"📅 {context_label.split('Periodo:')[1].strip()}")
        parts.append("   → I dati sopra si riferiscono SOLO a questo periodo. Rispondi con certezza.")
    parts.append(f"Colonne disponibili: {', '.join(cols)}")
    parts.append("="*60)

    # --- Colonne chiave ---
    col_cliente  = _first_col(df, cmap.get("cliente",  []))
    col_prodotto = _first_col(df, cmap.get("prodotto", []))
    col_fornitore= _first_col(df, cmap.get("fornitore",[]))
    col_importo  = _first_col(df, cmap.get("importo",  []))
    col_kg       = _first_col(df, cmap.get("kg",       []))
    col_qty      = _first_col(df, cmap.get("qty",      []))
    col_data     = _first_col(df, cmap.get("data",     []))

    # Colonne numeriche effettive
    num_cols = df.select_dtypes(include="number").columns.tolist()
    val_cols = [c for c in [col_importo, col_kg, col_qty] if c and c in num_cols]
    if not val_cols and num_cols:
        val_cols = num_cols[:3]

    # --- Riepilogo totali ---
    if val_cols:
        tot_lines = []
        for c in val_cols:
            try:
                tot = df[c].sum()
                tot_lines.append(f"  {c}: {_fmt_num(tot)}")
            except Exception:
                pass
        if tot_lines:
            parts.append("\nTOTALI COMPLESSIVI:\n" + "\n".join(tot_lines))

    # --- Aggregazioni per CLIENTE ---
    if col_cliente:
        parts.append(_agg_table(df, col_cliente, val_cols, top_n=15, label="CLIENTE"))

    # --- Aggregazioni per PRODOTTO ---
    if col_prodotto:
        parts.append(_agg_table(df, col_prodotto, val_cols, top_n=15, label="PRODOTTO"))

    # --- Aggregazioni per FORNITORE (acquisti) ---
    if col_fornitore:
        parts.append(_agg_table(df, col_fornitore, val_cols, top_n=15, label="FORNITORE"))

    # --- Altre colonne categoriche chiave ---
    cat_cols = df.select_dtypes(exclude="number").columns.tolist()
    done = {col_cliente, col_prodotto, col_fornitore, col_data}
    for c in cat_cols:
        if c in done or c is None:
            continue
        n_unique = df[c].nunique()
        # Solo colonne con cardinalità media (5-200 valori unici) → utili per groupby
        if 2 <= n_unique <= 200 and val_cols:
            parts.append(_agg_table(df, c, val_cols[:2], top_n=10, label=c))
        if len("\n".join(parts)) > 2000:
            break  # limite token (8k char max totale)

    # --- TABELLA PRONTA: Top 5 clienti + prodotto principale + fatturato ---
    # Pre-calcolata per rispondere ESATTAMENTE a "top N clienti con prodotto principale"
    # POSIZIONE: PRIMA dei CROSS (che sono pesanti) → se il contesto viene troncato
    # questa tabella è già inclusa (risponde alla domanda più frequente).
    if col_cliente and col_prodotto and val_cols:
        try:
            cli_tot = (df.groupby(col_cliente, observed=True)[val_cols[0]]
                        .sum().sort_values(ascending=False).head(5))
            top10_lines = [
                f"\nTOP 10 CLIENTI PER FATTURATO con PRODOTTO PRINCIPALE:",
                f"(usa questa tabella per 'top N clienti' — dati PRE-CALCOLATI esatti)",
                f"{'#':<3} | {'Cliente':<40} | {'Fatturato €':>14} | {'Prodotto Principale':<40} | {'Fat. Prod. Princ. €':>19}",
                "-" * 130,
            ]
            for rank, (cli, fat_tot) in enumerate(cli_tot.items(), 1):
                df_cli = df[df[col_cliente] == cli]
                prod_agg = (df_cli.groupby(col_prodotto, observed=True)[val_cols[0]]
                                  .sum().sort_values(ascending=False))
                if prod_agg.empty:
                    top_prod, fat_prod = "-", 0.0
                else:
                    top_prod = prod_agg.index[0]
                    fat_prod = prod_agg.values[0]
                cli_str  = str(cli)[:39]
                prod_str = str(top_prod)[:39]
                top10_lines.append(
                    f"{rank:<3} | {cli_str:<40} | {_fmt_num(fat_tot):>14} | {prod_str:<40} | {_fmt_num(fat_prod):>19}"
                )
            parts.append("\n".join(top10_lines))
        except Exception as e:
            parts.append(f"[Top10 error: {e}]")

    # --- Trend mensile ---
    if col_data and val_cols:
        parts.append(_monthly_trend(df, col_data, val_cols[:2]))

    # --- Indice prodotti compatto (fuzzy match AI: "selection"→nome esatto) ---
    if col_prodotto:
        try:
            all_prods = sorted(df[col_prodotto].dropna().astype(str).unique().tolist())
            prod_idx = ["\nINDICE PRODOTTI (usa per fuzzy match su nome parziale):"]
            for p in all_prods:
                prod_idx.append(f"  • {p}")
            parts.append("\n".join(prod_idx))
        except Exception:
            pass

    # --- Cross: TOP + BOTTOM CLIENTI per ogni PRODOTTO ---
    # TOP → risponde a: "Chi ha comprato di PIÙ X?"
    # BOTTOM → risponde a: "Chi ha comprato di MENO X?" / "chi ha fatturato meno?"
    if col_cliente and col_prodotto and val_cols:
        try:
            # Tutti i prodotti (non solo top 12) per trovare anche "selection"
            all_prod_list = df[col_prodotto].dropna().unique().tolist()
            cross_lines = ["\nTOP E BOTTOM CLIENTI per PRODOTTO"]
            cross_lines.append("(risponde a 'chi ha comprato di più/meno X?', 'chi ha fatturato più/meno con X?'):")
            for prod in all_prod_list:
                df_prod = df[df[col_prodotto] == prod]
                cli_agg = (df_prod.groupby(col_cliente, observed=True)[val_cols]
                                  .sum(numeric_only=True)
                                  .reset_index()
                                  .sort_values(val_cols[0], ascending=False))
                if cli_agg.empty or len(cli_agg) < 1:
                    continue
                cross_lines.append(f"\n  Prodotto: {prod}")
                # TOP 5 (di più)
                cross_lines.append("    TOP (di più):")
                for _, row in cli_agg.head(5).iterrows():
                    vals = " | ".join(f"{_fmt_num(row[c])}" for c in val_cols if c in row.index)
                    cross_lines.append(f"      ↑ {str(row[col_cliente])[:40]}: {vals}")
                # BOTTOM 3 (di meno) — solo se ci sono abbastanza clienti
                if len(cli_agg) > 5:
                    cross_lines.append("    BOTTOM (di meno):")
                    for _, row in cli_agg.tail(3).iterrows():
                        vals = " | ".join(f"{_fmt_num(row[c])}" for c in val_cols if c in row.index)
                        cross_lines.append(f"      ↓ {str(row[col_cliente])[:40]}: {vals}")
                elif len(cli_agg) > 1:
                    # Meno di 5 clienti: mostra tutti e indica il minimo
                    _, last_row = list(cli_agg.tail(1).iterrows())[0]
                    vals = " | ".join(f"{_fmt_num(last_row[c])}" for c in val_cols if c in last_row.index)
                    cross_lines.append(f"    MINIMO: {str(last_row[col_cliente])[:40]}: {vals}")
                if len("\n".join(parts) + "\n".join(cross_lines)) > 8000:
                    cross_lines.append("  [... altri prodotti omessi per limite token]")
                    break
            if len(cross_lines) > 2:
                parts.append("\n".join(cross_lines))
        except Exception as e:
            parts.append(f"[Cross-agg error: {e}]")

    # --- Cross: TOP + BOTTOM PRODOTTI per ogni CLIENTE (top 8 clienti) ---
    # Risponde a: "Cosa ha comprato di più/meno Esselunga?"
    if col_cliente and col_prodotto and val_cols:
        try:
            top_clients = (df.groupby(col_cliente, observed=True)[val_cols[0]]
                            .sum().sort_values(ascending=False).head(8).index.tolist())
            cross2_lines = ["\nTOP E BOTTOM PRODOTTI per CLIENTE"]
            cross2_lines.append("(risponde a 'cosa ha comprato di più/meno il cliente X?'):")
            for cli in top_clients:
                df_cli = df[df[col_cliente] == cli]
                prod_agg = (df_cli.groupby(col_prodotto, observed=True)[val_cols]
                                  .sum(numeric_only=True)
                                  .reset_index()
                                  .sort_values(val_cols[0], ascending=False))
                if prod_agg.empty:
                    continue
                cross2_lines.append(f"\n  Cliente: {cli}")
                cross2_lines.append("    TOP (di più):")
                for _, row in prod_agg.head(5).iterrows():
                    vals = " | ".join(f"{_fmt_num(row[c])}" for c in val_cols if c in row.index)
                    cross2_lines.append(f"      ↑ {str(row[col_prodotto])[:40]}: {vals}")
                if len(prod_agg) > 5:
                    cross2_lines.append("    BOTTOM (di meno):")
                    for _, row in prod_agg.tail(3).iterrows():
                        vals = " | ".join(f"{_fmt_num(row[c])}" for c in val_cols if c in row.index)
                        cross2_lines.append(f"      ↓ {str(row[col_prodotto])[:40]}: {vals}")
                if len("\n".join(parts) + "\n".join(cross2_lines)) > 9000:
                    break
            if len(cross2_lines) > 2:
                parts.append("\n".join(cross2_lines))
        except Exception as e:
            parts.append(f"[Cross-agg2 error: {e}]")

    # --- Analisi PROMO vs NORMALE (solo se le colonne sconto sono presenti) ---
    # Risponde a: "chi ha comprato X più in promo?" / "% promo per cliente"
    # Analisi promo: usa le stesse costanti e la stessa funzione del grafico
    _has_promo_cols = _COL_S7 in df.columns or any("sconto7" in c.lower() for c in df.columns)
    if _has_promo_cols and col_cliente and val_cols:
        try:
            df_tmp = df.copy()
            # __tipo__ già presente (df pre-classificato) o va calcolato ora
            if '__tipo__' not in df_tmp.columns:
                df_tmp['__tipo__'] = _classifica_vendita(df_tmp)
            # Mappa per analisi binaria (normale/promo, esclude Omaggio dal % promo)
            is_promo   = df_tmp['__tipo__'] == 'In Promozione'
            is_omaggio = df_tmp['__tipo__'] == 'Omaggio'
            is_normale = df_tmp['__tipo__'] == 'Vendita Normale'
            col_s7 = _COL_S7
            col_s4 = _COL_S4

            # METRICA UNIFICATA: usa Kg (col_kg) se disponibile, altrimenti €
            # Il grafico donut usa Kg → per coerenza l'AI usa la stessa metrica
            # QUESTO ELIMINA LA DISCREPANZA: righe con €=0 e Kg>0 (resi/campioni)
            # venivano conteggiate diversamente con € vs Kg
            _metric_col = col_kg if (col_kg and col_kg in df_tmp.columns) else val_cols[0]
            _metric_label = "Kg" if _metric_col == col_kg else "€"
            _eur_col = val_cols[0] if val_cols else None  # per riportare € a parte

            # Aggregazione per cliente: totale, promo, normale, % promo (su Kg)
            grp = df_tmp.groupby(col_cliente, observed=True)
            tot_m  = grp[_metric_col].sum()
            promo_m = df_tmp[is_promo].groupby(col_cliente, observed=True)[_metric_col].sum()
            norm_m  = df_tmp[~is_promo].groupby(col_cliente, observed=True)[_metric_col].sum()
            # Aggiungi anche € per informazione
            tot_eur_c   = grp[_eur_col].sum() if _eur_col and _eur_col != _metric_col else tot_m
            promo_eur_c = df_tmp[is_promo].groupby(col_cliente, observed=True)[_eur_col].sum() if _eur_col and _eur_col != _metric_col else promo_m

            combined = pd.DataFrame({
                "Totale":    tot_m,
                "Promo":     promo_m,
                "Normale":   norm_m,
                "Tot€":      tot_eur_c,
                "Promo€":    promo_eur_c,
            }).fillna(0)
            combined["% Promo"] = (combined["Promo"] / combined["Totale"].replace(0, 1) * 100).round(1)
            combined = combined.sort_values("% Promo", ascending=False).reset_index()

            promo_lines = [f"\nANALISI PROMO vs NORMALE per CLIENTE"]
            promo_lines.append(f"(Sconto7={col_s7}" + (f", Sconto4={col_s4}" if col_s4 else "") + ")")
            promo_lines.append(f"METRICA: % calcolata su {_metric_label} (= donut)")
            promo_lines.append(f"REGOLA CLASSIFICAZIONE:")
            promo_lines.append(f"  Vendita Normale = s7=0 E s4=0 (o vuoti)")
            promo_lines.append(f"  In Promozione   = s7>0 OPPURE s4>0 (qualsiasi valore, esclusi 99/100)")
            promo_lines.append(f"  Omaggio         = s7=99 o 100 OPPURE s4=99 o 100")
            promo_lines.append(f"{'Cliente':<40} | {'Tot Kg':>10} | {'Promo Kg':>10} | {'% Promo(Kg)':>12} | {'Tot €':>12} | {'Promo €':>12}")
            promo_lines.append("-" * 105)
            for _, row in combined.iterrows():
                cli = str(row[col_cliente])[:39]
                promo_lines.append(
                    f"{cli:<40} | {_fmt_num(row['Totale']):>10} | {_fmt_num(row['Promo']):>10} | {row['% Promo']:>11.1f}% | {_fmt_num(row['Tot€']):>12} | {_fmt_num(row['Promo€']):>12}"
                )
                if len("\n".join(promo_lines)) > 2500:
                    promo_lines.append("  [...altri clienti omessi per limite token]")
                    break
            promo_lines.append("")
            promo_lines.append(f"STESSO CALCOLO per PRODOTTO (% su {_metric_label}, top 20 per €):")
            promo_lines.append(f"{'Prodotto':<40} | {'Tot Kg':>10} | {'Promo Kg':>10} | {'% Promo(Kg)':>12} | {'Tot €':>12}")
            promo_lines.append("-" * 90)

            if col_prodotto:
                grp_p = df_tmp.groupby(col_prodotto, observed=True)
                tot_pm   = grp_p[_metric_col].sum()
                promo_pm = df_tmp[is_promo].groupby(col_prodotto, observed=True)[_metric_col].sum()
                tot_pe   = grp_p[_eur_col].sum() if _eur_col and _eur_col != _metric_col else tot_pm
                comb_p  = pd.DataFrame({"Totale": tot_pm, "Promo": promo_pm, "Tot€": tot_pe}).fillna(0)
                comb_p["% Promo"] = (comb_p["Promo"] / comb_p["Totale"].replace(0,1) * 100).round(1)
                comb_p = comb_p.sort_values("Tot€", ascending=False).head(20).reset_index()
                for _, row in comb_p.iterrows():
                    prod = str(row[col_prodotto])[:39]
                    promo_lines.append(
                        f"{prod:<40} | {_fmt_num(row['Totale']):>10} | {_fmt_num(row['Promo']):>10} | {row['% Promo']:>11.1f}% | {_fmt_num(row['Tot€']):>12}"
                    )

            # Cross: % promo per ogni PRODOTTO × CLIENTE — metrica Kg (= donut)
            if col_prodotto:
                promo_lines.append(f"\nCROSS: % PROMO per PRODOTTO × CLIENTE (% su {_metric_label} = UGUALE a donut):")
                top_p_list = (df_tmp.groupby(col_prodotto, observed=True)[_eur_col or _metric_col]
                               .sum().sort_values(ascending=False).head(15).index.tolist())
                for prod in top_p_list:
                    df_p = df_tmp[df_tmp[col_prodotto] == prod]
                    is_p_promo = df_p["__tipo__"] == "In Promozione"
                    cli_grp = df_p.groupby(col_cliente, observed=True)
                    cli_tot_m  = cli_grp[_metric_col].sum()
                    cli_promo_m = df_p[is_p_promo].groupby(col_cliente, observed=True)[_metric_col].sum()
                    cli_tot_e  = cli_grp[_eur_col].sum() if _eur_col and _eur_col != _metric_col else cli_tot_m
                    cli_df = pd.DataFrame({"TotKg": cli_tot_m, "PromoKg": cli_promo_m, "Tot€": cli_tot_e}).fillna(0)
                    cli_df["% Promo"] = (cli_df["PromoKg"] / cli_df["TotKg"].replace(0,1) * 100).round(1)
                    cli_df = cli_df.sort_values("% Promo", ascending=False).reset_index()
                    if cli_df.empty:
                        continue
                    promo_lines.append(f"\n  {prod}:")
                    for _, row in cli_df.iterrows():
                        promo_lines.append(
                            f"    {str(row[col_cliente])[:38]}: {_fmt_num(row['TotKg'])} Kg tot / {_fmt_num(row['PromoKg'])} Kg promo ({row['% Promo']:.1f}%) / {_fmt_num(row['Tot€'])} €"
                        )
                    if len("\n".join(promo_lines)) > 3500:
                        promo_lines.append("  [...omesso per limite token]")
                        break

            parts.append("\n".join(promo_lines))
        except Exception as e:
            parts.append(f"[Analisi promo error: {e}]")

    parts.append("\n" + "="*60 + " FINE CONTESTO =" + "="*44 + "\n")
    full_ctx = "\n".join(p for p in parts if p)
    # HARD CAP: tronca il contesto a 10000 char per non sforare i limiti Groq
    # System prompt ~8000 char + contesto dati ~10000 char = ~18000 char ≈ 4500 token
    # Groq free tier: 6000 TPM → safe margin con conversazione multi-turno
    _MAX_CTX = 10000
    if len(full_ctx) > _MAX_CTX:
        full_ctx = full_ctx[:_MAX_CTX] + "\n...[CONTESTO TRONCATO PER LIMITE TOKEN — usa filtri per ridurre i dati]\n"
    return full_ctx


def _transcribe_audio_groq(client, audio_bytes: bytes) -> str:
    """Trascrive audio WAV con Whisper via Groq (gratis, veloce)."""
    try:
        result = client.audio.transcriptions.create(
            file=("audio.wav", audio_bytes, "audio/wav"),
            model="whisper-large-v3-turbo",
            language="it",
            response_format="text",
        )
        return str(result).strip()
    except Exception as e:
        return f"[Errore trascrizione: {e}]"


def _call_groq(client, model_name: str, history: list,
               prompt: str, audio_bytes: bytes = None,
               max_retries: int = 1):
    """Chiama Groq con retry. Prova prima 70B poi 8B su rate limit."""
    final_prompt = prompt
    if audio_bytes:
        transcript = _transcribe_audio_groq(client, audio_bytes)
        final_prompt = f"[Domanda vocale trascritta]: {transcript}\n\n{prompt}"

    models_to_try = list(dict.fromkeys([model_name] + _GROQ_MODELS))  # dedup, order preserved
    current_model = models_to_try[0]

    for attempt in range(max_retries + 1):
        try:
            messages = [{"role": "system", "content": _AI_SYSTEM_PROMPT}]
            for m in history:
                messages.append({
                    "role":    "assistant" if m["role"] == "model" else m["role"],
                    "content": m["text"],
                })
            messages.append({"role": "user", "content": final_prompt})
            resp = client.chat.completions.create(
                model=current_model,
                messages=messages,
                temperature=0.05,   # quasi-deterministico → risposte precise e assertive
                max_tokens=8192,    # risposta lunga senza troncamenti
            )
            answer  = _deduplicate_response(resp.choices[0].message.content)
            in_tok  = getattr(resp.usage, "prompt_tokens",     0) or 0
            out_tok = getattr(resp.usage, "completion_tokens", 0) or 0
            return answer, in_tok, out_tok, None, current_model
        except Exception as e:
            err_str = str(e)
            is_rate  = "429" in err_str or "rate_limit" in err_str.lower()
            is_model = "model" in err_str.lower() and ("not found" in err_str.lower() or "does not exist" in err_str.lower())
            if (is_rate or is_model) and attempt < max_retries:
                # Prossimo modello nella lista
                idx = models_to_try.index(current_model) if current_model in models_to_try else 0
                if idx + 1 < len(models_to_try):
                    current_model = models_to_try[idx + 1]
                if is_rate:
                    wait_s = 3   # ridotto da 15s per fallback più rapido
                    m_wait = re.search(r"retry in (\d+)", err_str)
                    if m_wait:
                        wait_s = min(int(m_wait.group(1)), 20)
                    time.sleep(wait_s)
                continue
            return None, 0, 0, err_str, current_model
    return None, 0, 0, "Quota esaurita.", current_model


def _call_gemini(client, history: list, prompt: str, audio_bytes: bytes = None):
    """Chiama Gemini con retry su 429."""
    gem_history = [
        {"role": m["role"], "parts": [m["text"]]}
        for m in history
    ]
    if audio_bytes:
        audio_b64 = base64.b64encode(audio_bytes).decode()
        content = [
            {"inline_data": {"mime_type": "audio/wav", "data": audio_b64}},
            {"text": prompt or "Analizza l'audio."},
        ]
    else:
        content = prompt
    for attempt in range(3):
        try:
            chat = client.start_chat(history=gem_history)
            resp = chat.send_message(content)
            usage   = getattr(resp, "usage_metadata", None)
            in_tok  = getattr(usage, "prompt_token_count",    0) or 0
            out_tok = getattr(usage, "candidates_token_count",0) or 0
            return _deduplicate_response(resp.text), in_tok, out_tok, None
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str) and attempt < 2:
                time.sleep(20)
                continue
            return None, 0, 0, err_str
    return None, 0, 0, "Quota Gemini esaurita."


def _deduplicate_response(text: str) -> str:
    """
    Rimuove paragrafi e frasi identici ripetuti consecutivamente.
    LLaMA con temperature bassa tende a ripetere l'ultimo blocco 2-3 volte,
    sia con doppio newline che concatenati senza separatore.
    """
    if not text:
        return text

    # --- PASSATA 1: paragrafi separati da \n\n ---
    paragraphs = text.split("\n\n")
    deduped = []
    prev = None
    for p in paragraphs:
        stripped = p.strip()
        if stripped and stripped != prev:
            deduped.append(p)
            prev = stripped
    text = "\n\n".join(deduped)

    # --- PASSATA 2: blocchi ripetuti concatenati senza separatore ---
    # Usa regex: trova il pattern (X){2,} dove X è qualunque sequenza >=30 chars
    import re as _re
    # Cerca sequenze ripetute 2+ volte (almeno 30 caratteri per sequenza)
    # Il pattern è greedy-free per trovare la ripetizione più lunga
    changed = True
    max_iter = 5
    while changed and max_iter > 0:
        changed = False
        max_iter -= 1
        # Cerca: una stringa di almeno 30 char seguita dalla stessa stringa identica
        match = _re.search(
            r'(.{30,}?)\1+',
            text,
            flags=_re.DOTALL
        )
        if match:
            # Sostituisce tutte le ripetizioni con una sola occorrenza
            repeated = _re.escape(match.group(1))
            original = match.group(0)
            text = text.replace(original, match.group(1), 1)
            changed = True

    # --- PASSATA 3: frasi ripetute consecutive ---
    parts = [s.strip() for s in text.split(". ") if s.strip()]
    clean = []
    prev_s = None
    for s in parts:
        if s != prev_s or len(s) < 15:
            clean.append(s)
            prev_s = s
    text = ". ".join(clean)
    if text and not text.endswith((".", "!", "?")):
        text += "."
    return text


def _call_ai(client, provider: str, model_name: str,
             history: list, prompt: str,
             audio_bytes: bytes = None,
             max_retries: int = 2):
    """
    Wrapper principale: chiama Groq o Gemini.
    Se Groq fallisce per motivo non-quota, tenta fallback su Gemini
    (se gemini_api_key è nei secrets) prima di mostrare errore.
    Restituisce (answer, in_tok, out_tok, error, provider_used, model_used).
    """
    if provider == "groq":
        answer, in_tok, out_tok, err, model_used = _call_groq(
            client, model_name, history, prompt, audio_bytes, max_retries
        )
        if answer:
            return answer, in_tok, out_tok, None, "groq", model_used

        # Groq fallito: prova Gemini automaticamente
        gemini_key = st.secrets.get("gemini_api_key", "")
        if gemini_key:
            try:
                genai.configure(api_key=gemini_key)
                for gm in ["gemini-2.0-flash-lite", "gemini-2.5-flash"]:
                    try:
                        gem_client = genai.GenerativeModel(
                            model_name=gm,
                            system_instruction=_AI_SYSTEM_PROMPT,
                            generation_config=genai.GenerationConfig(
                                temperature=0.1, top_p=0.85, max_output_tokens=4096
                            ),
                        )
                        ans2, it2, ot2, err2 = _call_gemini(gem_client, history, prompt, audio_bytes)
                        if ans2:
                            return ans2, it2, ot2, None, "gemini_fallback", gm
                    except Exception:
                        continue
            except Exception:
                pass
        # Tutto fallito
        is_quota = "429" in (err or "") or "rate_limit" in (err or "").lower()
        return None, 0, 0, err, "groq", model_used

    else:  # gemini primario
        ans, it, ot, err = _call_gemini(client, history, prompt, audio_bytes)
        return ans, it, ot, err, "gemini", model_name


def _tts_audio(text: str) -> bytes | None:
    """Genera audio MP3 da testo in italiano via gTTS (gratis, nessuna API key)."""
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        gTTS(text=text, lang="it", slow=False).write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except ImportError:
        return None
    except Exception:
        return None


def _update_token_stats(in_tok: int, out_tok: int, provider: str, model: str) -> None:
    """Aggiorna contatore token in session_state."""
    if "ai_token_stats" not in st.session_state:
        st.session_state["ai_token_stats"] = {
            "session_input": 0, "session_output": 0,
            "session_calls": 0, "last_call_ts": None,
            "day_start_ts": time.time(), "provider": provider, "model": model,
        }
    s = st.session_state["ai_token_stats"]
    if time.time() - s["day_start_ts"] > 86400:
        s["session_input"] = s["session_output"] = s["session_calls"] = 0
        s["day_start_ts"]  = time.time()
    s["session_input"]  += in_tok
    s["session_output"] += out_tok
    s["session_calls"]  += 1
    s["last_call_ts"]    = time.time()
    s["provider"]        = provider
    s["model"]           = model


def _render_token_counter() -> None:
    """Widget token counter compatto nella sidebar."""
    if "ai_token_stats" not in st.session_state:
        return
    s         = st.session_state["ai_token_stats"]
    tot       = s["session_input"] + s["session_output"]
    provider  = s.get("provider", "groq")
    model_lbl = s.get("model", "")
    # Limiti per provider
    tpd_limit = _GROQ_FREE_TPD if provider == "groq" else 1_000_000
    rpm_limit = _GROQ_FREE_RPM if provider == "groq" else 15
    est_rem   = max(0, tpd_limit - tot)
    pct       = min(100, int(tot / tpd_limit * 100))

    last_ts   = s.get("last_call_ts")
    rpm_wait  = max(0, int(60 - (time.time() - last_ts))) if last_ts else 0
    color     = "#43e97b" if pct < 60 else "#f7971e" if pct < 85 else "#e74c3c"
    rate_txt  = f"⏱️ {rpm_wait}s" if rpm_wait > 0 else "✅ ok"
    prov_icon = "🟡 Groq" if provider == "groq" else "🔵 Gemini"
    reset_hour= "09:00" if provider == "groq" else "09:00"  # entrambi mezzanotte PT

    st.sidebar.markdown(
        f"""<div style="font-size:0.71rem; padding:6px 10px; margin:4px 0;
            background:rgba(0,0,0,0.2); border-radius:8px;
            border-left:3px solid {color};">
        <b>📊 Token</b> — <span style="color:{color}"><b>{pct}%</b></span> usato<br>
        ✉️ {tot:,} usati · ~{est_rem:,} rimanenti<br>
        🤖 {prov_icon} · {model_lbl.split("-")[0] if model_lbl else "—"}<br>
        📞 {s["session_calls"]} chiamate · Rate: {rate_txt}<br>
        <span style="opacity:0.55;font-size:0.63rem;">
        Stima sessione · Reset: {reset_hour} IT · Limite: {rpm_limit} req/min
        </span></div>""",
        unsafe_allow_html=True,
    )


def render_ai_assistant(context_df: pd.DataFrame = None, context_label: str = ""):
    """AI Data Assistant: Groq (free) + voce Whisper + output TTS."""
    st.sidebar.markdown("### 💬 AI Data Assistant")

    if "ai_chat_history" not in st.session_state:
        st.session_state["ai_chat_history"] = []

    has_history = bool(st.session_state["ai_chat_history"])

    # ── Stato provider (sempre visibile) ──────────────────────────
    # Mostriamo subito quale AI è attiva prima ancora del token counter
    _client_chk, _prov_chk, _mod_chk, _err_chk, _diag_chk = _get_ai_client()
    if _client_chk is not None:
        # Dopo la prima chiamata, mostra il provider realmente usato
        actual_prov  = st.session_state.get("ai_last_provider", _prov_chk)
        actual_model = st.session_state.get("ai_last_model",    _mod_chk)
        configured_prov = _prov_chk  # quello configurato dai secrets

        if actual_prov == "gemini_fallback":
            prov_color = "#f7971e"
            prov_label = "🔵 Gemini (fallback da Groq)"
        elif actual_prov == "groq":
            prov_color = "#43e97b"
            prov_label = "🟡 Groq (free)"
        else:
            prov_color = "#f7971e"
            prov_label = "🔵 Gemini"

        # Se configurato Groq ma non ancora usato: mostra "pronto"
        status_txt = "✅ Attivo" if st.session_state.get("ai_chat_history") else "⚙️ Configurato"
        st.sidebar.markdown(
            f'''<div style="font-size:0.72rem; padding:5px 10px; margin:2px 0 6px 0;
                background:rgba(0,0,0,0.2); border-radius:7px;
                border-left:3px solid {prov_color}; color:rgba(255,255,255,0.85);">
            {status_txt}: <b>{prov_label}</b><br>
            <span style="opacity:0.7">{actual_model}</span>
            </div>''',
            unsafe_allow_html=True
        )
        # Diagnostica espandibile (default chiusa se AI funziona)
        with st.sidebar.expander("🔍 Info provider / Diagnostica", expanded=False):
            st.code(_diag_chk, language=None)
            st.caption(
                "💡 Se vedi Gemini invece di Groq: controlla che groq_api_key "
                "sia PRIMA di [google_cloud] nel file Secrets."
            )
    else:
        st.sidebar.error("⚙️ AI non configurata — leggi la diagnostica:")
        with st.sidebar.expander("🔍 Diagnostica AI", expanded=True):
            st.code(_diag_chk, language=None)

    _render_token_counter()

    # ── Storico chat ────────────────────────────────────────────────
    with st.sidebar.expander("💬 Chat", expanded=has_history):
        if has_history:
            st.markdown('<div class="ai-chat-container">', unsafe_allow_html=True)
            for msg in st.session_state["ai_chat_history"]:
                if msg["role"] == "user":
                    icon = "🎤" if msg.get("voice") else "🧑"
                    st.markdown(
                        f'<div class="ai-chat-msg-user">{icon} {msg["text"]}</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown("🤖 **Risposta:**")
                    st.markdown(msg["text"])
                    if msg.get("audio_bytes"):
                        st.audio(msg["audio_bytes"], format="audio/mp3", autoplay=False)
            st.markdown('</div>', unsafe_allow_html=True)
            # Pulsante Pulisci
            if st.button("🗑️ Pulisci chat", key="clear_ai_chat"):
                st.session_state["ai_chat_history"] = []
                st.rerun()

            # Esporta / Copia chat — sempre visibile, usa pulsante 📋 nativo di st.code()
            # NON usiamo button+rerun perché lo stato si perde nel ciclo di render.
            # st.code() mostra un'icona 📋 in alto a destra che copia direttamente.
            chat_txt_export = "\n\n".join(
                f"{'Utente' if m['role']=='user' else 'AI'}: {m['text']}"
                for m in st.session_state["ai_chat_history"]
            )
            with st.expander("📤 Esporta / Copia chat", expanded=False):
                st.caption("Clicca l'icona 📋 in alto a destra del box per copiare tutto:")
                st.code(chat_txt_export, language=None)
        else:
            st.caption("Fai una domanda sui dati della pagina corrente.")
            st.caption("💡 Es: 'Top 5 clienti per fatturato' · 'Trend mensile' · 'Riepilogo per fornitore'")

    # ── Opzioni ─────────────────────────────────────────────────────
    with st.sidebar.expander("⚙️ Opzioni risposta", expanded=False):
        speak_answer = st.checkbox("🔊 Leggi risposta ad alta voce",
                                   value=st.session_state.get("ai_speak", False),
                                   key="ai_speak_cb")
        st.session_state["ai_speak"] = speak_answer

    # ── Input testo ─────────────────────────────────────────────────
    user_text = st.sidebar.chat_input("Scrivi domanda...", key="ai_chat_input")

    # ── Input vocale ────────────────────────────────────────────────
    audio_rec = None
    with st.sidebar.expander("🎤 Domanda vocale (Whisper)", expanded=False):
        st.caption("Registra → Groq Whisper trascrive → AI risponde.")
        try:
            audio_rec = st.audio_input("🎙️ Tieni premuto per parlare", key="ai_voice_input")
        except AttributeError:
            st.caption("⚠️ Richiede Streamlit ≥ 1.36")

    # ── Processa ────────────────────────────────────────────────────
    audio_bytes = None
    voice_mode  = False
    if audio_rec is not None:
        audio_bytes = audio_rec.read()
        voice_mode  = True
        user_text   = user_text or ""

    if not (user_text or audio_bytes):
        return

    client, provider, model_name, err, diag = _get_ai_client()
    if client is None:
        st.sidebar.warning(f"⚠️ AI non configurata\n\n{err}")
        with st.sidebar.expander("🔍 Diagnostica AI", expanded=True):
            st.code(diag, language=None)
        return

    context_text = _build_compact_context(context_df, context_label)
    history = [{"role": m["role"], "text": m["text"]}
               for m in st.session_state["ai_chat_history"]]
    prompt_txt = (user_text or "") + context_text

    with st.sidebar, st.spinner("🤖 Elaborazione in corso..."):
        answer, in_tok, out_tok, err_msg, prov_used, mod_used = _call_ai(
            client, provider, model_name,
            history, prompt_txt, audio_bytes=audio_bytes
        )

    if answer:
        _update_token_stats(in_tok, out_tok, prov_used, mod_used)
        # Salva provider realmente usato (per badge)
        st.session_state["ai_last_provider"] = prov_used
        st.session_state["ai_last_model"]    = mod_used
        audio_out = _tts_audio(answer) if st.session_state.get("ai_speak") else None
        display_q = f"[🎤 Vocale] {user_text or ''}" if voice_mode else user_text
        st.session_state["ai_chat_history"].append(
            {"role": "user",  "text": display_q, "voice": voice_mode}
        )
        st.session_state["ai_chat_history"].append(
            {"role": "model", "text": answer, "audio_bytes": audio_out}
        )
        st.rerun()
    else:
        is_quota = any(x in (err_msg or "") for x in ["429", "rate_limit", "quota"])
        if is_quota:
            st.sidebar.warning(
                f"⚠️ **Quota esaurita ({prov_used}).**\n\n"
                "Reset: ore **09:00 IT** (inverno) / 10:00 IT (estate).\n\n"
                "**Ora puoi:**\n"
                "1. Attendere 1 minuto (rolling window 60s)\n"
                "2. Filtrare i dati a meno righe\n"
                "3. Monitorare: console.groq.com/usage"
            )
        else:
            # Mostra errore con provider, modello e dimensione contesto
            ctx_size = len(context_text) if 'context_text' in dir() else 0
            st.sidebar.error(
                f"❌ Errore AI [{prov_used} / {mod_used}]: {err_msg}\n\n"
                f"📐 Contesto: {ctx_size:,} chars | "
                f"Suggerimento: riduci il periodo o filtra i dati."
            )




# ==========================================================================
# 5. NAVIGAZIONE
# ==========================================================================
st.sidebar.title("🖥️ EITA Dashboard")

# Menu subito sotto il titolo
st.sidebar.markdown("**Menu:**")
page = st.sidebar.radio(
    "Navigazione",
    ["📊 Vendite & Fatturazione", "🏷️ Analisi Customer Promo", "🏭 Analisi Acquisti"],
    label_visibility="collapsed"
)
st.sidebar.markdown("---")

# ── SELETTORE DATA GLOBALE ───────────────────────────────────────────────
# Unico filtro periodo per TUTTE e 3 le pagine.
# I dati di ogni pagina vengono filtrati automaticamente su questo range.
st.sidebar.markdown("**📅 Periodo Analisi:**")
_g_prev = st.session_state.get("global_date_range", None)
_g_def_s = _g_prev[0] if _g_prev else datetime.date(2026, 1, 1)
_g_def_e = _g_prev[1] if _g_prev else datetime.date(2026, 1, 31)
_g_result = st.sidebar.date_input(
    "Periodo",
    value=[_g_def_s, _g_def_e],
    key="global_date_input",
    label_visibility="collapsed",
    format="DD/MM/YYYY",
)
if isinstance(_g_result, (list, tuple)) and len(_g_result) == 2:
    G_START, G_END = _g_result[0], _g_result[1]
elif isinstance(_g_result, datetime.date):
    G_START = G_END = _g_result
else:
    G_START, G_END = _g_def_s, _g_def_e
st.session_state["global_date_range"] = [G_START, G_END]
st.sidebar.caption(f"📆 {G_START.strftime('%d/%m/%Y')} — {G_END.strftime('%d/%m/%Y')}")
st.sidebar.markdown("---")

# Toggle zoom grafici
if "chart_zoom_enabled" not in st.session_state:
    st.session_state["chart_zoom_enabled"] = False

_zoom_val = st.sidebar.checkbox(
    "🔍 Abilita zoom grafici",
    value=st.session_state["chart_zoom_enabled"],
    key="chart_zoom_cb",
    help="📱 Mobile: OFF=scorri pagina | ON=zooma grafici  🖥️ Desktop: nessun effetto"
)
st.session_state["chart_zoom_enabled"] = _zoom_val
if _zoom_val:
    st.sidebar.caption("🔍 Zoom attivo — tocca i grafici per zoomare")
else:
    st.sidebar.caption("📜 Scroll attivo — grafici statici")
st.sidebar.markdown("---")

# ── PRE-CARICAMENTO CONTESTO AI ─────────────────────────────────────────
# CRITICO: il contesto deve essere aggiornato SUL RENDER CORRENTE,
# non sul precedente. Carichiamo il file vendite PRIMA di render_ai_assistant.
# load_dataset e smart_analyze_and_clean sono @st.cache_data → zero overhead.
files, drive_error = get_drive_files_list()
if drive_error:
    st.sidebar.error(f"Errore Drive: {drive_error}")

_df_sales_global = None   # df vendite filtrato+classificato, condiviso da AI e donut
_periodo_g = f" | Periodo: {G_START.strftime('%d/%m/%Y')} – {G_END.strftime('%d/%m/%Y')}"

# ── CARICAMENTO PRE-RENDER del file vendite (cached) ─────────────────────
# Necessario per: (a) selettore Entity globale, (b) contesto AI corretto
_df_proc_pre = None
_entity_col_pre = None
if files:
    _sales_key_pre = next(
        (f for f in files if "from_order_to_invoice" in f.get('name','').lower()), None
    )
    if _sales_key_pre:
        try:
            _df_raw_pre  = load_dataset(_sales_key_pre['id'], _sales_key_pre['modifiedTime'])
            if _df_raw_pre is not None:
                _df_proc_pre = smart_analyze_and_clean(_df_raw_pre, "Sales")
                if _df_proc_pre is not None:
                    _entity_col_pre = next(
                        (c for c in ['Entity', 'Società', 'Company', 'Division', 'Azienda']
                         if c in _df_proc_pre.columns), None
                    )
        except Exception:
            _df_proc_pre = None

# ── SELETTORE ENTITY GLOBALE ─────────────────────────────────────────────
# Posizionato qui (prima del pre-load AI) in modo che filtraggio e contesto AI
# usino SEMPRE la stessa entità che l'utente ha selezionato.
# Senza questo selettore globale, il pre-load filtrava "EITA" hardcoded
# e se il campo Entity aveva valori diversi, scattava il fallback su tutti i dati.
_g_entity = st.session_state.get("global_entity", "EITA")
if _df_proc_pre is not None and _entity_col_pre:
    _all_entities = sorted(_df_proc_pre[_entity_col_pre].dropna().astype(str).unique())
    if _all_entities:
        _def_ent_idx = _all_entities.index(_g_entity) if _g_entity in _all_entities else 0
        _g_entity = st.sidebar.selectbox(
            "🏢 Entità / Società", _all_entities, index=_def_ent_idx,
            key="global_entity_select"
        )
        st.session_state["global_entity"] = _g_entity
    else:
        st.sidebar.caption("⚠️ Nessuna entità trovata nel file vendite")
else:
    # File non ancora caricato: usa valore salvato
    st.sidebar.caption(f"🏢 Entità: {_g_entity}")

# ── FILTRO CON ENTITY SELEZIONATA (no fallback a tutti i dati) ───────────
if _df_proc_pre is not None:
    _df_sales_global = _filtra_vendite_periodo(
        _df_proc_pre, G_START, G_END, entity=_g_entity
    )
    if _df_sales_global.empty:
        # Entità non trovata — segnala ma non espande a tutti i dati
        st.sidebar.warning(f"⚠️ Nessun dato per entità '{_g_entity}' nel periodo selezionato.")
        _df_sales_global = None

# Aggiorna il contesto AI con i dati corretti DEL RENDER CORRENTE
if _df_sales_global is not None and not _df_sales_global.empty:
    # Imposta solo se non è già stato aggiornato da una pagina (es. Page 1 usa df_global)
    # Page 1 aggiornerà ai_context_df con df_global (filtrato per data corretta) → NON sovrascrivere
    # Solo il pre-load iniziale (prima che Page 1 giri) usa questo valore come default.
    if st.session_state.get("ai_context_df") is None:
        st.session_state["ai_context_df"] = _df_sales_global
    st.session_state["ai_context_label"] = f"Vendite {_g_entity}{_periodo_g}"

# AI Assistant — ora legge il contesto AGGIORNATO
_ai_ctx_df    = st.session_state.get("ai_context_df",    None)
_ai_ctx_label = st.session_state.get("ai_context_label", "Dati correnti")
render_ai_assistant(context_df=_ai_ctx_df, context_label=_ai_ctx_label)

st.sidebar.markdown("---")


# ==========================================================================
# PAGINA 1: VENDITE E FATTURAZIONE
# ==========================================================================
if page == "📊 Vendite & Fatturazione":
    df_processed = None

    if files:
        file_map      = {f['name']: f for f in files}
        file_list     = list(file_map.keys())
        default_index = next(
            (i for i, n in enumerate(file_list) if "from_order_to_invoice" in n.lower()), 0
        )
        sel_file_name     = st.sidebar.selectbox("1. Sorgente Dati", file_list, index=default_index)
        selected_file_obj = file_map[sel_file_name]

        with st.spinner('Loading Sales Data...'):
            df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'])
            if df_raw is not None:
                df_processed = smart_analyze_and_clean(df_raw, "Sales")
    else:
        st.error("Nessun file trovato su Google Drive.")

    if df_processed is not None:
        guesses  = guess_column_role(df_processed, "Sales")
        all_cols = df_processed.columns.tolist()

        with st.sidebar.expander("⚙️ Mappatura Colonne", expanded=False):
            col_entity   = st.selectbox("Entità",                all_cols, index=set_idx(guesses['entity'],   all_cols))
            col_customer = st.selectbox("Cliente (Fatturazione)",all_cols, index=set_idx(guesses['customer'], all_cols))
            col_prod     = st.selectbox("Prodotto",              all_cols, index=set_idx(guesses['product'],  all_cols))
            col_euro     = st.selectbox("Valore (€)",            all_cols, index=set_idx(guesses['euro'],     all_cols))
            col_kg       = st.selectbox("Peso (Kg)",             all_cols, index=set_idx(guesses['kg'],       all_cols))
            col_cartons  = st.selectbox("Cartoni (Qty)",         all_cols, index=set_idx(guesses['cartons'],  all_cols))
            col_data     = st.selectbox("Data Riferimento",      all_cols, index=set_idx(guesses['date'],     all_cols))

        st.sidebar.markdown("### 🔍 Filtri Rapidi")
        df_global = df_processed.copy()
        sel_ent   = None

        # Entity filtrata dal selettore globale (_g_entity), non più da widget locale
        sel_ent = _g_entity
        if col_entity and col_entity in df_global.columns:
            df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

        if col_data and pd.api.types.is_datetime64_any_dtype(df_global[col_data]):
            # Usa il selettore data GLOBALE dalla sidebar (G_START / G_END)
            d_start, d_end = G_START, G_END
            df_global = df_global[
                (df_global[col_data].dt.date >= d_start) &
                (df_global[col_data].dt.date <= d_end)
            ]

        # FIX: filtri avanzati ora EFFETTIVAMENTE gated dal pulsante Submit.
        # Problema originale: active_filters veniva popolato in ogni render
        # dai widget dentro il form (non ci vuole il Submit per applicarli)
        # → il pulsante "Applica Filtri Avanzati" era decorativo.
        # Soluzione: leggi i valori selezionati, ma applica SOLO se submit=True
        # oppure se esistono già in session_state (persistenza cross-render).
        with st.sidebar.form("advanced_filters_form"):
            possible_filters = [
                c for c in all_cols
                if c not in {col_euro, col_kg, col_cartons, col_data, col_entity}
            ]
            filters_selected = st.multiselect("Aggiungi filtri (es. Vettore, Regione):", possible_filters)
            staged_filters: dict = {}
            for f_col in filters_selected:
                unique_vals = sorted(df_processed[f_col].astype(str).unique())
                sel_vals    = st.multiselect(f"Seleziona in {f_col}", unique_vals)
                if sel_vals:
                    staged_filters[f_col] = sel_vals
            apply_adv = st.form_submit_button("✅ Applica Filtri Avanzati")

        if apply_adv:
            st.session_state['sales_adv_filters'] = staged_filters
        active_filters = st.session_state.get('sales_adv_filters', {})
        for f_col, vals in active_filters.items():
            if f_col in df_global.columns:
                df_global = df_global[df_global[f_col].astype(str).isin(vals)]

        # --- Salva / Carica Settings Vendite ---
        with st.sidebar.expander("💾 Impostazioni Sessione", expanded=False):
            if st.button("💾 Salva impostazioni correnti", key="btn_save_sales"):
                st.session_state["sales_settings"] = {
                    "col_entity":   col_entity,
                    "col_customer": col_customer,
                    "col_prod":     col_prod,
                    "col_euro":     col_euro,
                    "col_kg":       col_kg,
                    "col_cartons":  col_cartons,
                    "col_data":     col_data,
                    "sel_ent":      sel_ent,
                }
                st.success("✅ Salvato!")
            if st.button("🔄 Reset impostazioni", key="btn_reset_sales"):
                for k in ["sales_settings", "sales_adv_filters"]:
                    st.session_state.pop(k, None)
                st.rerun()
            # Esporta / Importa
            st.download_button(
                "📤 Esporta settings",
                data=json.dumps(st.session_state.get("sales_settings", {}), indent=2, default=str),
                file_name="eita_sales_settings.json", mime="application/json",
                key="btn_exp_sales"
            )
            up_sales = st.file_uploader("📥 Importa settings", type="json", key="sales_cfg_up")
            if up_sales:
                try:
                    st.session_state["sales_settings"] = json.loads(up_sales.read())
                    st.success("Importato! Ricarica la pagina.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Errore: {ex}")

        st.title(f"📊 Performance Overview: {sel_ent or 'Global'}")

        # ── AGGIORNA CONTESTO AI con df_global (filtrato per entity+data+filtri extra) ──
        # df_global ha entity=_g_entity + data col_data in [G_START,G_END] + eventuali filtri avanzati
        # → è il dato esatto che l'utente vede nei grafici = unica fonte di verità per l'AI
        try:
            _periodo_sales = f" | Periodo: {d_start.strftime('%d/%m/%Y')} – {d_end.strftime('%d/%m/%Y')}"
        except Exception:
            _periodo_sales = _periodo_g
        if not df_global.empty:
            st.session_state["ai_context_df"]    = df_global
        st.session_state["ai_context_label"] = f"Vendite {_g_entity}{_periodo_sales}"

        if not df_global.empty:
            tot_euro    = df_global[col_euro].sum()
            tot_kg      = df_global[col_kg].sum()
            ord_num_col = next((c for c in df_global.columns if "Numero_Ordine" in c), None)
            tot_orders  = df_global[ord_num_col].nunique() if ord_num_col else len(df_global)
            top_c_data  = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
            top_name    = top_c_data.index[0]  if not top_c_data.empty else "-"
            top_val     = top_c_data.values[0] if not top_c_data.empty else 0
            short_top   = (str(top_name)[:20] + "..") if len(str(top_name)) > 20 else str(top_name)

            render_kpi_cards([
                {"title": "💰 Fatturato Netto",  "value": f"€ {tot_euro:,.0f}",  "subtitle": "Totale nel periodo selezionato"},
                {"title": "⚖️ Volume Totale",    "value": f"{tot_kg:,.0f} Kg",   "subtitle": "Peso netto cumulato"},
                {"title": "📦 Ordini Elaborati", "value": f"{tot_orders:,}",      "subtitle": "Transazioni uniche / Righe"},
                {"title": "👑 Top Customer",     "value": short_top,              "subtitle": f"Valore: € {top_val:,.0f}"},
            ])

            st.markdown("### 🧭 Analisi Esplorativa (Drill-Down)")
            col_l, col_r = st.columns([1.2, 1.8], gap="large")

            cust_totals      = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False)
            total_val_period = df_global[col_euro].sum()
            options          = ["🌍 TUTTI I CLIENTI"] + cust_totals.index.tolist()

            with col_l:
                sel_target = st.selectbox(
                    "📍 Focus Analisi:", options,
                    format_func=lambda x: (
                        f"{x} (Fatturato: € {total_val_period:,.0f})" if "TUTTI" in x
                        else f"{x} (€ {cust_totals[x]:,.0f})"
                    )
                )
                df_target = (df_global if "TUTTI" in sel_target
                             else df_global[df_global[col_customer] == sel_target])

                if not df_target.empty:
                    chart_type = st.radio(
                        "Rendering Grafico:", ["📊 Barre 3D", "🥧 Torta 3D", "🍩 Donut 3D"],
                        horizontal=True
                    )
                    prod_agg = (
                        df_target.groupby(col_prod)
                                 .agg({col_euro: 'sum', col_kg: 'sum', col_cartons: 'sum'})
                                 .reset_index()
                                 .sort_values(col_euro, ascending=False)
                                 .head(10)
                    )
                    if chart_type == "📊 Barre 3D":
                        # Barre con effetto 3D: sfumatura cromatica + shadow simulata
                        n_bars   = len(prod_agg)
                        colors   = [f"rgba({20+i*18},{80+i*14},{200-i*12}, 0.85)"
                                    for i in range(n_bars)]
                        fig = go.Figure()
                        # Shadow layer (barre leggermente più scure spostate)
                        fig.add_trace(go.Bar(
                            y=prod_agg[col_prod], x=prod_agg[col_euro] * 1.005,
                            orientation='h', showlegend=False,
                            marker=dict(color="rgba(0,0,0,0.12)", line=dict(width=0)),
                            hoverinfo='skip',
                        ))
                        # Main bars
                        fig.add_trace(go.Bar(
                            y=prod_agg[col_prod], x=prod_agg[col_euro], orientation='h',
                            marker=dict(
                                color=prod_agg[col_euro],
                                colorscale=[[0,"#0050d0"],[0.5,"#4da6ff"],[1,"#00c6ff"]],
                                line=dict(color="rgba(255,255,255,0.35)", width=1.2),
                                opacity=0.92,
                            ),
                            text=prod_agg[col_euro].apply(lambda v: f"€ {v:,.0f}"),
                            textposition='inside', insidetextanchor='middle',
                            textfont=dict(size=12, color="white", family="Arial Black"),
                            hovertemplate="<b>%{y}</b><br>💰 Fatturato: € %{x:,.2f}<extra></extra>"
                        ))
                        fig.update_layout(
                            height=460, barmode='overlay',
                            yaxis=dict(autorange="reversed", showgrid=False,
                                       tickfont=dict(size=11)),
                            xaxis=dict(showgrid=True,
                                       gridcolor='rgba(128,128,128,0.15)',
                                       tickprefix="€ "),
                            margin=dict(l=0, r=10, t=10, b=10),
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            showlegend=False,
                        )
                    else:
                        hole_size  = 0.48 if "Donut" in chart_type else 0
                        # Pull progressivo: primo slice estratto, altri leggermente
                        n_slices   = len(prod_agg)
                        pull_array = [0.12] + [0.02] * (n_slices - 1)
                        palette = [
                            "#0072ff","#00c6ff","#43e97b","#ff6b9d",
                            "#f7971e","#9b59b6","#1abc9c","#e74c3c",
                            "#3498db","#f39c12"
                        ][:n_slices]

                        fig = go.Figure(go.Pie(
                            labels=prod_agg[col_prod],
                            values=prod_agg[col_euro],
                            hole=hole_size,
                            pull=pull_array,
                            marker=dict(
                                colors=palette,
                                # Bordo bianco spesso simula effetto 3D/depth
                                line=dict(color='rgba(255,255,255,0.85)', width=3),
                            ),
                            # Solo percentuale sul grafico → nessuna sovrapposizione label
                            textinfo='percent',
                            textposition='inside',
                            textfont=dict(size=12, color='white', family='Arial Black'),
                            insidetextorientation='horizontal',
                            hovertemplate=(
                                "<b>%{label}</b><br>"
                                "💰 € %{value:,.2f}<br>"
                                "📊 %{percent}<extra></extra>"
                            ),
                            rotation=25,
                            # Leggenda con valore a fianco — NON label sul grafico
                            customdata=prod_agg[col_prod],
                        ))

                        if "Donut" in chart_type:
                            total_val = prod_agg[col_euro].sum()
                            center_txt = (
                                f"€ {total_val/1e6:.1f}M" if total_val >= 1e6
                                else f"€ {total_val/1e3:.0f}K" if total_val >= 1e3
                                else f"€ {total_val:,.0f}"
                            )
                            fig.add_annotation(
                                text=f"<b>{center_txt}</b>",
                                x=0.5, y=0.5, xref="paper", yref="paper",
                                showarrow=False,
                                font=dict(size=16, color="white", family="Arial Black"),
                                bgcolor="rgba(0,0,0,0)",
                            )

                        fig.update_layout(
                            height=480,
                            # Margine sinistro ampio → spazio per legenda verticale
                            margin=dict(l=10, r=180, t=30, b=10),
                            showlegend=True,
                            legend=dict(
                                orientation="v",
                                x=1.02, y=0.5,
                                xanchor="left",
                                font=dict(size=10),
                                itemsizing="constant",
                                # Tronca label lunghe nella legenda
                                tracegroupgap=4,
                            ),
                            paper_bgcolor='rgba(0,0,0,0)',
                        )
                    _plot(fig)
                    st.caption(f"📅 Data: **{col_data}**")

            # ── COL_R: Esplosione Prodotto o Dettaglio Cliente ──────────────
            with col_r:
                submit_btn = False  # default (sovrascritta dal form se TUTTI selezionato)
                if "TUTTI" in sel_target:
                    st.markdown("#### 💥 Esplosione Prodotto (Master-Detail)")
                    st.info("💡 Applica i filtri e premi **Applica** per esplorare la gerarchia.")
                    with st.form("product_explosion_form"):
                        group_mode   = st.radio(
                            "Gerarchia:", ["Prodotto → Cliente", "Cliente → Prodotto"],
                            horizontal=True
                        )
                        all_p_sorted    = df_target.groupby(col_prod)[col_euro].sum().sort_values(ascending=False)
                        tot_euro_target = df_target[col_euro].sum()
                        prod_options    = ["TUTTI I PRODOTTI"] + all_p_sorted.index.tolist()
                        sel_p = st.multiselect(
                            "Filtra Prodotti:", prod_options, default=["TUTTI I PRODOTTI"],
                            format_func=lambda x: (
                                f"{x} (€ {tot_euro_target:,.0f})" if x == "TUTTI I PRODOTTI"
                                else f"{x} (€ {all_p_sorted[x]:,.0f})"
                            )
                        )
                        cust_available = sorted(
                            df_target[col_customer].dropna().astype(str).unique().tolist()
                        )
                        sel_c      = st.multiselect("Filtra Clienti:", cust_available,
                                                    placeholder="Tutti i clienti...")
                        submit_btn = st.form_submit_button("🔄 Applica Filtri")
                else:
                    st.markdown("#### 🧾 Dettaglio per Cliente Selezionato")
                    st.caption(f"Portafoglio ordini per: {sel_target}")
                    ps = build_agg_with_ratios(df_target, col_prod, col_cartons, col_kg, col_euro)
                    st.dataframe(
                        ps,
                        column_config={
                            col_prod:            st.column_config.TextColumn("🏷️ Articolo / Prodotto"),
                            col_cartons:         st.column_config.NumberColumn("📦 CT",    format="%d"),
                            col_kg:              st.column_config.NumberColumn("⚖️ Kg",    format="%d"),
                            col_euro:            st.column_config.NumberColumn("💰 Valore",format="€ %.2f"),
                            'Valore Medio €/Kg': st.column_config.NumberColumn("€/Kg Med",format="€ %.2f"),
                            'Valore Medio €/CT': st.column_config.NumberColumn("€/CT Med",format="€ %.2f"),
                        },
                        hide_index=True, height=500, use_container_width=True)
                    st.download_button(
                        "📥 Scarica Dettaglio Excel (.xlsx)",
                        data=convert_df_to_excel(ps),
                        file_name=f"Dettaglio_{sel_target}_{datetime.date.today()}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_download_single"
                    )

            # ── SEZIONE DETTAGLIO — full width sotto le colonne ─────────────
            if "TUTTI" in sel_target and (submit_btn or 'sales_raw_df' in st.session_state):
                if submit_btn:
                    df_ps = df_target.copy()
                    if "TUTTI I PRODOTTI" not in sel_p:
                        df_ps = df_ps[df_ps[col_prod].isin(sel_p)]
                    if sel_c:
                        df_ps = df_ps[df_ps[col_customer].astype(str).isin(sel_c)]
                    st.session_state['sales_raw_df']     = df_ps
                    st.session_state['sales_group_mode'] = group_mode
                    st.session_state.pop('drill_down_selector', None)

                df_tree_raw   = st.session_state.get('sales_raw_df',    df_target)
                mode          = st.session_state.get('sales_group_mode', "Prodotto → Cliente")
                primary_col   = col_prod     if mode == "Prodotto → Cliente" else col_customer
                secondary_col = col_customer if mode == "Prodotto → Cliente" else col_prod

                st.divider()
                master_df = build_agg_with_ratios(
                    df_tree_raw, primary_col, col_cartons, col_kg, col_euro
                )
                st.dataframe(
                    master_df,
                    column_config={
                        primary_col:         st.column_config.TextColumn("Elemento Master"),
                        col_cartons:         st.column_config.NumberColumn("CT Tot",  format="%d"),
                        col_kg:              st.column_config.NumberColumn("Kg Tot",  format="%.0f"),
                        col_euro:            st.column_config.NumberColumn("Valore",  format="€ %.2f"),
                        'Valore Medio €/Kg': st.column_config.NumberColumn("€/Kg Med", format="€ %.2f"),
                        'Valore Medio €/CT': st.column_config.NumberColumn("€/CT Med", format="€ %.2f"),
                    }, hide_index=True, use_container_width=True)

                st.markdown("⬇️ **Seleziona un elemento per vedere il dettaglio:**")
                selected_val = st.selectbox(
                    "Elemento da esplorare:", master_df[primary_col].unique(),
                    key="drill_down_selector"
                )
                if selected_val is not None:
                    detail_df  = df_tree_raw[df_tree_raw[primary_col] == selected_val]
                    detail_agg = build_agg_with_ratios(
                        detail_df, secondary_col, col_cartons, col_kg, col_euro
                    )
                    st.markdown(
                        f'<div class="detail-section">Dettaglio per: <b>{selected_val}</b></div>',
                        unsafe_allow_html=True
                    )
                    st.dataframe(
                        detail_agg,
                        column_config={
                            secondary_col:       st.column_config.TextColumn("Dettaglio (Child)"),
                            col_cartons:         st.column_config.NumberColumn("CT",     format="%d"),
                            col_kg:              st.column_config.NumberColumn("Kg",     format="%.0f"),
                            col_euro:            st.column_config.NumberColumn("Valore", format="€ %.2f"),
                            'Valore Medio €/Kg': st.column_config.NumberColumn("€/Kg",  format="€ %.2f"),
                            'Valore Medio €/CT': st.column_config.NumberColumn("€/CT",  format="€ %.2f"),
                        }, hide_index=True, use_container_width=True)

                full_flat = (
                    df_tree_raw
                    .groupby([primary_col, secondary_col])
                    .agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'})
                    .reset_index()
                    .sort_values(col_euro, ascending=False)
                    .assign(**{
                        'Valore Medio €/Kg': lambda d: np.where(d[col_kg] > 0, d[col_euro] / d[col_kg], 0),
                        'Valore Medio €/CT': lambda d: np.where(d[col_cartons] > 0, d[col_euro] / d[col_cartons], 0),
                    })
                )
                st.download_button(
                    "📥 Scarica Report Excel Completo",
                    data=convert_df_to_excel(full_flat),
                    file_name=f"Explosion_Full_Report_{datetime.date.today()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )


# PAGINA 2: CUSTOMER PROMO
# ==========================================================================
elif page == "🏷️ Analisi Customer Promo":
    st.title("🏷️ Analisi Customer Promo")

    df_promo_processed = None

    if files:
        file_map = {f['name']: f for f in files}
        file_list = list(file_map.keys())

        # --- Carica Promo ---
        default_idx_p  = next(
            (i for i, n in enumerate(file_list) if "customer_promo" in n.lower()), 0
        )
        sel_promo_file = st.sidebar.selectbox("1. File Sorgente Promo", file_list, index=default_idx_p)
        with st.spinner('Elaborazione dati promozionali...'):
            df_promo_raw = load_dataset(
                file_map[sel_promo_file]['id'], file_map[sel_promo_file]['modifiedTime']
            )
            if df_promo_raw is not None:
                df_promo_processed = smart_analyze_and_clean(df_promo_raw, "Promo")

    if df_promo_processed is not None:
        guesses_p  = guess_column_role(df_promo_processed, "Promo")
        all_cols_p = df_promo_processed.columns.tolist()

        with st.sidebar.expander("⚙️ Verifica Colonne Promo", expanded=False):
            p_div    = st.selectbox("Division",           all_cols_p, index=set_idx(guesses_p['division'],     all_cols_p))
            p_status = st.selectbox("Stato",              all_cols_p, index=set_idx(guesses_p['status'],       all_cols_p))
            p_cust   = st.selectbox("Cliente",            all_cols_p, index=set_idx(guesses_p['customer'],     all_cols_p))
            p_prod   = st.selectbox("Prodotto",           all_cols_p, index=set_idx(guesses_p['product'],      all_cols_p))
            p_qty_f  = st.selectbox("Q.tà Prevista",      all_cols_p, index=set_idx(guesses_p['qty_forecast'], all_cols_p))
            p_qty_a  = st.selectbox("Q.tà Ordinata",      all_cols_p, index=set_idx(guesses_p['qty_actual'],   all_cols_p))
            p_start  = st.selectbox("Data Inizio Sell-In",all_cols_p, index=set_idx(guesses_p['start_date'],   all_cols_p))
            p_type   = st.selectbox("Tipo Promo",         all_cols_p, index=set_idx(guesses_p['type'],         all_cols_p))
            p_week   = st.selectbox("Week start",         all_cols_p, index=set_idx(guesses_p['week_start'],   all_cols_p))

        st.sidebar.markdown("### 🔍 Filtri Promo Rapidi")
        df_pglobal = df_promo_processed.copy()

        # Filtro Division
        if p_div in df_pglobal.columns:
            divs    = sorted(df_pglobal[p_div].dropna().unique().tolist())
            idx_div = divs.index(21) if 21 in divs else (divs.index('21') if '21' in divs else 0)
            sel_div = st.sidebar.selectbox("Division", divs, index=idx_div)
            df_pglobal = df_pglobal[df_pglobal[p_div] == sel_div]

        # Filtro data Sell-In — usa il selettore data GLOBALE (G_START / G_END)
        if p_start in df_pglobal.columns and pd.api.types.is_datetime64_any_dtype(df_pglobal[p_start]):
            d_start, d_end = G_START, G_END
            df_pglobal = df_pglobal[
                (df_pglobal[p_start].dt.date >= d_start) &
                (df_pglobal[p_start].dt.date <= d_end)
            ]

        # FIX: filtri avanzati gated da Submit (stessa logica di Sales page).
        # Problema originale: active_filters_p e sel_stati venivano applicati
        # ad ogni render senza richiedere il Submit → pulsante decorativo.
        with st.sidebar.form("promo_advanced_filters"):
            if p_status in df_pglobal.columns:
                stati         = sorted(df_pglobal[p_status].dropna().unique().tolist())
                default_stati = [20] if 20 in stati else ([str(20)] if str(20) in stati else stati)
                staged_stati  = st.multiselect("Stato Promozione", stati, default=default_stati)
            else:
                staged_stati = []

            possible_filters_p = [c for c in all_cols_p
                                   if c not in {p_qty_f, p_qty_a, p_start, p_div, p_status}]
            filters_selected_p = st.multiselect("Aggiungi altri filtri:", possible_filters_p)
            staged_adv_p: dict = {}
            for f_col in filters_selected_p:
                unique_vals = sorted(df_promo_processed[f_col].dropna().astype(str).unique())
                sel_vals    = st.multiselect(f"Seleziona {f_col}", unique_vals)
                if sel_vals:
                    staged_adv_p[f_col] = sel_vals
            apply_promo_filters = st.form_submit_button("✅ Applica Filtri Promo")

        if apply_promo_filters:
            st.session_state['promo_adv_stati']   = staged_stati
            st.session_state['promo_adv_filters'] = staged_adv_p
        elif 'promo_adv_stati' not in st.session_state:
            st.session_state['promo_adv_stati']   = staged_stati
            st.session_state['promo_adv_filters'] = {}

        # --- Salva / Carica Settings Promo ---
        with st.sidebar.expander("💾 Impostazioni Sessione", expanded=False):
            if st.button("💾 Salva impostazioni correnti", key="btn_save_promo"):
                st.session_state["promo_settings"] = {
                    "p_div":    p_div,    "p_status": p_status,
                    "p_cust":   p_cust,   "p_prod":   p_prod,
                    "p_qty_f":  p_qty_f,  "p_qty_a":  p_qty_a,
                    "p_start":  p_start,  "p_type":   p_type,
                    "p_week":   p_week,
                }
                st.success("✅ Salvato!")
            if st.button("🔄 Reset impostazioni", key="btn_reset_promo"):
                for k in ["promo_settings", "promo_adv_stati", "promo_adv_filters"]:
                    st.session_state.pop(k, None)
                st.rerun()
            st.download_button(
                "📤 Esporta settings",
                data=json.dumps(st.session_state.get("promo_settings", {}), indent=2, default=str),
                file_name="eita_promo_settings.json", mime="application/json",
                key="btn_exp_promo"
            )
            up_promo = st.file_uploader("📥 Importa settings", type="json", key="promo_cfg_up")
            if up_promo:
                try:
                    st.session_state["promo_settings"] = json.loads(up_promo.read())
                    st.success("Importato! Ricarica la pagina.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Errore: {ex}")

        active_stati   = st.session_state['promo_adv_stati']
        active_adv_p   = st.session_state['promo_adv_filters']

        if p_status in df_pglobal.columns and active_stati:
            df_pglobal = df_pglobal[df_pglobal[p_status].isin(active_stati)]
        for f_col, vals in active_adv_p.items():
            if f_col in df_pglobal.columns:
                df_pglobal = df_pglobal[df_pglobal[f_col].astype(str).isin(vals)]

        # ── _df_vendite = _df_sales_global (calcolato globalmente prima dell'AI) ──
        # Stesso df usato dal contesto AI → zero divergenze possibili.
        # Non serve ricalcolare: G_START/G_END e entity="EITA" sono già applicati.
        _df_vendite  = _df_sales_global  # alias esplicito per chiarezza nel codice sotto
        _periodo_promo = _periodo_g
        # Nota: ai_context_df è già stato impostato nel blocco globale con _df_sales_global.
        # Non serve aggiornarlo qui (sarebbe già il valore corretto).

        if not df_pglobal.empty:
            tot_promo_uniche = (
                int(df_pglobal[guesses_p['promo_id']].nunique())
                if guesses_p.get('promo_id') and guesses_p['promo_id'] in df_pglobal.columns
                else len(df_pglobal)
            )
            tot_prevista = float(df_pglobal[p_qty_f].sum()) if p_qty_f in df_pglobal.columns else 0.0
            tot_ordinata = float(df_pglobal[p_qty_a].sum()) if p_qty_a in df_pglobal.columns else 0.0
            hit_rate     = (tot_ordinata / tot_prevista * 100) if tot_prevista > 0 else 0.0

            render_kpi_cards([
                {"title": "🎯 Promozioni Attive", "value": str(tot_promo_uniche), "subtitle": "N° iniziative nel periodo"},
                {"title": "📈 Forecast (Previsto)", "value": f"{tot_prevista:,.0f}", "subtitle": "Quantità totale stimata"},
                {"title": "🛒 Actual (Ordinato)",   "value": f"{tot_ordinata:,.0f}", "subtitle": "Quantità effettiva ordinata"},
                {"title": "⚡ Hit Rate (Successo)",  "value": f"{hit_rate:.1f}%",   "subtitle": "Ordinato / Previsto"},
            ], card_class="promo-card")

            st.divider()
            col_pl, col_pr = st.columns([1, 1], gap="large")

            with col_pl:
                st.subheader("📊 Vendite: Promo vs Normale")
                # _df_vendite è già filtrato (G_START/G_END, entity EITA) e classificato
                # con _classifica_vendita() — IDENTICO a quello usato dal contesto AI.
                if _df_vendite is not None and not _df_vendite.empty:
                    st.caption(
                        f"📅 {G_START.strftime('%d/%m/%Y')} – {G_END.strftime('%d/%m/%Y')} "
                        f"— {len(_df_vendite):,} righe"
                    )
                    # ── Filtri opzionali per visualizzazione (non cambiano la fonte dati) ──
                    with st.form("promo_sales_chart_filter"):
                        _all_arts  = sorted(_df_vendite[_COL_AT].dropna().astype(str).unique()) if _COL_AT in _df_vendite.columns else []
                        _all_clis  = sorted(_df_vendite[_COL_CL].dropna().astype(str).unique()) if _COL_CL in _df_vendite.columns else []
                        _sel_art   = st.multiselect("Filtra Articolo", _all_arts, placeholder="Tutti...")
                        _sel_cli   = st.multiselect("Filtra Cliente",  _all_clis, placeholder="Tutti...")
                        _apply_ch  = st.form_submit_button("Aggiorna Grafico")
                    if _apply_ch:
                        st.session_state['pchart_art'] = _sel_art
                        st.session_state['pchart_cli'] = _sel_cli

                    df_s = _df_vendite.copy()
                    _f_art = st.session_state.get('pchart_art', [])
                    _f_cli = st.session_state.get('pchart_cli', [])
                    if _f_art and _COL_AT in df_s.columns:
                        df_s = df_s[df_s[_COL_AT].astype(str).isin(_f_art)]
                    if _f_cli and _COL_CL in df_s.columns:
                        df_s = df_s[df_s[_COL_CL].astype(str).isin(_f_cli)]

                    # ── Aggregazione Kg per tipo (__tipo__ già calcolato con regole ufficiali) ──
                    if _COL_KG not in df_s.columns:
                        st.warning(f"Colonna {_COL_KG} non trovata.")
                    else:
                        promo_stats = df_s.groupby('__tipo__')[_COL_KG].sum().reset_index()
                        promo_stats.columns = ['Tipo', 'Kg']
                        total_kg = promo_stats['Kg'].sum()

                        # Colori per categoria
                        _pcolors = {
                            'In Promozione':  '#ff6b9d',
                            'Vendita Normale':'#43e97b',
                            'Omaggio':        '#f5a623',
                        }
                        _pcolors_dark = {
                            'In Promozione':  '#c2185b',
                            'Vendita Normale':'#1b5e20',
                            'Omaggio':        '#b8741a',
                        }
                        labels = promo_stats['Tipo'].tolist()
                        values = promo_stats['Kg'].tolist()
                        colors      = [_pcolors.get(l, '#888')      for l in labels]
                        colors_dark = [_pcolors_dark.get(l, '#444') for l in labels]
                        pull = [0.08 if l == 'In Promozione' else 0 for l in labels]

                        fig_p = go.Figure()
                        fig_p.add_trace(go.Pie(
                            labels=labels, values=values, hole=0.41, pull=pull,
                            marker=dict(colors=colors_dark, line=dict(color='rgba(0,0,0,0)', width=0)),
                            textinfo='none', showlegend=False, hoverinfo='skip',
                            direction='clockwise', sort=False,
                        ))
                        fig_p.add_trace(go.Pie(
                            labels=labels, values=values, hole=0.38, pull=pull,
                            marker=dict(colors=colors, line=dict(color='rgba(255,255,255,0.8)', width=3)),
                            textinfo='percent', textposition='inside',
                            textfont=dict(size=15, color='white', family='Arial Black'),
                            insidetextorientation='horizontal',
                            direction='clockwise', sort=False,
                            hovertemplate="<b>%{label}</b><br>📦 %{value:,.0f} Kg<br>%{percent}<extra></extra>",
                            showlegend=True,
                        ))
                        fig_p.add_annotation(
                            text=f"<b>{total_kg/1e3:.0f}K Kg</b>",
                            x=0.5, y=0.5, xref='paper', yref='paper', showarrow=False,
                            font=dict(size=14, color='white', family='Arial Black'),
                        )
                        fig_p.update_layout(
                            height=340, margin=dict(l=10, r=140, t=10, b=10),
                            showlegend=True,
                            legend=dict(orientation='v', x=1.02, y=0.5, xanchor='left', font=dict(size=11)),
                            paper_bgcolor='rgba(0,0,0,0)',
                        )
                        _plot(fig_p)
                        st.caption(f"📅 Data: **{p_start}** (Data Inizio Sell-In)")

                        # ── Dettaglio Metriche ───────────────────────────────────
                        st.markdown("#### 📉 Dettaglio Metriche")
                        st.caption("ℹ️ % su Kg — stessa logica del contesto AI | Regola: Normale=s7=0 e s4=0, Promo=qualsiasi>0, Omaggio=99/100")
                        for tipo in ['In Promozione', 'Vendita Normale', 'Omaggio']:
                            row = promo_stats[promo_stats['Tipo'] == tipo]
                            if row.empty:
                                continue
                            kg_val   = row['Kg'].values[0]
                            pct      = (kg_val / total_kg * 100) if total_kg > 0 else 0
                            eur_val  = df_s[df_s['__tipo__'] == tipo][_COL_EU].sum() if _COL_EU in df_s.columns else 0
                            c1, c2, c3 = st.columns(3)
                            c1.metric(f"{tipo} %",   f"{pct:.1f}%")
                            c2.metric(f"Kg",          f"{kg_val:,.0f}")
                            c3.metric(f"€",           f"{eur_val:,.0f}")
                else:
                    st.info("File Vendite non trovato o nessun dato nel periodo selezionato.")

                # ── TABELLA DETTAGLIO sotto il grafico ───────────────────────────
                if _df_vendite is not None and not _df_vendite.empty:
                    st.markdown("---")
                    st.markdown("#### 📋 Dettaglio Vendite Promo / Normale")
                    st.caption(
                        "Tabella aggregata per Articolo × Cliente con % promo e % normale su Kg. "
                        "Filtri applicati: stessi del grafico sopra."
                    )

                    # Usa df_s (già filtrato per art/cli dal form sopra)
                    _df_tbl = df_s.copy() if '_f_art' in dir() or '_f_cli' in dir() else _df_vendite.copy()
                    if _f_art and _COL_AT in _df_tbl.columns:
                        _df_tbl = _df_tbl[_df_tbl[_COL_AT].astype(str).isin(_f_art)]
                    if _f_cli and _COL_CL in _df_tbl.columns:
                        _df_tbl = _df_tbl[_df_tbl[_COL_CL].astype(str).isin(_f_cli)]

                    _has_tbl_cols = all(c in _df_tbl.columns for c in [_COL_AT, _COL_CL, _COL_KG])
                    if _has_tbl_cols:
                        # Aggregazione per Articolo × Cliente con breakdown per tipo
                        _grp_cols = [_COL_AT, _COL_CL]
                        _agg_base = (
                            _df_tbl.groupby(_grp_cols + ['__tipo__'], observed=True)[[_COL_KG, _COL_EU, _COL_CT]]
                            .sum(numeric_only=True)
                            .reset_index()
                        )
                        # Pivot: una riga per Articolo×Cliente con colonne per tipo
                        _pivot_kg = _agg_base.pivot_table(
                            index=_grp_cols, columns='__tipo__', values=_COL_KG, aggfunc='sum', fill_value=0
                        ).reset_index()
                        _pivot_kg.columns = [c if isinstance(c, str) else f"Kg_{c}" for c in _pivot_kg.columns]

                        # Totali per riga
                        _tipo_cols_kg = [c for c in _pivot_kg.columns if c.startswith('Kg_') or c in ['In Promozione', 'Vendita Normale', 'Omaggio']]
                        # Rinomina colonne pivot se non hanno già il prefisso
                        _rename_map = {}
                        for c in _pivot_kg.columns:
                            if c in ('In Promozione', 'Vendita Normale', 'Omaggio'):
                                _rename_map[c] = f'Kg_{c}'
                        if _rename_map:
                            _pivot_kg = _pivot_kg.rename(columns=_rename_map)

                        _kg_promo   = _pivot_kg.get('Kg_In Promozione',   pd.Series(0, index=_pivot_kg.index))
                        _kg_normale = _pivot_kg.get('Kg_Vendita Normale',  pd.Series(0, index=_pivot_kg.index))
                        _kg_omaggio = _pivot_kg.get('Kg_Omaggio',          pd.Series(0, index=_pivot_kg.index))
                        _kg_tot     = _kg_promo + _kg_normale + _kg_omaggio

                        _pivot_kg['Kg Totali']   = _kg_tot
                        _pivot_kg['Kg Promo']    = _kg_promo
                        _pivot_kg['Kg Normale']  = _kg_normale
                        _pivot_kg['Kg Omaggio']  = _kg_omaggio
                        _pivot_kg['% Promo']     = (_kg_promo   / _kg_tot.replace(0,1) * 100).round(1)
                        _pivot_kg['% Normale']   = (_kg_normale / _kg_tot.replace(0,1) * 100).round(1)
                        _pivot_kg['% Omaggio']   = (_kg_omaggio / _kg_tot.replace(0,1) * 100).round(1)

                        # Aggiungi € e CT totali
                        _eur_ct = (
                            _df_tbl.groupby(_grp_cols, observed=True)[[_COL_EU, _COL_CT]]
                            .sum(numeric_only=True)
                            .reset_index()
                        )
                        _pivot_kg = _pivot_kg.merge(_eur_ct, on=_grp_cols, how='left')

                        # Selezione e ordinamento colonne finali
                        _tbl_cols = [_COL_AT, _COL_CL, _COL_CT, 'Kg Totali', 'Kg Promo', 'Kg Normale',
                                     'Kg Omaggio', '% Promo', '% Normale', '% Omaggio', _COL_EU]
                        _tbl_cols = [c for c in _tbl_cols if c in _pivot_kg.columns]
                        _tbl_final = (
                            _pivot_kg[_tbl_cols]
                            .sort_values('Kg Totali', ascending=False)
                            .reset_index(drop=True)
                        )

                        st.dataframe(
                            _tbl_final,
                            column_config={
                                _COL_AT:    st.column_config.TextColumn("🏷️ Articolo"),
                                _COL_CL:    st.column_config.TextColumn("👤 Cliente"),
                                _COL_CT:    st.column_config.NumberColumn("CT",         format="%d"),
                                'Kg Totali':  st.column_config.NumberColumn("Kg Tot",   format="%.0f"),
                                'Kg Promo':   st.column_config.NumberColumn("Kg Promo", format="%.0f"),
                                'Kg Normale': st.column_config.NumberColumn("Kg Norm",  format="%.0f"),
                                'Kg Omaggio': st.column_config.NumberColumn("Kg Omag",  format="%.0f"),
                                '% Promo':    st.column_config.ProgressColumn("% Promo", min_value=0, max_value=100, format="%.1f%%"),
                                '% Normale':  st.column_config.ProgressColumn("% Normale", min_value=0, max_value=100, format="%.1f%%"),
                                '% Omaggio':  st.column_config.NumberColumn("% Omag",   format="%.1f%%"),
                                _COL_EU:    st.column_config.NumberColumn("Fatturato €", format="€ %.2f"),
                            }, hide_index=True, use_container_width=True)
                        # Download Excel
                        if not _tbl_final.empty:
                            st.download_button(
                                "📥 Scarica tabella Excel",
                                data=convert_df_to_excel(_tbl_final),
                                file_name=f"Promo_Detail_{G_START}_{G_END}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key="promo_detail_download"
                            )
                    else:
                        st.caption("⚠️ Colonne insufficienti per la tabella dettaglio.")

            with col_pr:
                st.subheader("Top Promozioni (Forecast vs Actual)")
                promo_desc_col = guesses_p.get('promo_desc') or 'Descrizione Promozione'
                if promo_desc_col in df_pglobal.columns:
                    top_promos = (
                        df_pglobal.groupby(promo_desc_col)
                                  .agg({p_qty_a: 'sum'})
                                  .reset_index()
                                  .sort_values(p_qty_a, ascending=False)
                                  .head(8)
                    )
                    n_bars_pr = len(top_promos)
                    # Barre con effetto 3D (shadow + main)
                    fig = go.Figure()
                    # Shadow trace
                    fig.add_trace(go.Bar(
                        y=top_promos[promo_desc_col],
                        x=top_promos[p_qty_a] * 1.006,
                        orientation='h', showlegend=False,
                        marker=dict(color='rgba(0,0,0,0.15)', line=dict(width=0)),
                        hoverinfo='skip',
                    ))
                    # Main bars con gradiente rosa-viola premium
                    norm_vals = top_promos[p_qty_a] / (top_promos[p_qty_a].max() + 1e-9)
                    bar_colors = [
                        f"rgba({int(168+87*v)},{int(107-60*v)},{int(157+98*v)},0.92)"
                        for v in norm_vals
                    ]
                    fig.add_trace(go.Bar(
                        y=top_promos[promo_desc_col],
                        x=top_promos[p_qty_a],
                        orientation='h',
                        marker=dict(
                            color=bar_colors,
                            line=dict(color='rgba(255,255,255,0.4)', width=1.5),
                        ),
                        text=top_promos[p_qty_a].apply(lambda v: f"{v:,.0f}"),
                        textposition='inside', insidetextanchor='middle',
                        textfont=dict(size=12, color='white', family='Arial Black'),
                        hovertemplate=(
                            "<b>%{y}</b><br>"
                            "📦 Qty Actual: %{x:,.0f}<extra></extra>"
                        ),
                    ))
                    fig.update_layout(
                        height=460, barmode='overlay',
                        yaxis=dict(
                            autorange="reversed", showgrid=False,
                            tickfont=dict(size=10),
                            tickmode='array',
                            tickvals=list(range(n_bars_pr)),
                        ),
                        xaxis=dict(
                            showgrid=True, gridcolor='rgba(200,150,255,0.15)',
                            zeroline=False,
                        ),
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        margin=dict(l=10, r=10, t=15, b=10),
                        showlegend=False,
                        title=dict(
                            text="Top Promozioni per Volume",
                            font=dict(size=13, color='rgba(255,255,255,0.7)'),
                            x=0.5,
                        ),
                    )
                    _plot(fig)
                    st.caption(f"📅 Data: **{p_start}** (Data Inizio Sell-In)")

            st.subheader("📋 Dettaglio Iniziative Promozionali")

            with st.form("promo_detail_form"):
                st.caption("Seleziona i filtri e premi 'Aggiorna Tabella'.")
                f1, f2, f3, f4 = st.columns(4)
                with f1:
                    c_list = sorted(df_pglobal[p_cust].dropna().astype(str).unique()) if p_cust in df_pglobal.columns else []
                    sel_tc = st.multiselect("👤 Cliente",     c_list, placeholder="Tutti...")
                with f2:
                    p_list = sorted(df_pglobal[p_prod].dropna().astype(str).unique()) if p_prod in df_pglobal.columns else []
                    sel_tp = st.multiselect("🏷️ Prodotto",   p_list, placeholder="Tutti...")
                with f3:
                    s_list = (sorted(df_pglobal['Sconto promo'].dropna().astype(str).unique())
                              if 'Sconto promo' in df_pglobal.columns else [])
                    sel_ts = st.multiselect("📉 Sconto promo", s_list, placeholder="Tutti...")
                with f4:
                    w_list = sorted(df_pglobal[p_week].dropna().astype(str).unique()) if p_week in df_pglobal.columns else []
                    sel_tw = st.multiselect("📅 Week start",  w_list, placeholder="Tutte...")
                submit_promo = st.form_submit_button("🔄 Aggiorna Tabella")

            if submit_promo:
                df_display = df_pglobal.copy()
                if sel_tc: df_display = df_display[df_display[p_cust].astype(str).isin(sel_tc)]
                if sel_tp: df_display = df_display[df_display[p_prod].astype(str).isin(sel_tp)]
                if sel_ts and 'Sconto promo' in df_display.columns:
                    df_display = df_display[df_display['Sconto promo'].astype(str).isin(sel_ts)]
                if sel_tw and p_week in df_display.columns:
                    df_display = df_display[df_display[p_week].astype(str).isin(sel_tw)]

                promo_id_col   = guesses_p.get('promo_id')
                promo_desc_col = guesses_p.get('promo_desc') or 'Descrizione Promozione'
                cols_to_show   = [c for c in [promo_id_col, promo_desc_col, p_cust, p_prod,
                                               p_start, p_week, p_qty_f, p_qty_a, 'Sconto promo']
                                   if c and c in df_display.columns]
                df_display_sorted = (
                    df_display[cols_to_show].sort_values(by=p_qty_a, ascending=False)
                    if p_qty_a in df_display.columns else df_display[cols_to_show]
                )
                st.session_state['promo_detail_df'] = df_display_sorted

            if 'promo_detail_df' in st.session_state:
                df_p_show = st.session_state['promo_detail_df']
                st.dataframe(
                    df_p_show,
                    column_config={
                        p_qty_f: st.column_config.NumberColumn("Forecast Qty", format="%.0f"),
                        p_qty_a: st.column_config.NumberColumn("Actual Qty",   format="%.0f"),
                        p_start: st.column_config.DateColumn("Inizio Sell-In", format="DD/MM/YYYY"),
                    },
                    hide_index=True, height=500
                , use_container_width=True)
                st.download_button(
                    "📥 Scarica Report Promo Excel (.xlsx)",
                    data=convert_df_to_excel(df_p_show),
                    file_name=f"Promo_Report_{datetime.date.today()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_download_promo"
                )
        else:
            st.warning("Nessuna promozione trovata per i filtri selezionati.")


# ==========================================================================
# PAGINA 3: ANALISI ACQUISTI
# ==========================================================================
elif page == "🏭 Analisi Acquisti":
    st.title("🏭 Analisi Acquisti (Purchase History)")

    df_purch_processed = None

    if files:
        file_map       = {f['name']: f for f in files}
        file_list      = list(file_map.keys())
        default_idx_pu = next(
            (i for i, n in enumerate(file_list) if "purchase_orders_history" in n.lower()), 0
        )
        sel_purch_file = st.sidebar.selectbox("1. File Sorgente Acquisti", file_list, index=default_idx_pu)

        with st.spinner('Lettura file acquisti...'):
            df_purch_raw = load_dataset(
                file_map[sel_purch_file]['id'], file_map[sel_purch_file]['modifiedTime']
            )
            if df_purch_raw is not None:
                df_purch_processed = smart_analyze_and_clean(df_purch_raw, "Purchase")

                # LEGENDA: "Kg acquistati = costo della linea / prezzo €/kg"
                # = Line amount / Purchase price
                # FIX: SEMPRE ricalcola — la colonna esiste già nel file
                # Excel ma può avere valori zero o sbagliati.
                # Non usare il guard "if not in columns".
                if all(c in df_purch_processed.columns for c in ['Line amount', 'Purchase price']):
                    df_purch_processed['Kg acquistati'] = np.where(
                        df_purch_processed['Purchase price'] > 0,
                        df_purch_processed['Line amount'] / df_purch_processed['Purchase price'],
                        0
                    )
                elif all(c in df_purch_processed.columns for c in ['Row amount', 'Purchase price']):
                    df_purch_processed['Kg acquistati'] = np.where(
                        df_purch_processed['Purchase price'] > 0,
                        df_purch_processed['Row amount'] / df_purch_processed['Purchase price'],
                        0
                    )
                else:
                    df_purch_processed['Kg acquistati'] = 0
    else:
        st.error("Nessun file trovato.")

    if df_purch_processed is None:
        if files:
            st.warning(
                "⚠️ Impossibile caricare il file acquisti. "
                "Verifica che il file Purchase History sia accessibile su Google Drive "
                "e che il servizio Google sia connesso."
            )
        # else: il messaggio "Nessun file trovato" è già sopra
    
    if df_purch_processed is not None:
        guesses_pu  = guess_column_role(df_purch_processed, "Purchase")
        # Colonne da nascondere (dalla legenda: Part number old = vecchi codici, non mostrare nei filtri)
        HIDDEN_COLS_PU = {'Part number old'}
        all_cols_pu    = [c for c in df_purch_processed.columns if c not in HIDDEN_COLS_PU]

        # --- SETTINGS: carica impostazioni salvate ---
        pu_saved = st.session_state.get("pu_settings", {})

        with st.sidebar.expander("⚙️ Configurazione Colonne Acquisti", expanded=False):
            pu_div    = st.selectbox("Division",         all_cols_pu,
                         index=set_idx(pu_saved.get("pu_div",    guesses_pu.get('division')),   all_cols_pu))
            pu_supp   = st.selectbox("Supplier Name",    all_cols_pu,
                         index=set_idx(pu_saved.get("pu_supp",   guesses_pu.get('supplier')),   all_cols_pu))
            pu_date   = st.selectbox("Data riferimento",  all_cols_pu,
                         index=set_idx(pu_saved.get("pu_date",   guesses_pu.get('order_date')), all_cols_pu))
            pu_amount = st.selectbox("Invoice Amount",   all_cols_pu,
                         index=set_idx(pu_saved.get("pu_amount", guesses_pu.get('amount')),     all_cols_pu))
            pu_kg     = st.selectbox("Kg Acquistati",    all_cols_pu,
                         index=set_idx(pu_saved.get("pu_kg",     guesses_pu.get('kg')),         all_cols_pu))
            pu_prod   = st.selectbox("Part Description", all_cols_pu,
                         index=set_idx(pu_saved.get("pu_prod",   guesses_pu.get('product')),    all_cols_pu))
            pu_cat    = st.selectbox("Part Group",       all_cols_pu,
                         index=set_idx(pu_saved.get("pu_cat",    guesses_pu.get('category')),   all_cols_pu))

        df_pu_global = df_purch_processed  # NO .copy() — i filtri successivi creano nuovi oggetti
        st.sidebar.markdown("### 🔍 Filtri Acquisti")

        # --- Filtro Division (considera _g_entity globale come default) ---
        sel_div_pu = None
        if pu_div in df_pu_global.columns:
            divs = sorted(df_pu_global[pu_div].astype(str).unique())
            saved_div = pu_saved.get("sel_div_pu")
            if saved_div and saved_div in divs:
                default_div_idx = divs.index(saved_div)
            elif _g_entity in divs:
                default_div_idx = divs.index(_g_entity)
            elif "021" in divs:
                default_div_idx = divs.index("021")
            elif "21" in divs:
                default_div_idx = divs.index("21")
            else:
                default_div_idx = 0
            sel_div_pu   = st.sidebar.selectbox("Divisione", divs, index=default_div_idx)
            df_pu_global = df_pu_global[df_pu_global[pu_div].astype(str) == sel_div_pu]

        # --- Periodo di Analisi ---
        # Filtra per G_START/G_END esattamente come Page 1 e Page 2.
        # Se il risultato è vuoto → KPI=0 + warning con range disponibile nel file.
        d_start_pu = d_end_pu = None
        if pu_date in df_pu_global.columns:
            if not pd.api.types.is_datetime64_any_dtype(df_pu_global[pu_date]):
                df_pu_global[pu_date] = pd.to_datetime(
                    df_pu_global[pu_date], dayfirst=True, errors='coerce'
                )
            df_pu_global = df_pu_global.dropna(subset=[pu_date])

            if pd.api.types.is_datetime64_any_dtype(df_pu_global[pu_date]) and not df_pu_global.empty:
                _min_d = df_pu_global[pu_date].min()
                _max_d = df_pu_global[pu_date].max()

                # Applica direttamente il filtro globale (stesso pattern Page 1/2)
                d_start_pu, d_end_pu = G_START, G_END
                df_pu_global = df_pu_global[
                    (df_pu_global[pu_date].dt.date >= d_start_pu) &
                    (df_pu_global[pu_date].dt.date <= d_end_pu)
                ]

                # Se vuoto: avvisa con range disponibile (non sovrascrive la selezione)
                if df_pu_global.empty and pd.notnull(_min_d) and pd.notnull(_max_d):
                    st.warning(
                        f"⚠️ Nessun dato acquisti nel periodo selezionato "
                        f"(**{G_START.strftime('%d/%m/%Y')} – {G_END.strftime('%d/%m/%Y')}**). "
                        f"Dati disponibili dal **{_min_d.strftime('%d/%m/%Y')}** "
                        f"al **{_max_d.strftime('%d/%m/%Y')}** — "
                        f"modifica il **Periodo Analisi** in sidebar."
                    )

        # --- Filtro Fornitore ---
        if pu_supp in df_pu_global.columns:
            all_suppliers = ["Tutti"] + sorted(df_pu_global[pu_supp].dropna().astype(str).unique())
            saved_supps   = pu_saved.get("sel_suppliers", ["Tutti"])
            # Ripristina solo i fornitori ancora presenti nel dataset corrente
            valid_saved = [s for s in saved_supps if s in all_suppliers]
            if not valid_saved:
                valid_saved = ["Tutti"]
            sel_suppliers = st.sidebar.multiselect("Fornitori", all_suppliers, default=valid_saved)
            if sel_suppliers and "Tutti" not in sel_suppliers:
                df_pu_global = df_pu_global[df_pu_global[pu_supp].astype(str).isin(sel_suppliers)]
        else:
            sel_suppliers = ["Tutti"]

        # --- Salva / Carica Settings ---
        st.sidebar.markdown("---")
        st.sidebar.markdown("#### 💾 Salva Impostazioni")
        c_save, c_reset = st.sidebar.columns(2)
        with c_save:
            if st.button("💾 Salva", key="btn_save_pu",
                         help="Salva filtri e mappatura colonne per questa sessione"):
                st.session_state["pu_settings"] = {
                    "pu_div":       pu_div,
                    "pu_supp":      pu_supp,
                    "pu_date":      pu_date,
                    "pu_amount":    pu_amount,
                    "pu_kg":        pu_kg,
                    "pu_prod":      pu_prod,
                    "pu_cat":       pu_cat,
                    "sel_div_pu":   sel_div_pu,
                    "sel_suppliers":sel_suppliers,
                }
                st.sidebar.success("Impostazioni salvate ✅")
        with c_reset:
            if st.button("🔄 Reset", key="btn_reset_pu",
                         help="Ripristina impostazioni di default"):
                if "pu_settings" in st.session_state:
                    del st.session_state["pu_settings"]
                st.rerun()

        # Ricarica dati dal Drive (pulisce cache per il file Acquisti)
        if st.sidebar.button("🔄 Ricarica dati Drive", key="btn_reload_pu",
                              help="Forza il ricaricamento del file da Google Drive"):
            load_dataset.clear()
            smart_analyze_and_clean.clear()
            st.rerun()

        # Importa/Esporta settings come JSON (persistenza cross-sessione)
        with st.sidebar.expander("📤 Esporta / 📥 Importa Impostazioni", expanded=False):
            current_cfg = st.session_state.get("pu_settings", {})
            st.download_button(
                "📤 Esporta settings (.json)",
                data=json.dumps(current_cfg, indent=2, default=str),
                file_name="eita_purchase_settings.json",
                mime="application/json",
                key="btn_export_settings"
            )
            uploaded_cfg = st.file_uploader(
                "📥 Importa settings (.json)", type="json", key="settings_uploader"
            )
            if uploaded_cfg is not None:
                try:
                    loaded = json.loads(uploaded_cfg.read())
                    st.session_state["pu_settings"] = loaded
                    st.success("Impostazioni importate! Ricarica la pagina.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Errore importazione: {ex}")

        # Aggiorna contesto AI con df filtrato (aggiornato a ogni render)
        if not df_pu_global.empty:
            _periodo_pu = ""
            try:
                _periodo_pu = f" | Periodo: {d_start_pu.strftime('%d/%m/%Y')} – {d_end_pu.strftime('%d/%m/%Y')}"
            except Exception:
                pass
            st.session_state["ai_context_df"]    = df_pu_global
            st.session_state["ai_context_label"] = f"Acquisti{_periodo_pu}"

        # KPI — sempre visibili; quando df_pu_global è vuoto i valori sono 0
        tot_invoice_pu = df_pu_global[pu_amount].sum() if pu_amount in df_pu_global.columns else 0
        tot_kg_pu      = df_pu_global[pu_kg].sum()     if pu_kg     in df_pu_global.columns else 0
        tot_orders_pu  = (df_pu_global['Purchase order'].nunique()
                          if 'Purchase order' in df_pu_global.columns else 0)
        avg_price_kg   = (tot_invoice_pu / tot_kg_pu) if tot_kg_pu > 0 else 0

        render_kpi_cards([
            {"title": "💸 Spesa Totale",
             "value":    f"€ {tot_invoice_pu:,.0f}",
             "subtitle": "Invoice Amount (importo fatturato)"},
            {"title": "⚖️ Volume Totale",
             "value":    f"{tot_kg_pu:,.0f} Kg",
             "subtitle": "Kg Acquistati (Line amount / Purchase price)"},
            {"title": "📦 Ordini Totali",
             "value":    str(tot_orders_pu),
             "subtitle": "N° ordini di acquisto univoci"},
            {"title": "🏷️ Prezzo Medio",
             "value":    f"€ {avg_price_kg:.4f}",
             "subtitle": "€ per Kg (Invoice amount / Kg acq.)"},
        ], card_class="purch-card")

        # Caption periodo effettivo sotto i KPI
        if d_start_pu and d_end_pu and not df_pu_global.empty:
            st.caption(
                f"📅 Periodo: **{d_start_pu.strftime('%d/%m/%Y')} – {d_end_pu.strftime('%d/%m/%Y')}**"
            )

        if df_pu_global.empty:
            st.info("📭 Nessun dato da visualizzare per il periodo selezionato.")
        else:

            st.divider()
            c1, c2 = st.columns(2)

            with c1:
                st.subheader("📅 Trend Spesa nel Tempo")
                # Nota: la colonna pu_date è già stata convertita e dropna-ta nella sezione filtri sopra
                if (pu_date and pu_amount and pu_date in df_pu_global.columns
                        and pd.api.types.is_datetime64_any_dtype(df_pu_global[pu_date])
                        and not df_pu_global.empty):
                    try:
                        trend_pu = (df_pu_global
                                    .groupby(pd.Grouper(key=pu_date, freq='ME'))[pu_amount]
                                    .sum().reset_index())
                        fig_trend = go.Figure()

                        # trace[0] — area fill (solo colore, no legend)
                        fig_trend.add_trace(go.Scatter(
                            x=trend_pu[pu_date], y=trend_pu[pu_amount],
                            fill='tozeroy',
                            fillcolor='rgba(67,233,123,0.18)',
                            line=dict(color='rgba(0,0,0,0)', width=0),
                            mode='lines', showlegend=False, hoverinfo='skip',
                        ))
                        # trace[1] — linea principale + marker + etichette (compare in legend)
                        fig_trend.add_trace(go.Scatter(
                            x=trend_pu[pu_date], y=trend_pu[pu_amount],
                            mode='lines+markers+text',
                            name='💸 Spesa €',
                            showlegend=True,
                            line=dict(color='#38f9d7', width=2.5, shape='spline', smoothing=1.1),
                            marker=dict(
                                size=10, color='#43e97b',
                                line=dict(color='white', width=2.5),
                                symbol='circle',
                            ),
                            text=trend_pu[pu_amount].apply(
                                lambda v: f"€{v/1e3:.0f}K" if v >= 1000 else f"€{v:.0f}"
                            ),
                            textposition='top center',
                            textfont=dict(size=9, color='rgba(255,255,255,0.75)'),
                            hovertemplate=(
                                "📅 <b>%{x|%B %Y}</b><br>"
                                "💸 € %{y:,.2f}<extra></extra>"
                            ),
                        ))

                        # trace[2] — media mobile rolling 3 mesi (solo se dati sufficienti)
                        if len(trend_pu) >= 3:
                            roll_avg = trend_pu[pu_amount].rolling(3, center=True, min_periods=1).mean()
                            fig_trend.add_trace(go.Scatter(
                                x=trend_pu[pu_date], y=roll_avg,
                                mode='lines', name='Media 3M',
                                line=dict(color='rgba(247,151,30,0.7)', width=2,
                                          dash='dot', shape='spline'),
                                hovertemplate="📈 Media 3M: € %{y:,.2f}<extra></extra>",
                            ))

                        fig_trend.update_layout(
                            height=420,
                            xaxis=dict(
                                title="", showgrid=False,
                                tickformat="%b %Y", tickangle=-30,
                                tickfont=dict(size=10),
                            ),
                            yaxis=dict(
                                title="€ Spesa", showgrid=True,
                                gridcolor='rgba(67,233,123,0.1)',
                                tickprefix="€ ", tickfont=dict(size=10),
                                zeroline=False,
                            ),
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            margin=dict(l=0, r=0, t=10, b=10),
                            showlegend=True,
                            legend=dict(
                                x=0.01, y=0.99, font=dict(size=9),
                                bgcolor='rgba(0,0,0,0.2)', bordercolor='rgba(255,255,255,0.1)',
                                borderwidth=1,
                            ),
                        )
                        _plot(fig_trend)
                        st.caption(f"📅 Data: **{pu_date}**")
                    except Exception as e:
                        st.warning(f"Impossibile generare grafico temporale: {e}")
                else:
                    st.warning("Dati temporali non disponibili o formato data non valido.")

            with c2:
                st.subheader("🏆 Top Fornitori (per Spesa)")
                if pu_supp in df_pu_global.columns and pu_amount in df_pu_global.columns:
                    top_supp = (df_pu_global
                                .groupby(pu_supp)[pu_amount]
                                .sum().sort_values(ascending=False)
                                .head(10).reset_index())
                    # Calcola anche Kg per i top fornitori (asse secondario)
                    top_supp_full = (
                        df_pu_global.groupby(pu_supp)
                        .agg(
                            **{pu_amount: (pu_amount, 'sum'),
                               pu_kg:    (pu_kg,    'sum')}
                        )
                        .reset_index()
                        .sort_values(pu_amount, ascending=False)
                        .head(10)
                    ) if pu_kg in df_pu_global.columns else top_supp.copy()

                    n_sup = len(top_supp_full)
                    norm_s = top_supp_full[pu_amount] / (top_supp_full[pu_amount].max() + 1e-9)
                    bar_cols_s = [
                        f"rgba({int(0+43*v)},{int(198+35*v)},{int(255-87*v)},0.90)"
                        for v in norm_s
                    ]

                    # ── Top Fornitori: 2 pannelli side-by-side (€ | Kg) ──────────
                    # make_subplots con shared_yaxes elimina qualsiasi sovrapposizione
                    from plotly.subplots import make_subplots
                    _has_kg = pu_kg in top_supp_full.columns

                    if _has_kg:
                        fig_supp = make_subplots(
                            rows=1, cols=2,
                            shared_yaxes=True,
                            column_widths=[0.6, 0.4],
                            horizontal_spacing=0.04,
                            subplot_titles=["💸 Spesa (€)", "⚖️ Volume (Kg)"],
                        )
                    else:
                        fig_supp = make_subplots(rows=1, cols=1)

                    # Pannello SINISTRA — Spesa €
                    fig_supp.add_trace(go.Bar(
                        y=top_supp_full[pu_supp],
                        x=top_supp_full[pu_amount],
                        orientation='h',
                        name='💸 Spesa €',
                        marker=dict(color=bar_cols_s,
                                    line=dict(color='rgba(255,255,255,0.4)', width=0.8)),
                        text=top_supp_full[pu_amount].apply(
                            lambda v: f"€ {v/1e6:.2f}M" if v >= 1e6
                                      else (f"€ {v/1e3:.0f}K" if v >= 1000 else f"€ {v:.0f}")
                        ),
                        textposition='outside',
                        textfont=dict(size=11, family='Arial Bold'),
                        hovertemplate="<b>%{y}</b><br>💸 € %{x:,.0f}<extra></extra>",
                        cliponaxis=False,
                    ), row=1, col=1)

                    # Pannello DESTRA — Volume Kg
                    if _has_kg:
                        _kg_norm   = top_supp_full[pu_kg] / (top_supp_full[pu_kg].max() + 1e-9)
                        _kg_colors = [f"rgba(247,{int(151+60*v)},{int(30+80*v)},0.85)"
                                      for v in _kg_norm]
                        fig_supp.add_trace(go.Bar(
                            y=top_supp_full[pu_supp],
                            x=top_supp_full[pu_kg],
                            orientation='h',
                            name='⚖️ Kg',
                            marker=dict(color=_kg_colors,
                                        line=dict(color='rgba(255,255,255,0.4)', width=0.8)),
                            text=top_supp_full[pu_kg].apply(
                                lambda v: f"{v/1e3:.0f}K" if v >= 1000 else f"{v:.0f}"
                            ),
                            textposition='outside',
                            textfont=dict(size=11, family='Arial'),
                            hovertemplate="<b>%{y}</b><br>⚖️ %{x:,.0f} Kg<extra></extra>",
                            cliponaxis=False,
                        ), row=1, col=2)

                    _h_supp = max(320, n_sup * 52)
                    fig_supp.update_layout(
                        height=_h_supp,
                        showlegend=False,
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        margin=dict(l=10, r=70, t=36, b=10),
                        barmode='relative',
                    )
                    fig_supp.update_yaxes(
                        autorange="reversed", showgrid=False, tickfont=dict(size=10),
                    )
                    fig_supp.update_xaxes(
                        showgrid=True, gridcolor='rgba(0,198,255,0.12)',
                        tickprefix="€ ", zeroline=False, row=1, col=1
                    )
                    if _has_kg:
                        fig_supp.update_xaxes(
                            showgrid=True, gridcolor='rgba(247,151,30,0.12)',
                            ticksuffix=" Kg", zeroline=False, row=1, col=2
                        )

                    _plot(fig_supp)
                    st.caption(f"📅 Data: **{pu_date}**")

            # --- DETTAGLIO RIGHE ACQUISTO ---
            st.subheader("📋 Dettaglio Righe Acquisto")

            all_available_cols = [c for c in df_pu_global.columns if c not in HIDDEN_COLS_PU]

            # Colonne di default (da legenda utente)
            _DEFAULT_DETAIL_COLS = [
                'Supplier number', 'Supplier name', 'Purchase order',
                'Part number', 'Part description', 'Part group description',
                'Part net weight', 'Order quantity', 'Delivery date',
                'Purchase price', 'Supplier delivery number', 'Received quantity',
                'Date of receipt', 'Invoice date', 'Invoice quantity',
                'Invoice amount', 'Line amount', 'Kg acquistati',
            ]
            default_vis = [c for c in _DEFAULT_DETAIL_COLS if c in all_available_cols]

            # ---- RIGA 1: Mostra colonne + Ordina ----
            rc1, rc2, rc3 = st.columns([2.8, 1.5, 1.2])
            with rc1:
                with st.expander("📋 Mostra / Nascondi Colonne", expanded=False):
                    show_all_btn = st.checkbox("⭐ Tutte le colonne", value=False, key="pu_show_all")
                    if show_all_btn:
                        cols_to_display = all_available_cols
                    else:
                        cols_to_display = st.multiselect(
                            "Seleziona colonne da visualizzare:",
                            options=all_available_cols,
                            default=[c for c in default_vis if c in all_available_cols],
                            key="pu_cols_select"
                        )
                        if not cols_to_display:
                            cols_to_display = default_vis if default_vis else all_available_cols

            with rc2:
                sort_col_pu = st.selectbox(
                    "📊 Ordina per:",
                    options=cols_to_display or all_available_cols,
                    key="pu_sort_col"
                )
            with rc3:
                sort_asc_pu = st.radio(
                    "Direzione:", ["⬆️ Cresc.", "⬇️ Decresc."],
                    horizontal=False, key="pu_sort_dir"
                )

            # ---- RIGA 2: Filtri per Colonna — solo colonne categoriche chiave ----
            # FIX MEMORY: il vecchio loop su TUTTE le colonne eseguiva
            # .astype(str).unique() per ogni colonna ad ogni render → OOM.
            # Nuova logica: filtra solo su un sottoinsieme di colonne utili (≤10),
            # con cap a 300 valori unici per colonna, dentro un st.form.
            _FILTERABLE_COLS = [
                c for c in [pu_supp, pu_prod, pu_cat,
                             'Part group description', 'Part class description',
                             'Division', 'Facility', 'Warehouse', 'Incoterm']
                if c and c in df_pu_global.columns
            ]
            # Rimuovi duplicati preservando l'ordine
            seen = set()
            _FILTERABLE_COLS = [c for c in _FILTERABLE_COLS if not (c in seen or seen.add(c))]

            df_detail_filtered = df_pu_global  # NO .copy() — i filtri colonna creano nuovi oggetti

            with st.expander("🔍 Filtri per Colonna", expanded=False):
                st.caption(
                    "Filtri disponibili sulle colonne categoriche principali. "
                    "Per filtri su date/importi usa la sidebar."
                )
                with st.form("pu_col_filters_form"):
                    filter_cols_ui = st.columns(min(len(_FILTERABLE_COLS), 3) or 1)
                    staged_pu_filters = {}
                    for j, col_name in enumerate(_FILTERABLE_COLS):
                        with filter_cols_ui[j % len(filter_cols_ui)]:
                            uniq = sorted(df_pu_global[col_name].dropna().astype(str).unique().tolist())
                            if len(uniq) <= 300:
                                sel = st.multiselect(
                                    col_name,
                                    options=["Tutti"] + uniq,
                                    default=["Tutti"],
                                    key=f"pu_cf_{col_name}"
                                )
                                if sel and "Tutti" not in sel:
                                    staged_pu_filters[col_name] = sel
                            else:
                                st.caption(f"{col_name}: {len(uniq)} valori, usa ricerca nella tabella")
                    apply_pu_filters = st.form_submit_button("🔄 Applica Filtri Colonna")

                if apply_pu_filters:
                    st.session_state['pu_col_filters'] = staged_pu_filters
                active_pu_filters = st.session_state.get('pu_col_filters', {})
                for col_name, sel_vals in active_pu_filters.items():
                    if col_name in df_detail_filtered.columns:
                        df_detail_filtered = df_detail_filtered[
                            df_detail_filtered[col_name].astype(str).isin(sel_vals)
                        ]

            # ---- Applica ordinamento ----
            asc_flag = (sort_asc_pu == "⬆️ Cresc.")
            if sort_col_pu and sort_col_pu in df_detail_filtered.columns:
                df_detail_filtered = df_detail_filtered.sort_values(
                    by=sort_col_pu, ascending=asc_flag
                )

            final_cols = [c for c in cols_to_display if c in df_detail_filtered.columns]
            df_final   = df_detail_filtered[final_cols] if final_cols else df_detail_filtered

            # CAP DISPLAY: Streamlit renderizza tutto in DOM → troppo RAM con 100k+ righe
            _MAX_ROWS_DISPLAY = 5000
            _total_rows = len(df_final)
            if _total_rows > _MAX_ROWS_DISPLAY:
                df_final = df_final.head(_MAX_ROWS_DISPLAY)
                st.caption(
                    f"⚠️ Tabella limitata a **{_MAX_ROWS_DISPLAY:,}** righe su **{_total_rows:,}** totali. "
                    f"Applica filtri per vedere righe specifiche oppure usa il download Excel per l'export completo."
                )
            else:
                st.caption(f"Righe visualizzate: **{_total_rows:,}** / {len(df_pu_global):,} totali")

            # Column config con help= per tooltip (appare su hover sull'icona ?)
            col_cfg = {}
            for c in all_available_cols:
                tip = _COL_LEGEND.get(c, "")
                if c == 'Purchase order date':
                    col_cfg[c] = st.column_config.DateColumn("Data Ordine",    help=tip)
                elif c == 'Delivery date':
                    col_cfg[c] = st.column_config.DateColumn("Data Consegna",  help=tip)
                elif c == 'Date of receipt':
                    col_cfg[c] = st.column_config.DateColumn("Data Ricezione", help=tip)
                elif c == 'Invoice date':
                    col_cfg[c] = st.column_config.DateColumn("Data Fattura",   help=tip)
                elif c == 'Invoice amount':
                    col_cfg[c] = st.column_config.NumberColumn("Importo Fatt.", format="€ %.2f", help=tip)
                elif c == 'Row amount':
                    col_cfg[c] = st.column_config.NumberColumn("Importo Riga",  format="€ %.2f", help=tip)
                elif c == 'Line amount':
                    col_cfg[c] = st.column_config.NumberColumn("Importo Linea", format="€ %.2f", help=tip)
                elif c == 'Line amount internal':
                    col_cfg[c] = st.column_config.NumberColumn("Importo Linea Int.", format="€ %.2f", help=tip)
                elif c == 'Kg acquistati':
                    col_cfg[c] = st.column_config.NumberColumn("Kg Acquistati", format="%.2f", help=tip)
                elif c == 'Order quantity':
                    col_cfg[c] = st.column_config.NumberColumn("Qta Ord.",      format="%.0f", help=tip)
                elif c == 'Received quantity':
                    col_cfg[c] = st.column_config.NumberColumn("Qta Ricevuta",  format="%.0f", help=tip)
                elif c == 'Invoice quantity':
                    col_cfg[c] = st.column_config.NumberColumn("Qta Fatt.",     format="%.0f", help=tip)
                elif c == 'Purchase price':
                    col_cfg[c] = st.column_config.NumberColumn("Prezzo Acq.",   format="€ %.4f", help=tip)
                elif c == 'Part net weight':
                    col_cfg[c] = st.column_config.NumberColumn("Peso Netto kg", format="%.4f", help=tip)
                elif c == 'Exchange rate':
                    col_cfg[c] = st.column_config.NumberColumn("Cambio",        format="%.4f", help=tip)
                elif tip:
                    col_cfg[c] = st.column_config.TextColumn(c, help=tip)

            st.dataframe(
                df_final,
                column_config=col_cfg, height=520, hide_index=True
            , use_container_width=True)
            st.download_button(
                "📥 Scarica Report Acquisti (.xlsx)",
                data=convert_df_to_excel(df_final),
                file_name=f"Report_Acquisti_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
