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

# --- 1. CONFIGURAZIONE & STILE ---
st.set_page_config(
    page_title="EITA Analytics Pro v9",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS AVANZATO: FIX MOBILE E DARK MODE
st.markdown("""
<style>
    /* Container principale */
    .block-container {
        padding-top: 1rem; 
        padding-bottom: 3rem;
    }

    /* STILE KPI CARD (Compatibile Dark Mode) */
    div[data-testid="stMetric"] {
        background-color: #ffffff !important; /* Forza sfondo bianco */
        border: 1px solid #e0e0e0;
        border-left: 5px solid #004e92;
        padding: 15px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        border-radius: 8px;
        transition: transform 0.2s;
    }
    
    /* FORZA COLORI TESTO (Per evitare bianco su bianco in Dark Mode) */
    [data-testid="stMetricLabel"] {
        color: #6c757d !important; /* Grigio scuro per etichetta */
        font-weight: 600;
    }
    [data-testid="stMetricValue"] {
        color: #212529 !important; /* Nero quasi assoluto per il numero */
        font-weight: 800;
    }
    
    /* TITOLI E HEADER */
    h1, h2, h3 {
        font-family: 'Segoe UI', sans-serif; 
        color: #004e92 !important; /* Blu istituzionale forzato */
    }
    
    /* TABELLE */
    .stDataFrame {
        background-color: white;
        border-radius: 8px;
        padding: 10px;
    }

    /* --- MOBILE OPTIMIZATION --- */
    @media (max-width: 640px) {
        /* Riduci padding su mobile */
        .block-container {padding-left: 1rem; padding-right: 1rem;}
        
        /* Titoli più piccoli */
        h1 {font-size: 1.8rem !important;}
        
        /* Spazio tra i KPI impilati */
        div[data-testid="stMetric"] {
            margin-bottom: 15px;
        }
        
        /* Nascondi elementi sidebar meno utili se necessario */
        section[data-testid="stSidebar"] {
            width: 80% !important; /* Sidebar più larga su mobile quando aperta */
        }
    }
</style>
""", unsafe_allow_html=True)

# --- 2. MOTORE DATI ---
@st.cache_data(ttl=300)
def get_drive_files_list():
    try:
        if "google_cloud" not in st.secrets:
            return None, "Secrets mancanti"
        creds = service_account.Credentials.from_service_account_info(st.secrets["google_cloud"])
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["folder_id"]
        
        query = f"'{folder_id}' in parents and (mimeType contains 'spreadsheet' or mimeType contains 'csv' or name contains '.xlsx') and trashed = false"
        results = service.files().list(
            q=query, fields="files(id, name, modifiedTime, size)", 
            orderBy="modifiedTime desc", pageSize=50
        ).execute()
        return results.get('files', []), service
    except Exception as e:
        return None, str(e)

@st.cache_data(show_spinner=False) 
def load_dataset(file_id, modified_time, _service):
    try:
        request = _service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        try:
            df = pd.read_excel(fh)
        except:
            fh.seek(0)
            df = pd.read_csv(fh)
        return df
    except Exception as e:
        return None

# --- FUNZIONE DI PULIZIA & ANALISI (AI V8) ---
def smart_analyze_and_clean(df_in):
    df = df_in.copy()
    
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(100).tolist()
        if not sample: continue

        # A. CHECK DATA
        if any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                continue 
            except:
                pass
        
        # B. CHECK CODICE PRODOTTO (Fix numerico)
        is_product_code = False
        if any(len(s) >= 5 and s.isdigit() and '.' not in s and ',' not in s for s in sample):
            is_product_code = True
            df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True)
            continue

        # C. CHECK NUMERO (EURO/QUANTITÀ)
        if any(c.isdigit() for s in sample for c in s):
            try:
                clean_col = df[col].astype(str).str.replace('€', '').str.replace(' ', '')
                if clean_col.str.contains(',', regex=False).any():
                    clean_col = clean_col.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                
                converted = pd.to_numeric(clean_col, errors='coerce')
                if converted.notna().sum() / len(converted) > 0.8:
                    df[col] = converted.fillna(0)
            except:
                pass
    return df

