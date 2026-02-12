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

# --- 1. CONFIGURAZIONE & STILE EXTREME ---
st.set_page_config(
    page_title="EITA Analytics Pro v23",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS Custom: Glassmorphism, Responsive Grid perfette, Auto-Theme (Dark/Light compatibile)
st.markdown("""
<style>
    /* Rimuove i padding eccessivi di Streamlit per sfruttare tutto lo schermo */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 3rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 1600px;
    }

    /* --- CUSTOM KPI CARDS (CSS GRID) --- */
    /* Questa griglia impedisce lo sbordamento e si adatta da sola a PC, Tablet e Mobile */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 1.2rem;
        margin-bottom: 2rem;
    }

    /* Stile Vetro (Glassmorphism) compatibile con Light e Dark Mode */
    .kpi-card {
        background: rgba(130, 150, 200, 0.1);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(130, 150, 200, 0.2);
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.05);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    
    .kpi-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.1);
        border: 1px solid rgba(130, 150, 200, 0.4);
    }
    
    /* Decoro laterale moderno */
    .kpi-card::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        height: 100%;
        width: 6px;
        background: linear-gradient(180deg, #00c6ff, #0072ff);
        border-radius: 16px 0 0 16px;
    }

    .kpi-title {
        font-size: 0.9rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
        opacity: 0.8; /* Si adatta al testo base di Streamlit */
        margin-bottom: 0.5rem;
    }

    .kpi-value {
        font-size: 2rem;
        font-weight: 800;
        line-height: 1.2;
    }
    
    .kpi-subtitle {
        font-size: 0.8rem;
        opacity: 0.6;
        margin-top: 0.3rem;
    }

    /* Ottimizzazione UI Mobile Generale */
    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.8rem !important;
            padding-right: 0.8rem !important;
            padding-top: 1rem !important;
        }
        .kpi-grid { gap: 0.8rem; }
        .kpi-value { font-size: 1.6rem; }
    }
</style>
""", unsafe_allow_html=True)

# --- 2. MOTORE DATI (STABILE DALLA v16) ---
@st.cache_data(ttl=300)
def get_drive_files_list():
    try:
        if "google_cloud" not in st.secrets:
            return None, "Secrets mancanti"
        creds = service_account.Credentials.from_service_account_info(st.secrets["google_cloud"])
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["folder_id"]
        
        query = f"'{folder_id}' in parents and (mimeType contains 'spreadsheet' or mimeType contains 'csv' or name contains '.xlsx') and trashed = false"
        results = service.files().list(q=query, fields="files(id, name, modifiedTime, size)", orderBy="modifiedTime desc", pageSize=50).execute()
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
        while not done: _, done = downloader.next_chunk()
        fh.seek(0)
        try: df = pd.read_excel(fh)
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
        'customer': ['Decr_Cliente_Fat', 'Descr_Cliente_Fat', 'Descr_Cliente_Dest'],
        'product': ['Descr_Articolo']
    }
    for role, targets in golden_rules.items():
        for t in targets:
            if t in cols:
                guesses[role] = t
                break
    return guesses

# --- 3. SIDEBAR ---
st.sidebar.title("🚀 EITA Dashboard")
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
    
    with st.spinner('Analisi e Ottimizzazione Modello Dati...'):
        df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'], service)
        if df_raw is not None:
            df_processed = smart_analyze_and_clean(df_raw)
else:
    st.error("Nessun file trovato.")

