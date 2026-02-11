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
    page_title="EITA Analytics Pro v6",
    page_icon="🎯",
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
        padding: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
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

# --- FUNZIONE DI PULIZIA INTELLIGENTE ---
def smart_clean_dataframe(df_in):
    df = df_in.copy()
    
    # 1. Trova e converti Date
    for col in df.columns:
        if df[col].dtype == 'object':
            # Prova a convertire in data se contiene indicatori tipici
            if df[col].astype(str).str.contains(r'\d{2}[/-]\d{2}[/-]\d{4}', regex=True).any():
                try:
                    df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                except:
                    pass

    # 2. Trova e converti Numeri (Euro, Virgole)
    # Cerchiamo colonne Object che sembrano numeri
    for col in df.select_dtypes(include=['object']).columns:
        sample = df[col].astype(str).head(20).tolist()
        # Se contiene € o virgole e numeri
        if any(('€' in s or ',' in s) and any(c.isdigit() for c in s) for s in sample):
            try:
                # Pulisci: via € e spazi
                clean_col = df[col].astype(str).str.replace('€', '').str.replace(' ', '')
                # Gestione virgola italiana: 1.000,00 -> 1000.00
                if clean_col.str.contains(',', regex=False).any():
                    clean_col = clean_col.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                
                df[col] = pd.to_numeric(clean_col, errors='coerce').fillna(0)
            except:
                pass
                
    return df

# --- 3. SIDEBAR ---
st.sidebar.title("🎯 Control Panel v6")
files, service = get_drive_files_list()
df_processed = None

# A. SELECT FILE
if files:
    file_map = {f['name']: f for f in files}
    sel_file_name = st.sidebar.selectbox("1. File Sorgente", list(file_map.keys()))
    selected_file_obj = file_map[sel_file_name]
    
    with st.spinner('Analisi Tipologia Colonne...'):
        df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
        if df_raw is not None:
            # Pulizia Immediata
            df_processed = smart_clean_dataframe(df_raw)
else:
    st.error("Nessun file trovato.")

# B. MAPPATURA STRICT (Per evitare errori)
col_entity, col_customer, col_prod, col_euro, col_kg, col_data = [None]*6

if df_processed is not None:
    st.sidebar.subheader("2. Mappatura Colonne")
    
    # Dividiamo le colonne per TIPO per non confonderti
    all_cols = df_processed.columns.tolist()
    
    # Colonne Numeriche (Per Euro/Kg)
    num_cols = df_processed.select_dtypes(include=['number']).columns.tolist()
    # Colonne Data (Per Periodo)
    date_cols = df_processed.select_dtypes(include=['datetime']).columns.tolist()
    # Colonne Testo (Per Cliente/Prodotto) - Escludiamo quelle puramente numeriche o data
    text_cols = df_processed.select_dtypes(include=['object', 'category']).columns.tolist()
    
    # Helper index finder
    def get_idx(keywords, c_list):
        for i, c in enumerate(c_list):
            if any(k in c.lower() for k in keywords): return i
        return 0

    # 1. Campi TESTO
    with st.sidebar.expander("🅰️ Campi Testo (Chi/Cosa)", expanded=True):
        if not text_cols: text_cols = all_cols # Fallback
        
        col_entity = st.selectbox("Entità (es. EITA)", text_cols, index=get_idx(['entit', 'societ', 'company'], text_cols))
        col_customer = st.selectbox("Cliente (es. Esselunga)", text_cols, index=get_idx(['ragione', 'soc', 'client', 'destinatario'], text_cols))
        col_prod = st.selectbox("Prodotto (es. Articolo)", text_cols, index=get_idx(['descr', 'art', 'prod', 'item', 'material'], text_cols))

    # 2. Campi NUMERICI
    with st.sidebar.expander("🔢 Campi Numerici (Quanto)", expanded=True):
        if not num_cols: 
            st.warning("Nessuna colonna numerica trovata! Controlla formato Excel.")
            num_cols = all_cols
            
        col_euro = st.selectbox("Valore (€)", num_cols, index=get_idx(['imp', 'netto', 'tot', 'eur', 'amount'], num_cols))
        col_kg = st.selectbox("Quantità (Kg/Cartoni)", num_cols, index=get_idx(['qta', 'qty', 'carton', 'pezzi', 'kg'], num_cols))

    # 3. Campi DATA
    with st.sidebar.expander("📅 Campi Data (Quando)", expanded=True):
        if not date_cols:
            st.warning("Nessuna data trovata. Il filtro periodo sarà disabilitato.")
            col_data = None
        else:
            col_data = st.selectbox("Data Riferimento", date_cols, index=get_idx(['data', 'doc', 'date'], date_cols))

    # C. FILTRI LOGICI
    st.sidebar.markdown("---")
    st.sidebar.subheader("3. Filtri Attivi")
    
    df_global = df_processed.copy()
    
    # Filtro ENTITÀ
    if col_entity:
        ents = sorted(df_global[col_entity].astype(str).unique())
        idx_e = ents.index('EITA') if 'EITA' in ents else 0
        sel_ent = st.sidebar.selectbox("Filtra Entità", ents, index=idx_e)
        df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

    # Filtro DATA
    if col_data:
        min_d, max_d = df_global[col_data].min(), df_global[col_data].max()
        if pd.notnull(min_d):
            d_start, d_end = st.sidebar.date_input("Periodo", [min_d, max_d], min_value=min_d, max_value=max_d)
            df_global = df_global[(df_global[col_data].dt.date >= d_start) & (df_global[col_data].dt.date <= d_end)]

    # Filtro CLIENTE OPZIONALE
    if col_customer:
        custs = sorted(df_global[col_customer].astype(str).unique())
        sel_custs = st.sidebar.multiselect("Escludi/Includi Clienti Specifici", custs)
        if sel_custs:
            df_global = df_global[df_global[col_customer].astype(str).isin(sel_custs)]


