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
    page_title="EITA Analytics Pro v18",
    page_icon="🛡️",
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

# --- FUNZIONE DI PULIZIA & ANALISI (V18 - Bulletproof) ---
def smart_analyze_and_clean(df_in):
    df = df_in.copy()
    
    # Pulizia preliminare
    for col in df.columns:
        if col in ['Numero_Pallet', 'Sovrapponibile']: continue 
        
        # Gestione Date
        if df[col].dtype == 'object':
            # Euristiche semplici per date
            sample = df[col].dropna().astype(str).head(20).tolist()
            if sample and any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
                try:
                    df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                except:
                    pass
    return df

# LOGICA DI AUTO-ASSEGNAZIONE
def guess_column_role(df):
    cols = df.columns
    guesses = {
        'entity': None, 'customer': None, 'product': None, 
        'euro': None, 'kg': None, 'cartons': None, 'date': None
    }
    
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
    
    # Fallback
    for col in cols:
        if any(guesses.values()) and col in guesses.values(): continue
        if not guesses['date'] and pd.api.types.is_datetime64_any_dtype(df[col]):
            guesses['date'] = col
            continue

    return guesses

# --- 3. SIDEBAR ---
st.sidebar.title("💎 Control Panel v18")
files, service = get_drive_files_list()
df_processed = None

# A. SELECT FILE
if files:
    file_map = {f['name']: f for f in files}
    file_list = list(file_map.keys())
    
    target_file = "From_Order_to_Invoice"
    default_index = 0
    for i, fname in enumerate(file_list):
        if target_file.lower() in fname.lower():
            default_index = i
            break
            
    sel_file_name = st.sidebar.selectbox("1. File Sorgente", file_list, index=default_index)
    selected_file_obj = file_map[sel_file_name]
    
    with st.spinner('Loading & Protecting...'):
        df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
        if df_raw is not None:
            df_processed = smart_analyze_and_clean(df_raw)
else:
    st.error("Nessun file trovato.")

# B. MAPPATURA
col_entity, col_customer, col_prod, col_euro, col_kg, col_cartons, col_data = [None]*7

if df_processed is not None:
    guesses = guess_column_role(df_processed)
    all_cols = df_processed.columns.tolist()

    st.sidebar.subheader("2. Mappatura Campi")
    
    def set_idx(guess, options): return options.index(guess) if guess in options else 0

    with st.sidebar.expander("Verifica Colonne", expanded=True):
        col_entity = st.selectbox("Entità", all_cols, index=set_idx(guesses['entity'], all_cols))
        col_customer = st.selectbox("Cliente (Fatturazione)", all_cols, index=set_idx(guesses['customer'], all_cols), help="Cerca: Descr_Cliente_Fat")
        col_prod = st.selectbox("Prodotto", all_cols, index=set_idx(guesses['product'], all_cols))
        col_euro = st.selectbox("Valore (€)", all_cols, index=set_idx(guesses['euro'], all_cols), help="Importo_Netto_TotRiga")
        col_kg = st.selectbox("Peso (Kg)", all_cols, index=set_idx(guesses['kg'], all_cols), help="Peso_Netto_TotRiga")
        col_cartons = st.selectbox("Cartoni (Qty)", all_cols, index=set_idx(guesses['cartons'], all_cols), help="Qta_Cartoni_Ordinato")
        col_data = st.selectbox("Data", all_cols, index=set_idx(guesses['date'], all_cols), help="Data_Ordine")

    # C. FILTRI STANDARD
    st.sidebar.markdown("---")
    st.sidebar.subheader("3. Filtri Base")
    
    df_global = df_processed.copy()
    
    # ENTITÀ
    if col_entity:
        ents = sorted(df_global[col_entity].astype(str).unique())
        idx_e = ents.index('EITA') if 'EITA' in ents else 0
        sel_ent = st.sidebar.selectbox("Filtra Entità", ents, index=idx_e)
        df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

    # DATA
    if col_data:
        def_start = datetime.date(2026, 1, 1)
        def_end = datetime.date(2026, 1, 31)
        
        d_start, d_end = st.sidebar.date_input("Periodo Analisi", [def_start, def_end], format="DD/MM/YYYY")
        
        df_global = df_global[
            (df_global[col_data].dt.date >= d_start) & 
            (df_global[col_data].dt.date <= d_end)
        ]

    # CLIENTE (Filtro Base)
    if col_customer:
        custs = sorted(df_global[col_customer].astype(str).unique())
        sel_custs = st.sidebar.multiselect("Clienti (Rapido)", custs)
        if sel_custs:
            df_global = df_global[df_global[col_customer].astype(str).isin(sel_custs)]

    # D. FILTRI AVANZATI (SAFE)
    st.sidebar.markdown("---")
    st.sidebar.subheader("4. Filtri Avanzati")
    
    cols_to_exclude = [col_euro, col_kg, col_cartons, col_data]
    possible_filters = [c for c in all_cols if c not in cols_to_exclude]
    filters_selected = st.sidebar.multiselect("Aggiungi criterio di filtro:", possible_filters)
    
    for f_col in filters_selected:
        unique_vals_count = df_global[f_col].nunique()
        if unique_vals_count > 1000:
            search_query = st.sidebar.text_input(f"Cerca in {f_col}", key=f"search_{f_col}")
            if search_query:
                df_global = df_global[df_global[f_col].astype(str).str.contains(search_query, case=False, na=False)]
        else:
            unique_vals = sorted(df_global[f_col].astype(str).unique())
            sel_vals = st.sidebar.multiselect(f"Seleziona {f_col}", unique_vals, key=f"filter_{f_col}")
            if sel_vals:
                df_global = df_global[df_global[f_col].astype(str).isin(sel_vals)]


