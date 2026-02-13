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
import google.generativeai as genai

# ==========================================================================
# 1. CONFIGURAZIONE & STILE (v39.3 - Restored Features)
# ==========================================================================
st.set_page_config(
    page_title="EITA Analytics Pro v39.3",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .block-container {
        padding-top: 2rem !important; padding-bottom: 3rem !important;
        padding-left: 1.5rem !important; padding-right: 1.5rem !important;
        max-width: 1600px;
    }
    [data-testid="stElementToolbar"] { display: none; }
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 1.2rem; margin-bottom: 2rem;
    }
    .kpi-card {
        background: rgba(130, 150, 200, 0.1);
        backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(130, 150, 200, 0.2);
        border-radius: 16px; padding: 1.5rem;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.05);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        position: relative; overflow: hidden;
    }
    .kpi-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.15);
        border: 1px solid rgba(130, 150, 200, 0.4);
    }
    .kpi-title { font-size: 0.9rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; opacity: 0.8; margin-bottom: 0.5rem; }
    .kpi-value { font-size: 2rem; font-weight: 800; line-height: 1.2; }
    .kpi-subtitle { font-size: 0.8rem; opacity: 0.6; margin-top: 0.3rem; }
    /* AI Chat Style */
    .stChatMessage { background-color: rgba(255,255,255,0.05); border-radius: 10px; padding: 10px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# ==========================================================================
# 2. GOOGLE DRIVE SERVICES & CACHING
# ==========================================================================
@st.cache_resource
def get_google_service():
    """Singleton per connessione Google Drive."""
    try:
        if "google_cloud" not in st.secrets:
            return None
        creds = service_account.Credentials.from_service_account_info(st.secrets["google_cloud"])
        return build('drive', 'v3', credentials=creds)
    except Exception:
        return None

@st.cache_data(ttl=300)
def get_drive_files_list():
    """Recupera lista file (solo metadati necessari)."""
    try:
        service = get_google_service()
        if not service:
            return None, "Service unavailable"
        folder_id = st.secrets["folder_id"]
        query = (
            f"'{folder_id}' in parents and "
            "(mimeType contains 'spreadsheet' or mimeType contains 'csv' or name contains '.xlsx') "
            "and trashed = false"
        )
        results = service.files().list(
            q=query, fields="files(id, name, modifiedTime, size)",
            orderBy="modifiedTime desc", pageSize=50
        ).execute()
        return results.get('files', []), None
    except Exception as e:
        return None, str(e)

@st.cache_data(show_spinner=False)
def load_dataset(file_id, modified_time):
    """Download e parsing del file in DataFrame."""
    try:
        service = get_google_service()
        if not service: return None
        
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        
        try:
            return pd.read_excel(fh)
        except:
            fh.seek(0)
            return pd.read_csv(fh)
    except Exception:
        return None

def convert_df_to_excel(df):
    """Converte DF in bytes Excel per il download."""
    output = io.BytesIO()
    df_export = df.reset_index() if isinstance(df.index, pd.MultiIndex) else df.copy()
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Dati')
            workbook  = writer.book
            worksheet = writer.sheets['Dati']
            header_fmt = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1})
            for col_num, value in enumerate(df_export.columns.values):
                worksheet.write(0, col_num, value, header_fmt)
    except:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Dati')
    return output.getvalue()

