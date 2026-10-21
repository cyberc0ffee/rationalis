# Crea tests/fixtures/sintetico.dpm: un database Jet 3.x (Access 97) con la struttura DEDOTTA degli
# archivi DPM 5 (vedi notes/dpm_format.md). Serve solo a provare la lettura del formato Jet 3:
# i nomi delle colonne non sono verificati su un archivio reale.
# Va eseguito con PowerShell a 32 bit (il provider Jet OLEDB 4.0 esiste solo a 32 bit):
#   C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -File make_dpm_fixture.ps1
$ErrorActionPreference = "Stop"
$path = Join-Path $PSScriptRoot "sintetico.dpm"
if (Test-Path $path) { Remove-Item $path }
$conn = "Provider=Microsoft.Jet.OLEDB.4.0;Data Source=$path;Jet OLEDB:Engine Type=4"
$cat = New-Object -ComObject ADOX.Catalog
$cat.Create($conn) | Out-Null
$db = $cat.ActiveConnection
$sql = @(
  "CREATE TABLE T_Valute (ValutaID INTEGER, Valuta TEXT(4), [Desc] TEXT(50), Cambio DOUBLE, Principale BIT)",
  "CREATE TABLE T_Gruppi (GruppoID INTEGER, [Desc] TEXT(50), tpo INTEGER, InUso BIT)",
  "CREATE TABLE T_SottoGruppi (SottogruppoID INTEGER, GruppoID INTEGER, [Desc] TEXT(50), InUso BIT)",
  "CREATE TABLE T_Risorse (RisorsaID INTEGER, [Desc] TEXT(50), ValutaID INTEGER, SaldoIni CURRENCY, LimiteAttivo BIT, LimiteInf CURRENCY, LimiteSup CURRENCY, RisorsaLinkID INTEGER, InUso BIT)",
  "CREATE TABLE T_Modalita (ModalitaID INTEGER, [Desc] TEXT(50))",
  "CREATE TABLE T_Soggetti (SoggettoID INTEGER, [Desc] TEXT(50), InUso BIT)",
  "CREATE TABLE T_Destinazioni (DestinazioneID INTEGER, [Desc] TEXT(50), InUso BIT)",
  "CREATE TABLE T_Mov (MovID INTEGER, dta DATETIME, GruppoID INTEGER, SottogruppoID INTEGER, RisorsaID INTEGER, ModalitaID INTEGER, DestinazioneID INTEGER, SoggettoID INTEGER, Entrata CURRENCY, Usc CURRENCY, sal TEXT(1), [Desc] TEXT(80), Rif TEXT(30), C TEXT(1), Giroconto INTEGER, ScadenzaID INTEGER)",
  "CREATE TABLE T_Scadenze (ScadenzaID INTEGER, [Desc] TEXT(80))",
  "INSERT INTO T_Valute VALUES (1, 'Eur', 'Euro', 1, True)",
  "INSERT INTO T_Valute VALUES (2, 'US$', 'Dollaro USA', 0.9104, False)",
  "INSERT INTO T_Gruppi VALUES (1, 'Stipendi', 1, True)",
  "INSERT INTO T_Gruppi VALUES (2, 'Alimentari', 2, True)",
  "INSERT INTO T_Gruppi VALUES (3, 'Caffè e bar', 2, False)",
  "INSERT INTO T_SottoGruppi VALUES (1, 2, 'Macelleria', True)",
  "INSERT INTO T_Risorse VALUES (1, 'Cassa', 1, 100, False, 0, 0, 0, True)",
  "INSERT INTO T_Risorse VALUES (2, 'Banca c/c 15001', 1, 2500.5, True, -1000, 100000, 0, True)",
  "INSERT INTO T_Risorse VALUES (3, 'Visa', 1, 0, True, -1500, 0, 2, True)",
  "INSERT INTO T_Modalita VALUES (1, 'Bancomat')",
  "INSERT INTO T_Soggetti VALUES (1, 'Sonia', True)",
  "INSERT INTO T_Destinazioni VALUES (1, 'Vacanze', True)",
  "INSERT INTO T_Mov VALUES (1, #3/10/2002#, 1, 0, 2, 0, 0, 0, 1350, 0, '*', 'Stipendio marzo', '', '', 0, 0)",
  "INSERT INTO T_Mov VALUES (2, #5/2/2002#, 2, 1, 1, 0, 1, 1, 0, 43, '*', 'Macelleria € e città', '', 'A', 0, 0)",
  "INSERT INTO T_Mov VALUES (3, #5/3/2002#, 3, 0, 3, 0, 0, 0, 0, 2.6, Null, 'Caffè', '', '', 0, 0)",
  "INSERT INTO T_Mov VALUES (4, #5/4/2002#, 0, 0, 2, 1, 0, 0, 0, 250, '*', 'Prelievo', '', '', 7, 0)",
  "INSERT INTO T_Mov VALUES (5, #5/4/2002#, 0, 0, 1, 0, 0, 0, 250, 0, '*', 'Prelievo', '', '', 7, 0)",
  "INSERT INTO T_Scadenze VALUES (1, 'Rata auto')"
)
foreach ($s in $sql) { $db.Execute($s) | Out-Null }
$db.Close()
Write-Output "creato $path"