# --- 4. DASHBOARD BODY ---
st.title(f"📊 Report: {sel_ent if 'sel_ent' in locals() else 'Generale'}")

if df_processed is not None and not df_global.empty:

    # --- FASE CRITICA: PULIZIA E CASTING DEI DATI PRIMA DEI CALCOLI ---
    # Questa sezione trasforma tutto in numeri puri. Se esplode qui, non è colpa dei grafici.
    try:
        # Funzione helper per pulire valuta e numeri italiani
        def clean_currency(series):
            return pd.to_numeric(
                series.astype(str).str.replace('€', '').str.replace(' ', '').str.replace('.', '').str.replace(',', '.'),
                errors='coerce'
            ).fillna(0)

        # Sovrascriviamo le colonne nel dataframe globale con versioni sicure
        df_global[col_euro] = clean_currency(df_global[col_euro])
        df_global[col_kg] = clean_currency(df_global[col_kg])
        df_global[col_cartons] = clean_currency(df_global[col_cartons])
        
        # Forziamo cliente e prodotto a stringa (evita errori se sono numeri)
        if col_customer:
            df_global[col_customer] = df_global[col_customer].astype(str).fillna("-")
        if col_prod:
            df_global[col_prod] = df_global[col_prod].astype(str).fillna("-")

    except Exception as e:
        st.error(f"Errore nella pulizia dati preliminare: {e}")
        st.stop() # Ferma tutto se la pulizia base fallisce

    # --- KPI MACRO ---
    kpi_euro = df_global[col_euro].sum()
    kpi_kg = df_global[col_kg].sum()
    
    col_ord_num = next((c for c in df_global.columns if "Numero_Ordine" in c), None)
    kpi_orders = df_global[col_ord_num].nunique() if col_ord_num else len(df_global)
    lbl_orders = "N° Ordini" if col_ord_num else "N° Righe"
    
    # Top Cliente
    if col_customer:
        top_client_row = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
        top_client_name = top_client_row.index[0] if not top_client_row.empty else "-"
        top_client_val = top_client_row.values[0] if not top_client_row.empty else 0
    else:
        top_client_name, top_client_val = "-", 0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("1. Fatturato Totale", f"€ {kpi_euro:,.2f}")
    c2.metric("2. Quantità Totale", f"{kpi_kg:,.0f} Kg")
    c3.metric(f"3. {lbl_orders}", f"{kpi_orders:,}")
    c4.metric("4. Top Cliente", top_client_name[:18] + '..' if len(str(top_client_name))>18 else str(top_client_name), f"€ {top_client_val:,.0f}")

    st.markdown("---")
    
    # SEZIONE DRILL DOWN
    st.subheader("🔍 Analisi Dettaglio Cliente/Prodotto")
    
    col_left, col_right = st.columns([1, 2])
    
    # PREPARAZIONE DATI
    if col_customer:
        try:
            top_cust_list = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False)
            total_euro_all = df_global[col_euro].sum()
            
            options = ["TUTTI I CLIENTI"] + top_cust_list.index.tolist()
            
            with col_left:
                st.markdown("#### Seleziona Analisi")
                st.info("💡 Digita il nome per cercare")
                
                sel_target_cust = st.selectbox(
                    "Cerca Cliente (Ord. per Fatturato):", 
                    options,
                    format_func=lambda x: f"{x} (€ {total_euro_all:,.0f})" if x == "TUTTI I CLIENTI" else f"{x} (€ {top_cust_list[x]:,.0f})"
                )
                
                # DATASET TARGET
                if sel_target_cust == "TUTTI I CLIENTI":
                    df_target = df_global 
                    chart_title_suffix = "TUTTI I CLIENTI"
                else:
                    df_target = df_global[df_global[col_customer] == sel_target_cust]
                    chart_title_suffix = sel_target_cust

                # GRAFICO
                if not df_target.empty:
                    st.write("") 
                    chart_type = st.radio("Tipo Visualizzazione:", ["Barre", "Torta", "Donut"], horizontal=True, label_visibility="collapsed")
                    
                    # Aggregazione
                    prod_chart_data = df_target.groupby(col_prod).agg({
                        col_euro: 'sum',
                        col_kg: 'sum',
                        col_cartons: 'sum'
                    }).reset_index().sort_values(col_euro, ascending=False).head(10)
                    
                    if chart_type == "Barre":
                        fig = px.bar(
                            prod_chart_data, 
                            x=col_euro, 
                            y=col_prod, 
                            orientation='h',
                            title=f"Top 10 Prodotti ({chart_title_suffix})",
                            text_auto='.2s',
                            hover_data={col_euro: ':,.2f', col_kg: ':,.0f', col_cartons: ':,.0f'}
                        )
                        fig.update_layout(
                            height=500, 
                            yaxis=dict(autorange="reversed"),
                            margin=dict(l=0,r=0,t=30,b=0),
                            xaxis_title="Fatturato (€)",
                            yaxis_title=None
                        )
                        fig.update_traces(marker_color='#004e92')
                    
                    elif chart_type in ["Torta", "Donut"]:
                        hole_size = 0.4 if chart_type == "Donut" else 0
                        fig = px.pie(
                            prod_chart_data,
                            values=col_euro,
                            names=col_prod,
                            title=f"Top 10 Prodotti ({chart_title_suffix})",
                            hole=hole_size,
                            hover_data={col_kg: ':,.0f', col_cartons: ':,.0f'}
                        )
                        fig.update_traces(
                            textposition='outside',
                            textinfo='percent+label',
                            textfont_size=13
                        )
                        fig.update_layout(
                            height=500,
                            margin=dict(l=0,r=0,t=30,b=0),
                            showlegend=False
                        )

                    st.plotly_chart(fig, use_container_width=True)

            with col_right:
                if not df_target.empty:
                    
                    # CASO 1: TUTTI -> ESPLOSIONE
                    if sel_target_cust == "TUTTI I CLIENTI":
                        st.markdown(f"#### 💥 Esplosione Prodotto (Chi lo compra?)")
                        
                        all_prods_sorted = df_target.groupby(col_prod)[col_euro].sum().sort_values(ascending=False)
                        
                        target_prod = st.selectbox(
                            "Seleziona Prodotto per Dettaglio Clienti:", 
                            all_prods_sorted.index.tolist(),
                            format_func=lambda x: f"{x} (Tot: € {all_prods_sorted[x]:,.0f})"
                        )
                        
                        if target_prod:
                            df_prod_specific = df_target[df_target[col_prod] == target_prod]
                            
                            cust_breakdown = df_prod_specific.groupby(col_customer).agg({
                                col_cartons: 'sum',
                                col_kg: 'sum',
                                col_euro: 'sum'
                            }).reset_index().sort_values(col_euro, ascending=False)
                            
                            prod_tot_val = cust_breakdown[col_euro].sum()
                            cust_breakdown['% su Tot Prodotto'] = (cust_breakdown[col_euro] / prod_tot_val * 100)

                            st.dataframe(
                                cust_breakdown,
                                column_config={
                                    col_customer: "Cliente",
                                    col_cartons: st.column_config.NumberColumn("Cartoni", format="%.0f"),
                                    col_kg: st.column_config.NumberColumn("Kg", format="%.0f"),
                                    col_euro: st.column_config.NumberColumn("Spesa (€)", format="€ %.2f"),
                                    "% su Tot Prodotto": st.column_config.ProgressColumn("%", format="%.1f%%", min_value=0, max_value=100)
                                },
                                hide_index=True,
                                use_container_width=True,
                                height=500
                            )

                    # CASO 2: SINGOLO -> LISTA ACQUISTI
                    else:
                        st.markdown(f"#### Dettaglio Acquisti: **{chart_title_suffix}**")
                        
                        prod_stats = df_target.groupby(col_prod).agg({
                            col_cartons: 'sum',
                            col_kg: 'sum',
                            col_euro: 'sum'
                        }).reset_index().sort_values(col_euro, ascending=False)
                        
                        tot_val = prod_stats[col_euro].sum()
                        prod_stats['%'] = (prod_stats[col_euro] / tot_val * 100)
                        
                        st.dataframe(
                            prod_stats,
                            column_config={
                                col_prod: "Prodotto",
                                col_cartons: st.column_config.NumberColumn("Cartoni", format="%.0f"),
                                col_kg: st.column_config.NumberColumn("Kg", format="%.0f"),
                                col_euro: st.column_config.NumberColumn("Valore (€)", format="€ %.2f"),
                                "%": st.column_config.ProgressColumn("Peso %", format="%.1f%%", min_value=0, max_value=100)
                            },
                            hide_index=True,
                            use_container_width=True,
                            height=500
                        )
        except Exception as e:
            st.warning(f"Si è verificato un errore nel calcolo dei dettagli: {e}")

elif df_processed is not None:
    st.warning("Nessun dato trovato nel periodo selezionato.")