# ==========================================================================
# 3. PULIZIA E ANALISI INTELLIGENTE
# ==========================================================================
def smart_analyze_and_clean(df_in, page_type="Sales"):
    df = df_in.copy()
    
    if page_type == "Sales":
        target_numeric_cols = ['Importo_Netto_TotRiga', 'Peso_Netto_TotRiga', 'Qta_Cartoni_Ordinato', 'Prezzo_Netto', 'Sconto7_Promozionali', 'Sconto4_Free']
        protected_text_cols = ['Descr_Cliente_Fat', 'Descr_Cliente_Dest', 'Descr_Articolo', 'Entity', 'Ragione Sociale', 'Decr_Cliente_Fat']
    elif page_type == "Promo":
        target_numeric_cols = ['Quantità prevista', 'Quantità ordinata', 'Importo sconto', 'Sconto promo']
        protected_text_cols = ['Descrizione Cliente', 'Descrizione Prodotto', 'Descrizione Promozione', 'Riferimento', 'Tipo promo', 'Key Account', 'Decr_Cliente_Fat', 'Week start', 'Stato']
    elif page_type == "Purchase":
        target_numeric_cols = ['Order quantity', 'Received quantity', 'Invoice quantity', 'Invoice amount', 'Row amount', 'Purchase price', 'Kg acquistati', 'Exchange rate', 'Line amount', 'Part net weight']
        protected_text_cols = ['Supplier name', 'Part description', 'Part group description', 'Part class description', 'Division', 'Facility', 'Warehouse', 'Supplier number', 'Part number', 'Purchase order']
    else:
        target_numeric_cols, protected_text_cols = [], []

    for col in df.columns:
        if col in ['Numero_Pallet', 'Sovrapponibile', 'COMPANY']:
            continue
        
        if any(t in col for t in protected_text_cols):
            if 'Division' in col:
                df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(3)
            else:
                df[col] = df[col].astype(str).replace(['nan', 'NaN', 'None'], '-')
            continue
        
        sample = df[col].dropna().astype(str).head(100).tolist()
        if not sample: continue

        if any(('/' in s or '-' in s) and len(s) >= 8 and s[0].isdigit() for s in sample):
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                continue
            except: pass
        
        is_target = any(t in col for t in target_numeric_cols)
        numeric_score = sum(1 for s in sample if len(s)>0 and sum(c.isdigit() for c in s)/len(s) >= 0.5)
        looks_numeric = (numeric_score / len(sample) >= 0.6) if sample else False

        if is_target or looks_numeric:
            try:
                clean_col = df[col].astype(str).str.replace('€', '').str.replace('%', '').str.replace(' ', '')
                if clean_col.str.contains(',', regex=False).any():
                    clean_col = clean_col.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                converted = pd.to_numeric(clean_col, errors='coerce')
                if is_target or (converted.notna().sum() / len(converted) > 0.7):
                    df[col] = converted.fillna(0)
            except: pass
            
    return df

def guess_column_role(df, page_type="Sales"):
    cols = df.columns
    guesses = {}
    mapping_rules = {
        "Sales": {
            'euro': ['Importo_Netto_TotRiga'], 'kg': ['Peso_Netto_TotRiga'], 
            'cartons': ['Qta_Cartoni_Ordinato'], 'date': ['Data_Ordine', 'Data_Fattura'],
            'entity': ['Entity', 'Società', 'Company'], 'product': ['Descr_Articolo'],
            'customer': ['Decr_Cliente_Fat', 'Descr_Cliente_Fat']
        },
        "Promo": {
            'promo_id': ['Numero Promozione'], 'promo_desc': ['Descrizione Promozione'],
            'customer': ['Descrizione Cliente'], 'product': ['Descrizione Prodotto'],
            'qty_forecast': ['Quantità prevista'], 'qty_actual': ['Quantità ordinata'],
            'start_date': ['Sell in da'], 'division': ['Division'], 'type': ['Tipo promo'],
            'week_start': ['Week start'], 'status': ['Stato']
        },
        "Purchase": {
            'supplier': ['Supplier name'], 'order_date': ['Purchase order date'],
            'amount': ['Invoice amount', 'Row amount'], 'kg': ['Kg acquistati'],
            'division': ['Division'], 'product': ['Part description'],
            'category': ['Part group description'], 'price': ['Purchase price']
        }
    }
    rules = mapping_rules.get(page_type, {})
    for role, targets in rules.items():
        guesses[role] = next((t for t in targets if t in cols), None)
    return guesses

def set_idx(guess, options):
    return options.index(guess) if guess in options else 0

def safe_date_input(label, d_min, d_max, key):
    res = st.sidebar.date_input(label, [d_min, d_max], format="DD/MM/YYYY", key=key)
    return (res[0], res[1]) if isinstance(res, (list,tuple)) and len(res)==2 else (res[0], res[0]) if isinstance(res, (list,tuple)) and len(res)==1 else (res, res)

