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

# --- 1. CONFIGURAZIONE & STILE PREMIUM ---
st.set_page_config(
    page_title="EITA Analytics Pro v22",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS AVANZATO: UI Moderna, Profondità e Mobile Perfetto
st.markdown("""
<style>
    /* Sfondo generale più morbido per esaltare le ombre */
    .stApp {
        background-color: #f4f7f6;
    }
    
    .block-container {
        padding-top: 2rem; 
        padding-bottom: 3rem;
        max-width: 1400px; /* Contenimento su megaschermi */
    }
    
    /* --- NEXT-GEN KPI CARDS --- */
    div[data-testid="stMetric"] {
        background: linear-gradient(145deg, #ffffff, #f0f4f8);
        border: none;
        border-left: 6px solid #004e92;
        padding: 20px 15px;
        box-shadow: 5px 5px 15px rgba(0, 0, 0, 0.05), -5px -5px 15px rgba(255, 255, 255, 0.8);
        border-radius: 12px;
        transition: all 0.3s ease;
    }
    
    div[data-testid="stMetric"]:hover {
        transform: translateY(-5px);
        box-shadow: 8px 8px 20px rgba(0, 0, 0, 0.1), -8px -8px 20px rgba(255, 255, 255, 0.9);
    }
    
    [data-testid="stMetricLabel"] {
        color: #7f8c8d !important; 
        font-weight: 700;
        font-size: 0.95rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    [data-testid="stMetricValue"] {
        color: #2c3e50 !important; 
        font-weight: 900;
        font-size: 1.8rem !important;
        margin-top: 5px;
    }
    
    /* Titoli Moderni */
    h1, h2, h3, h4 {
        font-family: 'Inter', 'Segoe UI', sans-serif; 
        color: #1a252f !important;
        font-weight: 800;
    }
    
    /* Tabelle dal look pulito */
    .stDataFrame {
        background-color: #ffffff;
        border-radius: 12px;
        padding: 15px;
        box-shadow: 3px 3px 10px rgba(0,0,0,0.03);
    }

    /* --- RESPONSIVE MOBILE EXTREME --- */
    @media (max-width: 768px) {
        .block-container {
            padding-top: 1rem;
            padding-left: 0.8rem; 
            padding-right: 0.8rem;
        }
        h1 { font-size: 1.6rem !important; }
        h3 { font-size: 1.3rem !important; }
        
        div[data-testid="stMetric"] {
            margin-bottom: 12px;
            padding: 15px 10px;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.5rem !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.8rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# --- 2. MOTORE DATI (Intatto dalla v21) ---
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
            except: pass
        
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
            except: pass
    return df

def guess_column_role(df):
    cols = df.columns
    guesses = {'entity': None, 'customer': None, 'product': None, 'euro': None, 'kg': None, 'cartons': None, 'date': None}
    golden_rules = {
        'euro': ['Importo_Netto_TotRiga'], 
        'kg': ['Peso_Netto_TotRiga'],
        'cartons': ['Qta_Cartoni_Ordinato'],
        'date': ['Data_Ordine', 'Data_Fattura'], 
        'entity': ['Entity'],
        'customer': ['Descr_Cliente_Fat', 'Descr_Cliente_Dest'],
        'product': ['Descr_Articolo']
    }
    for role, targets in golden_rules.items():
        for t in targets:
            if t in cols:
                guesses[role] = t
                break
    return guesses

# --- 3. SIDEBAR ---
st.sidebar.title("✨ Control Panel")
files, service = get_drive_files_list()
df_processed = None

if files:
    file_map = {f['name']: f for f in files}
    target_file = "From_Order_to_Invoice"
    file_list = list(file_map.keys())
    default_index = 0
    for i, fname in enumerate(file_list):
        if target_file.lower() in fname.lower():
            default_index = i
            break
            
    sel_file_name = st.sidebar.selectbox("1. Sorgente Dati", file_list, index=default_index)
    selected_file_obj = file_map[sel_file_name]
    
    with st.spinner('Sincronizzazione Cloud...'):
        df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
        if df_raw is not None:
            df_processed = smart_analyze_and_clean(df_raw)
else:
    st.error("Nessun file trovato.")

if df_processed is not None:
    guesses = guess_column_role(df_processed)
    all_cols = df_processed.columns.tolist()

    with st.sidebar.expander("2. Mappatura Colonne", expanded=False):
        def set_idx(guess, options): return options.index(guess) if guess in options else 0
        col_entity = st.selectbox("Entità", all_cols, index=set_idx(guesses['entity'], all_cols))
        col_customer = st.selectbox("Cliente (Fatturazione)", all_cols, index=set_idx(guesses['customer'], all_cols))
        col_prod = st.selectbox("Prodotto", all_cols, index=set_idx(guesses['product'], all_cols))
        col_euro = st.selectbox("Valore (€)", all_cols, index=set_idx(guesses['euro'], all_cols))
        col_kg = st.selectbox("Peso (Kg)", all_cols, index=set_idx(guesses['kg'], all_cols))
        col_cartons = st.selectbox("Cartoni (Qty)", all_cols, index=set_idx(guesses['cartons'], all_cols))
        col_data = st.selectbox("Data Riferimento", all_cols, index=set_idx(guesses['date'], all_cols))

    st.sidebar.subheader("3. Filtri Base")
    df_global = df_processed.copy()
    
    if col_entity:
        ents = sorted(df_global[col_entity].astype(str).unique())
        idx_e = ents.index('EITA') if 'EITA' in ents else 0
        sel_ent = st.sidebar.selectbox("Filtra Entità", ents, index=idx_e)
        df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

    if col_data:
        def_start, def_end = datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)
        d_start, d_end = st.sidebar.date_input("Periodo Analisi", [def_start, def_end], format="DD/MM/YYYY")
        df_global = df_global[(df_global[col_data].dt.date >= d_start) & (df_global[col_data].dt.date <= d_end)]

    st.sidebar.subheader("4. Filtri Avanzati")
    possible_filters = [c for c in all_cols if c not in [col_euro, col_kg, col_cartons, col_data, col_entity]]
    filters_selected = st.sidebar.multiselect("Aggiungi Filtri Extra:", possible_filters)
    for f_col in filters_selected:
        unique_vals = sorted(df_global[f_col].astype(str).unique())
        sel_vals = st.sidebar.multiselect(f"Seleziona {f_col}", unique_vals)
        if sel_vals:
            df_global = df_global[df_global[f_col].astype(str).isin(sel_vals)]

# --- 4. DASHBOARD BODY ---
st.title(f"📊 Report Executive: {sel_ent if 'sel_ent' in locals() else 'Generale'}")

if df_processed is not None and not df_global.empty:
    # --- KPI MACRO ---
    tot_euro = df_global[col_euro].sum()
    tot_kg = df_global[col_kg].sum()
    
    col_ord_num = next((c for c in df_global.columns if "Numero_Ordine" in c), None)
    tot_orders = df_global[col_ord_num].nunique() if col_ord_num else len(df_global)
    
    top_c_data = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
    top_name = top_c_data.index[0] if not top_c_data.empty else "-"
    top_val = top_c_data.values[0] if not top_c_data.empty else 0
    
    # Layout responsivo per i KPI
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Fatturato Totale", f"€ {tot_euro:,.2f}")
    with c2: st.metric("Quantità Totale", f"{tot_kg:,.0f} Kg")
    with c3: st.metric("N° Ordini", f"{tot_orders:,}")
    with c4: st.metric("Top Cliente", top_name[:15]+".." if len(str(top_name))>15 else top_name, f"€ {top_val:,.0f}")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- DRILL DOWN ---
    st.subheader("🔍 Analisi Dinamica Cliente/Prodotto")
    
    col_l, col_r = st.columns([1, 1.8])
    
    cust_totals = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False)
    total_val_period = df_global[col_euro].sum()
    options = ["TUTTI I CLIENTI"] + cust_totals.index.tolist()
    
    with col_l:
        st.info("💡 Seleziona o digita per filtrare l'analisi")
        sel_target = st.selectbox(
            "Target Analisi (Ord. per Fatturato):", 
            options,
            format_func=lambda x: f"{x} (€ {total_val_period:,.0f})" if x == "TUTTI I CLIENTI" else f"{x} (€ {cust_totals[x]:,.0f})"
        )
        
        df_target = df_global if sel_target == "TUTTI I CLIENTI" else df_global[df_global[col_customer] == sel_target]
        
        if not df_target.empty:
            chart_type = st.radio("Seleziona Stile Grafico:", ["Barre 3D", "Torta 3D", "Donut"], horizontal=True)
            
            prod_agg = df_target.groupby(col_prod).agg({col_euro: 'sum', col_kg: 'sum', col_cartons: 'sum'}).reset_index().sort_values(col_euro, ascending=False).head(10)
            
            # --- CREAZIONE GRAFICI AVANZATI (3D FEEL) ---
            if chart_type == "Barre 3D":
                fig = px.bar(
                    prod_agg, x=col_euro, y=col_prod, orientation='h', 
                    text_auto='.2s', color=col_euro, color_continuous_scale='Blues' # Gradiente di colore
                )
                fig.update_layout(
                    height=450, yaxis=dict(autorange="reversed"), 
                    margin=dict(l=0,r=10,t=10,b=10), xaxis_title=None, yaxis_title=None,
                    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                    coloraxis_showscale=False # Nasconde la barra colore laterale
                )
                # Bordi neri per simulare profondità 3D
                fig.update_traces(marker_line_color='rgba(0,0,0,0.3)', marker_line_width=1.5)
            
            else:
                hole_size = 0.5 if chart_type == "Donut" else 0
                fig = px.pie(
                    prod_agg, values=col_euro, names=col_prod, hole=hole_size,
                    color_discrete_sequence=px.colors.qualitative.Prism # Colori premium
                )
                
                # Calcola l'esplosione (pull) solo per il primo elemento (il più grande)
                pull_array = [0.15] + [0] * (len(prod_agg) - 1)
                
                fig.update_traces(
                    textposition='outside', textinfo='percent+label', textfont_size=12,
                    pull=pull_array, # Crea l'effetto 3D "esploso"
                    marker=dict(line=dict(color='#ffffff', width=2)) # Bordi bianchi per stacco netto
                )
                fig.update_layout(
                    height=450, margin=dict(l=20,r=20,t=30,b=10), showlegend=False,
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                )
            
            st.plotly_chart(fig, use_container_width=True)

    with col_r:
        if sel_target == "TUTTI I CLIENTI":
            st.markdown("#### 💥 Esplosione Prodotto")
            all_p_sorted = df_target.groupby(col_prod)[col_euro].sum().sort_values(ascending=False)
            sel_p = st.selectbox("Su quale prodotto vuoi fare lo spaccato Clienti?", all_p_sorted.index.tolist(), format_func=lambda x: f"{x} (Fatturato: € {all_p_sorted[x]:,.0f})")
            
            if sel_p:
                df_ps = df_target[df_target[col_prod] == sel_p]
                cb = df_ps.groupby(col_customer).agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'}).reset_index().sort_values(col_euro, ascending=False)
                st.dataframe(
                    cb, 
                    column_config={
                        col_customer: "Ragione Sociale (Fatturazione)",
                        col_cartons: st.column_config.NumberColumn("Cart.", format="%d"),
                        col_kg: st.column_config.NumberColumn("Kg Tot.", format="%d"),
                        col_euro: st.column_config.NumberColumn("Valore", format="€ %.2f")
                    }, 
                    hide_index=True, use_container_width=True, height=520
                )
        else:
            st.markdown(f"#### Portafoglio Acquisti: **{sel_target}**")
            ps = df_target.groupby(col_prod).agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'}).reset_index().sort_values(col_euro, ascending=False)
            st.dataframe(
                ps, 
                column_config={
                    col_prod: "Articolo / Descrizione",
                    col_cartons: st.column_config.NumberColumn("Cartoni", format="%d"),
                    col_kg: st.column_config.NumberColumn("Kg Tot.", format="%d"),
                    col_euro: st.column_config.NumberColumn("Valore", format="€ %.2f")
                }, 
                hide_index=True, use_container_width=True, height=520
            )

elif df_processed is not None:
    st.warning("Nessun dato trovato per il periodo/filtri selezionati.")