import streamlit as st
import pandas as pd
import plotly.express as px
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

# --- CONFIGURAZIONE DELLA PAGINA ---
# Imposta il layout largo e il titolo della scheda del browser
st.set_page_config(
    page_title="Architetto Dashboard Pro",
    page_icon="📊",
    layout="wide"
)

# --- FUNZIONE DI CONNESSIONE A GOOGLE DRIVE ---
# Usiamo la cache per non sovraccaricare le API di Google (aggiornamento ogni 10 min)
@st.cache_data(ttl=600)
def scarica_dati_da_drive():
    try:
        # 1. Recupero credenziali dai secrets di Streamlit
        if "google_cloud" not in st.secrets or "folder_id" not in st.secrets:
            st.error("Configurazione mancante nel file secrets.toml!")
            return None, None, None

        info_credenziali = st.secrets["google_cloud"]
        folder_id = st.secrets["folder_id"]
        
        # 2. Autenticazione con il Service Account
        creds = service_account.Credentials.from_service_account_info(info_credenziali)
        service = build('drive', 'v3', credentials=creds)

        # 3. Ricerca dell'ultimo file Excel o CSV nella cartella specificata
        query = f"'{folder_id}' in parents and (mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or mimeType = 'text/csv') and trashed = false"
        risultati = service.files().list(
            q=query, 
            fields="files(id, name, modifiedTime, mimeType)",
            orderBy="modifiedTime desc"
        ).execute()
        
        elenco_file = risultati.get('files', [])

        if not elenco_file:
            st.warning("Nessun file trovato nella cartella Drive.")
            return None, None, None

        # Prendiamo il file più recente in assoluto
        file_recente = elenco_file[0]
        id_file = file_recente['id']
        nome_file = file_recente['name']
        data_modifica = file_recente['modifiedTime']

        # 4. Download del file in memoria (senza salvarlo su disco)
        richiesta = service.files().get_media(fileId=id_file)
        buffer = io.BytesIO()
        scaricatore = MediaIoBaseDownload(buffer, richiesta)
        
        completato = False
        while not completato:
            _, completato = scaricatore.next_chunk()

        buffer.seek(0)
        
        # 5. Lettura del file con Pandas
        if nome_file.endswith('.csv'):
            df = pd.read_csv(buffer)
        else:
            df = pd.read_excel(buffer)
            
        return df, nome_file, data_modifica

    except Exception as e:
        st.error(f"Errore durante il caricamento: {str(e)}")
        return None, None, None

# --- INTERFACCIA UTENTE (UI) ---
st.title("📊 BI Dashboard: Google Drive Sync")
st.markdown("Questa dashboard si aggiorna automaticamente con l'ultimo file caricato su Drive.")

# Sidebar per informazioni e controlli
with st.sidebar:
    st.header("⚙️ Impostazioni")
    if st.button("🔄 Forza Aggiornamento"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("Architetto Dashboard Pro v1.0")

# Caricamento effettivo dei dati
df, nome_file, ultima_mod = scarica_dati_da_drive()

if df is not None:
    # Mostra dettagli del file nella sidebar
    st.sidebar.success(f"Connesso a: {nome_file}")
    st.sidebar.info(f"Ultima modifica: {ultima_mod}")

    # --- KPI E METRICHE ---
    col1, col2, col3 = st.columns(3)
    
    # Identifica colonne numeriche per i calcoli
    colonne_num = df.select_dtypes(include=['number']).columns.tolist()
    
    with col1:
        st.metric("Totale Righe", len(df))
    with col2:
        if colonne_num:
            somma = df[colonne_num[0]].sum()
            st.metric(f"Somma {colonne_num[0]}", f"{somma:,.0f}")
    with col3:
        st.metric("Stato", "Sincronizzato")

    st.divider()

    # --- VISUALIZZAZIONI ---
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Distribuzione Dati")
        # Crea un grafico basato sulle colonne disponibili
        colonne_testo = df.select_dtypes(include=['object']).columns.tolist()
        if colonne_testo and colonne_num:
            fig_pie = px.pie(df, names=colonne_testo[0], values=colonne_num[0], 
                             hole=0.4, template="plotly_white")
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("Dati insufficienti per generare il grafico a torta.")

    with c2:
        st.subheader("Analisi Trend / Quantità")
        if colonne_num:
            fig_hist = px.histogram(df, x=colonne_num[0], nbins=30, 
                                   template="plotly_dark", color_discrete_sequence=['#636EFA'])
            st.plotly_chart(fig_hist, use_container_width=True)

    # --- TABELLA DATI ---
    with st.expander("🔍 Esplora i dati grezzi"):
        st.dataframe(df, use_container_width=True)

else:
    st.warning("In attesa dei dati... Controlla che il file secrets.toml sia configurato correttamente.")
    st.info("💡 Ricordati di condividere la cartella Drive con l'email del Service Account!")