# ==========================================================================
# 4. AI CHAT ENGINE (TEXT-TO-PANDAS)
# ==========================================================================
def get_ai_response(user_query):
    """
    Motore che genera codice Pandas basato sullo schema dei dati disponibili in Session State.
    NON invia i dati grezzi all'LLM.
    """
    available_dfs = {}
    if 'global_df_sales' in st.session_state: available_dfs['df_sales'] = st.session_state.global_df_sales
    if 'global_df_promo' in st.session_state: available_dfs['df_promo'] = st.session_state.global_df_promo
    if 'global_df_purch' in st.session_state: available_dfs['df_purch'] = st.session_state.global_df_purch

    if not available_dfs:
        return "⚠️ Nessun dato caricato. Carica un file dalle sezioni principali per iniziare."

    schema_info = ""
    for name, df in available_dfs.items():
        schema_info += f"\nDataFrame: {name}\nColumns: {list(df.columns)}\nDtypes: {df.dtypes.to_dict()}\n"

    prompt = f"""
    You are an expert Python Data Analyst. 
    You have access to the following pandas DataFrames: {list(available_dfs.keys())}.
    
    SCHEMAS:
    {schema_info}

    USER QUESTION: "{user_query}"

    INSTRUCTIONS:
    1. Write Python code using pandas/plotly to answer the question.
    2. Assume 'pd', 'px', 'go', 'np' and the dataframes are already imported.
    3. STORE THE FINAL RESULT IN A VARIABLE NAMED `result`.
    4. If the result is a number or string, `result` should be that value.
    5. If the result is a table, `result` should be a DataFrame.
    6. If a chart is requested, `result` should be a plotly Figure.
    7. Handle column names exactly as shown in Schemas.
    8. Return ONLY the python code, no markdown backticks, no comments explaining the code.
    """

    try:
        if "gemini_api_key" in st.secrets:
            genai.configure(api_key=st.secrets["gemini_api_key"])
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt)
            code = response.text.replace("```python", "").replace("```", "").strip()
            
            local_vars = {k: v for k, v in available_dfs.items()}
            local_vars.update({'pd': pd, 'px': px, 'go': go, 'np': np})
            
            exec(code, {}, local_vars)
            
            return local_vars.get('result', "❌ Nessun risultato generato dal codice.")
        else:
            return "🔑 API Key mancante. Vai su https://aistudio.google.com/app/apikey, crea una chiave gratuita e aggiungila in st.secrets come 'gemini_api_key'."
            
    except Exception as e:
        return f"🚨 Errore nell'analisi: {str(e)}"

# ==========================================================================
# 5. UI PRINCIPALE
# ==========================================================================
st.sidebar.title("🚀 EITA Dashboard")

