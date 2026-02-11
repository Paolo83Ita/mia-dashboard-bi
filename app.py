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
    page_title="EITA Analytics Pro v7",
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

# --- FUNZIONE DI PULIZIA & ANALISI CONTENUTO (AI-HEURISTIC) ---
def smart_analyze_and_clean(df_in):
    df = df_in.copy()
    
    # 1. RILEVAMENTO E CONVERSIONE TIPI
    for col in df.columns:
        # Prendi un campione non nullo
        sample = df[col].dropna().astype(str).head(50).tolist()
        if not sample: continue

        # CHECK DATA
        # Se contiene pattern data (es. 01/01/2026)
        if any('/' in s or '-' in s for s in sample) and any(c.isdigit() for c in sample[0]):
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                continue # Se è data, passa alla prox colonna
            except:
                pass
        
        # CHECK NUMERO (EURO/QUANTITÀ)
        # Se contiene cifre e magari simboli valuta
        if any(c.isdigit() for s in sample for c in s):
            try:
                # Pulizia aggressiva per formati italiani
                clean_col = df[col].astype(str).str.replace('€', '').str.replace(' ', '')
                if clean_col.str.contains(',', regex=False).any():
                    clean_col = clean_col.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                
                # Prova conversione
                converted = pd.to_numeric(clean_col, errors='coerce')
                
                # Se almeno l'80% sono numeri validi, è una colonna numerica
                if converted.notna().sum() / len(converted) > 0.8:
                    df[col] = converted.fillna(0)
            except:
                pass

    return df

# LOGICA DI AUTO-ASSEGNAZIONE COLONNE
def guess_column_role(df):
    cols = df.columns
    guesses = {
        'entity': None, 'customer': None, 'product': None, 
        'euro': None, 'kg': None, 'date': None
    }
    
    # Liste di parole chiave per punteggio
    kw_euro = ['eur', 'valore', 'importo', 'totale', 'amount', 'prezzo', 'fatturato']
    kw_kg = ['kg', 'qta', 'qty', 'quant', 'peso', 'carton', 'pezzi']
    kw_date = ['data', 'date', 'giorno', 'time', 'doc']
    kw_ent = ['entit', 'societ', 'company', 'azienda']
    kw_cust = ['client', 'customer', 'ragione', 'intestatario', 'destinatari']
    kw_prod = ['prod', 'artic', 'desc', 'item', 'material']

    # Analisi per ogni colonna
    for col in cols:
        col_lower = col.lower()
        dtype = df[col].dtype
        
        # DATA
        if pd.api.types.is_datetime64_any_dtype(dtype):
            guesses['date'] = col
            continue

        # NUMERI (Euro vs Kg)
        if pd.api.types.is_numeric_dtype(dtype):
            # Se ha nome 'euro' vince Euro
            if any(k in col_lower for k in kw_euro):
                guesses['euro'] = col
            # Se ha nome 'kg' vince Kg
            elif any(k in col_lower for k in kw_kg):
                guesses['kg'] = col
            # Se non ha nome chiaro, guardiamo i valori
            else:
                if df[col].mean() > 1000: # Probabilmente soldi o grandi quantità
                     if not guesses['euro']: guesses['euro'] = col
                else:
                     if not guesses['kg']: guesses['kg'] = col
            continue

        # TESTO (Entity vs Customer vs Product)
        if dtype == 'object':
            unique_count = df[col].nunique()
            total_count = len(df)
            
            # Entity: Solitamente ha pochissimi valori unici (es. EITA, ESTERO)
            if unique_count <= 10 or any(k in col_lower for k in kw_ent):
                if not guesses['entity']: guesses['entity'] = col
            
            # Customer: Molti valori, ma non tutti diversi (ripetuti per ordini)
            # Spesso contiene "SPA", "SRL"
            elif any(k in col_lower for k in kw_cust):
                guesses['customer'] = col
            
            # Product: Molti valori unici, descrizioni lunghe
            elif unique_count > 20 or any(k in col_lower for k in kw_prod):
                if not guesses['product']: guesses['product'] = col
            
            # Fallback per Customer se non trovato tramite nome
            elif unique_count > 5 and unique_count < (total_count / 2) and not guesses['customer']:
                guesses['customer'] = col

    return guesses

