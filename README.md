# Rationalis

Gestione e analisi finanziaria personale e aziendale: risorse (cassa, conti, carte), movimenti di entrata
e uscita, giroconti, scadenzario, disponibilità e proiezioni. Importa gli archivi di Danea Professional
Manager 5 e i movimenti da Excel.

Reimplementazione indipendente scritta da zero a partire dalla specifica funzionale
(`notes/spec.md` del laboratorio), senza codice, testi o grafica del programma originale.

## Avvio
- Doppio clic su **`Avvia Rationalis.bat`**, oppure
- `python -m rationalis [archivio.rtl]`

Requisiti: Python 3.11+ con `PySide6`, `openpyxl`, `access-parser`, `cryptography` (`pip install -e .[test]`).

Gli archivi (`.rtl`, file SQLite) vanno di default in `Documenti\Rationalis\archivi`, le copie di
sicurezza (`.rtz`, zip) in `Documenti\Rationalis\copie`.

## Versione portabile (senza installazione)
`python tools_build/build_portable.py` crea `dist/Rationalis/` (con `Rationalis.exe`, circa 150 MB) e
`dist/Rationalis-<versione>-portabile-win64.zip` (circa 60 MB), e verifica l'eseguibile con `--prova-avvio`.
Sul PC di destinazione basta estrarre lo zip e avviare `Rationalis.exe`: Python e librerie sono inclusi.
Con un file `PORTABILE.txt` accanto all'eseguibile impostazioni e archivi restano nella cartella `Dati\`
del programma (uso da chiavetta). Dettagli per l'utente in `tools_build/LEGGIMI.txt`, copiato nella cartella.

## macOS
Il codice è multipiattaforma; l'app per Mac va però costruita su un Mac (PyInstaller non fa compilazione
incrociata). Partire da `dist/Rationalis-<versione>-sorgente.zip` (creato con `tools_build/make_source_zip.py`):
- **solo usarlo**: doppio clic su `Avvia Rationalis.command` (al primo avvio crea `.venv` e installa le librerie;
  serve Python 3.11+ da python.org);
- **creare l'app**: `python3 -m pip install --only-binary=cryptography -r requirements.txt pyinstaller pillow` e poi
  `python3 tools_build/build_portable.py` → `dist/Rationalis.app`, `.dmg` e `.zip` (architettura del Mac usato:
  arm64 su Apple Silicon, x86_64 su Intel);
- **senza Mac**: il flusso `.github/workflows/build.yml` costruisce su GitHub Actions le versioni macOS arm64,
  macOS Intel e Windows, con test e prova dell'eseguibile.

L'app non è firmata né autenticata da Apple: al primo avvio clic destro › Apri (dettagli in
`tools_build/LEGGIMI_macOS.txt`). Per la distribuzione senza avvisi servono un Apple Developer ID e la notarizzazione.

## Funzioni (versione 1.0)
| Area | Contenuto |
|---|---|
| Archivi | nuovo (con gruppi e risorse iniziali), apri, recenti, copie di sicurezza e ripristino, copia automatica alla chiusura; gli archivi delle versioni precedenti si aggiornano da soli all'apertura |
| Codice d'accesso | protezione facoltativa dell'archivio: il file è cifrato (AES-256-GCM, chiave da scrypt), il database in chiaro esiste solo in memoria; senza codice nessun programma può leggerlo; le copie di sicurezza restano cifrate |
| Pagina d'avvio | benvenuto personalizzabile, situazione delle risorse, avvisi del giorno (note dell'agenda, movimenti scaduti), prossime scadenze, per iniziare; sezioni e apertura configurabili |
| Tabelle | gruppi (entrata/uscita/misto) e sottogruppi, risorse e modalità di pagamento, valute con valuta principale, destinazioni, soggetti, descrizioni frequenti, raggruppamenti; voci «in uso»; voci usate non cancellabili |
| Movimenti | griglia mensile per risorsa o per tutte; inserimento con completamento; calcolatrice negli importi (F2); colonne configurabili; ordinamento; taglia/copia/incolla in altro mese; duplica ultimo (F9); elimina (Maiusc+Canc); inverti saldo (F3); sposta in altra data; trova (Ctrl+F); vai al nuovo (F12); scala di visualizzazione (F5…F8); mese precedente/successivo (Ctrl+PgSu/PgGiù) |
| Operazioni | giroconti (1 prelievo, fino a 3 versamenti anche in valute diverse, controllo dello sbilancio), addebito spese carta di credito con commissioni, variazioni automatiche, cancellazione di tutti i movimenti |
| Scadenzario | movimenti o giroconti ripetuti ogni n giorni/settimane/mesi, giorno del mese, ultimo giorno, «primo lunedì» ecc.; fine per data o numero di volte; le modifiche toccano solo i non saldati |
| Analisi | totali del mese; disponibilità correnti, giornaliere, andamento e proiezione; elenco movimenti filtrati con ricerche salvate; riepiloghi su 3 periodi o 12 mesi; grafici a barre o torta; monitor statistiche; budget, prospetto annuale e scostamenti; elenco gruppi e sottogruppi |
| Strumenti | calcolatrice (quattro operazioni con ripetizione, percentuali, IVA, 5 cambi configurabili, nastro, sempre in primo piano), conversione valute, calcolo rendimenti RIN/REN, rubrica (per soggetto, ricerca, stampa completa/ridotta/minirubrica, esportazione), agenda con promemoria, annotazioni del mese, schede libere con moltiplicatore |
| Stampe | elenco movimenti, griglia vuota, ogni prospetto, rubrica, schede: anteprima, stampante o PDF; orientamento, margini, linee, bianco e nero, centratura, adatta alla pagina o percentuale; intestazione e piè di pagina con codici `&L &C &R &D &T &P &N &B &I &U &nn`; impostazioni salvate per tipo di stampa |
| Import/export | archivi DPM 5 (`.dpm`, `.dpz` zip) – **struttura da validare su un archivio reale**; import da Excel; export movimenti Excel/testo/HTML (reimportabile); ogni prospetto in Excel con numeri veri |

Regole delle analisi: i giroconti non sono né entrate né uscite; salvo filtro diverso contano solo i movimenti
saldati; importi di risorse diverse sono sommati in valuta principale al cambio corrente. Il budget vale per
ogni anno (12 importi mensili per gruppo); lo scostamento è movimenti − budget con segno, quindi positivo
significa meno spesa o più entrata del previsto.

Non realizzati (fuori specifica o da decidere): inserimento guidato «passo passo» per principianti,
stampa dei grafici (si esporta la tabella), guida in linea, composizione telefonica via modem (il pulsante ☎
copia il numero e lo passa all'applicazione telefonica di sistema), import da Easyfatt e Family Manager 4.

Nota sul codice d'accesso: proteggendo un archivio esistente, il vecchio file in chiaro viene sostituito ma i
suoi dati potrebbero restare recuperabili dal disco con strumenti forensi; per dati delicati conviene creare
l'archivio e proteggerlo subito.

## Test
```
python -m pytest
```
`tests/fixtures/sintetico.dpm` è un database Jet 3 costruito con la struttura dedotta degli archivi DPM
(`tests/fixtures/make_dpm_fixture.ps1`, PowerShell a 32 bit): verifica la lettura del formato, non la
corrispondenza esatta con gli archivi reali.
