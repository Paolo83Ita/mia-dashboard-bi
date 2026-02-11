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
    page_title="Director Dashboard Pro",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS per pulizia visiva
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    h1, h2, h3 {font-family: 'Helvetica Neue', sans-serif;}
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

# --- 3. SIDEBAR: SETUP & FILTRI ---
st.sidebar.title("💎 BI Control Panel")

# A. SELEZIONE FILE
files, service = get_drive_files_list()
df_original = None

with st.sidebar.expander("📂 1. Sorgente Dati", expanded=True):
    if files:
        file_map = {f['name']: f for f in files}
        sel_file_name = st.selectbox("Seleziona File", list(file_map.keys()), label_visibility="collapsed")
        selected_file_obj = file_map[sel_file_name]
        
        with st.spinner('Caricamento dati...'):
            df_original = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
        st.caption(f"Righe: {len(df_original):,}")
    else:
        st.error("Nessun file trovato.")

# B. MAPPATURA COLONNE (SETUP)
col_euro, col_kg, col_data, col_cat = None, None, None, None

if df_original is not None:
    # Helper functions per auto-selezione
    num_cols = df_original.select_dtypes(include=['number']).columns.tolist()
    date_cols = df_original.select_dtypes(include=['datetime']).columns.tolist()
    cat_cols = df_original.select_dtypes(include=['object', 'category']).columns.tolist()
    
    def get_idx(keywords, cols):
        for i, c in enumerate(cols):
            if any(k in c.lower() for k in keywords): return i
        return 0

    with st.sidebar.expander("⚙️ 2. Configurazione Colonne", expanded=False):
        st.info("Associa le colonne per far funzionare i KPI")
        col_euro = st.selectbox("Valore (€)", num_cols, index=get_idx(['eur', 'fatturato', 'total', 'amount'], num_cols))
        col_kg = st.selectbox("Quantità (Kg/Pz)", num_cols, index=get_idx(['kg', 'qty', 'qta', 'quantity', 'peso'], num_cols))
        col_data = st.selectbox("Data Ordine", date_cols, index=get_idx(['data', 'date', 'time'], date_cols))
        col_cat = st.selectbox("Entità/Cliente", cat_cols, index=get_idx(['client', 'custom', 'ragione', 'entity'], cat_cols))

    # C. MOTORE DI FILTRAGGIO (ANALISI)
    st.sidebar.markdown("---")
    st.sidebar.header("🔍 3. Filtri Analisi")
    
    df_filtered = df_original.copy()
    active_filters = {} # Dizionario per salvare i filtri attivi
    
    # 1. Filtro Temporale (Fondamentale)
    if col_data:
        min_d, max_d = df_filtered[col_data].min(), df_filtered[col_data].max()
        if not pd.isnull(min_d):
            # Default: MTD (Month to Date) o ultimo mese
            def_start = max_d.replace(day=1) 
            d_start, d_end = st.sidebar.date_input("Periodo", [def_start, max_d], min_value=min_d, max_value=max_d)
            
            # Applica filtro data
            df_filtered = df_filtered[(df_filtered[col_data].dt.date >= d_start) & (df_filtered[col_data].dt.date <= d_end)]
        else:
            d_start, d_end = None, None

    # 2. Filtri Categoriali "A Cascata"
    # L'utente sceglie su QUALI colonne vuole filtrare
    filters_selected = st.sidebar.multiselect("Aggiungi Filtro su:", cat_cols, default=[col_cat] if col_cat else None)
    
    for f_col in filters_selected:
        # Le opzioni disponibili dipendono dai filtri precedenti (Effetto Imbuto)
        options = sorted(df_filtered[f_col].astype(str).unique())
        selection = st.sidebar.multiselect(f"{f_col}", options)
        
        if selection:
            df_filtered = df_filtered[df_filtered[f_col].astype(str).isin(selection)]
            active_filters[f_col] = selection # Salviamo per usarlo nel YoY

# --- 4. DASHBOARD BODY ---
st.title("📊 Executive Dashboard")