# --- AI CHATBOT SIDEBAR ---
with st.sidebar:
    st.markdown("---")
    st.subheader("💬 AI Data Assistant")
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Ciao! Posso analizzare i dati caricati (Vendite, Promo, Acquisti). Chiedimi qualcosa!"}]

    with st.expander("Cronologia Chat", expanded=True):
        for msg in st.session_state.messages:
            st.chat_message(msg["role"]).write(msg["content"])

    if prompt := st.chat_input("Es: Top 5 clienti per fatturato?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)
        
        with st.spinner("Analisi in corso..."):
            ai_response = get_ai_response(prompt)
            
            if isinstance(ai_response, (pd.DataFrame, pd.Series)):
                st.session_state.messages.append({"role": "assistant", "content": "Ecco la tabella richiesta."})
                st.dataframe(ai_response, use_container_width=True)
            elif isinstance(ai_response, (go.Figure, px.bar.__class__)): 
                 st.session_state.messages.append({"role": "assistant", "content": "Ecco il grafico."})
                 st.plotly_chart(ai_response, use_container_width=True)
            else:
                st.session_state.messages.append({"role": "assistant", "content": str(ai_response)})
                st.chat_message("assistant").write(str(ai_response))
    st.markdown("---")

# Navigation
page = st.sidebar.radio("Navigazione:", ["📊 Vendite & Fatturazione", "🎁 Analisi Customer Promo", "📦 Analisi Acquisti"])
st.sidebar.markdown("---")

files, drive_error = get_drive_files_list()
if drive_error: st.sidebar.error(f"Errore Drive: {drive_error}")

# --------------------------------------------------------------------------
# PAGINA 1: VENDITE
# --------------------------------------------------------------------------
if page == "📊 Vendite & Fatturazione":
    df_sales = None
    if files:
        f_map = {f['name']: f for f in files}
        target = "From_Order_to_Invoice"
        idx = next((i for i,n in enumerate(f_map.keys()) if target.lower() in n.lower()), 0)
        sel_file = st.sidebar.selectbox("File Sorgente", list(f_map.keys()), index=idx)
        
        with st.spinner('Caricamento dati vendite...'):
            raw = load_dataset(f_map[sel_file]['id'], f_map[sel_file]['modifiedTime'])
            if raw is not None: 
                df_sales = smart_analyze_and_clean(raw, "Sales")
                st.session_state.global_df_sales = df_sales # PERSISTENZA GLOBALE

    if df_sales is not None:
        roles = guess_column_role(df_sales, "Sales")
        cols  = df_sales.columns.tolist()

        with st.sidebar.expander("⚙️ Configurazione Colonne", expanded=False):
            c_ent  = st.selectbox("Entità", cols, index=set_idx(roles['entity'], cols))
            c_cust = st.selectbox("Cliente", cols, index=set_idx(roles['customer'], cols))
            c_prod = st.selectbox("Prodotto", cols, index=set_idx(roles['product'], cols))
            c_euro = st.selectbox("Valore (€)", cols, index=set_idx(roles['euro'], cols))
            c_kg   = st.selectbox("Peso (Kg)", cols, index=set_idx(roles['kg'], cols))
            c_ct   = st.selectbox("Cartoni", cols, index=set_idx(roles['cartons'], cols))
            c_date = st.selectbox("Data Rif.", cols, index=set_idx(roles['date'], cols))

        df_glob = df_sales.copy()
        
        sel_ent = None
        if c_ent:
            ents = sorted(df_glob[c_ent].astype(str).unique())
            def_e = ents.index('EITA') if 'EITA' in ents else 0
            sel_ent = st.sidebar.selectbox("Entità / Società", ents, index=def_e)
            df_glob = df_glob[df_glob[c_ent].astype(str) == sel_ent]

        if c_date and pd.api.types.is_datetime64_any_dtype(df_glob[c_date]):
            d_s, d_e = safe_date_input("Periodo", datetime.date(2026,1,1), datetime.date(2026,1,31), "sales_d")
            df_glob = df_glob[(df_glob[c_date].dt.date >= d_s) & (df_glob[c_date].dt.date <= d_e)]

        with st.sidebar.form("sales_adv_filters"):
            exclude = [c_euro, c_kg, c_ct, c_date, c_ent]
            avail_f = [c for c in cols if c not in exclude]
            sel_fs  = st.multiselect("Filtri Aggiuntivi", avail_f)
            
            active_fs = {}
            for f in sel_fs:
                vals = sorted(df_sales[f].astype(str).unique())
                sel = st.multiselect(f"Valori per {f}", vals)
                if sel: active_fs[f] = sel
            
            if st.form_submit_button("Applica Filtri"):
                for f, v in active_fs.items():
                    df_glob = df_glob[df_glob[f].astype(str).isin(v)]

        st.title(f"Performance: {sel_ent if sel_ent else 'Global'}")
        
        if not df_glob.empty:
            k_euro, k_kg = df_glob[c_euro].sum(), df_glob[c_kg].sum()
            k_ord = df_glob.shape[0]
            
            top_c = df_glob.groupby(c_cust)[c_euro].sum().sort_values(ascending=False).head(1)
            t_name = top_c.index[0] if not top_c.empty else "-"
            t_val  = top_c.values[0] if not top_c.empty else 0

            st.markdown(f"""
            <div class="kpi-grid">
                <div class="kpi-card"><div class="kpi-title">💰 Fatturato</div><div class="kpi-value">€ {k_euro:,.0f}</div></div>
                <div class="kpi-card"><div class="kpi-title">⚖️ Volume</div><div class="kpi-value">{k_kg:,.0f} Kg</div></div>
                <div class="kpi-card"><div class="kpi-title">📦 Righe Ordine</div><div class="kpi-value">{k_ord:,}</div></div>
                <div class="kpi-card"><div class="kpi-title">👑 Top Cliente</div><div class="kpi-value">{t_name[:15]}..</div><div class="kpi-subtitle">€ {t_val:,.0f}</div></div>
            </div>
            """, unsafe_allow_html=True)

            c_left, c_right = st.columns([1.2, 1.8])
            
            with c_left:
                st.subheader("📊 Analisi Focus")
                cust_grp = df_glob.groupby(c_cust)[c_euro].sum().sort_values(ascending=False)
                opts = ["🌍 TUTTI"] + cust_grp.index.tolist()
                tgt = st.selectbox("Seleziona Target:", opts)
                
                df_focus = df_glob if tgt == "🌍 TUTTI" else df_glob[df_glob[c_cust] == tgt]
                
                top_p = df_focus.groupby(c_prod)[c_euro].sum().sort_values(ascending=False).head(10).reset_index()
                fig = px.bar(top_p, y=c_prod, x=c_euro, orientation='h', text_auto='.2s', color=c_euro, color_continuous_scale='Blues')
                fig.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title="", yaxis_title="")
                st.plotly_chart(fig, use_container_width=True)

            with c_right:
                st.subheader("💥 Matrix Esplosione")
                with st.form("matrix_form"):
                    mode = st.radio("Raggruppa per:", ["Prodotto → Cliente", "Cliente → Prodotto"], horizontal=True)
                    all_p = sorted(df_focus[c_prod].unique())
                    all_c = sorted(df_focus[c_cust].unique())
                    f_p = st.multiselect("Filtra Prodotti Matrice", all_p)
                    f_c = st.multiselect("Filtra Clienti Matrice", all_c)
                    submitted = st.form_submit_button("Genera Matrice")

                if submitted or 'sales_mtx' in st.session_state:
                    if submitted:
                        d_mtx = df_focus.copy()
                        if f_p: d_mtx = d_mtx[d_mtx[c_prod].isin(f_p)]
                        if f_c: d_mtx = d_mtx[d_mtx[c_cust].isin(f_c)]
                        st.session_state['sales_mtx'] = d_mtx
                        st.session_state['mtx_mode'] = mode
                    
                    d_view = st.session_state.get('sales_mtx', df_focus)
                    m_view = st.session_state.get('mtx_mode', "Prodotto → Cliente")
                    
                    col_1 = c_prod if "Prodotto" in m_view else c_cust
                    col_2 = c_cust if "Prodotto" in m_view else c_prod
                    
                    # --- RESTORED MATRIX COLUMNS ---
                    master = d_view.groupby(col_1)[[c_ct, c_kg, c_euro]].sum().sort_values(c_euro, ascending=False).reset_index()
                    master['Valore Medio €/Kg'] = np.where(master[c_kg] > 0, master[c_euro] / master[c_kg], 0)
                    master['Valore Medio €/CT'] = np.where(master[c_ct] > 0, master[c_euro] / master[c_ct], 0)

                    st.dataframe(
                        master, 
                        column_config={
                            'Valore Medio €/Kg': st.column_config.NumberColumn("€/Kg", format="€ %.2f"),
                            'Valore Medio €/CT': st.column_config.NumberColumn("€/CT", format="€ %.2f")
                        },
                        use_container_width=True, hide_index=True
                    )
                    
                    sel_m = st.selectbox(f"Dettaglio per {col_1}:", master[col_1].unique())
                    if sel_m:
                        detail = d_view[d_view[col_1] == sel_m].groupby(col_2)[[c_ct, c_kg, c_euro]].sum().sort_values(c_euro, ascending=False).reset_index()
                        detail['Valore Medio €/Kg'] = np.where(detail[c_kg] > 0, detail[c_euro] / detail[c_kg], 0)
                        detail['Valore Medio €/CT'] = np.where(detail[c_ct] > 0, detail[c_euro] / detail[c_ct], 0)
                        
                        st.markdown(f"**Dettaglio: {sel_m}**")
                        st.dataframe(
                            detail, 
                            column_config={
                                'Valore Medio €/Kg': st.column_config.NumberColumn("€/Kg", format="€ %.2f"),
                                'Valore Medio €/CT': st.column_config.NumberColumn("€/CT", format="€ %.2f")
                            },
                            use_container_width=True, hide_index=True
                        )
                        
                    full_flat = d_view.groupby([col_1, col_2])[[c_ct, c_kg, c_euro]].sum().reset_index()
                    full_flat['Valore Medio €/Kg'] = np.where(full_flat[c_kg] > 0, full_flat[c_euro] / full_flat[c_kg], 0)
                    full_flat['Valore Medio €/CT'] = np.where(full_flat[c_ct] > 0, full_flat[c_euro] / full_flat[c_ct], 0)
                    st.download_button("📥 Scarica Report Matrice", convert_df_to_excel(full_flat), "Matrix_Report.xlsx")