if df_processed is not None:
    guesses = guess_column_role(df_processed)
    all_cols = df_processed.columns.tolist()

    with st.sidebar.expander("⚙️ Mappatura Colonne", expanded=False):
        def set_idx(guess, options): return options.index(guess) if guess in options else 0
        col_entity = st.selectbox("Entità", all_cols, index=set_idx(guesses['entity'], all_cols))
        col_customer = st.selectbox("Cliente (Fatturazione)", all_cols, index=set_idx(guesses['customer'], all_cols), help="Verrà pre-selezionato Decr_Cliente_Fat")
        col_prod = st.selectbox("Prodotto", all_cols, index=set_idx(guesses['product'], all_cols))
        col_euro = st.selectbox("Valore (€)", all_cols, index=set_idx(guesses['euro'], all_cols))
        col_kg = st.selectbox("Peso (Kg)", all_cols, index=set_idx(guesses['kg'], all_cols))
        col_cartons = st.selectbox("Cartoni (Qty)", all_cols, index=set_idx(guesses['cartons'], all_cols))
        col_data = st.selectbox("Data Riferimento", all_cols, index=set_idx(guesses['date'], all_cols))

    st.sidebar.markdown("### 🔍 Filtri Rapidi")
    df_global = df_processed.copy()
    
    if col_entity:
        ents = sorted(df_global[col_entity].astype(str).unique())
        idx_e = ents.index('EITA') if 'EITA' in ents else 0
        sel_ent = st.sidebar.selectbox("Società / Entità", ents, index=idx_e)
        df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

    if col_data:
        def_start, def_end = datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)
        d_start, d_end = st.sidebar.date_input("Periodo di Analisi", [def_start, def_end], format="DD/MM/YYYY")
        df_global = df_global[(df_global[col_data].dt.date >= d_start) & (df_global[col_data].dt.date <= d_end)]

    st.sidebar.markdown("### 🎛️ Filtri Avanzati")
    possible_filters = [c for c in all_cols if c not in [col_euro, col_kg, col_cartons, col_data, col_entity]]
    filters_selected = st.sidebar.multiselect("Aggiungi filtri (es. Vettore, Regione):", possible_filters)
    for f_col in filters_selected:
        unique_vals = sorted(df_global[f_col].astype(str).unique())
        sel_vals = st.sidebar.multiselect(f"Seleziona in {f_col}", unique_vals)
        if sel_vals:
            df_global = df_global[df_global[f_col].astype(str).isin(sel_vals)]

# --- 4. DASHBOARD BODY ---
st.title(f"Performance Overview: {sel_ent if 'sel_ent' in locals() else 'Global'}")

