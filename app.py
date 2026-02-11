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
    page_title="EITA Analytics Pro v8",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 3rem;}
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-left: 5px solid #004e92;
        padding: 15px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        border-radius: 8px;
    }
    h1, h2, h3 {font-family: 'Segoe UI', sans-serif; color: #004e92;}
    .stAlert {padding: 0.5rem;}
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
    
    # 1. RILEVAMENTO E CONVERSIONE TIPI
    for col in df.columns:
        # Campione dati
        sample = df[col].dropna().astype(str).head(100).tolist()
        if not sample: continue

        # A. CHECK DATA (Priorità massima)
        if any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                continue 
            except:
                pass
        
        # B. CHECK CODICE PRODOTTO (Il fix richiesto)
        # Se i valori sembrano codici prodotto (es. 1141511 - interi lunghi, no decimali)
        # NON convertirli in numeri calcolabili, tienili come stringhe
        is_product_code = False
        if any(len(s) >= 5 and s.isdigit() and '.' not in s and ',' not in s for s in sample):
            # Verifica che non sia una quantità o un importo (solitamente hanno varianza alta o decimali)
            # Un codice prodotto spesso inizia con le stesse cifre
            is_product_code = True
            # Forza a stringa per evitare somme accidentali
            df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True)
            continue

        # C. CHECK NUMERO (EURO/QUANTITÀ)
        if any(c.isdigit() for s in sample for c in s):
            try:
                # Pulizia aggressiva
                clean_col = df[col].astype(str).str.replace('€', '').str.replace(' ', '')
                if clean_col.str.contains(',', regex=False).any():
                    clean_col = clean_col.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                
                converted = pd.to_numeric(clean_col, errors='coerce')
                if converted.notna().sum() / len(converted) > 0.8:
                    df[col] = converted.fillna(0)
            except:
                pass

    return df

# LOGICA DI AUTO-ASSEGNAZIONE COLONNE (V8)
def guess_column_role(df):
    cols = df.columns
    guesses = {
        'entity': None, 'customer': None, 'product': None, 
        'euro': None, 'kg': None, 'date': None
    }
    
    # Keywords
    kw_euro = ['eur', 'valore', 'importo', 'totale', 'amount', 'prezzo', 'fatturato', 'netto']
    kw_kg = ['kg', 'qta', 'qty', 'quant', 'peso', 'carton', 'pezzi', 'colli']
    kw_date = ['data', 'date', 'giorno', 'time', 'doc']
    kw_ent = ['entit', 'societ', 'company', 'azienda']
    kw_cust = ['client', 'customer', 'ragione', 'intestatario', 'destinatari', 'rag.soc']
    kw_prod = ['prod', 'artic', 'desc', 'item', 'material', 'codice']
    kw_invoice = ['boll', 'doc', 'num', 'fatt', 'rif'] # Keywords da evitare per prodotti

    # Analisi
    for col in cols:
        col_lower = col.lower()
        
        # Saltiamo le colonne bolla per i prodotti
        is_invoice_col = any(k in col_lower for k in kw_invoice)

        # 1. DATA
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            guesses['date'] = col
            continue

        # 2. NUMERI (Euro vs Kg)
        if pd.api.types.is_numeric_dtype(df[col]):
            if any(k in col_lower for k in kw_euro):
                guesses['euro'] = col
            elif any(k in col_lower for k in kw_kg):
                guesses['kg'] = col
            else:
                # Euristica valori
                if df[col].mean() > 500: # Probabili soldi
                     if not guesses['euro']: guesses['euro'] = col
                else:
                     if not guesses['kg'] and not is_invoice_col: guesses['kg'] = col
            continue

        # 3. TESTO/CODICI (Entity vs Customer vs Product)
        # Qui sta il fix per 1141511
        unique_vals = df[col].astype(str).unique()
        sample_vals = unique_vals[:20]
        
        # Controllo specifico codice prodotto (es. 1141511)
        has_prod_codes = any('1141511' in str(v) for v in sample_vals) or \
                         any(str(v).isdigit() and len(str(v)) >= 6 for v in sample_vals)

        if has_prod_codes and not is_invoice_col:
             guesses['product'] = col
             continue

        # Altri check testo
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
st.sidebar.title("🧠 AI Control Panel v8")
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

# B. MAPPATURA INTELLIGENTE
col_entity, col_customer, col_prod, col_euro, col_kg, col_data = [None]*6