# --------------------------------------------------------------------------
# PAGINA 2: PROMO
# --------------------------------------------------------------------------
elif page == "🎁 Analisi Customer Promo":
    st.title("🎁 Analisi Customer Promo")
    
    df_promo, df_sales_p = None, None
    if files:
        f_map = {f['name']: f for f in files}
        k_p = next((k for k in f_map if "customer_promo" in k.lower()), None)
        if k_p: 
            with st.spinner("Caricamento Promo..."):
                df_promo = smart_analyze_and_clean(load_dataset(f_map[k_p]['id'], f_map[k_p]['modifiedTime']), "Promo")
                st.session_state.global_df_promo = df_promo # PERSISTENZA GLOBALE
        
        k_s = next((k for k in f_map if "from_order" in k.lower()), None)
        if k_s:
            with st.spinner("Integrazione Vendite..."):
                df_sales_p = smart_analyze_and_clean(load_dataset(f_map[k_s]['id'], f_map[k_s]['modifiedTime']), "Sales")
                st.session_state.global_df_sales = df_sales_p # PERSISTENZA GLOBALE

    if df_promo is not None:
        roles_p = guess_column_role(df_promo, "Promo")
        cols_p  = df_promo.columns.tolist()
        
        with st.sidebar.expander("⚙️ Colonne Promo", expanded=False):
            cp_div = st.selectbox("Div", cols_p, index=set_idx(roles_p['division'], cols_p))
            cp_start = st.selectbox("Data Inizio", cols_p, index=set_idx(roles_p['start_date'], cols_p))
            cp_cust = st.selectbox("Cliente", cols_p, index=set_idx(roles_p['customer'], cols_p))
            cp_prod = st.selectbox("Prodotto", cols_p, index=set_idx(roles_p['product'], cols_p))
            cp_qty_f = st.selectbox("Q.Prev", cols_p, index=set_idx(roles_p['qty_forecast'], cols_p))
            cp_qty_a = st.selectbox("Q.Act", cols_p, index=set_idx(roles_p['qty_actual'], cols_p))
            cp_status = st.selectbox("Stato", cols_p, index=set_idx(roles_p['status'], cols_p))

        df_p_view = df_promo.copy()
        
        # --- RESTORED PROMO ADVANCED FILTERS ---
        if cp_div in df_p_view:
            divs = sorted(df_p_view[cp_div].unique())
            sel_div = st.sidebar.selectbox("Divisione", divs, index=divs.index(21) if 21 in divs else 0)
            df_p_view = df_p_view[df_p_view[cp_div] == sel_div]

        if cp_start and pd.api.types.is_datetime64_any_dtype(df_p_view[cp_start]):
            mi, ma = df_p_view[cp_start].min(), df_p_view[cp_start].max()
            if pd.notnull(mi):
                ds, de = safe_date_input("Periodo Sell-In", mi, ma, "promo_date")
                df_p_view = df_p_view[(df_p_view[cp_start].dt.date >= ds) & (df_p_view[cp_start].dt.date <= de)]

        with st.sidebar.form("promo_advanced_filters"):
            # Stato Promozione
            if cp_status in df_p_view.columns:
                stati = sorted(df_p_view[cp_status].dropna().unique().tolist())
                def_s = [20] if 20 in stati else ([str(20)] if str(20) in stati else stati)
                sel_stati = st.multiselect("Stato Promozione", stati, default=def_s)
            else:
                sel_stati = []
            
            # Filtri Dinamici
            exclude_p = [cp_qty_f, cp_qty_a, cp_start, cp_div, cp_status]
            avail_p = [c for c in cols_p if c not in exclude_p]
            sel_fp  = st.multiselect("Filtri Aggiuntivi Promo", avail_p)
            
            active_fp = {}
            for f in sel_fp:
                vals = sorted(df_promo[f].astype(str).unique())
                sel = st.multiselect(f"Valori per {f}", vals)
                if sel: active_fp[f] = sel

            apply_promo = st.form_submit_button("Applica Filtri Promo")

        # Applicazione Filtri Promo
        if apply_promo or sel_stati:
             if cp_status in df_p_view.columns and sel_stati:
                 df_p_view = df_p_view[df_p_view[cp_status].isin(sel_stati)]
             for f, v in active_fp.items():
                 df_p_view = df_p_view[df_p_view[f].astype(str).isin(v)]

        tot_promos = df_p_view[roles_p['promo_id']].nunique() if roles_p['promo_id'] else len(df_p_view)
        t_for, t_act = df_p_view[cp_qty_f].sum(), df_p_view[cp_qty_a].sum()
        hit_rate = (t_act / t_for * 100) if t_for > 0 else 0

        st.markdown(f"""
        <div class="kpi-grid">
            <div class="kpi-card promo-card"><div class="kpi-title">🎯 Attive</div><div class="kpi-value">{tot_promos}</div></div>
            <div class="kpi-card promo-card"><div class="kpi-title">📈 Forecast</div><div class="kpi-value">{t_for:,.0f}</div></div>
            <div class="kpi-card promo-card"><div class="kpi-title">🛒 Actual</div><div class="kpi-value">{t_act:,.0f}</div></div>
            <div class="kpi-card promo-card"><div class="kpi-title">⚡ Hit Rate</div><div class="kpi-value">{hit_rate:.1f}%</div></div>
        </div>
        """, unsafe_allow_html=True)
        st.divider()

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📊 Vendite: Promo vs Normale")
            if df_sales_p is not None:
                req_cols = ['Sconto7_Promozionali', 'Sconto4_Free', 'Peso_Netto_TotRiga', 'Qta_Cartoni_Ordinato']
                ent_col_candidates = ['Entity', 'Società', 'Company', 'Division', 'Azienda']
                found_ent = next((c for c in ent_col_candidates if c in df_sales_p.columns), None)

                if all(c in df_sales_p.columns for c in req_cols) and found_ent:
                    ents = sorted(df_sales_p[found_ent].astype(str).unique())
                    def_ent = ['EITA'] if 'EITA' in ents else []
                    sel_ent_chart = st.multiselect("1. Filtra Entità (Pre-filtro)", ents, default=def_ent, key="promo_chart_ent_fix")
                    
                    df_s_chart = df_sales_p.copy()
                    if sel_ent_chart:
                        df_s_chart = df_s_chart[df_s_chart[found_ent].astype(str).isin(sel_ent_chart)]
                    
                    with st.form("promo_chart_filters"):
                        fp_prods = sorted(df_s_chart['Descr_Articolo'].astype(str).unique())
                        fp_custs = sorted(df_s_chart['Decr_Cliente_Fat'].astype(str).unique())
                        sel_p = st.multiselect("2. Articolo", fp_prods)
                        sel_c = st.multiselect("3. Cliente", fp_custs)
                        st.form_submit_button("Aggiorna Grafico")
                    
                    if sel_p: df_s_chart = df_s_chart[df_s_chart['Descr_Articolo'].astype(str).isin(sel_p)]
                    if sel_c: df_s_chart = df_s_chart[df_s_chart['Decr_Cliente_Fat'].astype(str).isin(sel_c)]

                    df_s_chart['Tipo'] = np.where(
                        (df_s_chart['Sconto7_Promozionali'] != 0) | (df_s_chart['Sconto4_Free'] != 0),
                        'Promo', 'Normale'
                    )
                    stats = df_s_chart.groupby('Tipo')['Peso_Netto_TotRiga'].sum().reset_index()
                    if not stats.empty:
                        fig_pie = px.pie(stats, values='Peso_Netto_TotRiga', names='Tipo', hole=0.4, 
                                       color='Tipo', color_discrete_map={'Promo':'#FF6B6B', 'Normale':'#4ECDC4'})
                        st.plotly_chart(fig_pie, use_container_width=True)
                    else:
                        st.warning("Nessun dato vendite trovato con i filtri correnti.")
                else:
                    st.warning("Colonne necessarie (Sconti o Entità) mancanti nel file Vendite.")
            else:
                st.info("File vendite non disponibile per confronto.")

        with c2:
            st.subheader("Top Promo (Volume)")
            if df_p_view is not None:
                top_pr = df_p_view.groupby("Descrizione Promozione")[cp_qty_a].sum().sort_values(ascending=False).head(8).reset_index()
                fig_bar = px.bar(top_pr, x=cp_qty_a, y="Descrizione Promozione", orientation='h', color=cp_qty_a, color_continuous_scale='Purp')
                fig_bar.update_layout(yaxis={'autorange':'reversed'}, xaxis_title="", yaxis_title="")
                st.plotly_chart(fig_bar, use_container_width=True)

        st.subheader("Dettaglio Promo")
        st.dataframe(df_p_view[[cp_cust, cp_prod, cp_qty_f, cp_qty_a]].head(100), use_container_width=True)

