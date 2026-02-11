import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

# --- 1. SETUP & STILE POWER BI ---
st.set_page_config(page_title="Executive BI Dashboard", page_icon="📈", layout="wide")

# Custom CSS per look "Power BI" (Sfondo grigio chiaro, card bianche, meno padding)
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 1rem;}
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e6e6e6;
        padding: 15px;
        border-radius: 5px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    div[data-testid="stExpander"] {
        background-color: #f8f9fa;
        border-radius: 5px;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. MOTORE DI CONNESSIONE (BACKEND) ---
@st.cache_data(ttl=600)
def get_drive_service():
    if "google_cloud" not in st.secrets:
        return None
    creds = service_account.Credentials.from_service_account_info(st.secrets["google_cloud"])
    return build('drive', 'v3', credentials=creds)

@st.cache_data(ttl=600)
def get_file_list():
    service = get_drive_service()
    if not service: return []
    folder_id = st.secrets["folder_id"]
    query = f"'{folder_id}' in parents and (mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or mimeType = 'text/csv' or mimeType = 'application/vnd.ms-excel') and trashed = false"
    results = service.files().list(q=query, fields="files(id, name, modifiedTime)", orderBy="modifiedTime desc").execute()
    return results.get('files', [])

def load_file_content(file_id, file_name):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    buffer.seek(0)
    if file_name.endswith('.csv'): return pd.read_csv(buffer)
    return pd.read_excel(buffer)

# --- 3. INTERFACCIA UTENTE (FRONTEND) ---

# HEADER
c1, c2 = st.columns([3, 1])
with c1:
    st.title("📊 Corporate Analytics Hub")
    st.caption("Google Drive Integrated Solution")
with c2:
    if st.button("🔄 Refresh Dati Cloud", type="primary"):
        st.cache_data.clear()
        st.rerun()

# Recupero lista file
all_files = get_file_list()
if not all_files:
    st.error("Nessun file trovato. Verifica la connessione o carica dati su Drive.")
    st.stop()

file_options = {f['name']: f['id'] for f in all_files}

# TAB DI NAVIGAZIONE
tab1, tab2 = st.tabs(["🔍 Analisi Singola (Deep Dive)", "⚖️ Confronto Multi-Sorgente"])

# --- TAB 1: ANALISI DETTAGLIATA (POWER BI STYLE) ---
with tab1:
    # 1. TOP BAR: Selezione File e Filtri Globali
    with st.container(border=True):
        col_sel, col_filter = st.columns([1, 2])
        with col_sel:
            selected_filename = st.selectbox("📂 Seleziona Dataset", list(file_options.keys()), index=0)
        
        # Caricamento Dati
        df = load_file_content(file_options[selected_filename], selected_filename)
        
        # Logica Filtri Dinamici
        cols_obj = df.select_dtypes(include=['object']).columns.tolist()
        cols_num = df.select_dtypes(include=['number']).columns.tolist()
        
        with col_filter:
            if cols_obj:
                filter_col = st.selectbox("Filtra per:", ["Nessun Filtro"] + cols_obj)
                if filter_col != "Nessun Filtro":
                    unique_vals = df[filter_col].unique()
                    selected_vals = st.multiselect(f"Valori {filter_col}", unique_vals, default=unique_vals)
                    df = df[df[filter_col].isin(selected_vals)]

    # 2. KPI CARDS (Riga Indicatori)
    if not df.empty:
        st.markdown("### 📈 Key Performance Indicators")
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        
        kpi1.metric("Record Totali", len(df))
        kpi1.caption("Righe nel dataset")
        
        if cols_num:
            main_val = cols_num[0]
            totale = df[main_val].sum()
            media = df[main_val].mean()
            
            kpi2.metric(f"Totale {main_val}", f"€ {totale:,.0f}")
            kpi3.metric(f"Media {main_val}", f"€ {media:,.0f}")
            
            # Calcolo delta simulato (es. prima metà vs seconda metà del dataset)
            half = len(df) // 2
            delta = df.iloc[:half][main_val].sum() - df.iloc[half:][main_val].sum()
            kpi4.metric("Variazione (Simulata)", f"{delta:,.0f}", delta_color="normal")

        # 3. AREA VISUALIZZAZIONI
        st.markdown("---")
        
        # Configurazione Visuali
        c_left, c_right = st.columns([2, 1])
        
        with c_left:
            with st.container(border=True):
                st.subheader("Analisi Principale")
                # Barra opzioni grafico integrata
                g_type = st.radio("Tipo Visual:", ["Barre", "Linee", "Area"], horizontal=True, label_visibility="collapsed")
                
                if cols_num and cols_obj:
                    x_axis = st.selectbox("Asse X", cols_obj, key="x_main")
                    y_axis = st.selectbox("Asse Y", cols_num, key="y_main")
                    
                    if g_type == "Barre":
                        fig = px.bar(df, x=x_axis, y=y_axis, color=x_axis, template="plotly_white")
                    elif g_type == "Linee":
                        fig = px.line(df, x=x_axis, y=y_axis, template="plotly_white", markers=True)
                    else:
                        fig = px.area(df, x=x_axis, y=y_axis, template="plotly_white")
                        
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Servono almeno una colonna testo e una numerica.")

        with c_right:
            with st.container(border=True):
                st.subheader("Distribuzione")
                if cols_obj and cols_num:
                    cat_pie = st.selectbox("Categoria", cols_obj, key="pie_cat")
                    fig_pie = px.pie(df, names=cat_pie, values=cols_num[0], hole=0.6, template="plotly_white")
                    fig_pie.update_layout(showlegend=False)
                    st.plotly_chart(fig_pie, use_container_width=True)

        # 4. DATA TABLE
        with st.expander("Mostra Database Completo"):
            st.dataframe(df, use_container_width=True)

# --- TAB 2: CONFRONTO MULTI-SORGENTE ---
with tab2:
    st.subheader("⚔️ Confronto Diretto tra File")
    
    col_a, col_b = st.columns(2)
    
    # SELEZIONE FILE A
    with col_a:
        st.markdown("#### Sorgente A")
        file_a_name = st.selectbox("Seleziona File A", list(file_options.keys()), key="f_a")
        df_a = load_file_content(file_options[file_a_name], file_a_name)
        st.dataframe(df_a.head(5), use_container_width=True)
        col_num_a = df_a.select_dtypes(include='number').columns.tolist()
        if col_num_a:
            val_a = st.selectbox("Metrica A", col_num_a, key="m_a")
            tot_a = df_a[val_a].sum()
            st.metric("Totale A", f"{tot_a:,.0f}")

    # SELEZIONE FILE B
    with col_b:
        st.markdown("#### Sorgente B")
        file_b_name = st.selectbox("Seleziona File B", list(file_options.keys()), key="f_b", index=1 if len(file_options)>1 else 0)
        df_b = load_file_content(file_options[file_b_name], file_b_name)
        st.dataframe(df_b.head(5), use_container_width=True)
        col_num_b = df_b.select_dtypes(include='number').columns.tolist()
        if col_num_b:
            val_b = st.selectbox("Metrica B", col_num_b, key="m_b")
            tot_b = df_b[val_b].sum()
            st.metric("Totale B", f"{tot_b:,.0f}")

    # CONFRONTO GRAFICO
    st.divider()
    if col_num_a and col_num_b:
        st.markdown("#### Delta Visivo")
        delta_fig = go.Figure()
        delta_fig.add_trace(go.Bar(name=file_a_name, x=[val_a], y=[tot_a], marker_color='#2E86C1'))
        delta_fig.add_trace(go.Bar(name=file_b_name, x=[val_b], y=[tot_b], marker_color='#E74C3C'))
        delta_fig.update_layout(barmode='group', template='plotly_white', height=300)
        st.plotly_chart(delta_fig, use_container_width=True)

# FOOTER
st.markdown("---")
st.caption("Cloud BI System | Powered by Python & Streamlit")