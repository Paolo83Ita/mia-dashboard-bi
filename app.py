import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import datetime

# --- 1. CONFIGURAZIONE & STILE ---
st.set_page_config(
    page_title="EITA Analytics Pro",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS ottimizzato per tabelle compatte e leggibili
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 3rem;}
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border-left: 5px solid #004e92;
        padding: 10px;
        box-shadow: 1px 1px 3px rgba(0,0,0,0.1);
    }
    h1, h2, h3 {font-family: 'Segoe UI', sans-serif; color: #004e92;}
    /* Tabella Compatta */
    .dataframe {font-size: 0.9rem !important;}
</style>
""", unsafe_allow_html=True)

# --- 2. MOTORE DATI (CACHE) ---
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
        
        # Conversione date robusta
        for col in df.columns:
            if df[col].dtype == 'object':
                try:
                    df[col] = pd.to_datetime(df[col], dayfirst=True)
                except:
                    pass
        return df
    except Exception as e:
        return None

# --- 3. SIDEBAR: SETUP RIGOROSO ---
st.sidebar.title("🎯 Control Panel")

files, service = get_drive_files_list()
df_original = None

# A. CARICAMENTO
if files:
    file_map = {f['name']: f for f in files}
    sel_file_name = st.sidebar.selectbox("1. Seleziona File Sorgente", list(file_map.keys()))
    selected_file_obj = file_map[sel_file_name]
    
    with st.spinner('Accesso al Database...'):
        # Usiamo una copia locale per evitare di modificare la cache
        df_loaded = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
        if df_loaded is not None:
            df_original = df_loaded.copy()
else:
    st.error("Nessun file trovato.")

# B. MAPPATURA (Fondamentale per la logica richiesta)
col_euro, col_kg, col_data, col_entity, col_customer, col_prod = [None]*6

if df_original is not None:
    cols = df_original.columns.tolist()
    
    def get_idx(keywords, c_list):
        for i, c in enumerate(c_list):
            if any(k in c.lower() for k in keywords): return i
        return 0

    st.sidebar.markdown("---")
    st.sidebar.subheader("2. Configurazione Colonne")
    
    # Mapping
    col_entity = st.sidebar.selectbox("Colonna Entità (es. EITA)", cols, index=get_idx(['entity', 'entità', 'company', 'società'], cols))
    col_customer = st.sidebar.selectbox("Colonna Cliente", cols, index=get_idx(['customer', 'cliente', 'ragione', 'nome'], cols))
    col_prod = st.sidebar.selectbox("Colonna Prodotto", cols, index=get_idx(['prod', 'desc', 'art', 'item', 'material'], cols))
    col_euro = st.sidebar.selectbox("Colonna Valore (€)", cols, index=get_idx(['eur', 'valore', 'importo', 'amount', 'totale'], cols))
    col_kg = st.sidebar.selectbox("Colonna Quantità (Cartoni/Kg)", cols, index=get_idx(['qty', 'qta', 'carton', 'pezzi', 'kg'], cols))
    col_data = st.sidebar.selectbox("Colonna Data", cols, index=get_idx(['data', 'date', 'doc'], cols))

    # --- FIX CRITICO: PULIZIA NUMERI ITALIANI ---
    # Questo blocco risolve l'errore ValueError trasformando le colonne "Testo" in "Numeri"
    try:
        for col_to_fix in [col_euro, col_kg]:
            if df_original[col_to_fix].dtype == 'object':
                # Rimuove € e spazi
                df_original[col_to_fix] = df_original[col_to_fix].astype(str).str.replace('€', '').str.replace(' ', '')
                # Se c'è la virgola, assumiamo formato italiano: rimuovi punti migliaia, cambia virgola in punto
                if df_original[col_to_fix].str.contains(',', regex=False).any():
                     df_original[col_to_fix] = df_original[col_to_fix].str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                # Converte in numero, mettendo 0 dove non riesce
                df_original[col_to_fix] = pd.to_numeric(df_original[col_to_fix], errors='coerce').fillna(0)
    except Exception as e:
        st.sidebar.error(f"Errore nella conversione numeri: {e}")
    # --------------------------------------------

    # C. FILTRI GLOBALI (Gerarchici)
    st.sidebar.markdown("---")
    st.sidebar.subheader("3. Filtri Globali")
    
    df_global = df_original.copy()
    
    # 1. Filtro ENTITÀ (Il vincolo "EITA")
    if col_entity:
        entities = sorted(df_global[col_entity].astype(str).unique())
        # Cerchiamo di preselezionare EITA se c'è
        def_idx = entities.index('EITA') if 'EITA' in entities else 0
        sel_entity = st.sidebar.selectbox("Filtra Entità", entities, index=def_idx)
        df_global = df_global[df_global[col_entity].astype(str) == sel_entity]

    # 2. Filtro DATA (Finestra Temporale)
    if col_data:
        min_d, max_d = df_global[col_data].min(), df_global[col_data].max()
        if not pd.isnull(min_d):
            # Default: Ultimi 30 giorni o tutto se piccolo range
            d_start, d_end = st.sidebar.date_input("Periodo Analisi", [min_d, max_d], min_value=min_d, max_value=max_d)
            df_global = df_global[(df_global[col_data].dt.date >= d_start) & (df_global[col_data].dt.date <= d_end)]

    # 3. Filtro CLIENTE (Opzionale per restringere il campo globale)
    customers = sorted(df_global[col_customer].astype(str).unique())
    sel_customers = st.sidebar.multiselect("Filtra Clienti (Opzionale)", customers)
    
    if sel_customers:
        df_global = df_global[df_global[col_customer].astype(str).isin(sel_customers)]

# --- 4. DASHBOARD BODY ---
st.title(f"📊 Report Analitico: {sel_entity if 'sel_entity' in locals() else ''}")

if df_original is not None and not df_global.empty:

    # --- KPI MACRO ---
    tot_eur = df_global[col_euro].sum()
    tot_qty = df_global[col_kg].sum()
    unique_cust = df_global[col_customer].nunique()
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Fatturato Totale", f"€ {tot_eur:,.2f}")
    k2.metric(f"Totale {col_kg}", f"{tot_qty:,.0f}")
    k3.metric("Clienti Attivi", unique_cust)
    k4.metric("Ordini/Righe", len(df_global))

    st.markdown("---")

    # --- SEZIONE DEEP DIVE (L'Analisi Richiesta) ---
    st.subheader("🔍 Analisi Dettaglio Cliente/Prodotto")
    
    col_left, col_right = st.columns([1, 2])
    
    with col_left:
        st.info("1. Seleziona un Cliente per 'spaccare' il dato")
        # Aggreghiamo per cliente per mostrare la lista ordinata per importanza
        df_cust_summary = df_global.groupby(col_customer)[[col_euro]].sum().sort_values(col_euro, ascending=False)
        
        # Selectbox dinamica ordinata per fatturato
        if not df_cust_summary.empty:
            target_customer = st.selectbox(
                "Scegli Cliente:", 
                df_cust_summary.index.tolist(),
                format_func=lambda x: f"{x} (€ {df_cust_summary.loc[x, col_euro]:,.0f})"
            )
            
            # Mini KPI del cliente
            cust_total = df_cust_summary.loc[target_customer, col_euro]
            st.metric(f"Totale {target_customer}", f"€ {cust_total:,.2f}")
            
            # Grafico Trend Cliente (se ci sono date)
            df_cust_trend = df_global[df_global[col_customer] == target_customer].groupby(col_data)[col_euro].sum().reset_index()
            fig_trend = px.bar(df_cust_trend, x=col_data, y=col_euro, title="Andamento Ordini")
            fig_trend.update_layout(height=250, xaxis_title=None, yaxis_title=None, margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            st.warning("Nessun cliente trovato con i filtri attuali.")
            target_customer = None

    with col_right:
        if target_customer:
            st.success(f"2. Dettaglio Prodotti per: **{target_customer}**")
            
            # Filtriamo solo per il cliente selezionato
            df_detail = df_global[df_global[col_customer] == target_customer]
            
            # Raggruppiamo per Prodotto (SOMMA)
            df_prod_summary = df_detail.groupby(col_prod)[[col_kg, col_euro]].sum().reset_index()
            df_prod_summary = df_prod_summary.sort_values(col_euro, ascending=False)
            
            # Calcolo % Incidenza
            total_prod_sum = df_prod_summary[col_euro].sum()
            if total_prod_sum > 0:
                df_prod_summary['% Incidenza'] = (df_prod_summary[col_euro] / total_prod_sum * 100).map('{:.1f}%'.format)
            else:
                df_prod_summary['% Incidenza'] = "0%"
            
            # Formattazione per visualizzazione
            st.dataframe(
                df_prod_summary,
                column_config={
                    col_prod: "Prodotto",
                    col_kg: st.column_config.NumberColumn("Quantità (Cartoni/Kg)", format="%.0f"),
                    col_euro: st.column_config.NumberColumn("Valore Totale (€)", format="€ %.2f"),
                    "% Incidenza": "Impatto %"
                },
                use_container_width=True,
                hide_index=True,
                height=400
            )

    st.markdown("---")
    
    # --- MATRICE DI ANALISI GENERALE (CROSS DATA) ---
    with st.expander("📑 Matrice Completa (Tutti i Clienti nel periodo)", expanded=False):
        # Pivot Table: Righe=Clienti, Colonne=Metriche
        pivot_data = df_global.groupby(col_customer)[[col_euro, col_kg]].sum().sort_values(col_euro, ascending=False)
        st.dataframe(pivot_data.style.format("€ {:,.2f}"), use_container_width=True)

elif df_original is not None:
    st.warning("Nessun dato trovato con i filtri attuali. Controlla le date o l'Entità.")