# --- 3. SIDEBAR ---
st.sidebar.title("🧠 AI Control Panel")
files, service = get_drive_files_list()
df_processed = None

# A. SELECT FILE
if files:
    file_map = {f['name']: f for f in files}
    sel_file_name = st.sidebar.selectbox("1. File Sorgente", list(file_map.keys()))
    selected_file_obj = file_map[sel_file_name]
    
    with st.spinner('Lettura e Comprensione Dati...'):
        df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
        if df_raw is not None:
            df_processed = smart_analyze_and_clean(df_raw)
else:
    st.error("Nessun file trovato.")

# B. MAPPATURA INTELLIGENTE
col_entity, col_customer, col_prod, col_euro, col_kg, col_data = [None]*6

if df_processed is not None:
    # Eseguiamo la "predizione" delle colonne
    guesses = guess_column_role(df_processed)
    all_cols = df_processed.columns.tolist()

    st.sidebar.subheader("2. Verifica Colonne (Auto-Detect)")
    
    def set_idx(guess, options):
        return options.index(guess) if guess in options else 0

    with st.sidebar.expander("Mappatura Campi", expanded=True):
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
    
    # 1. ENTITÀ
    if col_entity:
        ents = sorted(df_global[col_entity].astype(str).unique())
        idx_e = ents.index('EITA') if 'EITA' in ents else 0
        sel_ent = st.sidebar.selectbox("Filtra Entità", ents, index=idx_e)
        df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

    # 2. DATA (Periodo Fisso Default)
    if col_data:
        # Range dati disponibili
        min_d = df_global[col_data].min().date() if pd.notnull(df_global[col_data].min()) else datetime.date(2025,1,1)
        max_d = df_global[col_data].max().date() if pd.notnull(df_global[col_data].max()) else datetime.date(2026,12,31)
        
        # Default richiesto: Gennaio 2026
        def_start = datetime.date(2026, 1, 1)
        def_end = datetime.date(2026, 1, 31)
        
        # Controllo se il default è dentro il range, altrimenti adatta
        if def_start < min_d: def_start = min_d
        if def_end > max_d: def_end = max_d
        
        d_start, d_end = st.sidebar.date_input(
            "Periodo Analisi", 
            [def_start, def_end],
            format="DD/MM/YYYY" # Formato data richiesto
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

    # --- CALCOLO KPI RICHIESTI ---
    # 1. Fatturato Generale Periodo
    kpi_euro = df_global[col_euro].sum()
    
    # 2. Quantità Totale Periodo
    kpi_qty = df_global[col_kg].sum()
    
    # 3. N° Totale Ordini (Righe o Univoci se c'è ID ordine, qui usiamo righe come proxy se non c'è ID)
    # Se c'è una colonna 'Ordine' o 'Doc', contiamo gli univoci, altrimenti righe
    kpi_orders = len(df_global)
    
    # 4. Top Cliente
    if col_customer:
        top_client_row = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
        if not top_client_row.empty:
            top_client_name = top_client_row.index[0]
            top_client_val = top_client_row.values[0]
        else:
            top_client_name = "N/A"
            top_client_val = 0
    else:
        top_client_name = "N/A"
    
    # Visualizzazione
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("1. Fatturato Totale", f"€ {kpi_euro:,.2f}", help="Somma fatturato periodo")
    c2.metric("2. Quantità Totale", f"{kpi_qty:,.0f}", help="Somma quantità periodo")
    c3.metric("3. N° Ordini/Righe", f"{kpi_orders:,}", help="Totale movimenti nel periodo")
    c4.metric("4. Top Cliente", top_client_name, f"€ {top_client_val:,.0f}")

    st.markdown("---")
    
    # SEZIONE DRILL DOWN (Mantenuta per dettaglio)
    st.subheader("🔍 Analisi Dettaglio")
    
    col_left, col_right = st.columns([1, 2])
    
    with col_left:
        st.markdown("#### Selezione Cliente")
        # Top clienti
        top_cust_list = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False)
        
        sel_target_cust = st.selectbox(
            "Cliente:", 
            top_cust_list.index.tolist(),
            format_func=lambda x: f"{x} (€ {top_cust_list[x]:,.0f})"
        )
        
        # Mini chart temporale
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
            
            # Calcolo %
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