# --------------------------------------------------------------------------
# PAGINA 3: ACQUISTI
# --------------------------------------------------------------------------
elif page == "📦 Analisi Acquisti":
    st.title("📦 Analisi Acquisti")
    
    df_purch = None
    if files:
        f_map = {f['name']: f for f in files}
        k_pu = next((k for k in f_map if "purchase" in k.lower()), None)
        if k_pu:
            with st.spinner("Caricamento Acquisti..."):
                raw_pu = load_dataset(f_map[k_pu]['id'], f_map[k_pu]['modifiedTime'])
                if raw_pu is not None:
                    df_purch = smart_analyze_and_clean(raw_pu, "Purchase")
                    if 'Kg acquistati' not in df_purch.columns and 'Row amount' in df_purch.columns and 'Purchase price' in df_purch.columns:
                        df_purch['Kg acquistati'] = np.where(df_purch['Purchase price'] > 0, df_purch['Row amount'] / df_purch['Purchase price'], 0)
                    st.session_state.global_df_purch = df_purch # PERSISTENZA GLOBALE
    
    if df_purch is not None:
        roles_pu = guess_column_role(df_purch, "Purchase")
        cols_pu = df_purch.columns.tolist()

        with st.sidebar.expander("⚙️ Colonne Acquisti", expanded=False):
            cpu_div = st.selectbox("Division", cols_pu, index=set_idx(roles_pu['division'], cols_pu))
            cpu_date = st.selectbox("Data Ordine", cols_pu, index=set_idx(roles_pu['order_date'], cols_pu))
            cpu_supp = st.selectbox("Fornitore", cols_pu, index=set_idx(roles_pu['supplier'], cols_pu))
            cpu_amt = st.selectbox("Importo", cols_pu, index=set_idx(roles_pu['amount'], cols_pu))
            cpu_kg = st.selectbox("Kg", cols_pu, index=set_idx(roles_pu['kg'], cols_pu))

        df_pu_glob = df_purch.copy()
        
        # --- RESTORED PURCHASE ADVANCED FILTERS ---
        if cpu_div in df_pu_glob.columns:
            divs = sorted(df_pu_glob[cpu_div].astype(str).unique())
            idx_021 = divs.index("021") if "021" in divs else (divs.index("21") if "21" in divs else 0)
            sel_d = st.sidebar.selectbox("Divisione", divs, index=idx_021)
            df_pu_glob = df_pu_glob[df_pu_glob[cpu_div].astype(str) == sel_d]

        if cpu_date and pd.api.types.is_datetime64_any_dtype(df_pu_glob[cpu_date]):
            mi, ma = df_pu_glob[cpu_date].min(), df_pu_glob[cpu_date].max()
            if pd.notnull(mi):
                ds, de = safe_date_input("Periodo Ordini", mi, ma, "pu_date")
                df_pu_glob = df_pu_glob[(df_pu_glob[cpu_date].dt.date >= ds) & (df_pu_glob[cpu_date].dt.date <= de)]

        with st.sidebar.form("purch_adv_filters"):
            # Filtro Fornitori Esplicito
            if cpu_supp in df_pu_glob.columns:
                all_s = sorted(df_pu_glob[cpu_supp].dropna().unique())
                sel_s = st.multiselect("Fornitori", all_s)
            else: sel_s = []

            # Filtri Dinamici
            exclude_pu = [cpu_div, cpu_date, cpu_supp, cpu_amt, cpu_kg]
            avail_pu = [c for c in cols_pu if c not in exclude_pu]
            sel_fpu  = st.multiselect("Filtri Aggiuntivi Acquisti", avail_pu)
            
            active_fpu = {}
            for f in sel_fpu:
                vals = sorted(df_purch[f].astype(str).unique())
                sel = st.multiselect(f"Valori per {f}", vals)
                if sel: active_fpu[f] = sel
            
            apply_pu = st.form_submit_button("Applica Filtri Acquisti")

        if apply_pu or sel_s:
            if sel_s: df_pu_glob = df_pu_glob[df_pu_glob[cpu_supp].isin(sel_s)]
            for f, v in active_fpu.items():
                df_pu_glob = df_pu_glob[df_pu_glob[f].astype(str).isin(v)]

        tot_eur = df_pu_glob[cpu_amt].sum() if cpu_amt else 0
        tot_wgt = df_pu_glob[cpu_kg].sum() if cpu_kg else 0
        
        st.markdown(f"""
        <div class="kpi-grid">
            <div class="kpi-card purch-card"><div class="kpi-title">💸 Spesa Totale</div><div class="kpi-value">€ {tot_eur:,.0f}</div></div>
            <div class="kpi-card purch-card"><div class="kpi-title">⚖️ Kg Totali</div><div class="kpi-value">{tot_wgt:,.0f}</div></div>
        </div>
        """, unsafe_allow_html=True)
        
        c_trend, c_bar = st.columns(2)
        with c_trend:
            st.subheader("📅 Trend Temporale")
            valid_chart = False
            if cpu_date and cpu_amt:
                try:
                    if not pd.api.types.is_datetime64_any_dtype(df_pu_glob[cpu_date]):
                         df_pu_glob[cpu_date] = pd.to_datetime(df_pu_glob[cpu_date], errors='coerce')
                    
                    df_chart = df_pu_glob.dropna(subset=[cpu_date])
                    if not df_chart.empty:
                        trend = df_chart.groupby(pd.Grouper(key=cpu_date, freq='ME'))[cpu_amt].sum().reset_index()
                        fig_t = px.line(trend, x=cpu_date, y=cpu_amt, markers=True)
                        st.plotly_chart(fig_t, use_container_width=True)
                        valid_chart = True
                except: pass
            if not valid_chart: st.caption("Dati temporali insufficienti per il grafico.")

        with c_bar:
            st.subheader("🏆 Top Fornitori")
            if cpu_supp and cpu_amt:
                top_s = df_pu_glob.groupby(cpu_supp)[cpu_amt].sum().sort_values(ascending=False).head(10).reset_index()
                fig_s = px.bar(top_s, y=cpu_supp, x=cpu_amt, orientation='h', color=cpu_amt)
                fig_s.update_layout(yaxis={'autorange':'reversed'})
                st.plotly_chart(fig_s, use_container_width=True)

        st.subheader("Dettaglio Ordini")
        show = ['Purchase order', cpu_date, cpu_supp, 'Part description', 'Order quantity', cpu_amt]
        show = [c for c in show if c in df_pu_glob.columns]
        st.dataframe(df_pu_glob[show], use_container_width=True)
        st.download_button("📥 Scarica Excel", convert_df_to_excel(df_pu_glob[show]), "Acquisti.xlsx")
