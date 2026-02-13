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
# 1. CONFIGURAZIONE & STILE (v41.3 - Upgraded Acquisti Page + Fixes)
# ==========================================================================
st.set_page_config(
    page_title="EITA Analytics Pro v41.3",
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
        background: rgba(130,150,200,0.1); backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(130,150,200,0.2); border-radius: 16px;
        padding: 1.5rem; box-shadow: 0 8px 32px 0 rgba(0,0,0,0.05);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        position: relative; overflow: hidden;
    }
    .kpi-card:hover {
        transform: translateY(-5px); box-shadow: 0 12px 40px 0 rgba(0,0,0,0.15);
        border: 1px solid rgba(130,150,200,0.4);
    }
    .kpi-card::before {
        content:""; position:absolute; left:0; top:0; height:100%; width:6px;
        background:linear-gradient(180deg,#00c6ff,#0072ff);
        border-radius:16px 0 0 16px;
    }
    .kpi-card.promo-card::before { background:linear-gradient(180deg,#ff9a9e,#fecfef); }
    .kpi-card.purch-card::before { background:linear-gradient(180deg,#43e97b,#38f9d7); }
    .kpi-title  { font-size:0.9rem; font-weight:600; text-transform:uppercase;
                  letter-spacing:1px; opacity:0.8; margin-bottom:0.5rem; }
    .kpi-value  { font-size:2rem; font-weight:800; line-height:1.2; }
    .kpi-subtitle { font-size:0.8rem; opacity:0.6; margin-top:0.3rem; }
    .stPlotlyChart { filter:drop-shadow(4px 6px 8px rgba(0,0,0,0.2));
                     transition:all 0.3s ease; }
    .stPlotlyChart:hover { filter:drop-shadow(6px 10px 12px rgba(0,0,0,0.3)); }
    .detail-section {
        background-color:#f8f9fa; border-left:5px solid #00c6ff;
        padding:15px; margin-top:20px; border-radius:4px;
    }
    @media (max-width:768px) {
        .block-container { padding-left:0.5rem !important;
                           padding-right:0.5rem !important;
                           padding-top:1rem !important; }
        .kpi-grid { gap:0.8rem; }
        .kpi-value { font-size:1.6rem; }
        .kpi-card  { padding:1.2rem; }
    }
</style>
""", unsafe_allow_html=True)


# ==========================================================================
# 2. GOOGLE API SERVICE
# ==========================================================================

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


@st.cache_resource
def get_google_service():
    if "google_cloud" not in st.secrets:
        return None, "Secrets 'google_cloud' non trovati in .streamlit/secrets.toml"

    try:
        sa_info = dict(st.secrets["google_cloud"])
        if "private_key" in sa_info:
            sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")

        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=_DRIVE_SCOPES
        )

        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return service, None

    except Exception as e:
        return None, f"Errore credenziali Google: {e}"


@st.cache_data(ttl=300)
def get_drive_files_list():
    try:
        service, svc_error = get_google_service()
        if service is None:
            return None, svc_error or "Service non disponibile"

        folder_id = st.secrets.get("folder_id", "")
        if not folder_id:
            return None, "Secret 'folder_id' mancante in secrets.toml"

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
        return results.get("files", []), None

    except Exception as e:
        return None, str(e)


@st.cache_data(show_spinner=False)
def load_dataset(file_id, modified_time):
    try:
        service, _ = get_google_service()
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


# ==========================================================================
# 3. UTILITY FUNCTIONS
# ==========================================================================

def convert_df_to_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    df_export = df.reset_index() if isinstance(df.index, pd.MultiIndex) else df.copy()

    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Dati')
            wb  = writer.book
            ws  = writer.sheets['Dati']
            hdr = wb.add_format({'bold': True, 'bg_color': '#f0f0f0',
                                 'border': 1, 'text_wrap': True, 'valign': 'vcenter'})
            num = wb.add_format({'num_format': '#,##0.0000'})
            for c_num, val in enumerate(df_export.columns.values):
                ws.write(0, c_num, val, hdr)
            for i, col in enumerate(df_export.columns):
                series_len = df_export[col].astype(str).map(len)
                col_max    = int(series_len.max()) if not series_len.empty else 0
                final_len  = min(max(col_max, len(str(col))) + 5, 60)
                if pd.api.types.is_numeric_dtype(df_export[col]):
                    ws.set_column(i, i, final_len, num)
                else:
                    ws.set_column(i, i, final_len)
    except ModuleNotFoundError:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Dati')
    return output.getvalue()


@st.cache_data(show_spinner=False)
def smart_analyze_and_clean(df_in: pd.DataFrame, page_type: str = "Sales") -> pd.DataFrame:
    df = df_in.copy()

    if page_type == "Sales":
        target_numeric  = {'Importo_Netto_TotRiga', 'Peso_Netto_TotRiga',
                           'Qta_Cartoni_Ordinato', 'Prezzo_Netto',
                           'Sconto7_Promozionali', 'Sconto4_Free'}
        protected_text  = {'Descr_Cliente_Fat', 'Descr_Cliente_Dest', 'Descr_Articolo',
                           'Entity', 'Ragione Sociale', 'Decr_Cliente_Fat'}
    elif page_type == "Promo":
        target_numeric  = {'Quantità prevista', 'Quantità ordinata',
                           'Importo sconto', 'Sconto promo'}
        protected_text  = {'Descrizione Cliente', 'Descrizione Prodotto',
                           'Descrizione Promozione', 'Riferimento', 'Tipo promo',
                           'Codice prodotto', 'Key Account', 'Decr_Cliente_Fat', 'Week start'}
    elif page_type == "Purchase":
        target_numeric  = {'Order quantity', 'Received quantity', 'Invoice quantity',
                           'Invoice amount', 'Row amount', 'Purchase price',
                           'Kg acquistati', 'Exchange rate', 'Line amount', 'Part net weight'}
        protected_text  = {'Supplier name', 'Part description', 'Part group description',
                           'Part class description', 'Division', 'Facility', 'Warehouse',
                           'Supplier number', 'Part number', 'Purchase order'}
    else:
        target_numeric = protected_text = set()

    SKIP_COLS = {'Numero_Pallet', 'Sovrapponibile', 'COMPANY'}

    for col in df.columns:
        if col in SKIP_COLS:
            continue

        if any(t in col for t in protected_text):
            if col == 'Division':
                df[col] = (df[col].astype(str)
                               .str.replace(r'\.0$', '', regex=True)
                               .str.zfill(3))
            else:
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

        is_target = any(t in col for t in target_numeric)

        if not is_target:
            numeric_like = sum(
                1 for s in sample
                if len(s) > 0 and sum(c.isdigit() for c in s) / len(s) >= 0.5
            )
            looks_numeric = (numeric_like / len(sample) >= 0.6) and (page_type != "Purchase")
        else:
            looks_numeric = True

        if is_target or looks_numeric:
            try:
                clean = (df[col].astype(str)
                                .str.replace('€', '', regex=False)
                                .str.replace('%', '', regex=False)
                                .str.replace(' ', '', regex=False))
                if clean.str.contains(',', regex=False).any():
                    clean = (clean.str.replace('.', '', regex=False)
                                  .str.replace(',', '.', regex=False))
                converted = pd.to_numeric(clean, errors='coerce')
                if is_target or converted.notna().sum() / len(converted) > 0.7:
                    df[col] = converted.fillna(0)
            except Exception:
                pass
    return df


def guess_column_role(df: pd.DataFrame, page_type: str = "Sales") -> dict:
    cols = df.columns.tolist()

    if page_type == "Purchase":
        defaults = {'supplier': None, 'order_date': None, 'amount': None,
                    'kg': None, 'division': None, 'product': None, 'category': None}
        rules = {
            'supplier':   ['Supplier name', 'Supplier number'],
            'order_date': ['Purchase order date', 'Date of receipt'],
            'amount':     ['Invoice amount', 'Total Invoice amount', 'Line amount', 'Row amount'],
            'kg':         ['Kg acquistati'],
            'division':   ['Division'],
            'product':    ['Part description', 'Part number'],
            'category':   ['Part group description', 'Part group'],
        }
    elif page_type == "Sales":
        defaults = {'entity': None, 'customer': None, 'product': None,
                    'euro': None, 'kg': None, 'cartons': None, 'date': None}
        rules = {
            'euro':     ['Importo_Netto_TotRiga'],
            'kg':       ['Peso_Netto_TotRiga'],
            'cartons':  ['Qta_Cartoni_Ordinato'],
            'date':     ['Data_Ordine', 'Data_Fattura'],
            'entity':   ['Entity'],
            'customer': ['Decr_Cliente_Fat', 'Descr_Cliente_Fat', 'Descr_Cliente_Dest'],
            'product':  ['Descr_Articolo'],
        }
    elif page_type == "Promo":
        defaults = {'promo_id': None, 'promo_desc': None, 'customer': None,
                    'product': None, 'qty_forecast': None, 'qty_actual': None,
                    'start_date': None, 'status': None, 'division': None,
                    'type': None, 'week_start': None}
        rules = {
            'promo_id':    ['Numero Promozione'],
            'promo_desc':  ['Descrizione Promozione', 'Riferimento'],
            'customer':    ['Descrizione Cliente'],
            'product':     ['Descrizione Prodotto'],
            'qty_forecast':['Quantità prevista'],
            'qty_actual':  ['Quantità ordinata'],
            'start_date':  ['Sell in da'],
            'status':      ['Stato'],
            'division':    ['Division'],
            'type':        ['Tipo promo'],
            'week_start':  ['Week start'],
        }
    else:
        return {}

    guesses = dict(defaults)
    for role, targets in rules.items():
        for t in targets:
            if t in cols:
                guesses[role] = t
                break
    return guesses


def set_idx(guess, options: list) -> int:
    return options.index(guess) if guess in options else 0


def safe_date_input(label: str, default_start, default_end, key: str = None):
    result = st.sidebar.date_input(
        label, [default_start, default_end], format="DD/MM/YYYY", key=key
    )
    if isinstance(result, (list, tuple)):
        return (result[0], result[1]) if len(result) == 2 else (result[0], result[0])
    return result, result


def render_kpi_cards(cards: list, card_class: str = "") -> None:
    items = "".join(
        f'<div class="kpi-card {card_class}">'
        f'  <div class="kpi-title">{c["title"]}</div>'
        f'  <div class="kpi-value">{c["value"]}</div>'
        f'  <div class="kpi-subtitle">{c["subtitle"]}</div>'
        f'</div>'
        for c in cards
    )
    st.markdown(f'<div class="kpi-grid">{items}</div>', unsafe_allow_html=True)


# ==========================================================================
# 4. AI DATA ASSISTANT (Gemini - Limite righe aumentato a 500)
# ==========================================================================

def _get_gemini_client():
    try:
        api_key = st.secrets.get("gemini_api_key", "")
        if not api_key:
            return None, "Secret 'gemini_api_key' non trovato"
        genai.configure(api_key=api_key)
        
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=(
                "Sei un assistente dati esperto di business intelligence. "
                "Aiuti l'utente a interpretare dati aziendali di vendita, promozioni e acquisti. "
                "Rispondi sempre in italiano, in modo conciso e professionale. "
                "Se ti viene fornito un contesto dati (CSV/tabella), analizzalo e rispondi "
                "basandoti sui numeri reali. "
                "Evita risposte generiche: sii specifico e orientato all'azione."
            )
        )
        return model, None
    except Exception as e:
        return None, str(e)


def render_ai_assistant(context_df: pd.DataFrame = None, context_label: str = ""):
    st.sidebar.markdown("### 💬 AI Data Assistant")

    with st.sidebar.expander("Chat", expanded=False):
        if "ai_chat_history" not in st.session_state:
            st.session_state["ai_chat_history"] = []

        for msg in st.session_state["ai_chat_history"]:
            role_icon = "🧑" if msg["role"] == "user" else "🤖"
            st.markdown(f"**{role_icon}** {msg['text']}")

        if st.session_state["ai_chat_history"]:
            if st.button("🗑️ Pulisci chat", key="clear_ai_chat"):
                st.session_state["ai_chat_history"] = []
                st.rerun()

    user_input = st.sidebar.chat_input("Chiedi ai dati...", key="ai_chat_input")

    if user_input:
        model, err = _get_gemini_client()

        if model is None:
            st.sidebar.error(f"Gemini non disponibile: {err}")
            return

        context_text = ""
        if context_df is not None and not context_df.empty:
            sample = context_df.head(500)
            context_text = (
                "\n\nCONTESTO DATI ATTUALI ("
                + context_label
                + f", prime {len(sample)} righe di {len(context_df)} totali):\n"
                + sample.to_csv(index=False)
                + f"\nColonne: " + ", ".join(context_df.columns.tolist()) + "\n"
            )

        history = []
        for msg in st.session_state["ai_chat_history"]:
            history.append({
                "role": msg["role"],
                "parts": [msg["text"]]
            })

        try:
            chat = model.start_chat(history=history)
            full_prompt = user_input + context_text
            response = chat.send_message(full_prompt)
            answer = response.text

            if hasattr(response, 'usage_metadata'):
                st.sidebar.info(f"Token usati: Input {response.usage_metadata.prompt_token_count}, Output {response.usage_metadata.candidates_token_count}")

            st.session_state["ai_chat_history"].append({"role": "user", "text": user_input})
            st.session_state["ai_chat_history"].append({"role": "model", "text": answer})
            st.rerun()

        except Exception as e:
            st.sidebar.error(f"Errore Gemini: {e}")


# ==========================================================================
# 5. NAVIGAZIONE
# ==========================================================================
st.sidebar.title("🚀 EITA Dashboard")
st.sidebar.markdown("---")

_ai_ctx_df    = st.session_state.get("ai_context_df",    None)
_ai_ctx_label = st.session_state.get("ai_context_label", "Dati correnti")
render_ai_assistant(context_df=_ai_ctx_df, context_label=_ai_ctx_label)

st.sidebar.markdown("---")
st.sidebar.markdown("**Menu:**")
page = st.sidebar.radio(
    "",
    ["📊 Vendite & Fatturazione", "🎁 Analisi Customer Promo", "📦 Analisi Acquisti"],
    label_visibility="collapsed"
)
st.sidebar.markdown("---")

files, drive_error = get_drive_files_list()
if drive_error:
    st.sidebar.error(f"Errore Drive: {drive_error}")


# ==========================================================================
# PAGINA 1: VENDITE & FATTURAZIONE (mantenuta originale)
# ==========================================================================
if page == "📊 Vendite & Fatturazione":
    df_processed = None

    if files:
        file_map      = {f['name']: f for f in files}
        file_list     = list(file_map.keys())
        default_index = next(
            (i for i, n in enumerate(file_list) if "from_order_to_invoice" in n.lower()), 0
        )
        sel_file_name     = st.sidebar.selectbox("1. Sorgente Dati", file_list, index=default_index)
        selected_file_obj = file_map[sel_file_name]

        with st.spinner('Loading Sales Data...'):
            df_raw = load_dataset(selected_file_obj['id'], selected_file_obj['modifiedTime'])
            if df_raw is not None:
                df_processed = smart_analyze_and_clean(df_raw, "Sales")
    else:
        st.error("Nessun file trovato su Google Drive.")

    if df_processed is not None:
        guesses  = guess_column_role(df_processed, "Sales")
        all_cols = df_processed.columns.tolist()

        with st.sidebar.expander("⚙️ Mappatura Colonne", expanded=False):
            col_entity   = st.selectbox("Entità",                all_cols, index=set_idx(guesses.get('entity'),   all_cols))
            col_customer = st.selectbox("Cliente (Fatturazione)",all_cols, index=set_idx(guesses.get('customer'), all_cols))
            col_prod     = st.selectbox("Prodotto",              all_cols, index=set_idx(guesses.get('product'),  all_cols))
            col_euro     = st.selectbox("Valore (€)",            all_cols, index=set_idx(guesses.get('euro'),     all_cols))
            col_kg       = st.selectbox("Peso (Kg)",             all_cols, index=set_idx(guesses.get('kg'),       all_cols))
            col_cartons  = st.selectbox("Cartoni (Qty)",         all_cols, index=set_idx(guesses.get('cartons'),  all_cols))
            col_data     = st.selectbox("Data Riferimento",      all_cols, index=set_idx(guesses.get('date'),     all_cols))

        st.sidebar.markdown("### 🔍 Filtri Rapidi")
        df_global = df_processed.copy()
        sel_ent   = None

        if col_entity:
            ents    = sorted(df_global[col_entity].astype(str).unique())
            idx_e   = ents.index('EITA') if 'EITA' in ents else 0
            sel_ent = st.sidebar.selectbox("Società / Entità", ents, index=idx_e)
            df_global = df_global[df_global[col_entity].astype(str) == sel_ent]

        if col_data and pd.api.types.is_datetime64_any_dtype(df_global[col_data]):
            d_start, d_end = safe_date_input(
                "Periodo di Analisi",
                datetime.date(2026, 1, 1), datetime.date.today(),
                key="sales_date"
            )
            df_global = df_global[
                (df_global[col_data].dt.date >= d_start) &
                (df_global[col_data].dt.date <= d_end)
            ]

        with st.sidebar.form("advanced_filters_form"):
            possible_filters = [c for c in all_cols if c not in {col_euro, col_kg, col_cartons, col_data, col_entity}]
            filters_selected = st.multiselect("Aggiungi filtri (es. Vettore, Regione):", possible_filters)
            staged_filters: dict = {}
            for f_col in filters_selected:
                unique_vals = sorted(df_processed[f_col].astype(str).unique())
                sel_vals    = st.multiselect(f"Seleziona in {f_col}", unique_vals)
                if sel_vals:
                    staged_filters[f_col] = sel_vals
            apply_adv = st.form_submit_button("✅ Applica Filtri Avanzati")

        if apply_adv:
            st.session_state['sales_adv_filters'] = staged_filters
        active_filters = st.session_state.get('sales_adv_filters', {})
        for f_col, vals in active_filters.items():
            if f_col in df_global.columns:
                df_global = df_global[df_global[f_col].astype(str).isin(vals)]

        st.title(f"Performance Overview: {sel_ent or 'Global'}")

        st.session_state["ai_context_df"]    = df_global
        st.session_state["ai_context_label"] = f"Vendite {sel_ent or 'Global'}"

        if not df_global.empty:
            tot_euro    = df_global[col_euro].sum() if col_euro else 0
            tot_kg      = df_global[col_kg].sum() if col_kg else 0
            ord_num_col = next((c for c in df_global.columns if "Numero_Ordine" in c), None)
            tot_orders  = df_global[ord_num_col].nunique() if ord_num_col else len(df_global)
            top_c_data  = df_global.groupby(col_customer)[col_euro].sum().sort_values(ascending=False).head(1) if col_customer and col_euro else pd.Series()
            top_name    = top_c_data.index[0] if not top_c_data.empty else "-"
            top_val     = top_c_data.values[0] if not top_c_data.empty else 0
            short_top   = (str(top_name)[:20] + "..") if len(str(top_name)) > 20 else str(top_name)

            render_kpi_cards([
                {"title": "💰 Fatturato Netto",  "value": f"€ {tot_euro:,.0f}",  "subtitle": "Totale nel periodo selezionato"},
                {"title": "⚖️ Volume Totale",    "value": f"{tot_kg:,.0f} Kg",   "subtitle": "Peso netto cumulato"},
                {"title": "📦 Ordini Elaborati", "value": f"{tot_orders:,}",      "subtitle": "Transazioni uniche / Righe"},
                {"title": "👑 Top Customer",     "value": short_top,              "subtitle": f"Valore: € {top_val:,.0f}"},
            ])

            # Grafici e drill-down mantenuti (omessi per brevità - identici alla base)


# ==========================================================================
# PAGINA 2: ANALISI CUSTOMER PROMO (mantenuta originale)
# ==========================================================================
elif page == "🎁 Analisi Customer Promo":
    # Codice completo Promo identico alla v41.2 (omesso per brevità - copia dalla tua base)


# ==========================================================================
# PAGINA 3: ANALISI ACQUISTI (Upgraded)
# ==========================================================================
elif page == "📦 Analisi Acquisti":
    st.title("📦 Analisi Acquisti (Purchase History)")

    df_purch_processed = None

    if files:
        file_map       = {f['name']: f for f in files}
        file_list      = list(file_map.keys())
        default_idx_pu = next(
            (i for i, n in enumerate(file_list) if "purchase_orders_history" in n.lower()), 0
        )
        sel_purch_file = st.sidebar.selectbox("1. File Sorgente Acquisti", file_list, index=default_idx_pu)

        with st.spinner('Lettura file acquisti...'):
            df_purch_raw = load_dataset(
                file_map[sel_purch_file]['id'], file_map[sel_purch_file]['modifiedTime']
            )
            if df_purch_raw is not None:
                df_purch_processed = smart_analyze_and_clean(df_purch_raw, "Purchase")

                if 'Kg acquistati' not in df_purch_processed.columns:
                    if 'Invoice amount' in df_purch_processed.columns and 'Purchase price' in df_purch_processed.columns:
                        df_purch_processed['Kg acquistati'] = np.where(
                            df_purch_processed['Purchase price'] > 0,
                            df_purch_processed['Invoice amount'] / df_purch_processed['Purchase price'],
                            0
                        )
                    else:
                        df_purch_processed['Kg acquistati'] = 0

    if df_purch_processed is not None:
        guesses_pu  = guess_column_role(df_purch_processed, "Purchase")
        all_cols_pu = df_purch_processed.columns.tolist()

        df_pu_global = df_purch_processed.copy()
        st.sidebar.markdown("### 🔍 Filtri Dinamici su Tutte le Colonne")

        filtered_df = df_pu_global.copy()
        filter_state = st.session_state.get("purchase_filters", {})

        with st.sidebar.expander("Filtri per Colonna", expanded=True):
            for col in df_pu_global.columns:
                unique_vals = ["Tutti"] + sorted(df_pu_global[col].astype(str).dropna().unique().tolist())
                default_val = filter_state.get(col, "Tutti")
                default_idx = unique_vals.index(default_val) if default_val in unique_vals else 0
                selected = st.selectbox(f"{col}", unique_vals, index=default_idx, key=f"filter_{col}")
                filter_state[col] = selected
                if selected != "Tutti":
                    filtered_df = filtered_df[filtered_df[col].astype(str) == selected]

        st.session_state["purchase_filters"] = filter_state

        if 'Division' in filtered_df.columns and filter_state.get('Division', "Tutti") == "Tutti":
            if "021" in filtered_df['Division'].astype(str).unique():
                filtered_df = filtered_df[filtered_df['Division'].astype(str) == "021"]

        date_col = guesses_pu.get('order_date')
        if date_col and date_col in filtered_df.columns and pd.api.types.is_datetime64_any_dtype(filtered_df[date_col]):
            min_d, max_d = filtered_df[date_col].min().date(), filtered_df[date_col].max().date()
            if pd.notnull(min_d):
                d_start_pu, d_end_pu = safe_date_input(
                    "Periodo Ordini", min_d, max_d, key="purch_date"
                )
                filtered_df = filtered_df[
                    (filtered_df[date_col].dt.date >= d_start_pu) &
                    (filtered_df[date_col].dt.date <= d_end_pu)
                ]

        if not filtered_df.empty:
            st.session_state["ai_context_df"]    = filtered_df
            st.session_state["ai_context_label"] = "Acquisti"

        amount_col = guesses_pu.get('amount') or 'Invoice amount'
        kg_col = guesses_pu.get('kg') or 'Kg acquistati'
        if not filtered_df.empty:
            tot_invoice_pu = filtered_df[amount_col].sum() if amount_col in filtered_df.columns else 0
            tot_kg_pu      = filtered_df[kg_col].sum() if kg_col in filtered_df.columns else 0
            tot_orders_pu  = filtered_df['Purchase order'].nunique() if 'Purchase order' in filtered_df.columns else 0
            avg_price_kg   = (tot_invoice_pu / tot_kg_pu) if tot_kg_pu > 0 else 0

            render_kpi_cards([
                {"title": "💸 Spesa Totale",    "value": f"€ {tot_invoice_pu:,.0f}", "subtitle": "Totale Invoice Amount"},
                {"title": "⚖️ Volume Totale",   "value": f"{tot_kg_pu:,.0f} Kg",     "subtitle": "Kg acquistati (calcolati da Invoice/Price)"},
                {"title": "📦 Ordini Totali",   "value": str(tot_orders_pu),          "subtitle": "Numero Ordini Acquisto"},
                {"title": "🏷️ Prezzo Medio",   "value": f"€ {avg_price_kg:.2f}",    "subtitle": "Prezzo medio al Kg (Invoice / Kg)"},
            ], card_class="purch-card")

            st.divider()
            c1, c2 = st.columns(2)

            with c1:
                st.subheader("📅 Trend Spesa nel Tempo")
                if date_col in filtered_df.columns:
                    if not pd.api.types.is_datetime64_any_dtype(filtered_df[date_col]):
                        filtered_df[date_col] = pd.to_datetime(filtered_df[date_col], dayfirst=True, errors='coerce')
                        filtered_df = filtered_df.dropna(subset=[date_col])

                if (date_col and amount_col and pd.api.types.is_datetime64_any_dtype(filtered_df[date_col]) and not filtered_df.empty):
                    try:
                        trend_pu = filtered_df.groupby(pd.Grouper(key=date_col, freq='ME'))[amount_col].sum().reset_index()
                        fig_trend = px.line(trend_pu, x=date_col, y=amount_col, markers=True)
                        fig_trend.update_layout(height=400, xaxis_title="", yaxis_title="€ Spesa")
                        st.plotly_chart(fig_trend, use_container_width=True)
                    except Exception as e:
                        st.warning(f"Impossibile generare grafico temporale: {e}")

            with c2:
                st.subheader("🏆 Top Fornitori (per Spesa)")
                supplier_col = guesses_pu.get('supplier') or 'Supplier name'
                if supplier_col in filtered_df.columns and amount_col in filtered_df.columns:
                    top_supp = filtered_df.groupby(supplier_col)[amount_col].sum().sort_values(ascending=False).head(10).reset_index()
                    fig_supp = px.bar(top_supp, x=amount_col, y=supplier_col, orientation='h', color=amount_col, color_continuous_scale='Viridis')
                    fig_supp.update_layout(height=400, yaxis=dict(autorange="reversed"), xaxis_title="€ Spesa", yaxis_title="")
                    st.plotly_chart(fig_supp, use_container_width=True)

            st.subheader("📋 Dettaglio Righe Acquisto")

            all_columns = filtered_df.columns.tolist()
            default_columns = [c for c in ['Purchase order', 'Purchase order date', 'Supplier name', 'Part description', 'Part group description', 'Order quantity', 'Received quantity', 'Invoice amount', 'Kg acquistati'] if c in all_columns]

            with st.expander("⚙️ Seleziona e Ordina Colonne", expanded=False):
                selected_columns = st.multiselect("Seleziona colonne", options=all_columns, default=default_columns)
                if not selected_columns:
                    selected_columns = default_columns

                sort_col = st.selectbox("Ordina per", options=["Nessuno"] + selected_columns)
                sort_asc = st.checkbox("Crescente", value=False)
                if sort_col != "Nessuno":
                    filtered_df = filtered_df.sort_values(by=sort_col, ascending=sort_asc)

            search_term = st.text_input("🔍 Ricerca globale")
            if search_term:
                mask = np.column_stack([filtered_df[col].astype(str).str.contains(search_term, case=False, na=False) for col in selected_columns])
                filtered_df = filtered_df.loc[mask.any(axis=1)]

            st.dataframe(
                filtered_df[selected_columns],
                column_config={
                    'Purchase order date': st.column_config.DateColumn("Data Ordine"),
                    'Invoice amount': st.column_config.NumberColumn("Importo Fatt.", format="€ %.2f"),
                    'Kg acquistati': st.column_config.NumberColumn("Kg Calc.", format="%.0f"),
                    'Order quantity': st.column_config.NumberColumn("Qta Ord.", format="%.0f"),
                },
                use_container_width=True,
                height=600
            )

            st.download_button(
                "📥 Scarica Report Filtrato",
                data=convert_df_to_excel(filtered_df[selected_columns]),
                file_name=f"Report_Acquisti_Filtrato_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
