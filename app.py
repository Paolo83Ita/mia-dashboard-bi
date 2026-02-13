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

# ==========================================================================
# 1. CONFIGURAZIONE & STILE (v40.0 - Fix Google Drive Connection)
# ==========================================================================
st.set_page_config(
    page_title="EITA Analytics Pro v40.0",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .block-container {
        padding-top: 2rem !important; padding-bottom: 3rem !important;
        padding-left: 1.5rem !important; padding-right: 1.5rem !important;
        max-width: 1600px;
    }
    [data-testid="stElementToolbar"] { display: none; }
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 1.2rem; margin-bottom: 2rem;
    }
    .kpi-card {
        background: rgba(130,150,200,0.1); backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(130,150,200,0.2); border-radius: 16px;
        padding: 1.5rem; box-shadow: 0 8px 32px 0 rgba(0,0,0,0.05);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        position: relative; overflow: hidden;
    }
    .kpi-card:hover {
        transform: translateY(-5px); box-shadow: 0 12px 40px 0 rgba(0,0,0,0.15);
        border: 1px solid rgba(130,150,200,0.4);
    }
    .kpi-card::before {
        content:""; position:absolute; left:0; top:0; height:100%; width:6px;
        background:linear-gradient(180deg,#00c6ff,#0072ff);
        border-radius:16px 0 0 16px;
    }
    .kpi-card.promo-card::before { background:linear-gradient(180deg,#ff9a9e,#fecfef); }
    .kpi-card.purch-card::before { background:linear-gradient(180deg,#43e97b,#38f9d7); }
    .kpi-title  { font-size:0.9rem; font-weight:600; text-transform:uppercase;
                  letter-spacing:1px; opacity:0.8; margin-bottom:0.5rem; }
    .kpi-value  { font-size:2rem; font-weight:800; line-height:1.2; }
    .kpi-subtitle { font-size:0.8rem; opacity:0.6; margin-top:0.3rem; }
    .stPlotlyChart { filter:drop-shadow(4px 6px 8px rgba(0,0,0,0.2));
                     transition:all 0.3s ease; }
    .stPlotlyChart:hover { filter:drop-shadow(6px 10px 12px rgba(0,0,0,0.3)); }
    .detail-section {
        background-color:#f8f9fa; border-left:5px solid #00c6ff;
        padding:15px; margin-top:20px; border-radius:4px;
    }
    @media (max-width:768px) {
        .block-container { padding-left:0.5rem !important;
                           padding-right:0.5rem !important;
                           padding-top:1rem !important; }
        .kpi-grid { gap:0.8rem; }
        .kpi-value { font-size:1.6rem; }
        .kpi-card  { padding:1.2rem; }
    }
</style>
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
            # FIX (v36): guard page_type != "Purchase" ripristinato
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
            'date':     ['Data_Ordine', 'Data_Fattura'],
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
            'order_date': ['Purchase order date', 'Date of receipt'],
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
# 4. NAVIGAZIONE
# ==========================================================================
st.sidebar.title("🚀 EITA Dashboard")
page = st.sidebar.radio(
    "Vai alla sezione:",
    ["📊 Vendite & Fatturazione", "🎁 Analisi Customer Promo", "📦 Analisi Acquisti"]
)
st.sidebar.markdown("---")

files, drive_error = get_drive_files_list()
if drive_error:
    st.sidebar.error(f"Errore Drive: {drive_error}")


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

        if col_entity:
            ents    = sorted(df_global[col_entity].astype(str).unique())
            idx_e   = ents.index('EITA') if 'EITA' in ents else 0
            sel_ent = st.sidebar.selectbox("Società / Entità", ents, index=idx_e)
            df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

        if col_data and pd.api.types.is_datetime64_any_dtype(df_global[col_data]):
            d_start, d_end = safe_date_input(
                "Periodo di Analisi",
                datetime.date(2026, 1, 1), datetime.date(2026, 1, 31),
                key="sales_date"
            )
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

        st.title(f"Performance Overview: {sel_ent or 'Global'}")

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
                        fig = go.Figure(go.Bar(
                            y=prod_agg[col_prod], x=prod_agg[col_euro], orientation='h',
                            marker=dict(color=prod_agg[col_euro], colorscale='Blues',
                                        line=dict(color='rgba(0,0,0,0.4)', width=1.5)),
                            text=prod_agg[col_euro].apply(lambda v: f"€ {v:,.0f}"),
                            textposition='inside', insidetextanchor='middle',
                            hovertemplate="<b>%{y}</b><br>Fatturato: € %{x:,.2f}<extra></extra>"
                        ))
                        fig.update_layout(
                            height=450,
                            yaxis=dict(autorange="reversed", showgrid=False),
                            xaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)'),
                            margin=dict(l=0, r=0, t=10, b=10),
                            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                        )
                    else:
                        hole_size  = 0.45 if "Donut" in chart_type else 0
                        pull_array = [0.12] + [0] * (len(prod_agg) - 1)
                        fig = go.Figure(go.Pie(
                            labels=prod_agg[col_prod], values=prod_agg[col_euro],
                            hole=hole_size, pull=pull_array,
                            marker=dict(colors=px.colors.qualitative.Pastel,
                                        line=dict(color='white', width=2.5)),
                            textinfo='percent+label', textposition='outside',
                            hovertemplate="<b>%{label}</b><br>€ %{value:,.2f}<br>%{percent}<extra></extra>"
                        ))
                        fig.update_layout(
                            height=450, margin=dict(l=20, r=20, t=20, b=20),
                            showlegend=False,
                            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                        )
                    st.plotly_chart(fig, use_container_width=True)

            with col_r:
                if "TUTTI" in sel_target:
                    st.markdown("#### 💥 Esplosione Prodotto (Master-Detail)")
                    st.info("💡 Usa il menu a tendina per il drill-down.")

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

                    if submit_btn or 'sales_raw_df' in st.session_state:
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

                        # OTTIMIZZAZIONE: usa helper riutilizzabile per aggregazione
                        master_df = build_agg_with_ratios(
                            df_tree_raw, primary_col, col_cartons, col_kg, col_euro
                        )
                        st.dataframe(
                            master_df,
                            column_config={
                                primary_col:         st.column_config.TextColumn("Elemento (Master)", width="medium"),
                                col_cartons:         st.column_config.NumberColumn("CT Tot",    format="%d"),
                                col_kg:              st.column_config.NumberColumn("Kg Tot",    format="%.0f"),
                                col_euro:            st.column_config.NumberColumn("Valore Tot",format="€ %.2f"),
                                'Valore Medio €/Kg': st.column_config.NumberColumn("€/Kg Med", format="€ %.2f"),
                                'Valore Medio €/CT': st.column_config.NumberColumn("€/CT Med", format="€ %.2f"),
                            },
                            use_container_width=True, hide_index=True
                        )

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
                                    secondary_col:       st.column_config.TextColumn("Dettaglio (Child)", width="medium"),
                                    col_cartons:         st.column_config.NumberColumn("CT",     format="%d"),
                                    col_kg:              st.column_config.NumberColumn("Kg",     format="%.0f"),
                                    col_euro:            st.column_config.NumberColumn("Valore", format="€ %.2f"),
                                    'Valore Medio €/Kg': st.column_config.NumberColumn("€/Kg",  format="€ %.2f"),
                                    'Valore Medio €/CT': st.column_config.NumberColumn("€/CT",  format="€ %.2f"),
                                },
                                use_container_width=True, hide_index=True
                            )

                        # Export flat (tutti i livelli — grouped su 2 chiavi)
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

                else:
                    st.markdown("#### 🧾 Dettaglio per Cliente Selezionato")
                    st.caption(f"Portafoglio ordini per: {sel_target}")
                    ps = build_agg_with_ratios(df_target, col_prod, col_cartons, col_kg, col_euro)
                    st.dataframe(
                        ps,
                        column_config={
                            col_prod:            st.column_config.TextColumn("🏷️ Articolo / Prodotto", width="large"),
                            col_cartons:         st.column_config.NumberColumn("📦 CT",    format="%d"),
                            col_kg:              st.column_config.NumberColumn("⚖️ Kg",    format="%d"),
                            col_euro:            st.column_config.NumberColumn("💰 Valore",format="€ %.2f"),
                            'Valore Medio €/Kg': st.column_config.NumberColumn("€/Kg Med",format="€ %.2f"),
                            'Valore Medio €/CT': st.column_config.NumberColumn("€/CT Med",format="€ %.2f"),
                        },
                        hide_index=True, use_container_width=True, height=500
                    )
                    st.download_button(
                        "📥 Scarica Dettaglio Excel (.xlsx)",
                        data=convert_df_to_excel(ps),
                        file_name=f"Dettaglio_{sel_target}_{datetime.date.today()}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_download_single"
                    )


# ==========================================================================
# PAGINA 2: CUSTOMER PROMO
# ==========================================================================
elif page == "🎁 Analisi Customer Promo":
    st.title("🎁 Analisi Customer Promo")

    df_promo_processed = None
    df_sales_for_promo = None

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

        # --- Carica Sales (per cross-analysis) ---
        # OTTIMIZZAZIONE: load_dataset è già cachata per (id, modifiedTime).
        # smart_analyze_and_clean è ora cachata → se il file Sales è già stato
        # processato nella Pagina 1, non viene rielaborato.
        sales_key = next(
            (n for n in file_list if "from_order_to_invoice" in n.lower()), None
        )
        if sales_key:
            with st.spinner('Integrazione dati vendita per analisi Promo...'):
                df_sales_raw = load_dataset(
                    file_map[sales_key]['id'], file_map[sales_key]['modifiedTime']
                )
                if df_sales_raw is not None:
                    df_sales_for_promo = smart_analyze_and_clean(df_sales_raw, "Sales")

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

        # Filtro data Sell-In
        if p_start in df_pglobal.columns and pd.api.types.is_datetime64_any_dtype(df_pglobal[p_start]):
            min_date, max_date = df_pglobal[p_start].min(), df_pglobal[p_start].max()
            if pd.notnull(min_date) and pd.notnull(max_date):
                d_start, d_end = safe_date_input(
                    "Periodo Sell-In", min_date.date(), max_date.date(), key="promo_date"
                )
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
        # Prima apertura pagina → applica i default di stato senza richiedere Submit
        elif 'promo_adv_stati' not in st.session_state:
            st.session_state['promo_adv_stati']   = staged_stati  # default pre-selezionati
            st.session_state['promo_adv_filters'] = {}

        active_stati   = st.session_state['promo_adv_stati']
        active_adv_p   = st.session_state['promo_adv_filters']

        if p_status in df_pglobal.columns and active_stati:
            df_pglobal = df_pglobal[df_pglobal[p_status].isin(active_stati)]
        for f_col, vals in active_adv_p.items():
            if f_col in df_pglobal.columns:
                df_pglobal = df_pglobal[df_pglobal[f_col].astype(str).isin(vals)]

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
                if df_sales_for_promo is not None:
                    df_s     = df_sales_for_promo.copy()
                    col_s7   = 'Sconto7_Promozionali'
                    col_s4   = 'Sconto4_Free'
                    col_kg_s = 'Peso_Netto_TotRiga'
                    col_ct_s = 'Qta_Cartoni_Ordinato'
                    col_art  = 'Descr_Articolo'
                    col_cli  = 'Decr_Cliente_Fat'

                    possible_ent = ['Entity', 'Società', 'Company', 'Division', 'Azienda']
                    col_ent      = next((c for c in possible_ent if c in df_s.columns), None)

                    if col_ent and all(c in df_s.columns for c in [col_s7, col_s4, col_kg_s, col_ct_s]):
                        st.caption("Filtra Dati Vendite per Grafico Promo")

                        all_ents       = sorted(df_s[col_ent].dropna().astype(str).unique())
                        default_ent    = ['EITA'] if 'EITA' in all_ents else []
                        sel_ent_chart  = st.multiselect(
                            "1. Filtra Entità (Pre-filtro)", all_ents, default=default_ent,
                            key="promo_chart_entity_filter_outside"
                        )
                        if sel_ent_chart:
                            df_s = df_s[df_s[col_ent].astype(str).isin(sel_ent_chart)]

                        # FIX: filtri Prodotto/Cliente gated da Submit
                        # Problema originale: sel_prod_chart e sel_cust_chart venivano
                        # applicati subito senza richiedere "Aggiorna Grafico".
                        with st.form("promo_sales_chart_filter"):
                            all_prods      = sorted(df_s[col_art].dropna().astype(str).unique())
                            all_custs      = sorted(df_s[col_cli].dropna().astype(str).unique())
                            sel_prod_chart = st.multiselect("2. Filtra Articolo", all_prods, placeholder="Tutti...")
                            sel_cust_chart = st.multiselect("3. Filtra Cliente",  all_custs, placeholder="Tutti...")
                            apply_chart    = st.form_submit_button("Aggiorna Grafico")

                        if apply_chart:
                            st.session_state['promo_chart_prod'] = sel_prod_chart
                            st.session_state['promo_chart_cust'] = sel_cust_chart

                        active_prod = st.session_state.get('promo_chart_prod', [])
                        active_cust = st.session_state.get('promo_chart_cust', [])
                        if active_prod:
                            df_s = df_s[df_s[col_art].astype(str).isin(active_prod)]
                        if active_cust:
                            df_s = df_s[df_s[col_cli].astype(str).isin(active_cust)]

                        df_s['Tipo Vendita'] = np.where(
                            (df_s[col_s7] != 0) | (df_s[col_s4] != 0),
                            'In Promozione', 'Vendita Normale'
                        )
                        promo_stats = df_s.groupby('Tipo Vendita').agg(
                            {col_kg_s: 'sum', col_ct_s: 'sum'}
                        ).reset_index()
                        total_kg = promo_stats[col_kg_s].sum()

                        if not promo_stats.empty:
                            fig_p = px.pie(
                                promo_stats, values=col_kg_s, names='Tipo Vendita', hole=0.4,
                                color='Tipo Vendita',
                                color_discrete_map={
                                    'In Promozione': '#FF6B6B',
                                    'Vendita Normale': '#4ECDC4'
                                }
                            )
                            fig_p.update_traces(textposition='inside', textinfo='percent+label')
                            fig_p.update_layout(showlegend=True, margin=dict(l=20, r=20, t=20, b=20))
                            st.plotly_chart(fig_p, use_container_width=True)

                            st.markdown("#### 📉 Dettaglio Metriche")
                            p_row = promo_stats[promo_stats['Tipo Vendita'] == 'In Promozione']
                            if not p_row.empty:
                                p_kg = p_row[col_kg_s].values[0]
                                p_ct = p_row[col_ct_s].values[0]
                                p_share = (p_kg / total_kg * 100) if total_kg > 0 else 0
                                m1, m2, m3 = st.columns(3)
                                m1.metric("% su Totale (Kg)", f"{p_share:.1f}%")
                                m2.metric("Kg Promo",         f"{p_kg:,.0f}")
                                m3.metric("Cartoni Promo",    f"{p_ct:,.0f}")
                            else:
                                st.info("Nessuna vendita in promozione trovata con i filtri correnti.")
                        else:
                            st.warning("Nessun dato trovato.")
                    else:
                        st.error(f"Colonne mancanti. Colonna Entità rilevata: {col_ent or 'NON TROVATA'}")
                else:
                    st.warning("File Vendite non trovato per l'analisi incrociata.")

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
                    fig = go.Figure(go.Bar(
                        x=top_promos[p_qty_a], y=top_promos[promo_desc_col], orientation='h',
                        marker=dict(color=top_promos[p_qty_a], colorscale='Purp',
                                    line=dict(color='rgba(0,0,0,0.4)', width=1.5))
                    ))
                    fig.update_layout(
                        height=450, yaxis=dict(autorange="reversed"),
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig, use_container_width=True)

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
                    hide_index=True, use_container_width=True, height=500
                )
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
elif page == "📦 Analisi Acquisti":
    st.title("📦 Analisi Acquisti (Purchase History)")

    # FIX CRITICO: df_purch_processed inizializzato a None PRIMA del blocco
    # condizionale. Nella v38.2, era definito solo dentro
    # `if df_purch_raw is not None:`, quindi se il download falliva →
    # NameError: name 'df_purch_processed' is not defined alla riga successiva.
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

                if 'Kg acquistati' not in df_purch_processed.columns:
                    if all(c in df_purch_processed.columns for c in ['Row amount', 'Purchase price']):
                        df_purch_processed['Kg acquistati'] = np.where(
                            df_purch_processed['Purchase price'] > 0,
                            df_purch_processed['Row amount'] / df_purch_processed['Purchase price'],
                            0
                        )
                    else:
                        df_purch_processed['Kg acquistati'] = 0
    else:
        st.error("Nessun file trovato.")

    # Ora il check è sicuro — df_purch_processed è sempre definita (None o DataFrame)
    if df_purch_processed is not None:
        guesses_pu  = guess_column_role(df_purch_processed, "Purchase")
        all_cols_pu = df_purch_processed.columns.tolist()

        with st.sidebar.expander("⚙️ Configurazione Colonne Acquisti", expanded=False):
            pu_div    = st.selectbox("Division",        all_cols_pu, index=set_idx(guesses_pu['division'],   all_cols_pu))
            pu_supp   = st.selectbox("Supplier Name",   all_cols_pu, index=set_idx(guesses_pu['supplier'],   all_cols_pu))
            pu_date   = st.selectbox("Order Date",      all_cols_pu, index=set_idx(guesses_pu['order_date'], all_cols_pu))
            pu_amount = st.selectbox("Invoice Amount",  all_cols_pu, index=set_idx(guesses_pu['amount'],     all_cols_pu))
            pu_kg     = st.selectbox("Kg Acquistati",   all_cols_pu, index=set_idx(guesses_pu['kg'],         all_cols_pu))
            pu_prod   = st.selectbox("Part Description",all_cols_pu, index=set_idx(guesses_pu['product'],    all_cols_pu))
            pu_cat    = st.selectbox("Part Group",      all_cols_pu, index=set_idx(guesses_pu['category'],   all_cols_pu))

        df_pu_global = df_purch_processed.copy()
        st.sidebar.markdown("### 🔍 Filtri Acquisti")

        if pu_div in df_pu_global.columns:
            divs = sorted(df_pu_global[pu_div].astype(str).unique())
            default_div_idx = 0
            if "021" in divs: default_div_idx = divs.index("021")
            elif "21"  in divs: default_div_idx = divs.index("21")
            sel_div_pu   = st.sidebar.selectbox("Divisione", divs, index=default_div_idx)
            df_pu_global = df_pu_global[df_pu_global[pu_div].astype(str) == sel_div_pu]

        if pu_date in df_pu_global.columns and pd.api.types.is_datetime64_any_dtype(df_pu_global[pu_date]):
            min_d, max_d = df_pu_global[pu_date].min(), df_pu_global[pu_date].max()
            if pd.notnull(min_d):
                d_start_pu, d_end_pu = safe_date_input(
                    "Periodo Ordini", min_d.date(), max_d.date(), key="purch_date"
                )
                df_pu_global = df_pu_global[
                    (df_pu_global[pu_date].dt.date >= d_start_pu) &
                    (df_pu_global[pu_date].dt.date <= d_end_pu)
                ]

        if pu_supp in df_pu_global.columns:
            all_suppliers = sorted(df_pu_global[pu_supp].dropna().astype(str).unique())
            sel_suppliers = st.sidebar.multiselect("Fornitori", all_suppliers)
            if sel_suppliers:
                df_pu_global = df_pu_global[df_pu_global[pu_supp].astype(str).isin(sel_suppliers)]

        if not df_pu_global.empty:
            tot_invoice_pu = df_pu_global[pu_amount].sum() if pu_amount else 0
            tot_kg_pu      = df_pu_global[pu_kg].sum()     if pu_kg     else 0
            tot_orders_pu  = (df_pu_global['Purchase order'].nunique()
                              if 'Purchase order' in df_pu_global.columns else 0)
            avg_price_kg   = (tot_invoice_pu / tot_kg_pu) if tot_kg_pu > 0 else 0

            render_kpi_cards([
                {"title": "💸 Spesa Totale",    "value": f"€ {tot_invoice_pu:,.0f}", "subtitle": "Totale Fatturato (Invoice Amount)"},
                {"title": "⚖️ Volume Totale",   "value": f"{tot_kg_pu:,.0f} Kg",     "subtitle": "Kg Acquistati (Calcolati/Reali)"},
                {"title": "📦 Ordini Totali",   "value": str(tot_orders_pu),          "subtitle": "Numero Ordini Acquisto"},
                {"title": "🏷️ Prezzo Medio",   "value": f"€ {avg_price_kg:.2f}",    "subtitle": "Prezzo medio al Kg"},
            ], card_class="purch-card")

            st.divider()
            c1, c2 = st.columns(2)

            with c1:
                st.subheader("📅 Trend Spesa nel Tempo")
                # Riconversione difensiva della colonna data (già gestita in smart_analyze)
                if pu_date in df_pu_global.columns:
                    if not pd.api.types.is_datetime64_any_dtype(df_pu_global[pu_date]):
                        df_pu_global[pu_date] = pd.to_datetime(
                            df_pu_global[pu_date], dayfirst=True, errors='coerce'
                        )
                        df_pu_global = df_pu_global.dropna(subset=[pu_date])

                if (pu_date and pu_amount
                        and pd.api.types.is_datetime64_any_dtype(df_pu_global[pu_date])
                        and not df_pu_global.empty):
                    try:
                        trend_pu = (df_pu_global
                                    .groupby(pd.Grouper(key=pu_date, freq='ME'))[pu_amount]
                                    .sum()
                                    .reset_index())
                        fig_trend = px.line(trend_pu, x=pu_date, y=pu_amount, markers=True)
                        fig_trend.update_layout(height=400, xaxis_title="", yaxis_title="€ Fatturato")
                        st.plotly_chart(fig_trend, use_container_width=True)
                    except Exception as e:
                        st.warning(f"Impossibile generare grafico temporale: {e}")
                else:
                    st.warning("Dati temporali non disponibili o formato data non valido.")

            with c2:
                st.subheader("🏆 Top Fornitori (per Spesa)")
                if pu_supp and pu_amount:
                    top_supp = (df_pu_global
                                .groupby(pu_supp)[pu_amount]
                                .sum()
                                .sort_values(ascending=False)
                                .head(10)
                                .reset_index())
                    fig_supp = px.bar(
                        top_supp, x=pu_amount, y=pu_supp, orientation='h',
                        color=pu_amount, color_continuous_scale='Viridis'
                    )
                    fig_supp.update_layout(
                        height=400, yaxis=dict(autorange="reversed"),
                        xaxis_title="€ Fatturato", yaxis_title=""
                    )
                    st.plotly_chart(fig_supp, use_container_width=True)

            st.subheader("📋 Dettaglio Righe Acquisto")
            cols_to_show  = [
                'Purchase order', 'Purchase order date', 'Supplier name',
                'Part description', 'Part group description',
                'Order quantity', 'Received quantity', 'Invoice amount', 'Kg acquistati'
            ]
            cols_present  = [c for c in cols_to_show if c in df_pu_global.columns]

            st.dataframe(
                df_pu_global[cols_present],
                column_config={
                    'Purchase order date': st.column_config.DateColumn("Data Ordine"),
                    'Invoice amount':      st.column_config.NumberColumn("Importo Fatt.", format="€ %.2f"),
                    'Kg acquistati':       st.column_config.NumberColumn("Kg Calc.",      format="%.0f"),
                    'Order quantity':      st.column_config.NumberColumn("Qta Ord.",       format="%.0f"),
                },
                use_container_width=True, height=500
            )
            st.download_button(
                "📥 Scarica Report Acquisti (.xlsx)",
                data=convert_df_to_excel(df_pu_global[cols_present]),
                file_name=f"Report_Acquisti_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