# LOGICA DI AUTO-ASSEGNAZIONE
def guess_column_role(df):
    cols = df.columns
    guesses = {
        'entity': None, 'customer': None, 'product': None, 
        'euro': None, 'kg': None, 'date': None
    }
    
    kw_euro = ['eur', 'valore', 'importo', 'totale', 'amount', 'prezzo', 'fatturato', 'netto']
    kw_kg = ['kg', 'qta', 'qty', 'quant', 'peso', 'carton', 'pezzi', 'colli']
    kw_ent = ['entit', 'societ', 'company', 'azienda']
    kw_cust = ['client', 'customer', 'ragione', 'intestatario', 'destinatari', 'rag.soc']
    kw_prod = ['prod', 'artic', 'desc', 'item', 'material', 'codice']
    kw_invoice = ['boll', 'doc', 'num', 'fatt', 'rif']

    for col in cols:
        col_lower = col.lower()
        is_invoice_col = any(k in col_lower for k in kw_invoice)

        if pd.api.types.is_datetime64_any_dtype(df[col]):
            guesses['date'] = col
            continue

        if pd.api.types.is_numeric_dtype(df[col]):
            if any(k in col_lower for k in kw_euro):
                guesses['euro'] = col
            elif any(k in col_lower for k in kw_kg):
                guesses['kg'] = col
            else:
                if df[col].mean() > 500: 
                     if not guesses['euro']: guesses['euro'] = col
                else:
                     if not guesses['kg'] and not is_invoice_col: guesses['kg'] = col
            continue

        unique_vals = df[col].astype(str).unique()
        sample_vals = unique_vals[:20]
        
        has_prod_codes = any('1141511' in str(v) for v in sample_vals) or \
                         any(str(v).isdigit() and len(str(v)) >= 6 for v in sample_vals)

        if has_prod_codes and not is_invoice_col:
             guesses['product'] = col
             continue

        if len(unique_vals) <= 10 or any(k in col_lower for k in kw_ent):
            if not guesses['entity']: guesses['entity'] = col
        elif any(k in col_lower for k in kw_cust):
            guesses['customer'] = col
        elif any(k in col_lower for k in kw_prod):
            if not guesses['product']: guesses['product'] = col
        elif len(unique_vals) > 5 and not guesses['customer'] and not is_invoice_col:
            guesses['customer'] = col

    return guesses

# --- 3. SIDEBAR ---
st.sidebar.title("📱 Mobile Control Panel")
files, service = get_drive_files_list()
df_processed = None

# A. SELECT FILE
if files:
    file_map = {f['name']: f for f in files}
    sel_file_name = st.sidebar.selectbox("1. File Sorgente", list(file_map.keys()))
    selected_file_obj = file_map[sel_file_name]
    
    with st.spinner('Analisi Euristica Dati...'):
        df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
        if df_raw is not None:
            df_processed = smart_analyze_and_clean(df_raw)
else:
    st.error("Nessun file trovato.")

# B. MAPPATURA
col_entity, col_customer, col_prod, col_euro, col_kg, col_data = [None]*6

if df_processed is not None:
    guesses = guess_column_role(df_processed)
    all_cols = df_processed.columns.tolist()

    # Logica per nascondere impostazioni avanzate su mobile se non servono
    with st.sidebar.expander("2. Verifica Colonne", expanded=False):
        def set_idx(guess, options): return options.index(guess) if guess in options else 0
        
        col_entity = st.selectbox("Entità", all_cols, index=set_idx(guesses['entity'], all_cols))
        col_customer = st.selectbox("Cliente", all_cols, index=set_idx(guesses['customer'], all_cols))
        col_prod = st.selectbox("Prodotto", all_cols, index=set_idx(guesses['product'], all_cols))
        col_euro = st.selectbox("Fatturato (€)", all_cols, index=set_idx(guesses['euro'], all_cols))
        col_kg = st.selectbox("Quantità (Kg)", all_cols, index=set_idx(guesses['kg'], all_cols))
        col_data = st.selectbox("Data", all_cols, index=set_idx(guesses['date'], all_cols))

    # C. FILTRI
    st.sidebar.markdown("---")
    st.sidebar.subheader("3. Filtri")
    
    df_global = df_processed.copy()
    
    # ENTITÀ
    if col_entity:
        ents = sorted(df_global[col_entity].astype(str).unique())
        idx_e = ents.index('EITA') if 'EITA' in ents else 0
        sel_ent = st.sidebar.selectbox("Filtra Entità", ents, index=idx_e)
        df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

    # DATA
    if col_data:
        def_start = datetime.date(2026, 1, 1)
        def_end = datetime.date(2026, 1, 31)
        
        d_start, d_end = st.sidebar.date_input("Periodo", [def_start, def_end], format="DD/MM/YYYY")
        
        df_global = df_global[
            (df_global[col_data].dt.date >= d_start) & 
            (df_global[col_data].dt.date <= d_end)
        ]

    # CLIENTE
    if col_customer:
        custs = sorted(df_global[col_customer].astype(str).unique())
        sel_custs = st.sidebar.multiselect("Clienti Specifici", custs)
        if sel_custs:
            df_global = df_global[df_global[col_customer].astype(str).isin(sel_custs)]


