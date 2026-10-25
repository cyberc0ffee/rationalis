# Rationalis

Gestione e analisi finanziaria personale, familiare e per piccole attività, per **Windows e macOS**.
Risorse (cassa, conti, carte di credito), movimenti di entrata e uscita, giroconti anche tra valute
diverse, scadenzario, disponibilità e proiezioni, riepiloghi, grafici, budget, rubrica, agenda e stampe.
I dati restano sul tuo computer, in un file che puoi proteggere con un codice d'accesso (cifratura AES-256).

Interfaccia in italiano. Licenza [MIT](LICENSE).

## Scaricare (Windows)
Dalla pagina **Releases** del repository scaricare `Rationalis-<versione>-portabile-win64.zip`
(Windows 10/11, 64 bit), estrarlo e avviare `Rationalis.exe`. Non serve installare nulla: Python e le
librerie sono inclusi. L'eseguibile non è firmato: al primo avvio SmartScreen chiede «Ulteriori
informazioni» › «Esegui comunque» (dettagli in [`tools_build/LEGGIMI.txt`](tools_build/LEGGIMI.txt)).

Su **macOS** non ci sono pacchetti pronti: si avvia dal sorgente (vedi sotto) oppure si costruisce l'app
come descritto in [Pacchetti](#pacchetti).

## Avviare dal sorgente
Serve Python 3.11 o successivo.
```
pip install -r requirements.txt
python -m rationalis [archivio.rtl]
```
Su Windows c'è anche `Avvia Rationalis.bat`, su macOS `Avvia Rationalis.command` (al primo avvio crea un
ambiente `.venv` e installa le librerie).

Gli archivi (`.rtl`, database SQLite) vanno di default in `Documenti/Rationalis/archivi`, le copie di
sicurezza (`.rtz`, zip) in `Documenti/Rationalis/copie`. Lo stesso archivio si apre su Windows e su Mac.

## Funzioni
| Area | Contenuto |
|---|---|
| Archivi | nuovo (con gruppi e risorse iniziali), apri, recenti, copie di sicurezza e ripristino, copia automatica alla chiusura; gli archivi delle versioni precedenti si aggiornano da soli all'apertura |
| Codice d'accesso | protezione facoltativa: il file è cifrato (AES-256-GCM, chiave derivata con scrypt) e il database in chiaro esiste solo in memoria; anche le copie di sicurezza restano cifrate |
| Pagina d'avvio | benvenuto personalizzabile, situazione delle risorse, avvisi del giorno (note dell'agenda, movimenti scaduti), prossime scadenze |
| Tabelle | gruppi (entrata/uscita/misto) e sottogruppi, risorse e modalità di pagamento, valute con valuta principale, destinazioni, soggetti, descrizioni frequenti, raggruppamenti |
| Movimenti | griglia mensile per risorsa o per tutte; inserimento con completamento; calcolatrice negli importi (F2); colonne configurabili; ordinamento; taglia/copia/incolla in altro mese; duplica ultimo (F9); inverti saldo (F3); trova (Ctrl+F); vai al nuovo (F12); zoom (F5…F8) |
| Operazioni | giroconti (1 prelievo, fino a 3 versamenti, controllo dello sbilancio), addebito spese della carta di credito, variazioni automatiche |
| Scadenzario | movimenti o giroconti ripetuti ogni n giorni/settimane/mesi, giorno del mese, ultimo giorno, «primo lunedì» ecc.; le modifiche toccano solo i movimenti non ancora saldati |
| Analisi | totali del mese; disponibilità correnti, giornaliere, andamento e proiezione; elenco filtrato con ricerche salvate; riepiloghi su 3 periodi o 12 mesi; grafici; monitor statistiche; budget, prospetto annuale e scostamenti |
| Strumenti | calcolatrice (percentuali, IVA, cambi, nastro), conversione valute, rendimenti RIN/REN, rubrica, agenda con promemoria, annotazioni del mese, schede libere |
| Stampe | elenchi e prospetti con anteprima, stampante o PDF; orientamento, margini, linee, adattamento alla pagina; intestazione e piè di pagina con codici `&L &C &R &D &T &P &N &B &I &U` |
| Import/export | import da Excel; export movimenti in Excel/testo/HTML (reimportabile); ogni prospetto in Excel; import di archivi Danea Professional Manager 5 (vedi sotto) |

Regole delle analisi: i giroconti non sono né entrate né uscite; salvo filtro diverso contano solo i
movimenti saldati; importi di risorse diverse sono sommati in valuta principale al cambio corrente. Lo
scostamento di budget è movimenti − budget con segno: positivo significa meno spesa o più entrata del previsto.

Non realizzati: inserimento guidato per principianti, stampa dei grafici (si esporta la tabella), guida in
linea, composizione telefonica via modem (il pulsante ☎ passa il numero all'applicazione telefonica di sistema).

Nota sul codice d'accesso: proteggendo un archivio già esistente il vecchio file in chiaro viene sostituito,
ma i suoi dati potrebbero restare recuperabili dal disco con strumenti forensi; per dati delicati conviene
creare l'archivio e proteggerlo subito.

## Importazione da Danea Professional Manager 5
Rationalis può importare gli archivi `.dpm` (e le copie `.dpz` in formato zip) creati con Danea
Professional Manager 5, così da non perdere i propri dati cambiando programma. L'importatore legge il
database Microsoft Access/Jet contenuto nel file; la struttura delle tabelle è stata ricostruita ai soli
fini di interoperabilità e **non è ancora stata verificata su un archivio reale**: tutto ciò che non viene
riconosciuto è segnalato nel rapporto di importazione invece di andare perso in silenzio. Segnalazioni e
archivi di prova (senza dati personali) sono benvenuti.

## Sviluppo
```
pip install -r requirements.txt pytest
python -m pytest
```
`tests/fixtures/sintetico.dpm` è un database Jet 3 creato appositamente (`tests/fixtures/make_dpm_fixture.ps1`,
PowerShell a 32 bit) per provare la lettura del formato; non contiene dati reali.

### Pacchetti
`python tools_build/build_portable.py` (con `pip install pyinstaller pillow`) crea il pacchetto per il
sistema su cui gira, lo verifica avviandolo con `--prova-avvio` e produce lo zip (Windows) o `.dmg` e
`.zip` (macOS). PyInstaller non fa compilazione incrociata: le versioni per Mac si costruiscono su un Mac
oppure con il flusso [`.github/workflows/build.yml`](.github/workflows/build.yml) di GitHub Actions, che
costruisce e prova Windows, macOS Apple Silicon e macOS Intel. Su Mac Intel installare le dipendenze con
`--only-binary=cryptography`.

Modalità portabile: con un file `PORTABILE.txt` accanto all'eseguibile (o accanto a `Rationalis.app`)
impostazioni e archivi restano in una cartella `Dati` accanto al programma.

## Licenza e marchi
Rationalis è distribuito con licenza [MIT](LICENSE). Le librerie incluse nei pacchetti hanno le proprie
licenze, elencate in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (in particolare Qt/PySide6, LGPL-3.0).

Rationalis è un progetto indipendente, scritto da zero: non contiene codice, testi o grafica di altri
programmi e **non è affiliato, approvato o sponsorizzato da Danea Soft S.r.l. né da TeamSystem**.
«Danea», «Danea Professional Manager» ed «Easyfatt» sono marchi dei rispettivi titolari e sono citati
solo per indicare la compatibilità dei file importabili.