if df_original is not None and not df_filtered.empty:

    # --- CALCOLO KPI & YOY (CORRETTO) ---
    curr_euro = df_filtered[col_euro].sum()
    curr_kg = df_filtered[col_kg].sum()
    
    # Calcolo Incidenza
    # Incidenza = (Fatturato Filtrato / Fatturato Totale Periodo SENZA filtri categoriali)
    mask_date_only = (df_original[col_data].dt.date >= d_start) & (df_original[col_data].dt.date <= d_end)
    total_period_turnover = df_original[mask_date_only][col_euro].sum()
    incidence = (curr_euro / total_period_turnover * 100) if total_period_turnover > 0 else 0

    # Calcolo Anno Precedente (Logic Fix)
    prev_euro = 0
    has_yoy = False
    
    if d_start and d_end:
        try:
            # Shift data di 1 anno indietro
            p_start = d_start.replace(year=d_start.year - 1)
            p_end = d_end.replace(year=d_end.year - 1)
            
            # 1. Filtro Data LY
            mask_prev = (df_original[col_data].dt.date >= p_start) & (df_original[col_data].dt.date <= p_end)
            df_prev = df_original[mask_prev]
            
            # 2. RIAPPLICA GLI STESSI FILTRI CATEGORIALI (Fix Incongruenza)
            for col, values in active_filters.items():
                if col in df_prev.columns:
                    df_prev = df_prev[df_prev[col].astype(str).isin(values)]
            
            prev_euro = df_prev[col_euro].sum()
            has_yoy = True
        except ValueError:
            pass # Gestione anni bisestili (es. 29 feb)

    delta_val = ((curr_euro - prev_euro) / prev_euro * 100) if prev_euro > 0 else 0

    # --- DISPLAY KPI ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"Totale {col_euro}", f"€ {curr_euro:,.0f}", f"{delta_val:+.1f}% vs LY" if has_yoy else None)
    k2.metric("Incidenza (su Tot. Azienda)", f"{incidence:.1f}%", f"di € {total_period_turnover:,.0f}")
    k3.metric(f"Totale {col_kg}", f"{curr_kg:,.0f}", delta_color="off") # Unità dinamica nel nome
    k4.metric("N. Ordini/Righe", f"{len(df_filtered):,}")

    st.divider()

    # --- GRAFICI AVANZATI ---
    g1, g2 = st.columns([2, 1])

    with g1:
        st.subheader("📈 Analisi Trend")
        
        # Controlli Grafico
        c1, c2 = st.columns(2)
        x_axis = c1.selectbox("Raggruppa per:", cat_cols, index=0)
        y_axis = c2.selectbox("Metrica:", [col_euro, col_kg])
        
        # Aggregazione
        df_chart = df_filtered.groupby(x_axis)[y_axis].sum().reset_index().sort_values(y_axis, ascending=False).head(15)
        
        # Unità di misura dinamica per asse e tooltip
        unit_prefix = "€" if y_axis == col_euro else ""
        
        fig = px.bar(
            df_chart, x=x_axis, y=y_axis,
            text_auto='.2s',
            color=y_axis, color_continuous_scale="Blues"
        )
        
        # Layout Pulito e Assi Dinamici
        fig.update_layout(
            xaxis_title=None,
            yaxis_title=y_axis, # Nome della colonna come titolo asse
            plot_bgcolor="white",
            height=400,
            hovermode="x unified"
        )
        fig.update_traces(
            hovertemplate=f"<b>%{{x}}</b><br>{y_axis}: {unit_prefix} %{{y:,.0f}}<extra></extra>"
        )
        st.plotly_chart(fig, use_container_width=True)

    with g2:
        st.subheader("🍩 Composizione")
        fig_pie = px.donut(df_chart.head(8), values=y_axis, names=x_axis, hole=0.6)
        fig_pie.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), height=350)
        
        # Centro Donut
        total_chart = df_chart[y_axis].sum()
        fig_pie.add_annotation(text=f"TOP 8<br>{unit_prefix} {total_chart:,.0f}", showarrow=False, font_size=16, font_weight="bold")
        
        st.plotly_chart(fig_pie, use_container_width=True)

    # --- TABELLA DETTAGLIO ---
    with st.expander("📑 Dati Analitici (Scarica Excel)"):
        st.dataframe(df_filtered, use_container_width=True)

elif df_original is not None:
    st.warning("Nessun dato trovato per il periodo selezionato.")
