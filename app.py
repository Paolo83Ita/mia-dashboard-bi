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
    page_title="Executive Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS per migliorare l'estetica (Rimuove padding eccessivi e stilizza i KPI)
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 0rem;}
    [data-testid="stMetricValue"] {font-size: 1.8rem !important;}
    div[data-testid="stExpander"] div[role="button"] p {font-size: 1.1rem; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

# --- 2. MOTORE DI CONNESSIONE (CACHE PER LISTA FILE) ---
@st.cache_data(ttl=300)  # Aggiorna la lista file ogni 5 minuti
def get_drive_files_list():
    try:
        if "google_cloud" not in st.secrets:
            return None, "Secrets mancanti"
            
        creds = service_account.Credentials.from_service_account_info(st.secrets["google_cloud"])
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["folder_id"]

        query = f"'{folder_id}' in parents and (mimeType contains 'spreadsheet' or mimeType contains 'csv' or name contains '.xlsx') and trashed = false"
        results = service.files().list(
            q=query, 
            fields="files(id, name, modifiedTime, size)", 
            orderBy="modifiedTime desc",
            pageSize=20
        ).execute()
        return results.get('files', []), service
    except Exception as e:
        return None, str(e)

# --- 3. MOTORE DI SCARICAMENTO (CACHE PESANTE PER DATI) ---
# Questa funzione viene eseguita SOLO se file_id o modified_time cambiano.
# Altrimenti Streamlit usa la memoria RAM -> VELOCITÀ ISTANTANEA.
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
        
        # Ottimizzazione lettura Excel
        try:
            # Prova a leggere come Excel
            df = pd.read_excel(fh)
        except:
            fh.seek(0)
            # Fallback su CSV
            df = pd.read_csv(fh)
            
        # Converti colonne data automaticamente
        for col in df.columns:
            if df[col].dtype == 'object':
                try:
                    df[col] = pd.to_datetime(df[col])
                except (ValueError, TypeError):
                    pass
        return df
    except Exception as e:
        return None

# --- 4. INTERFACCIA UTENTE ---

# HEADER
col_title, col_btn = st.columns([6,1])
with col_title:
    st.title("📊 Executive BI Dashboard")
with col_btn:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# SIDEBAR: SELEZIONE & FILTRI
with st.sidebar:
    st.header("🗂️ Sorgente Dati")
    files, service = get_drive_files_list()
    
    df_original = None
    
    if files:
        file_map = {f['name']: f for f in files}
        sel_file_name = st.selectbox("Seleziona File", list(file_map.keys()))
        selected_file_obj = file_map[sel_file_name]
        
        # Mostra info file (dimensione e data)
        mod_time_fmt = datetime.datetime.strptime(selected_file_obj['modifiedTime'], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%d/%m/%Y %H:%M")
        st.caption(f"Ultima modifica: {mod_time_fmt}")

        # CARICAMENTO DATI (Con Spinner)
        with st.spinner('Scaricamento e elaborazione dati in corso...'):
            df_original = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
    else:
        st.error("Nessun file trovato o errore connessione.")

    # --- FILTRI INCROCIATI (IL CUORE DELLA BI) ---
    st.divider()
    st.header("🔍 Filtri Avanzati")
    
    df_filtered = df_original.copy() if df_original is not None else None
    
    if df_filtered is not None:
        # Identifica colonne filtro (Testo e Date)
        filter_cols = df_filtered.select_dtypes(include=['object', 'category']).columns.tolist()
        date_cols = df_filtered.select_dtypes(include=['datetime']).columns.tolist()
        
        # Filtro Data (se presente)
        if date_cols:
            date_col = date_cols[0] # Prende la prima colonna data trovata
            min_date = df_filtered[date_col].min()
            max_date = df_filtered[date_col].max()
            if not pd.isnull(min_date) and not pd.isnull(max_date):
                start_date, end_date = st.date_input(
                    f"Periodo ({date_col})",
                    [min_date, max_date],
                    min_value=min_date,
                    max_value=max_date
                )
                df_filtered = df_filtered[
                    (df_filtered[date_col].dt.date >= start_date) & 
                    (df_filtered[date_col].dt.date <= end_date)
                ]

        # Filtri Categorici Dinamici
        # Limitiamo ai primi 5 filtri categorici per non intasare, o scegliamo specifici
        for col in filter_cols[:5]: 
            options = sorted(df_filtered[col].astype(str).unique().tolist())
            # Multiselect intelligente
            selected_vals = st.multiselect(f"{col}", options)
            if selected_vals:
                df_filtered = df_filtered[df_filtered[col].astype(str).isin(selected_vals)]
                
        st.caption(f"Record visualizzati: {len(df_filtered)} / {len(df_original)}")

# --- 5. DASHBOARD VISUALIZATION ---

if df_filtered is not None and not df_filtered.empty:
    
    # Identificazione Colonne
    num_cols = df_filtered.select_dtypes(include=['number']).columns.tolist()
    cat_cols = df_filtered.select_dtypes(include=['object', 'category']).columns.tolist()
    
    if not num_cols:
        st.warning("Il file non contiene colonne numeriche per generare KPI.")
    else:
        # --- RIGA KPI (CARDS) ---
        kpi_cols = st.columns(4)
        
        # KPI 1: Totale Principale (es. Fatturato)
        val_main = df_filtered[num_cols[0]].sum()
        kpi_cols[0].metric(label=f"Totale {num_cols[0]}", value=f"{val_main:,.0f}")
        
        # KPI 2: Media (es. Valore Medio Ordine)
        val_avg = df_filtered[num_cols[0]].mean()
        kpi_cols[1].metric(label=f"Media {num_cols[0]}", value=f"{val_avg:,.0f}")
        
        # KPI 3: Conteggio (es. Numero Ordini)
        kpi_cols[2].metric(label="Volume Transazioni", value=len(df_filtered))
        
        # KPI 4: Seconda metrica numerica (se esiste)
        if len(num_cols) > 1:
            val_sec = df_filtered[num_cols[1]].sum()
            kpi_cols[3].metric(label=f"Totale {num_cols[1]}", value=f"{val_sec:,.0f}")
        else:
             kpi_cols[3].metric(label="Stato Dati", value="OK")

        st.markdown("---")

        # --- ZONA GRAFICI (GRID LAYOUT) ---
        
        # Selettori grafici rapidi
        c_sel1, c_sel2 = st.columns(2)
        with c_sel1:
            chart_x = st.selectbox("Asse Raggruppamento (X)", cat_cols if cat_cols else num_cols, index=0)
        with c_sel2:
            chart_y = st.selectbox("Metrica Valore (Y)", num_cols, index=0)

        row1_col1, row1_col2 = st.columns([2, 1])

        with row1_col1:
            st.subheader("Analisi Trend / Categoria")
            # Logica: Se l'asse X è una data -> Line Chart, altrimenti Bar Chart
            if chart_x in date_cols:
                # Aggregazione temporale
                df_trend = df_filtered.groupby(chart_x)[chart_y].sum().reset_index()
                fig_main = px.line(df_trend, x=chart_x, y=chart_y, markers=True, 
                                  template="plotly_white", line_shape="spline")
                fig_main.update_traces(line_color="#0068C9", line_width=3)
                fig_main.update_layout(xaxis_title="", yaxis_title="", height=400)
            else:
                # Aggregazione categoriale (Top 15)
                df_bar = df_filtered.groupby(chart_x)[chart_y].sum().reset_index().sort_values(chart_y, ascending=False).head(15)
                fig_main = px.bar(df_bar, x=chart_x, y=chart_y, 
                                 template="plotly_white", text_auto='.2s')
                fig_main.update_traces(marker_color="#0068C9")
                fig_main.update_layout(xaxis_title="", yaxis_title="", height=400)
            
            st.plotly_chart(fig_main, use_container_width=True)

        with row1_col2:
            st.subheader("Composizione")
            if cat_cols:
                # Pie Chart sul primo campo categorico o quello selezionato
                target_cat = chart_x if chart_x in cat_cols else cat_cols[0]
                df_pie = df_filtered.groupby(target_cat)[chart_y].sum().reset_index().sort_values(chart_y, ascending=False).head(10)
                fig_pie = px.pie(df_pie, names=target_cat, values=chart_y, hole=0.5, template="plotly_white")
                fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                fig_pie.update_layout(showlegend=False, height=400, margin=dict(t=0, b=0, l=0, r=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Necessaria colonna Categoria per grafico a torta")

        # --- DATA TABLE DETTAGLIATA ---
        with st.expander("📂 Visualizza Dati Dettagliati (Export Excel)", expanded=False):
            st.dataframe(df_filtered, use_container_width=True, height=300)

elif df_original is not None:
    st.warning("Il filtro applicato non ha prodotto risultati. Prova a resettare i filtri nella sidebar.")
else:
    st.info("👈 Seleziona un file dalla barra laterale per iniziare.")
