🛠 Risoluzione Problemi di Condivisione Drive
Se ricevi l'errore "L'account non esiste" o non riesci ad accedere alla Admin Console, segui questi passaggi nell'ordine esatto:
1. Verifica l'indirizzo email (Errore di Sintassi)
Assicurati che l'email del Service Account sia esattamente quella che vedi nella Cloud Console.
 * Spesso l'errore "Account non Google" appare se c'è uno spazio vuoto alla fine del testo quando lo incolli nel box di condivisione di Drive.
 * L'email deve terminare con .iam.gserviceaccount.com.
2. La "Via del Link" (Se la condivisione diretta fallisce)
Se la tua organizzazione blocca l'invito ad account esterni:
 * Clicca col tasto destro sulla cartella su Google Drive.
 * Scegli Condividi.
 * In basso, sotto "Accesso generale", cambia da "Con limitazioni" a "Chiunque abbia il link".
 * Imposta il ruolo a Visualizzatore.
 * Clicca su Fine.
Nota sulla sicurezza: Poiché conosciamo l'ID della cartella nel codice, la dashboard funzionerà. L'ID è una stringa di circa 33 caratteri casuali: è virtualmente impossibile che qualcuno la indovini se non ha il link.
3. Differenza tra Account Personale e Business
 * Se hai @https://www.google.com/url?sa=E&source=gmail&q=gmail.com: Non hai una Admin Console. Usa il metodo "Chiunque abbia il link".
 * Se hai @https://www.google.com/search?q=tuaazienda.com: Devi chiedere all'amministratore IT di abilitare la "Condivisione esterna" o usare il metodo del link sopra citato.
4. Test del Service Account
Se hai già il file JSON delle credenziali, il Service Account è attivo. Non serve "entrare" nell'account, serve solo che la cartella Drive "accetti" le sue chiamate.
