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

# --- 1. CONFIGURAZIONE & STILE EXTREME (v25) ---
st.set_page_config(
    page_title="EITA Analytics Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS Custom: Glassmorphism & Responsive Layout
st.markdown("""
<style>
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 3rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 1600px;
    }

    /* KPI GRID RESPONSIVA */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 1.2rem;
        margin-bottom: 2rem;
    }

    /* GLASSMORPHISM CARD */
    .kpi-card {
        background: rgba(130, 150, 200, 0.1);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(130, 150, 200, 0.2);
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.05);
        transition: transform 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    
    .kpi-card:hover { transform: translateY(-5px); box-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.1); }
    .kpi-card::before {
        content: ""; position: absolute; left: 0; top: 0; height: 100%; width: 6px;
        background: linear-gradient(180deg, #00c6ff, #0072ff); border-radius: 16px 0 0 16px;
    }

    /* Variazione colore per pagina Promo */
    .kpi-card.promo-card::before {
        background: linear-gradient(180deg, #ff9a9e, #fecfef);
    }

    .kpi-title { font-size: 0.9rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; opacity: 0.8; margin-bottom: 0.5rem; }
    .kpi-value { font-size: 2rem; font-weight: 800; line-height: 1.2; }
    .kpi-subtitle { font-size: 0.8rem; opacity: 0.6; margin-top: 0.3rem; }

    @media (max-width: 768px) {
        .block-container { padding-left: 0.8rem !important; padding-right: 0.8rem !important; }
        .kpi-value { font-size: 1.6rem; }
    }
</style>
""", unsafe_allow_html=True)

# --- 2. MOTORE DATI ---
@st.cache_data(ttl=300)
def get_drive_files_list():
    try:
        if "google_cloud" not in st.secrets: return None, "Secrets mancanti"
        creds = service_account.Credentials.from_service_account_info(st.secrets["google_cloud"])
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["folder_id"]
        query = f"'{folder_id}' in parents and (mimeType contains 'spreadsheet' or name contains '.xlsx' or name contains '.csv') and trashed = false"
        results = service.files().list(q=query, fields="files(id, name, modifiedTime, size)", orderBy="modifiedTime desc").execute()
        return results.get('files', []), service
    except Exception as e: return None, str(e)

@st.cache_data(show_spinner=False) 
def load_dataset(file_id, modified_time, _service):
    try:
        request = _service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0)
        try: return pd.read_excel(fh)
        except: return pd.read_csv(fh)
    except: return None

def smart_analyze_and_clean(df_in, page_type="Sales"):
    df = df_in.copy()
    
    if page_type == "Sales":
        target_numeric_cols = ['Importo_Netto_TotRiga', 'Peso_Netto_TotRiga', 'Qta_Cartoni_Ordinato', 'Prezzo_Netto']
        target_date_cols = ['Data_Ordine', 'Data_Fattura', 'Data_Consegna']
    else:
        target_numeric_cols = ['Quantità prevista', 'Quantità ordinata', 'Importo sconto', 'Sconto promo']
        target_date_cols = ['Sell in da', 'Sell in a', 'Sell out da', 'Sell out a']

    for col in df.columns:
        if col in ['Numero_Pallet', 'Sovrapponibile', 'COMPANY']: continue 
        
        sample = df[col].dropna().astype(str).head(50).tolist()
        if not sample: continue

        # Pulizia Date
        if any(t in col for t in target_date_cols) or any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
            
        # Pulizia Numeri
        is_target_numeric = any(t in col for t in target_numeric_cols)
        if is_target_numeric or (df[col].dtype == 'object' and any(c.isdigit() for s in sample for c in s) and "Data" not in col and "Sell" not in col):
            try:
                clean = df[col].astype(str).str.replace('€', '').str.replace('%', '').str.replace(' ', '')
                if clean.str.contains(',', regex=False).any():
                    clean = clean.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df[col] = pd.to_numeric(clean, errors='coerce').fillna(0)
            except: pass
            
    return df

