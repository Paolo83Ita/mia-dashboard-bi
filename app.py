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
    page_title="EITA Analytics Pro v10",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS FIX MOBILE & DARK MODE
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 3rem;}
    div[data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 1px solid #e0e0e0;
        border-left: 5px solid #004e92;
        padding: 15px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        border-radius: 8px;
    }
    [data-testid="stMetricLabel"] {color: #6c757d !important; font-weight: 600;}
    [data-testid="stMetricValue"] {color: #212529 !important; font-weight: 800;}
    h1, h2, h3 {font-family: 'Segoe UI', sans-serif; color: #004e92 !important;}
    .stDataFrame {background-color: white; border-radius: 8px; padding: 10px;}
    
    @media (max-width: 640px) {
        .block-container {padding-left: 1rem; padding-right: 1rem;}
        h1 {font-size: 1.8rem !important;}
        div[data-testid="stMetric"] {margin-bottom: 15px;}
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

# --- FUNZIONE DI PULIZIA & ANALISI (V10 - Custom Legend) ---
def smart_analyze_and_clean(df_in):
    df = df_in.copy()
    
    # 1. CLEANING BASE
    for col in df.columns:
        # Skip se la colonna è nella ignore list (es. Numero Pallet che è fuorviante)
        if col in ['Numero_Pallet', 'Sovrapponibile']:
            continue

        sample = df[col].dropna().astype(str).head(100).tolist()
        if not sample: continue

        # A. DATE (Format check)
        if any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                continue 
            except:
                pass
        
        # B. NUMERI (Euro/Quantità) - Pulizia € e virgole
        # Priorità alle colonne che sappiamo essere numeriche dalla legenda
        target_numeric_cols = ['Importo_Netto_TotRiga', 'Peso_Netto_TotRiga', 'Qta_Cartoni_Ordinato', 'Prezzo_Netto']
        
        is_target_numeric = any(t in col for t in target_numeric_cols)
        looks_numeric = any(c.isdigit() for s in sample for c in s)

        if is_target_numeric or looks_numeric:
            try:
                # Pulizia aggressiva
                clean_col = df[col].astype(str).str.replace('€', '').str.replace(' ', '')
                if clean_col.str.contains(',', regex=False).any():
                    clean_col = clean_col.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                
                converted = pd.to_numeric(clean_col, errors='coerce')
                
                # Se era un target o se sembra numero
                if is_target_numeric or converted.notna().sum() / len(converted) > 0.7:
                    df[col] = converted.fillna(0)
            except:
                pass
    return df

# LOGICA DI AUTO-ASSEGNAZIONE CON LEGENDA (V10)
def guess_column_role(df):
    cols = df.columns
    guesses = {
        'entity': None, 'customer': None, 'product': None, 
        'euro': None, 'kg': None, 'date': None
    }
    
    # --- DIZIONARIO GOLDEN (Dalla tua Legenda) ---
    # Cerchiamo PRIMA le colonne esatte fornite
    golden_rules = {
        'euro': ['Importo_Netto_TotRiga'], # Priorità assoluta al Totale Riga
        'kg': ['Peso_Netto_TotRiga', 'Qta_Cartoni_Ordinato'],
        'date': ['Data_Ordine', 'Data_Fattura', 'Data_Consegna'], # Ordine come default
        'entity': ['Entity', 'Società'],
        'customer': ['Descr_Cliente_Fat', 'Descr_Cliente_Dest', 'Ragione Sociale'], # Meglio Descrizione che Codice
        'product': ['Descr_Articolo', 'Descrizione articolo'] # Meglio Descrizione che Codice
    }

    # 1. CERCA COLONNE ESATTE (Match perfetto)
    for role, targets in golden_rules.items():
        for t in targets:
            if t in cols:
                guesses[role] = t
                break # Trovato il migliore, stop
    
    # 2. EURISTICA (Fallback se non trova i nomi esatti)
    # Se non abbiamo trovato colonna tramite Golden Rules, usiamo la vecchia logica
    kw_euro = ['eur', 'valore', 'importo', 'totale', 'amount', 'prezzo', 'fatturato']
    kw_kg = ['kg', 'qta', 'qty', 'quant', 'peso', 'carton', 'pezzi']
    kw_ent = ['entit', 'societ', 'company']
    kw_cust = ['client', 'customer', 'ragione', 'intestatario']
    kw_prod = ['prod', 'artic', 'desc', 'item', 'material']
    kw_ignore = ['cod_', 'numero_', 'sett.', 'mese', 'anno', 'stato'] # Ignora codici se possibile per descrizioni

    for col in cols:
        col_lower = col.lower()
        
        # Skip se già assegnato
        if any(guesses.values()) and col in guesses.values(): continue

        if not guesses['date'] and pd.api.types.is_datetime64_any_dtype(df[col]):
            guesses['date'] = col
            continue

        if pd.api.types.is_numeric_dtype(df[col]):
            if not guesses['euro'] and any(k in col_lower for k in kw_euro) and 'cod' not in col_lower:
                guesses['euro'] = col
            elif not guesses['kg'] and any(k in col_lower for k in kw_kg) and 'cod' not in col_lower:
                guesses['kg'] = col
            continue

        if not guesses['entity'] and any(k in col_lower for k in kw_ent):
            guesses['entity'] = col
        elif not guesses['customer'] and any(k in col_lower for k in kw_cust) and 'cod' not in col_lower:
             guesses['customer'] = col
        elif not guesses['product'] and any(k in col_lower for k in kw_prod) and 'cod' not in col_lower:
             guesses['product'] = col

    return guesses

# --- 3. SIDEBAR ---
st.sidebar.title("💎 Control Panel v10")
files, service = get_drive_files_list()
df_processed = None

# A. SELECT FILE (PRIORITÀ A 'From_Order_to_Invoice')
if files:
    file_map = {f['name']: f for f in files}
    file_list = list(file_map.keys())
    
    # Cerca il file target
    target_file = "From_Order_to_Invoice"
    # Trova indice parziale (es. se si chiama "From_Order_to_Invoice_v2.xlsx")
    default_index = 0
    for i, fname in enumerate(file_list):
        if target_file.lower() in fname.lower():
            default_index = i
            break
            
    sel_file_name = st.sidebar.selectbox("1. File Sorgente", file_list, index=default_index)
    selected_file_obj = file_map[sel_file_name]
    
    with st.spinner('Analisi e Mappatura Legenda...'):
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

    st.sidebar.subheader("2. Mappatura Campi")
    
    def set_idx(guess, options): return options.index(guess) if guess in options else 0

    with st.sidebar.expander("Verifica Colonne (Auto)", expanded=True):
        col_entity = st.selectbox("Entità", all_cols, index=set_idx(guesses['entity'], all_cols))
        col_customer = st.selectbox("Cliente", all_cols, index=set_idx(guesses['customer'], all_cols))
        col_prod = st.selectbox("Prodotto", all_cols, index=set_idx(guesses['product'], all_cols))
        col_euro = st.selectbox("Valore (€)", all_cols, index=set_idx(guesses['euro'], all_cols), help="Cerca: Importo_Netto_TotRiga")
        col_kg = st.selectbox("Quantità (Kg)", all_cols, index=set_idx(guesses['kg'], all_cols), help="Cerca: Peso_Netto_TotRiga")
        col_data = st.selectbox("Data Riferimento", all_cols, index=set_idx(guesses['date'], all_cols), help="Cerca: Data_Ordine")

    # C. FILTRI
    st.sidebar.markdown("---")
    st.sidebar.subheader("3. Filtri")
    
    df_global = df_processed.copy()
    
    # ENTITÀ
    if col_entity:
        ents = sorted(df_global[col_entity].astype(str).unique())
        # Default EITA
        idx_e = ents.index('EITA') if 'EITA' in ents else 0
        sel_ent = st.sidebar.selectbox("Filtra Entità", ents, index=idx_e)
        df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

    # DATA (Default richiesto: 01/01/2026 - 31/01/2026)
    if col_data:
        # Date di default fisse come richiesto
        def_start = datetime.date(2026, 1, 1)
        def_end = datetime.date(2026, 1, 31)
        
        d_start, d_end = st.sidebar.date_input("Periodo Analisi", [def_start, def_end], format="DD/MM/YYYY")
        
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

    # --- KPI MACRO (Richiesti) ---
    # 1. Fatturato Generale Periodo (Sum Importo_Netto_TotRiga)
    kpi_euro = df_global[col_euro].sum()
    
    # 2. Quantità Totale KG (Sum Peso_Netto_TotRiga)
    kpi_qty = df_global[col_kg].sum()
    
    # 3. N° Totale Ordini (Count Unique Numero_Ordine se possibile, altrimenti righe)
    # Cerchiamo colonna Numero_Ordine per conteggio preciso
    col_ord_num = next((c for c in df_global.columns if "Numero_Ordine" in c), None)
    if col_ord_num:
        kpi_orders = df_global[col_ord_num].nunique()
        lbl_orders = "N° Ordini"
    else:
        kpi_orders = len(df_global)
        lbl_orders = "N° Righe"
    
    # 4. Top Cliente (Per Fatturato)
    if col_customer:
        top_client_row = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
        if not top_client_row.empty:
            top_client_name = top_client_row.index[0]
            top_client_val = top_client_row.values[0]
        else:
            top_client_name, top_client_val = "-", 0
    else:
        top_client_name, top_client_val = "-", 0
    
    # VISUALIZZAZIONE KPI
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("1. Fatturato Totale", f"€ {kpi_euro:,.2f}", help="Somma Importo_Netto_TotRiga")
    c2.metric("2. Quantità Totale", f"{kpi_qty:,.0f} Kg", help="Somma Peso_Netto_TotRiga")
    c3.metric(f"3. {lbl_orders}", f"{kpi_orders:,}", help="Ordini unici nel periodo")
    
    short_name = top_client_name[:18] + '..' if len(str(top_client_name))>18 else str(top_client_name)
    c4.metric("4. Top Cliente", short_name, f"€ {top_client_val:,.0f}")

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
        
        # Chart Trend
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
                    col_kg: st.column_config.NumberColumn("Kg Totali", format="%.0f"),
                    col_euro: st.column_config.NumberColumn("Valore Totale", format="€ %.2f"),
                    "%": st.column_config.ProgressColumn("Peso %", format="%.0f", min_value=0, max_value=100)
                },
                hide_index=True,
                use_container_width=True,
                height=400
            )

elif df_processed is not None:
    st.warning("Nessun dato trovato nel periodo selezionato.")