# --- 4. DASHBOARD BODY ---
st.title(f"📊 Report: {sel_ent if 'sel_ent' in locals() else 'Generale'}")

if df_processed is not None and not df_global.empty:

    # --- KPI MACRO ---
    kpi_euro = df_global[col_euro].sum()
    kpi_qty = df_global[col_kg].sum()
    kpi_orders = len(df_global)
    
    if col_customer:
        top_client_row = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
        if not top_client_row.empty:
            top_client_name = top_client_row.index[0]
            top_client_val = top_client_row.values[0]
        else:
            top_client_name, top_client_val = "-", 0
    else:
        top_client_name, top_client_val = "-", 0
    
    # Visualizzazione KPI
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("1. Fatturato", f"€ {kpi_euro:,.0f}", help="Totale periodo")
    c2.metric("2. Quantità", f"{kpi_qty:,.0f}", help="Totale Kg/Pz")
    c3.metric("3. Ordini", f"{kpi_orders:,}")
    
    # Tronca nome cliente lungo per mobile
    short_name = top_client_name[:15] + '..' if len(str(top_client_name))>15 else str(top_client_name)
    c4.metric("4. Top", short_name, f"€ {top_client_val:,.0f}")

    st.markdown("---")
    
    # SEZIONE DRILL DOWN
    st.subheader("🔍 Analisi Dettaglio")
    
    col_left, col_right = st.columns([1, 2])
    
    with col_left:
        st.markdown("#### Selezione Cliente")
        top_cust_list = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False)
        
        sel_target_cust = st.selectbox(
            "Seleziona Cliente:", 
            top_cust_list.index.tolist(),
            format_func=lambda x: f"{x} (€ {top_cust_list[x]:,.0f})"
        )
        
        # Chart mobile-friendly
        if col_data and sel_target_cust:
            df_c = df_global[df_global[col_customer] == sel_target_cust]
            daily = df_c.groupby(col_data)[col_euro].sum().reset_index()
            fig = px.bar(daily, x=col_data, y=col_euro, title="Trend Giornaliero")
            fig.update_layout(height=250, margin=dict(l=0,r=0,t=30,b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

    with col_right:
        if sel_target_cust:
            st.markdown(f"#### Prodotti: **{sel_target_cust}**")
            
            df_det = df_global[df_global[col_customer] == sel_target_cust]
            
            prod_stats = df_det.groupby(col_prod).agg({
                col_kg: 'sum',
                col_euro: 'sum'
            }).reset_index().sort_values(col_euro, ascending=False)
            
            tot_val = prod_stats[col_euro].sum()
            prod_stats['%'] = (prod_stats[col_euro] / tot_val * 100)
            
            st.dataframe(
                prod_stats,
                column_config={
                    col_prod: "Prodotto",
                    col_kg: st.column_config.NumberColumn("Q.tà", format="%.0f"),
                    col_euro: st.column_config.NumberColumn("€", format="%.0f"),
                    "%": st.column_config.ProgressColumn("%", format="%.0f", min_value=0, max_value=100)
                },
                hide_index=True,
                use_container_width=True,
                height=400
            )

elif df_processed is not None:
    st.warning("Nessun dato trovato nel periodo selezionato.")