# --- 4. DASHBOARD BODY ---
st.title(f"📊 Report: {sel_ent if 'sel_ent' in locals() else 'Generale'}")

if df_processed is not None and not df_global.empty:

    # KPI
    tot_eur = df_global[col_euro].sum()
    tot_qty = df_global[col_kg].sum()
    n_cust = df_global[col_customer].nunique()
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fatturato Periodo", f"€ {tot_eur:,.2f}")
    c2.metric("Quantità Totale", f"{tot_qty:,.0f}")
    c3.metric("Clienti Movimentati", n_cust)
    c4.metric("N. Ordini", len(df_global))

    st.markdown("---")
    
    # SEZIONE DRILL DOWN
    st.subheader("🔍 Spaccato Cliente / Prodotto")
    
    c_left, c_right = st.columns([1, 2])
    
    with c_left:
        st.markdown("#### 1. Scegli Cliente")
        # Top 50 clienti per fatturato per non intasare la lista
        top_cust = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(100)
        
        sel_target_cust = st.selectbox(
            "Cliente (Ordinati per Fatturato)", 
            top_cust.index.tolist(),
            format_func=lambda x: f"{x} (€ {top_cust[x]:,.0f})"
        )
        
        # Mini chart cliente
        if col_data and sel_target_cust:
            df_c = df_global[df_global[col_customer] == sel_target_cust]
            daily = df_c.groupby(col_data)[col_euro].sum().reset_index()
            st.bar_chart(daily, x=col_data, y=col_euro, color="#004e92", height=200)

    with c_right:
        if sel_target_cust:
            st.markdown(f"#### 2. Dettaglio: **{sel_target_cust}**")
            
            df_det = df_global[df_global[col_customer] == sel_target_cust]
            
            # Group by Product
            prod_stats = df_det.groupby(col_prod).agg({
                col_kg: 'sum',
                col_euro: 'sum'
            }).reset_index().sort_values(col_euro, ascending=False)
            
            tot_cust_val = prod_stats[col_euro].sum()
            prod_stats['Incidenza %'] = (prod_stats[col_euro] / tot_cust_val * 100)
            
            st.dataframe(
                prod_stats,
                column_config={
                    col_prod: "Prodotto / Articolo",
                    col_kg: st.column_config.NumberColumn("Quantità", format="%.0f"),
                    col_euro: st.column_config.NumberColumn("Valore (€)", format="€ %.2f"),
                    "Incidenza %": st.column_config.ProgressColumn("Peso %", format="%.1f%%", min_value=0, max_value=100)
                },
                hide_index=True,
                use_container_width=True,
                height=500
            )

elif df_processed is not None:
    st.warning("Nessun dato. Controlla che la data non filtri via tutto o che l'Entità esista.")