def guess_column_role(df, page_type="Sales"):
    cols = df.columns
    guesses = {}
    
    if page_type == "Sales":
        guesses = {'entity': None, 'customer': None, 'product': None, 'euro': None, 'kg': None, 'cartons': None, 'date': None}
        golden_rules = {
            'euro': ['Importo_Netto_TotRiga'], 'kg': ['Peso_Netto_TotRiga'], 'cartons': ['Qta_Cartoni_Ordinato'],
            'date': ['Data_Ordine', 'Data_Fattura'], 'entity': ['Entity'], 'customer': ['Decr_Cliente_Fat', 'Descr_Cliente_Fat'], 'product': ['Descr_Articolo']
        }
    else:
        guesses = {'promo_id': None, 'promo_desc': None, 'customer': None, 'product': None, 'qty_forecast': None, 'qty_actual': None, 'start_date': None, 'status': None, 'division': None, 'type': None}
        golden_rules = {
            'promo_id': ['Numero Promozione'], 'promo_desc': ['Descrizione Promozione', 'Riferimento'],
            'customer': ['Descrizione Cliente'], 'product': ['Descrizione Prodotto'],
            'qty_forecast': ['Quantità prevista'], 'qty_actual': ['Quantità ordinata'],
            'start_date': ['Sell in da'], 'status': ['Stato'], 'division': ['Division'], 'type': ['Tipo promo']
        }

    for role, targets in golden_rules.items():
        for t in targets:
            if t in cols:
                guesses[role] = t
                break
    return guesses

# --- 3. NAVIGAZIONE ---
st.sidebar.title("🎮 Menu Principale")
page = st.sidebar.radio("Vai alla sezione:", ["📊 Vendite & Fatturazione", "🎁 Analisi Customer Promo"])

files, service = get_drive_files_list()