if df_processed is not None:
    guesses = guess_column_role(df_processed)
    all_cols = df_processed.columns.tolist()

    st.sidebar.subheader("2. Verifica Colonne")
    
    def set_idx(guess, options):
        return options.index(guess) if guess in options else 0

    with st.sidebar.expander("Mappatura Campi (Modificabile)", expanded=True):
        col_entity = st.selectbox("Entità", all_cols, index=set_idx(guesses['entity'], all_cols))
        col_customer = st.selectbox("Cliente", all_cols, index=set_idx(guesses['customer'], all_cols))
        col_prod = st.selectbox("Prodotto (Cod/Art)", all_cols, index=set_idx(guesses['product'], all_cols))
        col_euro = st.selectbox("Fatturato (€)", all_cols, index=set_idx(guesses['euro'], all_cols))
        col_kg = st.selectbox("Quantità (Kg)", all_cols, index=set_idx(guesses['kg'], all_cols))
        col_data = st.selectbox("Data", all_cols, index=set_idx(guesses['date'], all_cols))

    # C. FILTRI
    st.sidebar.markdown("---")
    st.sidebar.subheader("3. Filtri")
    
    df_global = df_processed.copy()
    
    # 1. ENTITÀ
    if col_entity:
        ents = sorted(df_global[col_entity].astype(str).unique())
        idx_e = ents.index('EITA') if 'EITA' in ents else 0
        sel_ent = st.sidebar.selectbox("Filtra Entità", ents, index=idx_e)
        df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

    # 2. DATA (Periodo Fisso Gennaio 2026)
    d_start, d_end = datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)
    
    if col_data:
        # Default richiesto
        def_start = datetime.date(2026, 1, 1)
        def_end = datetime.date(2026, 1, 31)
        
        d_start, d_end = st.sidebar.date_input(
            "Periodo Analisi", 
            [def_start, def_end],
            format="DD/MM/YYYY"
        )
        
        # Filtro Data
        df_global = df_global[
            (df_global[col_data].dt.date >= d_start) & 
            (df_global[col_data].dt.date <= d_end)
        ]

    # 3. CLIENTE (Opzionale)
    if col_customer:
        custs = sorted(df_global[col_customer].astype(str).unique())
        sel_custs = st.sidebar.multiselect("Clienti Specifici (Opzionale)", custs)
        if sel_custs:
            df_global = df_global[df_global[col_customer].astype(str).isin(sel_custs)]


# --- 4. DASHBOARD BODY ---
st.title(f"📊 Report Analitico: {sel_ent if 'sel_ent' in locals() else 'Generale'}")

if df_processed is not None and not df_global.empty:

    # --- KPI MACRO ---
    kpi_euro = df_global[col_euro].sum()
    kpi_qty = df_global[col_kg].sum()
    kpi_orders = len(df_global) # Numero righe
    
    # 4. Top Cliente
    if col_customer:
        top_client_row = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
        if not top_client_row.empty:
            top_client_name = top_client_row.index[0]
            top_client_val = top_client_row.values[0]
        else:
            top_client_name = "-"
            top_client_val = 0
    else:
        top_client_name = "-"
    
    # Visualizzazione KPI
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("1. Fatturato Totale", f"€ {kpi_euro:,.2f}", help="Somma fatturato periodo")
    c2.metric("2. Quantità Totale", f"{kpi_qty:,.0f}", help="Somma quantità periodo")
    c3.metric("3. N° Ordini/Righe", f"{kpi_orders:,}", help="Totale movimenti nel periodo")
    c4.metric("4. Top Cliente", top_client_name[:20] + '..' if len(str(top_client_name))>20 else str(top_client_name), f"€ {top_client_val:,.0f}")

    st.markdown("---")
    
    # SEZIONE DRILL DOWN
    st.subheader("🔍 Analisi Dettaglio")
    
    col_left, col_right = st.columns([1, 2])
    
    with col_left:
        st.markdown("#### Selezione Cliente")
        top_cust_list = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False)
        
        sel_target_cust = st.selectbox(
            "Cliente:", 
            top_cust_list.index.tolist(),
            format_func=lambda x: f"{x} (€ {top_cust_list[x]:,.0f})"
        )
        
        if col_data and sel_target_cust:
            df_c = df_global[df_global[col_customer] == sel_target_cust]
            daily = df_c.groupby(col_data)[col_euro].sum().reset_index()
            fig = px.bar(daily, x=col_data, y=col_euro, title="Andamento Giornaliero")
            fig.update_layout(height=250, xaxis_title=None, yaxis_title=None, margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig, use_container_width=True)

    with col_right:
        if sel_target_cust:
            st.markdown(f"#### Dettaglio Prodotti: **{sel_target_cust}**")
            
            df_det = df_global[df_global[col_customer] == sel_target_cust]
            
            # Pivot prodotti
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
                    col_euro: st.column_config.NumberColumn("Valore", format="€ %.2f"),
                    "%": st.column_config.ProgressColumn("Peso", format="%.1f%%", min_value=0, max_value=100)
                },
                hide_index=True,
                use_container_width=True,
                height=400
            )

elif df_processed is not None:
    st.warning("Nessun dato trovato nel periodo selezionato.")