if df_processed is not None and not df_global.empty:
    
    # --- CALCOLI KPI ---
    tot_euro = df_global[col_euro].sum()
    tot_kg = df_global[col_kg].sum()
    col_ord_num = next((c for c in df_global.columns if "Numero_Ordine" in c), None)
    tot_orders = df_global[col_ord_num].nunique() if col_ord_num else len(df_global)
    
    top_c_data = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
    top_name = top_c_data.index[0] if not top_c_data.empty else "-"
    top_val = top_c_data.values[0] if not top_c_data.empty else 0
    short_top_name = top_name[:20]+".." if len(str(top_name))>20 else str(top_name)

    # --- INIEZIONE CUSTOM HTML KPI (Perfetto per ogni tema e schermo) ---
    kpi_html = f"""
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-title">💰 Fatturato Netto</div>
            <div class="kpi-value">€ {tot_euro:,.0f}</div>
            <div class="kpi-subtitle">Totale nel periodo selezionato</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">⚖️ Volume Totale</div>
            <div class="kpi-value">{tot_kg:,.0f} Kg</div>
            <div class="kpi-subtitle">Peso netto cumulato</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">📦 Ordini Elaborati</div>
            <div class="kpi-value">{tot_orders:,}</div>
            <div class="kpi-subtitle">Transazioni uniche / Righe</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">👑 Top Customer</div>
            <div class="kpi-value">{short_top_name}</div>
            <div class="kpi-subtitle">Valore: € {top_val:,.0f}</div>
        </div>
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)
    
    # --- SEZIONE GRAFICI E DETTAGLI ---
    st.markdown("### 🧭 Analisi Esplorativa (Drill-Down)")
    
    col_l, col_r = st.columns([1.2, 1.8], gap="large")
    
    cust_totals = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False)
    total_val_period = df_global[col_euro].sum()
    options = ["🌍 TUTTI I CLIENTI"] + cust_totals.index.tolist()
    
    with col_l:
        sel_target = st.selectbox(
            "📍 Focus Analisi:", 
            options,
            format_func=lambda x: f"{x} (Fatturato: € {total_val_period:,.0f})" if "TUTTI" in x else f"{x} (€ {cust_totals[x]:,.0f})"
        )
        
        df_target = df_global if "TUTTI" in sel_target else df_global[df_global[col_customer] == sel_target]
        
        if not df_target.empty:
            chart_type = st.radio("Seleziona Rendering Grafico:", ["📊 Barre 3D", "🍩 Donut Dinamico"], horizontal=True)
            
            prod_agg = df_target.groupby(col_prod).agg({col_euro: 'sum', col_kg: 'sum', col_cartons: 'sum'}).reset_index().sort_values(col_euro, ascending=False).head(10)
            
            if chart_type == "📊 Barre 3D":
                # GRAFICO A BARRE CUSTOM 3D EFFECT
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    y=prod_agg[col_prod],
                    x=prod_agg[col_euro],
                    orientation='h',
                    marker=dict(
                        color=prod_agg[col_euro],
                        colorscale='Blues',
                        line=dict(color='rgba(255, 255, 255, 0.5)', width=2) # Effetto luce sui bordi
                    ),
                    text=prod_agg[col_euro].apply(lambda x: f"€ {x:,.0f}"),
                    textposition='inside',
                    insidetextanchor='middle',
                    hovertemplate="<b>%{y}</b><br>Fatturato: € %{x:,.2f}<extra></extra>"
                ))
                fig.update_layout(
                    height=500,
                    yaxis=dict(autorange="reversed", showgrid=False),
                    xaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)'),
                    margin=dict(l=0,r=0,t=10,b=10),
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(size=12)
                )
            
            else:
                # GRAFICO DONUT 3D EFFECT
                pull_array = [0.08] + [0] * (len(prod_agg) - 1) # Esplode solo il primo
                fig = go.Figure(data=[go.Pie(
                    labels=prod_agg[col_prod],
                    values=prod_agg[col_euro],
                    hole=0.45,
                    pull=pull_array,
                    marker=dict(
                        colors=px.colors.qualitative.Pastel,
                        line=dict(color='rgba(255, 255, 255, 0.8)', width=3) # Bordo netto per profondità
                    ),
                    textinfo='percent+label',
                    textposition='outside',
                    hovertemplate="<b>%{label}</b><br>Valore: € %{value:,.2f}<br>Quota: %{percent}<extra></extra>"
                )])
                fig.update_layout(
                    height=500,
                    margin=dict(l=20,r=20,t=20,b=20),
                    showlegend=False,
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                )
            
            st.plotly_chart(fig, use_container_width=True)

    with col_r:
        if "TUTTI" in sel_target:
            st.markdown("#### 💥 Esplosione Prodotto")
            st.caption("Seleziona un prodotto per vedere quali clienti lo acquistano.")
            all_p_sorted = df_target.groupby(col_prod)[col_euro].sum().sort_values(ascending=False)
            sel_p = st.selectbox("Catalogo Prodotti (Top Selling in cima):", all_p_sorted.index.tolist(), format_func=lambda x: f"{x} (Incasso Tot: € {all_p_sorted[x]:,.0f})")
            
            if sel_p:
                df_ps = df_target[df_target[col_prod] == sel_p]
                cb = df_ps.groupby(col_customer).agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'}).reset_index().sort_values(col_euro, ascending=False)
                st.dataframe(
                    cb, 
                    column_config={
                        col_customer: st.column_config.TextColumn("👤 Ragione Sociale Cliente", width="large"),
                        col_cartons: st.column_config.NumberColumn("📦 CT", format="%d"),
                        col_kg: st.column_config.NumberColumn("⚖️ Kg", format="%d"),
                        col_euro: st.column_config.NumberColumn("💰 Valore", format="€ %.2f")
                    }, 
                    hide_index=True, use_container_width=True, height=520
                )
        else:
            st.markdown(f"#### 🧾 Dettaglio Acquisti")
            st.caption(f"Portafoglio ordini per: {sel_target}")
            ps = df_target.groupby(col_prod).agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'}).reset_index().sort_values(col_euro, ascending=False)
            st.dataframe(
                ps, 
                column_config={
                    col_prod: st.column_config.TextColumn("🏷️ Articolo / Prodotto", width="large"),
                    col_cartons: st.column_config.NumberColumn("📦 CT", format="%d"),
                    col_kg: st.column_config.NumberColumn("⚖️ Kg", format="%d"),
                    col_euro: st.column_config.NumberColumn("💰 Valore", format="€ %.2f")
                }, 
                hide_index=True, use_container_width=True, height=520
            )

elif df_processed is not None:
    st.info("Nessun dato trovato. Modifica i filtri o il periodo selezionato.")
