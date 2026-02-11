import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import datetime
import traceback

# --- 1. CONFIGURAZIONE & STILE ---
st.set_page_config(
    page_title="EITA Analytics v19",
    page_icon="🛡️",
    layout="wide"
)

st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 1px solid #e0e0e0;
        border-left: 5px solid #004e92;
        padding: 10px;
        border-radius: 8px;
    }
    h1, h2, h3 {color: #004e92 !important;}
</style>
""", unsafe_allow_html=True)

# --- 2. GESTORE DATI (CACHE OTTIMIZZATA) ---
@st.cache_data(ttl=300)
def get_drive_files_list():
    try:
        if "google_cloud" not in st.secrets:
            return None, "Configurazione mancante nei Secrets."
        creds = service_account.Credentials.from_service_account_info(st.secrets["google_cloud"])
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["folder_id"]
        query = f"'{folder_id}' in parents and (mimeType contains 'spreadsheet' or name contains '.xlsx' or name contains '.csv') and trashed = false"
        results = service.files().list(q=query, fields="files(id, name, modifiedTime)").execute()
        return results.get('files', []), service
    except Exception as e:
        return None, str(e)

@st.cache_data(show_spinner="Lettura file...", ttl=600)
def load_and_optimize_data(file_id, modified_time, _service):
    try:
        request = _service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        
        # Caricamento leggero
        if file_id.endswith('.csv'):
            df = pd.read_csv(fh)
        else:
            df = pd.read_excel(fh)
            
        # OTTIMIZZAZIONE MEMORIA: Trasforma tipi pesanti in leggeri
        for col in df.columns:
            if df[col].dtype == 'float64':
                df[col] = df[col].astype('float32')
            if df[col].dtype == 'int64':
                df[col] = df[col].astype('int32')
        return df
    except Exception as e:
        st.error(f"Errore caricamento file: {e}")
        return None

# --- 3. LOGICA PRINCIPALE ---
def main():
    st.sidebar.title("💎 Control Panel v19")
    
    files, service = get_drive_files_list()
    if not files:
        st.error("Nessun file trovato nel Drive.")
        return

    file_map = {f['name']: f for f in files}
    # Pre-seleziona il file corretto se esiste
    target_name = next((n for n in file_map.keys() if "From_Order_to_Invoice" in n), list(file_map.keys())[0])
    sel_file = st.sidebar.selectbox("1. Seleziona Sorgente", list(file_map.keys()), index=list(file_map.keys()).index(target_name))
    
    df_raw = load_and_optimize_data(file_map[sel_file]['id'], file_map[sel_file]['modifiedTime'], service)
    
    if df_raw is not None:
        try:
            # --- MAPPATURA COLONNE ---
            cols = df_raw.columns.tolist()
            with st.sidebar.expander("2. Verifica Mappatura", expanded=False):
                c_eur = st.selectbox("Valore €", cols, index=cols.index('Importo_Netto_TotRiga') if 'Importo_Netto_TotRiga' in cols else 0)
                c_kg = st.selectbox("Peso Kg", cols, index=cols.index('Peso_Netto_TotRiga') if 'Peso_Netto_TotRiga' in cols else 0)
                c_cart = st.selectbox("Cartoni", cols, index=cols.index('Qta_Cartoni_Ordinato') if 'Qta_Cartoni_Ordinato' in cols else 0)
                c_cust = st.selectbox("Cliente", cols, index=cols.index('Descr_Cliente_Fat') if 'Descr_Cliente_Fat' in cols else 0)
                c_prod = st.selectbox("Prodotto", cols, index=cols.index('Descr_Articolo') if 'Descr_Articolo' in cols else 0)
                c_data = st.selectbox("Data", cols, index=cols.index('Data_Ordine') if 'Data_Ordine' in cols else 0)
                c_ent = st.selectbox("Entity", cols, index=cols.index('Entity') if 'Entity' in cols else 0)

            # --- PULIZIA DATI ---
            df = df_raw.copy()
            # Forza numeri
            for c in [c_eur, c_kg, c_cart]:
                df[c] = pd.to_numeric(df[c].astype(str).str.replace('€','').str.replace(' ','').str.replace('.','').str.replace(',','.'), errors='coerce').fillna(0)
            # Forza date
            df[c_data] = pd.to_datetime(df[c_data], dayfirst=True, errors='coerce')
            # Forza testo
            df[c_cust] = df[c_cust].astype(str).fillna("N/A")
            df[c_prod] = df[c_prod].astype(str).fillna("N/A")

            # --- FILTRI ---
            st.sidebar.subheader("3. Filtri")
            # Entity
            ents = sorted(df[c_ent].unique().astype(str))
            sel_ent = st.sidebar.selectbox("Entità", ents, index=ents.index('EITA') if 'EITA' in ents else 0)
            df = df[df[c_ent].astype(str) == sel_ent]
            
            # Data
            d_min, d_max = datetime.date(2026,1,1), datetime.date(2026,1,31)
            sel_dates = st.sidebar.date_input("Periodo", [d_min, d_max])
            if len(sel_dates) == 2:
                df = df[(df[c_data].dt.date >= sel_dates[0]) & (df[c_data].dt.date <= sel_dates[1])]

            # --- DASHBOARD ---
            st.title(f"📊 Dashboard: {sel_ent}")
            
            if df.empty:
                st.warning("Nessun dato trovato per i filtri selezionati.")
                return

            # KPI
            k1, k2, k3, k4 = st.columns(4)
            tot_eur = df[c_eur].sum()
            k1.metric("Fatturato Totale", f"€ {tot_eur:,.2f}")
            k2.metric("Quantità (Kg)", f"{df[c_kg].sum():,.0f}")
            k3.metric("N° Ordini", df['Numero_Ordine'].nunique() if 'Numero_Ordine' in df.columns else len(df))
            
            top_c = df.groupby(c_cust)[c_eur].sum().sort_values(ascending=False).head(1)
            k4.metric("Top Cliente", str(top_client_name := top_c.index[0] if not top_c.empty else "N/A")[:15], f"€ {top_c.values[0] if not top_c.empty else 0:,.0f}")

            st.divider()

            # DRILL DOWN
            col_l, col_r = st.columns([1, 2])
            
            with col_l:
                st.subheader("Analisi Prodotti")
                # Lista clienti ordinata
                cust_list = df.groupby(c_cust)[c_eur].sum().sort_values(ascending=False)
                options = ["TUTTI I CLIENTI"] + cust_list.index.tolist()
                
                sel_target = st.selectbox("Seleziona Target (Ricerca attiva):", options)
                
                df_target = df if sel_target == "TUTTI I CLIENTI" else df[df[c_cust] == sel_target]
                
                # Grafico
                prod_agg = df_target.groupby(c_prod).agg({c_eur:'sum', c_kg:'sum', c_cart:'sum'}).reset_index().sort_values(c_eur, ascending=False).head(10)
                
                chart_mode = st.radio("Formato:", ["Barre", "Torta"], horizontal=True)
                if chart_mode == "Barre":
                    fig = px.bar(prod_agg, x=c_eur, y=c_prod, orientation='h', text_auto='.2s', color_discrete_sequence=['#004e92'])
                    fig.update_layout(yaxis=dict(autorange="reversed"), height=400, margin=dict(l=0,r=0,t=0,b=0))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    fig = px.pie(prod_agg, values=c_eur, names=c_prod, hole=0.4)
                    fig.update_traces(textposition='outside', textinfo='percent+label')
                    st.plotly_chart(fig, use_container_width=True)

            with col_r:
                if sel_target == "TUTTI I CLIENTI":
                    st.subheader("💥 Dettaglio Vendite per Prodotto")
                    all_p = df_target.groupby(c_prod)[c_eur].sum().sort_values(ascending=False)
                    sel_p = st.selectbox("Esplora chi compra:", all_p.index.tolist())
                    
                    df_p = df_target[df_target[c_prod] == sel_p]
                    res = df_p.groupby(c_cust).agg({c_cart:'sum', c_kg:'sum', c_eur:'sum'}).reset_index().sort_values(c_eur, ascending=False)
                    st.dataframe(res, column_config={c_eur: st.column_config.NumberColumn("Valore", format="€ %.2f")}, use_container_width=True, hide_index=True)
                else:
                    st.subheader(f"Dettaglio Acquisti: {sel_target}")
                    res = df_target.groupby(c_prod).agg({c_cart:'sum', c_kg:'sum', c_eur:'sum'}).reset_index().sort_values(c_eur, ascending=False)
                    st.dataframe(res, column_config={c_eur: st.column_config.NumberColumn("Valore", format="€ %.2f")}, use_container_width=True, hide_index=True)

        except Exception as e:
            st.error("⚠️ Si è verificato un errore nei calcoli.")
            with st.expander("Visualizza Dettagli Tecnici (Copia questo per l'assistenza)"):
                st.code(traceback.format_exc())

if __name__ == "__main__":
    main()