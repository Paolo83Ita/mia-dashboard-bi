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
    page_title="EITA Analytics Mobile Pro",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS AVANZATO PER MOBILE E CONTRASTO (DARK/LIGHT MODE)
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 3rem;}
    
    /* KPI CARDS: Forza contrasto e bordi per Mobile */
    div[data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 1px solid #e0e0e0;
        border-left: 5px solid #004e92;
        padding: 12px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        border-radius: 8px;
    }
    
    /* Forza colore testo per evitare scritte bianche su sfondo bianco su mobile */
    [data-testid="stMetricLabel"] {
        color: #555555 !important; 
        font-weight: 600;
        font-size: 0.9rem !important;
    }
    [data-testid="stMetricValue"] {
        color: #111111 !important; 
        font-weight: 800;
        font-size: 1.5rem !important;
    }
    
    h1, h2, h3 {font-family: 'Segoe UI', sans-serif; color: #004e92 !important;}
    
    /* Ottimizzazione Tabelle */
    .stDataFrame {
        border: 1px solid #eee;
        border-radius: 8px;
    }

    /* MEDIA QUERIES PER MOBILE */
    @media (max-width: 640px) {
        .block-container {padding-left: 0.5rem; padding-right: 0.5rem;}
        div[data-testid="stMetric"] {
            margin-bottom: 10px;
            padding: 10px;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.3rem !important;
        }
        /* Nasconde alcuni elementi meno critici su schermi piccolissimi */
        .stMarkdown p { font-size: 0.85rem; }
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

# --- FUNZIONE DI PULIZIA & ANALISI ---
def smart_analyze_and_clean(df_in):
    df = df_in.copy()
    target_numeric_cols = ['Importo_Netto_TotRiga', 'Peso_Netto_TotRiga', 'Qta_Cartoni_Ordinato', 'Prezzo_Netto']
    
    for col in df.columns:
        if col in ['Numero_Pallet', 'Sovrapponibile']: continue 
        sample = df[col].dropna().astype(str).head(100).tolist()
        if not sample: continue

        if any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                continue 
            except:
                pass
        
        is_target_numeric = any(t in col for t in target_numeric_cols)
        looks_numeric = any(c.isdigit() for s in sample for c in s)
        if is_target_numeric or looks_numeric:
            try:
                clean_col = df[col].astype(str).str.replace('€', '').str.replace(' ', '')
                if clean_col.str.contains(',', regex=False).any():
                    clean_col = clean_col.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                converted = pd.to_numeric(clean_col, errors='coerce')
                if is_target_numeric or converted.notna().sum() / len(converted) > 0.7:
                    df[col] = converted.fillna(0)
            except:
                pass
    return df

# LOGICA DI AUTO-ASSEGNAZIONE
def guess_column_role(df):
    cols = df.columns
    guesses = {'entity': None, 'customer': None, 'product': None, 'euro': None, 'kg': None, 'cartons': None, 'date': None}
    golden_rules = {
        'euro': ['Importo_Netto_TotRiga'], 
        'kg': ['Peso_Netto_TotRiga'],
        'cartons': ['Qta_Cartoni_Ordinato'],
        'date': ['Data_Ordine', 'Data_Fattura', 'Data_Consegna'], 
        'entity': ['Entity', 'Società'],
        'customer': ['Descr_Cliente_Fat', 'Descr_Cliente_Dest', 'Ragione Sociale'],
        'product': ['Descr_Articolo', 'Descrizione articolo']
    }
    for role, targets in golden_rules.items():
        for t in targets:
            if t in cols:
                guesses[role] = t
                break
    return guesses

# --- 3. SIDEBAR ---
st.sidebar.title("💎 BI Mobile Control")
files, service = get_drive_files_list()
df_processed = None

if files:
    file_map = {f['name']: f for f in files}
    target_file = "From_Order_to_Invoice"
    default_index = 0
    file_list = list(file_map.keys())
    for i, fname in enumerate(file_list):
        if target_file.lower() in fname.lower():
            default_index = i
            break
            
    sel_file_name = st.sidebar.selectbox("1. Sorgente", file_list, index=default_index)
    selected_file_obj = file_map[sel_file_name]
    
    with st.spinner('Loading...'):
        df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
        if df_raw is not None:
            df_processed = smart_analyze_and_clean(df_raw)
else:
    st.error("Nessun file trovato.")

if df_processed is not None:
    guesses = guess_column_role(df_processed)
    all_cols = df_processed.columns.tolist()

    with st.sidebar.expander("2. Mappatura Campi", expanded=False):
        def set_idx(guess, options): return options.index(guess) if guess in options else 0
        col_entity = st.selectbox("Entità", all_cols, index=set_idx(guesses['entity'], all_cols))
        col_customer = st.selectbox("Cliente", all_cols, index=set_idx(guesses['customer'], all_cols))
        col_prod = st.selectbox("Prodotto", all_cols, index=set_idx(guesses['product'], all_cols))
        col_euro = st.selectbox("Valore (€)", all_cols, index=set_idx(guesses['euro'], all_cols))
        col_kg = st.selectbox("Peso (Kg)", all_cols, index=set_idx(guesses['kg'], all_cols))
        col_cartons = st.selectbox("Cartoni (Qty)", all_cols, index=set_idx(guesses['cartons'], all_cols))
        col_data = st.selectbox("Data", all_cols, index=set_idx(guesses['date'], all_cols))

    st.sidebar.subheader("3. Filtri")
    df_global = df_processed.copy()
    
    if col_entity:
        ents = sorted(df_global[col_entity].astype(str).unique())
        idx_e = ents.index('EITA') if 'EITA' in ents else 0
        sel_ent = st.sidebar.selectbox("Entità", ents, index=idx_e)
        df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

    if col_data:
        def_start, def_end = datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)
        d_start, d_end = st.sidebar.date_input("Periodo Analisi", [def_start, def_end], format="DD/MM/YYYY")
        df_global = df_global[(df_global[col_data].dt.date >= d_start) & (df_global[col_data].dt.date <= d_end)]

    if col_customer:
        custs = sorted(df_global[col_customer].astype(str).unique())
        sel_custs = st.sidebar.multiselect("Clienti Rapido", custs)
        if sel_custs:
            df_global = df_global[df_global[col_customer].astype(str).isin(sel_custs)]

# --- 4. DASHBOARD BODY ---
st.title(f"📊 Report: {sel_ent if 'sel_ent' in locals() else 'Generale'}")

if df_processed is not None and not df_global.empty:
    # KPI MACRO
    kpi_euro = df_global[col_euro].sum()
    kpi_kg = df_global[col_kg].sum()
    
    col_ord_num = next((c for c in df_global.columns if "Numero_Ordine" in c), None)
    kpi_orders = df_global[col_ord_num].nunique() if col_ord_num else len(df_global)
    
    if col_customer:
        top_c = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
        top_name = top_c.index[0] if not top_c.empty else "-"
        top_val = top_c.values[0] if not top_c.empty else 0
    
    c1, c2, c3, c4 = st.columns([1,1,1,1])
    with c1: st.metric("Fatturato", f"€ {kpi_euro:,.0f}")
    with c2: st.metric("Peso Totale", f"{kpi_kg:,.0f} Kg")
    with c3: st.metric("N° Ordini", f"{kpi_orders:,}")
    with c4: st.metric("Top Cliente", top_name[:12]+".." if len(str(top_name))>12 else top_name, f"€ {top_val:,.0f}")

    st.markdown("---")
    
    # SEZIONE DRILL DOWN
    st.subheader("🔍 Dettaglio Cliente & Prodotto")
    
    col_left, col_right = st.columns([1, 1.8])
    
    if col_customer:
        top_cust_list = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False)
        total_euro_all = df_global[col_euro].sum()
        options = ["TUTTI I CLIENTI"] + top_cust_list.index.tolist()
        
        with col_left:
            sel_target_cust = st.selectbox(
                "Cerca Cliente (Ord. Fatturato):", 
                options,
                format_func=lambda x: f"{x} (€ {total_euro_all:,.0f})" if x == "TUTTI I CLIENTI" else f"{x} (€ {top_cust_list[x]:,.0f})"
            )
            
            df_target = df_global if sel_target_cust == "TUTTI I CLIENTI" else df_global[df_global[col_customer] == sel_target_cust]
            
            if not df_target.empty:
                chart_type = st.radio("Grafico:", ["Barre", "Torta", "Donut"], horizontal=True)
                
                prod_data = df_target.groupby(col_prod).agg({col_euro: 'sum', col_kg: 'sum', col_cartons: 'sum'}).reset_index().sort_values(col_euro, ascending=False).head(10)
                
                if chart_type == "Barre":
                    fig = px.bar(prod_data, x=col_euro, y=col_prod, orientation='h', text_auto='.2s')
                    fig.update_layout(height=350, yaxis=dict(autorange="reversed"), margin=dict(l=0,r=10,t=10,b=10), xaxis_title=None, yaxis_title=None)
                    fig.update_traces(marker_color='#004e92')
                else:
                    fig = px.pie(prod_data, values=col_euro, names=col_prod, hole=0.4 if chart_type=="Donut" else 0)
                    fig.update_traces(textposition='outside', textinfo='percent+label', textfont_size=11)
                    fig.update_layout(height=380, margin=dict(l=0,r=0,t=30,b=10), showlegend=False)
                
                st.plotly_chart(fig, use_container_width=True)

        with col_right:
            if sel_target_cust == "TUTTI I CLIENTI":
                st.markdown("#### 💥 Esplosione Prodotto")
                all_p_sorted = df_target.groupby(col_prod)[col_euro].sum().sort_values(ascending=False)
                target_prod = st.selectbox("Seleziona Prodotto:", all_p_sorted.index.tolist())
                
                if target_prod:
                    df_ps = df_target[df_target[col_prod] == target_prod]
                    cb = df_ps.groupby(col_customer).agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'}).reset_index().sort_values(col_euro, ascending=False)
                    st.dataframe(cb, column_config={col_euro: st.column_config.NumberColumn("Valore", format="€ %.2f")}, hide_index=True, use_container_width=True)
            else:
                st.markdown(f"#### Acquisti: {sel_target_cust}")
                ps = df_target.groupby(col_prod).agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'}).reset_index().sort_values(col_euro, ascending=False)
                st.dataframe(ps, column_config={col_euro: st.column_config.NumberColumn("Valore", format="€ %.2f")}, hide_index=True, use_container_width=True)

elif df_processed is not None:
    st.warning("Nessun dato trovato nel periodo selezionato.")