# =====================================================================
# PAGINA 1: VENDITE E FATTURAZIONE
# =====================================================================
if page == "📊 Vendite & Fatturazione":
    st.title("Performance Sales & Invoicing")
    df_processed = None
    
    if files:
        file_map = {f['name']: f for f in files}
        target_file = "From_Order_to_Invoice"
        file_list = list(file_map.keys())
        default_index = next((i for i, f in enumerate(file_list) if target_file.lower() in f.lower()), 0)
        
        sel_file = st.sidebar.selectbox("File Sorgente", file_list, index=default_index)
        with st.spinner('Elaborazione dati...'):
            df_raw = load_dataset(file_map[sel_file]['id'], file_map[sel_file]['modifiedTime'], service)
            if df_raw is not None:
                df_processed = smart_analyze_and_clean(df_raw, "Sales")
                
        if df_processed is not None:
            guesses = guess_column_role(df_processed, "Sales")
            
            # FILTRI BARRA LATERALE
            st.sidebar.markdown("---")
            st.sidebar.subheader("Filtri Dashboard")
            df_global = df_processed.copy()
            
            col_ent = guesses['entity'] or 'Entity'
            if col_ent in df_global.columns:
                ents = sorted(df_global[col_ent].astype(str).unique())
                idx_e = ents.index('EITA') if 'EITA' in ents else 0
                sel_ent = st.sidebar.selectbox("Società", ents, index=idx_e)
                df_global = df_global[df_global[col_ent].astype(str) == sel_ent]

            col_data = guesses['date'] or 'Data_Ordine'
            if col_data in df_global.columns:
                d_start, d_end = st.sidebar.date_input("Periodo", [datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)], format="DD/MM/YYYY")
                df_global = df_global[(df_global[col_data].dt.date >= d_start) & (df_global[col_data].dt.date <= d_end)]

            # KPI CALCOLATI
            c_euro = guesses['euro'] or 'Importo_Netto_TotRiga'
            c_kg = guesses['kg'] or 'Peso_Netto_TotRiga'
            c_cust = guesses['customer'] or 'Decr_Cliente_Fat'
            c_prod = guesses['product'] or 'Descr_Articolo'
            c_cart = guesses['cartons'] or 'Qta_Cartoni_Ordinato'

            if not df_global.empty:
                # Cast esplicito a float per evitare ValueError nei KPI
                tot_euro = float(df_global[c_euro].sum()) if c_euro in df_global.columns else 0.0
                tot_kg = float(df_global[c_kg].sum()) if c_kg in df_global.columns else 0.0
                tot_orders = int(df_global['Numero_Ordine'].nunique()) if 'Numero_Ordine' in df_global.columns else len(df_global)
                
                top_c = df_global.groupby(c_cust)[c_euro].sum().sort_values(ascending=False).head(1) if c_cust in df_global.columns else pd.Series()
                t_name = top_c.index[0] if not top_c.empty else "-"
                t_val = float(top_c.values[0]) if not top_c.empty else 0.0

                kpi_html = f"""
                <div class="kpi-grid">
                    <div class="kpi-card">
                        <div class="kpi-title">💰 Fatturato</div>
                        <div class="kpi-value">€ {tot_euro:,.0f}</div>
                        <div class="kpi-subtitle">Periodo selezionato</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-title">⚖️ Volume</div>
                        <div class="kpi-value">{tot_kg:,.0f} Kg</div>
                        <div class="kpi-subtitle">Peso netto totale</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-title">📦 Ordini</div>
                        <div class="kpi-value">{tot_orders:,}</div>
                        <div class="kpi-subtitle">Transazioni / Righe</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-title">👑 Top Cliente</div>
                        <div class="kpi-value">{str(t_name)[:18]}..</div>
                        <div class="kpi-subtitle">Fatturato: € {t_val:,.0f}</div>
                    </div>
                </div>
                """
                st.markdown(kpi_html, unsafe_allow_html=True)

                # DRILL DOWN
                st.divider()
                st.subheader("🧭 Analisi Esplorativa")
                col_l, col_r = st.columns([1.2, 1.8], gap="large")
                
                cust_totals = df_global.groupby(c_cust)[c_euro].sum().sort_values(ascending=False)
                sel_target = col_l.selectbox("Focus su:", ["🌍 TUTTI I CLIENTI"] + cust_totals.index.tolist())
                
                df_target = df_global if "TUTTI" in sel_target else df_global[df_global[c_cust] == sel_target]
                
                with col_l:
                    chart_type = st.radio("Stile Grafico:", ["📊 Barre", "🍩 Donut"], horizontal=True)
                    prod_agg = df_target.groupby(c_prod).agg({c_euro: 'sum', c_kg: 'sum', c_cart: 'sum'}).reset_index().sort_values(c_euro, ascending=False).head(10)
                    
                    if chart_type == "📊 Barre":
                        fig = go.Figure(go.Bar(y=prod_agg[c_prod], x=prod_agg[c_euro], orientation='h', marker=dict(color=prod_agg[c_euro], colorscale='Blues')))
                        fig.update_layout(height=450, yaxis=dict(autorange="reversed"), margin=dict(l=0,r=0,t=10,b=10), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        fig = go.Figure(go.Pie(labels=prod_agg[c_prod], values=prod_agg[c_euro], hole=0.45, pull=[0.1]+[0]*9))
                        fig.update_traces(textposition='outside', textinfo='percent+label')
                        fig.update_layout(height=450, showlegend=False, paper_bgcolor='rgba(0,0,0,0)')
                        st.plotly_chart(fig, use_container_width=True)

                with col_r:
                    if "TUTTI" in sel_target:
                        st.markdown("#### 💥 Esplosione Prodotto")
                        all_p = df_target.groupby(c_prod)[c_euro].sum().sort_values(ascending=False)
                        sel_p = st.selectbox("Seleziona Prodotto:", all_p.index.tolist())
                        if sel_p:
                            df_p = df_target[df_target[c_prod] == sel_p]
                            res = df_p.groupby(c_cust).agg({c_cart:'sum', c_kg:'sum', c_euro:'sum'}).reset_index().sort_values(c_euro, ascending=False)
                            st.dataframe(res, use_container_width=True, hide_index=True)
                    else:
                        st.markdown(f"#### 🧾 Dettaglio Acquisti: {sel_target}")
                        res = df_target.groupby(c_prod).agg({c_cart:'sum', c_kg:'sum', c_euro:'sum'}).reset_index().sort_values(c_euro, ascending=False)
                        st.dataframe(res, use_container_width=True, hide_index=True)


# =====================================================================
# PAGINA 2: CUSTOMER PROMO
# =====================================================================
else:
    st.title("🎁 Analisi Customer Promo")
    df_promo_processed = None
    
    if files:
        file_map = {f['name']: f for f in files}
        target_file_promo = "Customer_Promo"
        file_list = list(file_map.keys())
        default_idx_promo = next((i for i, f in enumerate(file_list) if target_file_promo.lower() in f.lower()), 0)
        
        sel_promo_file = st.sidebar.selectbox("File Sorgente", file_list, index=default_idx_promo)
        with st.spinner('Elaborazione dati promozionali...'):
            df_promo_raw = load_dataset(file_map[sel_promo_file]['id'], file_map[sel_promo_file]['modifiedTime'], service)
            if df_promo_raw is not None:
                df_promo_processed = smart_analyze_and_clean(df_promo_raw, "Promo")
    
    if df_promo_processed is not None:
        guesses_p = guess_column_role(df_promo_processed, "Promo")
        all_cols_p = df_promo_processed.columns.tolist()

        # MAPPATURA (Nascosta in expander per pulizia)
        with st.sidebar.expander("⚙️ Verifica Colonne Promo", expanded=False):
            def set_idx(guess, options): return options.index(guess) if guess in options else 0
            p_div = st.selectbox("Division", all_cols_p, index=set_idx(guesses_p['division'], all_cols_p))
            p_status = st.selectbox("Stato", all_cols_p, index=set_idx(guesses_p['status'], all_cols_p))
            p_cust = st.selectbox("Cliente", all_cols_p, index=set_idx(guesses_p['customer'], all_cols_p))
            p_prod = st.selectbox("Prodotto", all_cols_p, index=set_idx(guesses_p['product'], all_cols_p))
            p_qty_f = st.selectbox("Q.tà Prevista", all_cols_p, index=set_idx(guesses_p['qty_forecast'], all_cols_p))
            p_qty_a = st.selectbox("Q.tà Ordinata", all_cols_p, index=set_idx(guesses_p['qty_actual'], all_cols_p))
            p_start = st.selectbox("Data Inizio (Sell in)", all_cols_p, index=set_idx(guesses_p['start_date'], all_cols_p))
            p_type = st.selectbox("Tipo Promo", all_cols_p, index=set_idx(guesses_p['type'], all_cols_p))

        st.sidebar.markdown("---")
        st.sidebar.subheader("Filtri Promo")
        
        df_pglobal = df_promo_processed.copy()

        # Filtro Division (Default 21)
        if p_div in df_pglobal.columns:
            divs = sorted(df_pglobal[p_div].dropna().unique().tolist())
            idx_div = divs.index(21) if 21 in divs else (divs.index('21') if '21' in divs else 0)
            sel_div = st.sidebar.selectbox("Division", divs, index=idx_div)
            df_pglobal = df_pglobal[df_pglobal[p_div] == sel_div]

        # Filtro Stato
        if p_status in df_pglobal.columns:
            stati = sorted(df_pglobal[p_status].dropna().unique().tolist())
            # Pre-seleziona lo stato '20' (Attiva) se esiste, altrimenti tutti
            default_stati = [20] if 20 in stati else ([str(20)] if str(20) in stati else stati)
            sel_stati = st.sidebar.multiselect("Stato Promozione", stati, default=default_stati)
            if sel_stati:
                df_pglobal = df_pglobal[df_pglobal[p_status].isin(sel_stati)]

        # Filtro Data
        if p_start in df_pglobal.columns and pd.api.types.is_datetime64_any_dtype(df_pglobal[p_start]):
            min_d, max_d = df_pglobal[p_start].min(), df_pglobal[p_start].max()
            if pd.notnull(min_d):
                d_start, d_end = st.sidebar.date_input("Periodo Sell-In", [min_d, max_d], min_value=min_d, max_value=max_d, format="DD/MM/YYYY")
                df_pglobal = df_pglobal[(df_pglobal[p_start].dt.date >= d_start) & (df_pglobal[p_start].dt.date <= d_end)]

        # Filtro Key Account
        if "Key Account" in df_pglobal.columns:
            kas = sorted(df_pglobal["Key Account"].dropna().astype(str).unique())
            sel_ka = st.sidebar.multiselect("Key Account", kas)
            if sel_ka:
                df_pglobal = df_pglobal[df_pglobal["Key Account"].astype(str).isin(sel_ka)]

        if not df_pglobal.empty:
            # CALCOLI KPI PROMO
            # Usiamo float() e int() per sicurezza anti-ValueError
            tot_promo_uniche = int(df_pglobal[guesses_p['promo_id']].nunique()) if guesses_p['promo_id'] in df_pglobal.columns else len(df_pglobal)
            tot_prevista = float(df_pglobal[p_qty_f].sum()) if p_qty_f in df_pglobal.columns else 0.0
            tot_ordinata = float(df_pglobal[p_qty_a].sum()) if p_qty_a in df_pglobal.columns else 0.0
            
            # Calcolo Hit Rate (Evita divisione per zero)
            hit_rate = (tot_ordinata / tot_prevista * 100) if tot_prevista > 0 else 0.0

            kpi_promo_html = f"""
            <div class="kpi-grid">
                <div class="kpi-card promo-card">
                    <div class="kpi-title">🎯 Promozioni Attive</div>
                    <div class="kpi-value">{tot_promo_uniche}</div>
                    <div class="kpi-subtitle">N° iniziative nel periodo</div>
                </div>
                <div class="kpi-card promo-card">
                    <div class="kpi-title">📈 Forecast (Previsto)</div>
                    <div class="kpi-value">{tot_prevista:,.0f}</div>
                    <div class="kpi-subtitle">Quantità totale stimata</div>
                </div>
                <div class="kpi-card promo-card">
                    <div class="kpi-title">🛒 Actual (Ordinato)</div>
                    <div class="kpi-value">{tot_ordinata:,.0f}</div>
                    <div class="kpi-subtitle">Quantità effettiva ordinata</div>
                </div>
                <div class="kpi-card promo-card">
                    <div class="kpi-title">⚡ Hit Rate (Successo)</div>
                    <div class="kpi-value">{hit_rate:.1f}%</div>
                    <div class="kpi-subtitle">Ordinato / Previsto</div>
                </div>
            </div>
            """
            st.markdown(kpi_promo_html, unsafe_allow_html=True)

            st.divider()
            col_l, col_r = st.columns([1, 1])

            with col_l:
                st.subheader("Performance per Tipo Promo")
                if p_type in df_pglobal.columns:
                    # Raggruppa per tipo promo per confrontare Previsto e Ordinato
                    type_agg = df_pglobal.groupby(p_type).agg({p_qty_f: 'sum', p_qty_a: 'sum'}).reset_index()
                    
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=type_agg[p_type], y=type_agg[p_qty_f], name='Forecast (Previsto)', marker_color='#a8c0ff'))
                    fig.add_trace(go.Bar(x=type_agg[p_type], y=type_agg[p_qty_a], name='Actual (Ordinato)', marker_color='#3f2b96'))
                    fig.update_layout(barmode='group', height=400, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                    st.plotly_chart(fig, use_container_width=True)

            with col_r:
                st.subheader("Top Promozioni (per Volume)")
                promo_desc_col = guesses_p['promo_desc'] or 'Descrizione Promozione'
                if promo_desc_col in df_pglobal.columns:
                    top_promos = df_pglobal.groupby(promo_desc_col).agg({p_qty_a: 'sum'}).reset_index().sort_values(p_qty_a, ascending=False).head(8)
                    fig = px.bar(top_promos, y=promo_desc_col, x=p_qty_a, orientation='h', color=p_qty_a, color_continuous_scale='Purp')
                    fig.update_layout(height=400, yaxis=dict(autorange="reversed"), coloraxis_showscale=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig, use_container_width=True)

            st.subheader("📋 Dettaglio Iniziative Promozionali")
            
            # Colonne utili da mostrare nella tabella
            cols_to_show = [c for c in [guesses_p['promo_id'], promo_desc_col, p_cust, p_prod, p_start, p_qty_f, p_qty_a, 'Sconto promo'] if c in df_pglobal.columns]
            
            st.dataframe(
                df_pglobal[cols_to_show].sort_values(by=p_qty_a, ascending=False),
                column_config={
                    p_qty_f: st.column_config.NumberColumn("Forecast Qty", format="%.0f"),
                    p_qty_a: st.column_config.NumberColumn("Actual Qty", format="%.0f"),
                    p_start: st.column_config.DateColumn("Inizio Sell-In", format="DD/MM/YYYY")
                },
                hide_index=True, use_container_width=True, height=400
            )

        else:
            st.warning("Nessuna promozione trovata per i filtri selezionati.")


