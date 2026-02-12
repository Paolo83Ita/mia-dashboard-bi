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

# --- 1. CONFIGURAZIONE & STILE (v36.1 - Added Metrics to Detail) ---
st.set_page_config(
    page_title="EITA Analytics Pro v36.1",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 3rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 1600px;
    }
    [data-testid="stElementToolbar"] { display: none; }
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 1.2rem;
        margin-bottom: 2rem;
    }
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
        box-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.15);
        border: 1px solid rgba(130, 150, 200, 0.4);
    }
    .kpi-card::before {
        content: ""; position: absolute; left: 0; top: 0; height: 100%; width: 6px;
        background: linear-gradient(180deg, #00c6ff, #0072ff); border-radius: 16px 0 0 16px;
    }
    .kpi-card.promo-card::before { background: linear-gradient(180deg, #ff9a9e, #fecfef); }
    .kpi-card.purch-card::before { background: linear-gradient(180deg, #43e97b, #38f9d7); }
    .kpi-title { font-size: 0.9rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; opacity: 0.8; margin-bottom: 0.5rem; }
    .kpi-value { font-size: 2rem; font-weight: 800; line-height: 1.2; }
    .kpi-subtitle { font-size: 0.8rem; opacity: 0.6; margin-top: 0.3rem; }
    .stPlotlyChart { filter: drop-shadow(4px 6px 8px rgba(0,0,0,0.2)); transition: all 0.3s ease; }
    .stPlotlyChart:hover { filter: drop-shadow(6px 10px 12px rgba(0,0,0,0.3)); }
    .detail-section {
        background-color: #f8f9fa;
        border-left: 5px solid #00c6ff;
        padding: 15px;
        margin-top: 20px;
        border-radius: 4px;
    }
    @media (max-width: 768px) {
        .block-container { padding-left: 0.5rem !important; padding-right: 0.5rem !important; padding-top: 1rem !important; }
        .kpi-grid { gap: 0.8rem; }
        .kpi-value { font-size: 1.6rem; }
        .kpi-card { padding: 1.2rem; }
    }
</style>
""", unsafe_allow_html=True)

# ==========================================================================
# FIX #1: Google API Service separato con @st.cache_resource
# ==========================================================================
@st.cache_resource
def get_google_service():
    """Crea e cachea il service object Google Drive come risorsa singleton."""
    try:
        if "google_cloud" not in st.secrets:
            return None
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["google_cloud"]
        )
        return build('drive', 'v3', credentials=creds)
    except Exception:
        return None


@st.cache_data(ttl=300)
def get_drive_files_list():
    """Recupera la lista file da Drive. Ritorna solo dati serializzabili."""
    try:
        service = get_google_service()
        if service is None:
            return None, "Service non disponibile o secrets mancanti"
        folder_id = st.secrets["folder_id"]
        query = (
            f"'{folder_id}' in parents and "
            "(mimeType contains 'spreadsheet' or mimeType contains 'csv' "
            "or name contains '.xlsx') and trashed = false"
        )
        results = service.files().list(
            q=query,
            fields="files(id, name, modifiedTime, size)",
            orderBy="modifiedTime desc",
            pageSize=50
        ).execute()
        return results.get('files', []), None
    except Exception as e:
        return None, str(e)


@st.cache_data(show_spinner=False)
def load_dataset(file_id, modified_time):
    """Carica un dataset da Google Drive. Usa get_google_service() internamente."""
    try:
        service = get_google_service()
        if service is None:
            return None
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        try:
            return pd.read_excel(fh)
        except Exception:
            fh.seek(0)
            return pd.read_csv(fh)
    except Exception:
        return None


def convert_df_to_excel(df):
    output = io.BytesIO()
    if isinstance(df.index, pd.MultiIndex):
        df_export = df.reset_index()
    else:
        df_export = df.copy()

    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Dati')
            workbook = writer.book
            worksheet = writer.sheets['Dati']
            header_fmt = workbook.add_format(
                {'bold': True, 'bg_color': '#f0f0f0', 'border': 1,
                 'text_wrap': True, 'valign': 'vcenter'}
            )
            num_fmt = workbook.add_format({'num_format': '#,##0.0000'})
            for col_num, value in enumerate(df_export.columns.values):
                worksheet.write(0, col_num, value, header_fmt)
            for i, col in enumerate(df_export.columns):
                max_len = max(
                    df_export[col].astype(str).map(len).max()
                    if not df_export[col].empty else 0,
                    len(str(col))
                )
                final_len = min(max_len + 5, 60)
                if pd.api.types.is_numeric_dtype(df_export[col]):
                    worksheet.set_column(i, i, final_len, num_fmt)
                else:
                    worksheet.set_column(i, i, final_len)
    except ModuleNotFoundError:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Dati')
    return output.getvalue()


def smart_analyze_and_clean(df_in, page_type="Sales"):
    df = df_in.copy()
    if page_type == "Sales":
        target_numeric_cols = ['Importo_Netto_TotRiga', 'Peso_Netto_TotRiga', 'Qta_Cartoni_Ordinato', 'Prezzo_Netto']
        protected_text_cols = ['Descr_Cliente_Fat', 'Descr_Cliente_Dest', 'Descr_Articolo', 'Entity', 'Ragione Sociale']
    elif page_type == "Promo":
        target_numeric_cols = ['Quantità prevista', 'Quantità ordinata', 'Importo sconto', 'Sconto promo']
        protected_text_cols = ['Descrizione Cliente', 'Descrizione Prodotto', 'Descrizione Promozione', 'Riferimento', 'Tipo promo', 'Codice prodotto', 'Key Account', 'Decr_Cliente_Fat', 'Week start']
    else:
        target_numeric_cols = []
        protected_text_cols = []

    for col in df.columns:
        if col in ['Numero_Pallet', 'Sovrapponibile', 'COMPANY']:
            continue
        if any(t in col for t in protected_text_cols):
            df[col] = df[col].astype(str).replace(['nan', 'NaN', 'None'], '-')
            continue
        sample = df[col].dropna().astype(str).head(100).tolist()
        if not sample:
            continue
        if any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                continue
            except Exception:
                pass
        is_target_numeric = any(t in col for t in target_numeric_cols)

        # FIX #5: Euristica looks_numeric più conservativa.
        if not is_target_numeric:
            numeric_like_count = sum(
                1 for s in sample
                if len(s) > 0 and sum(c.isdigit() for c in s) / len(s) >= 0.5
            )
            looks_numeric = (numeric_like_count / len(sample)) >= 0.6
        else:
            looks_numeric = True

        if is_target_numeric or (looks_numeric and page_type != "Purchase"):
            try:
                clean_col = df[col].astype(str).str.replace('€', '').str.replace('%', '').str.replace(' ', '')
                if clean_col.str.contains(',', regex=False).any():
                    clean_col = clean_col.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                converted = pd.to_numeric(clean_col, errors='coerce')
                if is_target_numeric or converted.notna().sum() / len(converted) > 0.7:
                    df[col] = converted.fillna(0)
            except Exception:
                pass
    return df


def guess_column_role(df, page_type="Sales"):
    cols = df.columns
    guesses = {}
    if page_type == "Sales":
        guesses = {'entity': None, 'customer': None, 'product': None, 'euro': None, 'kg': None, 'cartons': None, 'date': None}
        golden_rules = {
            'euro': ['Importo_Netto_TotRiga'], 'kg': ['Peso_Netto_TotRiga'], 'cartons': ['Qta_Cartoni_Ordinato'],
            'date': ['Data_Ordine', 'Data_Fattura'], 'entity': ['Entity'],
            'customer': ['Decr_Cliente_Fat', 'Descr_Cliente_Fat', 'Descr_Cliente_Dest'],
            'product': ['Descr_Articolo']
        }
    elif page_type == "Promo":
        guesses = {
            'promo_id': None, 'promo_desc': None, 'customer': None, 'product': None,
            'qty_forecast': None, 'qty_actual': None, 'start_date': None,
            'status': None, 'division': None, 'type': None, 'week_start': None
        }
        golden_rules = {
            'promo_id': ['Numero Promozione'], 'promo_desc': ['Descrizione Promozione', 'Riferimento'],
            'customer': ['Descrizione Cliente'], 'product': ['Descrizione Prodotto'],
            'qty_forecast': ['Quantità prevista'], 'qty_actual': ['Quantità ordinata'],
            'start_date': ['Sell in da'], 'status': ['Stato'], 'division': ['Division'],
            'type': ['Tipo promo'], 'week_start': ['Week start']
        }
    else:
        return {}

    for role, targets in golden_rules.items():
        for t in targets:
            if t in cols:
                guesses[role] = t
                break
    return guesses


# FIX #2: set_idx definita UNA SOLA VOLTA a livello modulo.
def set_idx(guess, options):
    """Helper: ritorna l'indice di guess in options, oppure 0."""
    return options.index(guess) if guess in options else 0


# FIX #3: Helper per il date_input con unpacking sicuro.
def safe_date_input(label, default_start, default_end, key=None):
    """
    Wrapper per st.sidebar.date_input che gestisce la selezione
    di un singolo giorno restituendo (start, start) in quel caso.
    """
    date_range = st.sidebar.date_input(
        label, [default_start, default_end],
        format="DD/MM/YYYY",
        key=key
    )
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        return date_range[0], date_range[1]
    elif isinstance(date_range, (list, tuple)) and len(date_range) == 1:
        return date_range[0], date_range[0]
    else:
        return date_range, date_range


# --- 3. NAVIGAZIONE MULTIPAGINA ---
st.sidebar.title("🚀 EITA Dashboard")
page = st.sidebar.radio(
    "Vai alla sezione:",
    ["📊 Vendite & Fatturazione", "🎁 Analisi Customer Promo", "📦 Analisi Acquisti"]
)
st.sidebar.markdown("---")

files, drive_error = get_drive_files_list()

if drive_error:
    st.sidebar.error(f"Errore Drive: {drive_error}")

# =====================================================================
# PAGINA 1: VENDITE E FATTURAZIONE
# =====================================================================
if page == "📊 Vendite & Fatturazione":
    df_processed = None
    if files:
        file_map = {f['name']: f for f in files}
        target_file = "From_Order_to_Invoice"
        file_list = list(file_map.keys())
        default_index = next(
            (i for i, f in enumerate(file_list) if target_file.lower() in f.lower()), 0
        )
        sel_file_name = st.sidebar.selectbox("1. Sorgente Dati", file_list, index=default_index)
        selected_file_obj = file_map[sel_file_name]
        with st.spinner('Loading Sales Data...'):
            df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'])
            if df_raw is not None:
                df_processed = smart_analyze_and_clean(df_raw, "Sales")
    else:
        st.error("Nessun file trovato su Google Drive.")

    if df_processed is not None:
        guesses = guess_column_role(df_processed, "Sales")
        all_cols = df_processed.columns.tolist()

        with st.sidebar.expander("⚙️ Mappatura Colonne", expanded=False):
            col_entity   = st.selectbox("Entità", all_cols, index=set_idx(guesses['entity'], all_cols))
            col_customer = st.selectbox("Cliente (Fatturazione)", all_cols, index=set_idx(guesses['customer'], all_cols))
            col_prod     = st.selectbox("Prodotto", all_cols, index=set_idx(guesses['product'], all_cols))
            col_euro     = st.selectbox("Valore (€)", all_cols, index=set_idx(guesses['euro'], all_cols))
            col_kg       = st.selectbox("Peso (Kg)", all_cols, index=set_idx(guesses['kg'], all_cols))
            col_cartons  = st.selectbox("Cartoni (Qty)", all_cols, index=set_idx(guesses['cartons'], all_cols))
            col_data     = st.selectbox("Data Riferimento", all_cols, index=set_idx(guesses['date'], all_cols))

        st.sidebar.markdown("### 🔍 Filtri Rapidi")
        df_global = df_processed.copy()
        sel_ent = None

        if col_entity:
            ents = sorted(df_global[col_entity].astype(str).unique())
            idx_e = ents.index('EITA') if 'EITA' in ents else 0
            sel_ent = st.sidebar.selectbox("Società / Entità", ents, index=idx_e)
            df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

        if col_data and pd.api.types.is_datetime64_any_dtype(df_global[col_data]):
            def_start = datetime.date(2026, 1, 1)
            def_end   = datetime.date(2026, 1, 31)
            # FIX #3: uso safe_date_input
            d_start, d_end = safe_date_input(
                "Periodo di Analisi", def_start, def_end, key="sales_date"
            )
            df_global = df_global[
                (df_global[col_data].dt.date >= d_start) &
                (df_global[col_data].dt.date <= d_end)
            ]

        st.sidebar.markdown("### 🎛️ Filtri Avanzati")
        possible_filters = [
            c for c in all_cols
            if c not in [col_euro, col_kg, col_cartons, col_data, col_entity]
        ]
        filters_selected = st.sidebar.multiselect("Aggiungi filtri (es. Vettore, Regione):", possible_filters)
        for f_col in filters_selected:
            unique_vals = sorted(df_global[f_col].astype(str).unique())
            sel_vals = st.sidebar.multiselect(f"Seleziona in {f_col}", unique_vals)
            if sel_vals:
                df_global = df_global[df_global[f_col].astype(str).isin(sel_vals)]

        st.title(f"Performance Overview: {sel_ent if sel_ent else 'Global'}")

        if not df_global.empty:
            tot_euro    = df_global[col_euro].sum()
            tot_kg      = df_global[col_kg].sum()
            col_ord_num = next((c for c in df_global.columns if "Numero_Ordine" in c), None)
            tot_orders  = df_global[col_ord_num].nunique() if col_ord_num else len(df_global)

            top_c_data = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1)
            top_name = top_c_data.index[0] if not top_c_data.empty else "-"
            top_val  = top_c_data.values[0] if not top_c_data.empty else 0
            short_top_name = (top_name[:20] + "..") if len(str(top_name)) > 20 else str(top_name)

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

            st.markdown("### 🧭 Analisi Esplorativa (Drill-Down)")
            col_l, col_r = st.columns([1.2, 1.8], gap="large")

            cust_totals       = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False)
            total_val_period = df_global[col_euro].sum()
            options           = ["🌍 TUTTI I CLIENTI"] + cust_totals.index.tolist()

            with col_l:
                sel_target = st.selectbox(
                    "📍 Focus Analisi:",
                    options,
                    format_func=lambda x: (
                        f"{x} (Fatturato: € {total_val_period:,.0f})"
                        if "TUTTI" in x
                        else f"{x} (€ {cust_totals[x]:,.0f})"
                    )
                )
                df_target = df_global if "TUTTI" in sel_target else df_global[df_global[col_customer] == sel_target]

                if not df_target.empty:
                    chart_type = st.radio(
                        "Rendering Grafico:",
                        ["📊 Barre 3D", "🥧 Torta 3D", "🍩 Donut 3D"],
                        horizontal=True
                    )
                    prod_agg = (
                        df_target
                        .groupby(col_prod)
                        .agg({col_euro: 'sum', col_kg: 'sum', col_cartons: 'sum'})
                        .reset_index()
                        .sort_values(col_euro, ascending=False)
                        .head(10)
                    )

                    if chart_type == "📊 Barre 3D":
                        fig = go.Figure()
                        fig.add_trace(go.Bar(
                            y=prod_agg[col_prod], x=prod_agg[col_euro], orientation='h',
                            marker=dict(
                                color=prod_agg[col_euro], colorscale='Blues',
                                line=dict(color='rgba(0,0,0,0.4)', width=1.5)
                            ),
                            text=prod_agg[col_euro].apply(lambda x: f"€ {x:,.0f}"),
                            textposition='inside', insidetextanchor='middle',
                            hovertemplate="<b>%{y}</b><br>Fatturato: € %{x:,.2f}<extra></extra>"
                        ))
                        fig.update_layout(
                            height=450,
                            yaxis=dict(autorange="reversed", showgrid=False),
                            xaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)'),
                            margin=dict(l=0, r=0, t=10, b=10),
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)'
                        )
                    else:
                        hole_size  = 0.45 if "Donut" in chart_type else 0
                        pull_array = [0.12] + [0] * (len(prod_agg) - 1)
                        fig = go.Figure(data=[go.Pie(
                            labels=prod_agg[col_prod], values=prod_agg[col_euro],
                            hole=hole_size, pull=pull_array,
                            marker=dict(
                                colors=px.colors.qualitative.Pastel,
                                line=dict(color='white', width=2.5)
                            ),
                            textinfo='percent+label', textposition='outside',
                            hovertemplate="<b>%{label}</b><br>Valore: € %{value:,.2f}<br>Quota: %{percent}<extra></extra>"
                        )])
                        fig.update_layout(
                            height=450, margin=dict(l=20, r=20, t=20, b=20),
                            showlegend=False,
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)'
                        )

                    st.plotly_chart(fig, use_container_width=True)

            with col_r:
                if "TUTTI" in sel_target:
                    st.markdown("#### 💥 Esplosione Prodotto (Master-Detail)")
                    st.info("💡 Usa il menu a tendina per il drill-down. È più affidabile del clic su grafico.")

                    with st.form("product_explosion_form"):
                        group_mode = st.radio(
                            "Gerarchia Raggruppamento (Livelli):",
                            ["Prodotto → Cliente", "Cliente → Prodotto"],
                            horizontal=True
                        )
                        all_p_sorted     = df_target.groupby(col_prod)[col_euro].sum().sort_values(ascending=False)
                        tot_euro_target = df_target[col_euro].sum()
                        prod_options    = ["TUTTI I PRODOTTI"] + all_p_sorted.index.tolist()

                        sel_p = st.multiselect(
                            "Filtra Prodotti:",
                            prod_options,
                            default=["TUTTI I PRODOTTI"],
                            format_func=lambda x: (
                                f"{x} (Incasso Tot: € {tot_euro_target:,.0f})"
                                if x == "TUTTI I PRODOTTI"
                                else f"{x} (Incasso Tot: € {all_p_sorted[x]:,.0f})"
                            )
                        )
                        cust_available = sorted(
                            df_target[col_customer].dropna().astype(str).unique().tolist()
                        )
                        sel_c       = st.multiselect("Filtra Clienti:", cust_available, placeholder="Tutti i clienti...")
                        submit_btn = st.form_submit_button("🔄 Applica Filtri")

                    # FIX #6: Chiave session_state corretta.
                    if submit_btn or 'sales_raw_df' in st.session_state:
                        if submit_btn:
                            df_ps = df_target.copy()
                            if "TUTTI I PRODOTTI" not in sel_p:
                                df_ps = df_ps[df_ps[col_prod].isin(sel_p)]
                            if sel_c:
                                df_ps = df_ps[df_ps[col_customer].astype(str).isin(sel_c)]
                            st.session_state['sales_raw_df']    = df_ps
                            st.session_state['sales_group_mode'] = group_mode
                            # Reset selettore per evitare errori se la lista cambia
                            if 'drill_down_selector' in st.session_state:
                                del st.session_state['drill_down_selector']

                        df_tree_raw = st.session_state.get('sales_raw_df', df_target)
                        mode        = st.session_state.get('sales_group_mode', "Prodotto → Cliente")
                        primary_col   = col_prod     if mode == "Prodotto → Cliente" else col_customer
                        secondary_col = col_customer if mode == "Prodotto → Cliente" else col_prod

                        master_df = (
                            df_tree_raw
                            .groupby(primary_col)
                            .agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'})
                            .reset_index()
                            .sort_values(col_euro, ascending=False)
                        )
                        master_df['Valore Medio €/Kg'] = np.where(
                            master_df[col_kg] > 0, master_df[col_euro] / master_df[col_kg], 0
                        )
                        master_df['Valore Medio €/CT'] = np.where(
                            master_df[col_cartons] > 0, master_df[col_euro] / master_df[col_cartons], 0
                        )

                        st.dataframe(
                            master_df,
                            column_config={
                                primary_col:          st.column_config.TextColumn("Elemento (Master)", width="medium"),
                                col_cartons:          st.column_config.NumberColumn("CT Tot", format="%d"),
                                col_kg:               st.column_config.NumberColumn("Kg Tot", format="%.0f"),
                                col_euro:             st.column_config.NumberColumn("Valore Tot", format="€ %.2f"),
                                'Valore Medio €/Kg':  st.column_config.NumberColumn("€/Kg Med", format="€ %.2f"),
                                'Valore Medio €/CT':  st.column_config.NumberColumn("€/CT Med", format="€ %.2f"),
                            },
                            use_container_width=True,
                            hide_index=True
                        )

                        st.markdown("⬇️ **Seleziona un elemento per vedere il dettaglio:**")
                        unique_elements = master_df[primary_col].unique()
                        selected_val    = st.selectbox(
                            "Elemento da esplorare:", unique_elements, key="drill_down_selector"
                        )

                        if selected_val is not None:
                            detail_df  = df_tree_raw[df_tree_raw[primary_col] == selected_val]
                            detail_agg = (
                                detail_df
                                .groupby(secondary_col)
                                .agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'})
                                .reset_index()
                                .sort_values(col_euro, ascending=False)
                            )
                            detail_agg['Valore Medio €/Kg'] = np.where(
                                detail_agg[col_kg] > 0, detail_agg[col_euro] / detail_agg[col_kg], 0
                            )
                            detail_agg['Valore Medio €/CT'] = np.where(
                                detail_agg[col_cartons] > 0, detail_agg[col_euro] / detail_agg[col_cartons], 0
                            )

                            st.markdown(
                                f'<div class="detail-section">Dettaglio per: <b>{selected_val}</b></div>',
                                unsafe_allow_html=True
                            )

                            st.dataframe(
                                detail_agg,
                                column_config={
                                    secondary_col:        st.column_config.TextColumn("Dettaglio (Child)", width="medium"),
                                    col_cartons:          st.column_config.NumberColumn("CT", format="%d"),
                                    col_kg:               st.column_config.NumberColumn("Kg", format="%.0f"),
                                    col_euro:             st.column_config.NumberColumn("Valore", format="€ %.2f"),
                                    'Valore Medio €/Kg':  st.column_config.NumberColumn("€/Kg", format="€ %.2f"),
                                    'Valore Medio €/CT':  st.column_config.NumberColumn("€/CT", format="€ %.2f"),
                                },
                                use_container_width=True,
                                hide_index=True
                            )

                        full_flat = (
                            df_tree_raw
                            .groupby([primary_col, secondary_col])
                            .agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'})
                            .reset_index()
                            .sort_values(col_euro, ascending=False)
                        )
                        full_flat['Valore Medio €/Kg'] = np.where(
                            full_flat[col_kg] > 0, full_flat[col_euro] / full_flat[col_kg], 0
                        )
                        full_flat['Valore Medio €/CT'] = np.where(
                            full_flat[col_cartons] > 0, full_flat[col_euro] / full_flat[col_cartons], 0
                        )

                        excel_data = convert_df_to_excel(full_flat)
                        st.download_button(
                            label="📥 Scarica Report Excel Completo",
                            data=excel_data,
                            file_name=f"Explosion_Full_Report_{datetime.date.today()}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )

                else:
                    st.markdown(f"#### 🧾 Dettaglio Acquisti")
                    st.caption(f"Portafoglio ordini per: {sel_target}")
                    ps = (
                        df_target
                        .groupby(col_prod)
                        .agg({col_cartons: 'sum', col_kg: 'sum', col_euro: 'sum'})
                        .reset_index()
                        .sort_values(col_euro, ascending=False)
                    )
                    # --- ADDED METRICS HERE (v36.1) ---
                    ps['Valore Medio €/Kg'] = np.where(
                        ps[col_kg] > 0, ps[col_euro] / ps[col_kg], 0
                    )
                    ps['Valore Medio €/CT'] = np.where(
                        ps[col_cartons] > 0, ps[col_euro] / ps[col_cartons], 0
                    )
                    # ----------------------------------

                    st.dataframe(
                        ps,
                        column_config={
                            col_prod:    st.column_config.TextColumn("🏷️ Articolo / Prodotto", width="large"),
                            col_cartons: st.column_config.NumberColumn("📦 CT", format="%d"),
                            col_kg:      st.column_config.NumberColumn("⚖️ Kg", format="%d"),
                            col_euro:    st.column_config.NumberColumn("💰 Valore", format="€ %.2f"),
                            'Valore Medio €/Kg': st.column_config.NumberColumn("€/Kg Med", format="€ %.2f"),
                            'Valore Medio €/CT': st.column_config.NumberColumn("€/CT Med", format="€ %.2f"),
                        },
                        hide_index=True, use_container_width=True, height=500
                    )
                    excel_data_single = convert_df_to_excel(ps)
                    st.download_button(
                        label="📥 Scarica Dettaglio Excel (.xlsx)",
                        data=excel_data_single,
                        file_name=f"Dettaglio_{sel_target}_{datetime.date.today()}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_download_single"
                    )

# =====================================================================
# PAGINA 2: CUSTOMER PROMO
# =====================================================================
elif page == "🎁 Analisi Customer Promo":
    st.title("🎁 Analisi Customer Promo")
    df_promo_processed = None

    if files:
        file_map      = {f['name']: f for f in files}
        target_file_p = "Customer_Promo"
        file_list     = list(file_map.keys())
        default_idx_p = next(
            (i for i, f in enumerate(file_list) if target_file_p.lower() in f.lower()), 0
        )
        sel_promo_file = st.sidebar.selectbox("1. File Sorgente Promo", file_list, index=default_idx_p)
        with st.spinner('Elaborazione dati promozionali...'):
            df_promo_raw = load_dataset(
                file_map[sel_promo_file]['id'],
                file_map[sel_promo_file]['modifiedTime']
            )
            if df_promo_raw is not None:
                df_promo_processed = smart_analyze_and_clean(df_promo_raw, "Promo")

    if df_promo_processed is not None:
        guesses_p  = guess_column_role(df_promo_processed, "Promo")
        all_cols_p = df_promo_processed.columns.tolist()

        with st.sidebar.expander("⚙️ Verifica Colonne Promo", expanded=False):
            p_div    = st.selectbox("Division",           all_cols_p, index=set_idx(guesses_p['division'],      all_cols_p))
            p_status = st.selectbox("Stato",              all_cols_p, index=set_idx(guesses_p['status'],       all_cols_p))
            p_cust   = st.selectbox("Cliente",            all_cols_p, index=set_idx(guesses_p['customer'],     all_cols_p))
            p_prod   = st.selectbox("Prodotto",           all_cols_p, index=set_idx(guesses_p['product'],      all_cols_p))
            p_qty_f  = st.selectbox("Q.tà Prevista",      all_cols_p, index=set_idx(guesses_p['qty_forecast'], all_cols_p))
            p_qty_a  = st.selectbox("Q.tà Ordinata",      all_cols_p, index=set_idx(guesses_p['qty_actual'],   all_cols_p))
            p_start  = st.selectbox("Data Inizio Sell-In",all_cols_p, index=set_idx(guesses_p['start_date'],   all_cols_p))
            p_type   = st.selectbox("Tipo Promo",         all_cols_p, index=set_idx(guesses_p['type'],         all_cols_p))
            p_week   = st.selectbox("Week start",         all_cols_p, index=set_idx(guesses_p['week_start'],   all_cols_p))

        st.sidebar.markdown("### 🔍 Filtri Promo Rapidi")
        df_pglobal = df_promo_processed.copy()

        if p_div in df_pglobal.columns:
            divs    = sorted(df_pglobal[p_div].dropna().unique().tolist())
            idx_div = divs.index(21) if 21 in divs else (divs.index('21') if '21' in divs else 0)
            sel_div = st.sidebar.selectbox("Division", divs, index=idx_div)
            df_pglobal = df_pglobal[df_pglobal[p_div] == sel_div]

        if p_start in df_pglobal.columns and pd.api.types.is_datetime64_any_dtype(df_pglobal[p_start]):
            min_date = df_pglobal[p_start].min()
            max_date = df_pglobal[p_start].max()
            if pd.notnull(min_date) and pd.notnull(max_date):
                d_start, d_end = safe_date_input(
                    "Periodo Sell-In", min_date.date(), max_date.date(), key="promo_date"
                )
                df_pglobal = df_pglobal[
                    (df_pglobal[p_start].dt.date >= d_start) &
                    (df_pglobal[p_start].dt.date <= d_end)
                ]

        st.sidebar.markdown("### 🎛️ Filtri Avanzati Promo")

        if p_status in df_pglobal.columns:
            stati         = sorted(df_pglobal[p_status].dropna().unique().tolist())
            default_stati = [20] if 20 in stati else ([str(20)] if str(20) in stati else stati)
            sel_stati     = st.sidebar.multiselect("Stato Promozione", stati, default=default_stati)
            if sel_stati:
                df_pglobal = df_pglobal[df_pglobal[p_status].isin(sel_stati)]

        possible_filters_p = [
            c for c in all_cols_p if c not in [p_qty_f, p_qty_a, p_start, p_div, p_status]
        ]
        filters_selected_p = st.sidebar.multiselect(
            "Aggiungi altri filtri (es. Key Account, Gerarchia):", possible_filters_p
        )
        for f_col in filters_selected_p:
            unique_vals = sorted(df_pglobal[f_col].dropna().astype(str).unique())
            sel_vals    = st.sidebar.multiselect(f"Seleziona {f_col}", unique_vals)
            if sel_vals:
                df_pglobal = df_pglobal[df_pglobal[f_col].astype(str).isin(sel_vals)]

        if not df_pglobal.empty:
            tot_promo_uniche = (
                int(df_pglobal[guesses_p['promo_id']].nunique())
                if guesses_p.get('promo_id') and guesses_p['promo_id'] in df_pglobal.columns
                else len(df_pglobal)
            )
            tot_prevista = float(df_pglobal[p_qty_f].sum()) if p_qty_f in df_pglobal.columns else 0.0
            tot_ordinata = float(df_pglobal[p_qty_a].sum()) if p_qty_a in df_pglobal.columns else 0.0
            hit_rate     = (tot_ordinata / tot_prevista * 100) if tot_prevista > 0 else 0.0

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

            col_pl, col_pr = st.columns([1, 1], gap="large")

            with col_pl:
                st.subheader("Performance per Tipo Promo")
                if p_type in df_pglobal.columns:
                    type_agg = df_pglobal.groupby(p_type).agg({p_qty_f: 'sum', p_qty_a: 'sum'}).reset_index()
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        x=type_agg[p_type], y=type_agg[p_qty_f], name='Forecast (Previsto)',
                        marker=dict(color='#89CFF0', line=dict(color='rgba(255,255,255,0.8)', width=1.5))
                    ))
                    fig.add_trace(go.Bar(
                        x=type_agg[p_type], y=type_agg[p_qty_a], name='Actual (Ordinato)',
                        marker=dict(color='#004e92', line=dict(color='rgba(0,0,0,0.5)', width=1.5))
                    ))
                    fig.update_layout(
                        barmode='group', height=450,
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig, use_container_width=True)

            with col_pr:
                st.subheader("Top Promozioni (per Volume)")
                promo_desc_col = guesses_p.get('promo_desc') or 'Descrizione Promozione'
                if promo_desc_col in df_pglobal.columns:
                    top_promos = (
                        df_pglobal.groupby(promo_desc_col)
                        .agg({p_qty_a: 'sum'})
                        .reset_index()
                        .sort_values(p_qty_a, ascending=False)
                        .head(8)
                    )
                    fig = go.Figure(go.Bar(
                        x=top_promos[p_qty_a], y=top_promos[promo_desc_col], orientation='h',
                        marker=dict(
                            color=top_promos[p_qty_a], colorscale='Purp',
                            line=dict(color='rgba(0,0,0,0.4)', width=1.5)
                        )
                    ))
                    fig.update_layout(
                        height=450, yaxis=dict(autorange="reversed"),
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig, use_container_width=True)

            st.subheader("📋 Dettaglio Iniziative Promozionali")

            with st.form("promo_detail_form"):
                st.caption("Seleziona i filtri e premi 'Aggiorna Tabella' per applicare.")
                f1, f2, f3, f4 = st.columns(4)

                with f1:
                    c_list = sorted(df_pglobal[p_cust].dropna().astype(str).unique()) if p_cust in df_pglobal.columns else []
                    sel_tc = st.multiselect("👤 Cliente", c_list, placeholder="Tutti...")

                with f2:
                    p_list = sorted(df_pglobal[p_prod].dropna().astype(str).unique()) if p_prod in df_pglobal.columns else []
                    sel_tp = st.multiselect("🏷️ Prodotto", p_list, placeholder="Tutti...")

                with f3:
                    s_list = (
                        sorted(df_pglobal['Sconto promo'].dropna().astype(str).unique())
                        if 'Sconto promo' in df_pglobal.columns else []
                    )
                    sel_ts = st.multiselect("📉 Sconto promo", s_list, placeholder="Tutti...")

                with f4:
                    w_list = sorted(df_pglobal[p_week].dropna().astype(str).unique()) if p_week in df_pglobal.columns else []
                    sel_tw = st.multiselect("📅 Week start", w_list, placeholder="Tutte...")

                submit_promo = st.form_submit_button("🔄 Aggiorna Tabella")

            if submit_promo:
                df_display = df_pglobal.copy()
                if sel_tc: df_display = df_display[df_display[p_cust].astype(str).isin(sel_tc)]
                if sel_tp: df_display = df_display[df_display[p_prod].astype(str).isin(sel_tp)]
                if sel_ts: df_display = df_display[df_display['Sconto promo'].astype(str).isin(sel_ts)]
                if sel_tw: df_display = df_display[df_display[p_week].astype(str).isin(sel_tw)]

                promo_id_col   = guesses_p.get('promo_id')
                promo_desc_col = guesses_p.get('promo_desc') or 'Descrizione Promozione'
                cols_to_show   = [
                    c for c in [promo_id_col, promo_desc_col, p_cust, p_prod, p_start, p_week, p_qty_f, p_qty_a, 'Sconto promo']
                    if c and c in df_display.columns
                ]
                df_display_sorted = (
                    df_display[cols_to_show].sort_values(by=p_qty_a, ascending=False)
                    if p_qty_a in df_display.columns
                    else df_display[cols_to_show]
                )
                st.session_state['promo_detail_df'] = df_display_sorted

            if 'promo_detail_df' in st.session_state:
                df_p_show = st.session_state['promo_detail_df']
                st.dataframe(
                    df_p_show,
                    column_config={
                        p_qty_f: st.column_config.NumberColumn("Forecast Qty", format="%.0f"),
                        p_qty_a: st.column_config.NumberColumn("Actual Qty",   format="%.0f"),
                        p_start: st.column_config.DateColumn("Inizio Sell-In", format="DD/MM/YYYY"),
                    },
                    hide_index=True, use_container_width=True, height=500
                )
                excel_data_promo = convert_df_to_excel(df_p_show)
                st.download_button(
                    label="📥 Scarica Report Promo Excel (.xlsx)",
                    data=excel_data_promo,
                    file_name=f"Promo_Report_{datetime.date.today()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_download_promo"
                )
        else:
            st.warning("Nessuna promozione trovata per i filtri selezionati.")

