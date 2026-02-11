import streamlit as st
import pandas as pd
import plotly.express as px
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

# --- CONFIGURAZIONE DELLA PAGINA ---
st.set_page_config(
    page_title="Architetto Dashboard Pro",
    page_icon="📊",
    layout="wide"
)

# --- FUNZIONE DI CONNESSIONE E LISTA FILE ---
@st.cache_data(ttl=600)
def ottieni_lista_file():
    try:
        if "google_cloud" not in st.secrets or "folder_id" not in st.secrets:
            return None, "config_missing"

        creds = service_account.Credentials.from_service_account_info(st.secrets["google_cloud"])
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["folder_id"]

        # Cerchiamo tutti i file Excel e CSV nella cartella
        query = f"'{folder_id}' in parents and (mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or mimeType = 'text/csv' or mimeType = 'application/vnd.ms-excel') and trashed = false"
        risultati = service.files().list(
            q=query, 
            fields="files(id, name, modifiedTime, mimeType)", 
            orderBy="modifiedTime desc"
        ).execute()
        
        return risultati.get('files', []), service
    except Exception as e:
        return str(e), None

# --- FUNZIONE DOWNLOAD FILE SELEZIONATO ---
def scarica_file_specifico(service, file_id, nome_file, mime_type):
    try:
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        scaricatore = MediaIoBaseDownload(buffer, request)
        
        completato = False
        while not completato:
            _, completato = scaricatore.next_chunk()
        buffer.seek(0)
        
        if nome_file.endswith('.csv'):
            return pd.read_csv(buffer)
        else:
            return pd.read_excel(buffer)
    except Exception as e:
        st.error(f"Errore nel download del file: {e}")
        return None

# --- INTERFACCIA UTENTE (UI) ---
st.title("📊 Cloud BI Dashboard: Analisi Multi-File")

# Sidebar: Gestione Connessione e Selezione
with st.sidebar:
    st.header("⚙️ Sorgente Dati")
    elenco_file, service = ottieni_lista_file()

    if isinstance(elenco_file, list) and elenco_file:
        opzioni_file = {f['name']: f for f in elenco_file}
        scelta_nome = st.selectbox("Seleziona il file da analizzare:", list(opzioni_file.keys()))
        file_selezionato = opzioni_file[scelta_nome]
        
        st.divider()
        if st.button("🔄 Forza Ricaricamento"):
            st.cache_data.clear()
            st.rerun()
    else:
        st.warning("Nessun file trovato o errore di configurazione.")
        file_selezionato = None

# Caricamento dati del file scelto
if file_selezionato and service:
    df = scarica_file_specifico(
        service, 
        file_selezionato['id'], 
        file_selezionato['name'], 
        file_selezionato['mimeType']
    )

    if df is not None:
        # --- METRICHE HEADER ---
        st.sidebar.success(f"Analizzando: {file_selezionato['name']}")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Righe Totali", len(df))
        
        colonne_num = df.select_dtypes(include=['number']).columns.tolist()
        colonne_testo = df.columns.tolist() # Tutte per dare massima libertà

        if colonne_num:
            col2.metric("Media Valori", f"{df[colonne_num[0]].mean():,.2f}")
        col3.metric("Colonne", len(df.columns))

        st.divider()

        # --- GRAFICI INTERATTIVI ---
        st.subheader(f"📈 Visualizzazione: {file_selezionato['name']}")
        c1, c2 = st.columns(2)

        with c1:
            st.write("### Distribuzione e Proporzioni")
            if len(colonne_testo) >= 1:
                cat = st.selectbox("Scegli la categoria (Giri/Nomi/Stati):", colonne_testo, key="cat_sel")
                val = st.selectbox("Scegli il valore (Numeri):", colonne_num if colonne_num else colonne_testo, key="val_sel")
                
                fig_pie = px.pie(df, names=cat, values=val, hole=0.4, 
                                 template="plotly_white", color_discrete_sequence=px.colors.qualitative.Safe)
                st.plotly_chart(fig_pie, use_container_width=True)

        with c2:
            st.write("### Confronto e Trend")
            if colonne_num:
                x_axis = st.selectbox("Asse Orizzontale (X):", colonne_testo, index=min(1, len(colonne_testo)-1), key="x_axis")
                y_axis = st.selectbox("Asse Verticale (Y):", colonne_num, key="y_axis")
                
                fig_bar = px.bar(df, x=x_axis, y=y_axis, template="plotly_dark", 
                                 color_discrete_sequence=['#00D4FF'])
                st.plotly_chart(fig_bar, use_container_width=True)

        # --- TABELLA DETTAGLIATA ---
        with st.expander("🔍 Esamina la tabella completa dei dati"):
            st.dataframe(df, use_container_width=True)
else:
    st.info("Seleziona un file dalla barra laterale per iniziare l'analisi.")