# =====================================================================
# PAGINA 3: ANALISI ACQUISTI
# =====================================================================
elif page == "📦 Analisi Acquisti":
    st.title("📦 Analisi Acquisti (Purchase History)")

    if files:
        file_map        = {f['name']: f for f in files}
        target_file_pu  = "Purchase_orders_history"
        file_list       = list(file_map.keys())
        default_idx_pu  = next(
            (i for i, f in enumerate(file_list) if target_file_pu.lower() in f.lower()), 0
        )
        sel_purch_file = st.sidebar.selectbox("1. File Sorgente Acquisti", file_list, index=default_idx_pu)
        with st.spinner('Lettura file acquisti...'):
            df_purch_raw = load_dataset(
                file_map[sel_purch_file]['id'],
                file_map[sel_purch_file]['modifiedTime']
            )
            if df_purch_raw is not None:
                df_purch_processed = smart_analyze_and_clean(df_purch_raw, "Purchase")
                st.info("ℹ️ Pagina pronta. In attesa della legenda colonne per attivare i calcoli KPI.")
                st.markdown("### Anteprima Dati Grezzi")
                st.dataframe(df_purch_processed.head(10), use_container_width=True)
                st.markdown("### Colonne Disponibili")
                st.write(df_purch_processed.columns.tolist())
    else:
        st.error("Nessun file trovato.")