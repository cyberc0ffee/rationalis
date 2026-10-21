"""Finestre degli strumenti (fase 3): conversione valute, rendimenti, rubrica, agenda, annotazioni del mese,
schede libere, codice d'accesso."""
from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QGuiApplication, QTextCharFormat
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCalendarWidget, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from .. import tools
from ..balances import convert
from ..db import Archive, ArchiveError, ValidationError
from ..finance import Investment, ren_from_rin
from ..money import ZERO, fmt_amount, parse_amount, parse_rate, round_to
from ..ui_text import long_date, month_name
from .common import AmountEdit, DateEdit, LookupCombo, ask, error, from_qdate, lookup_items, to_qdate
from .printing import print_table


# --- conversione valute ----------------------------------------------------------------------
class CurrencyConverterDialog(QDialog):
    """Un importo in una valuta, convertito subito in tutte le altre con i cambi della tabella."""

    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Conversione valute")
        self.valute = arc.rows("valute", order="principale DESC, sigla")
        self.edits: dict[int, AmountEdit] = {}
        form = QFormLayout()
        for v in self.valute:
            e = AmountEdit(4)
            e.textEdited.connect(lambda _t, vid=v["id"]: self._changed(vid))
            self.edits[v["id"]] = e
            form.addRow(f"{v['sigla']} – {v['nome']}" + ("  (principale)" if v["principale"] else ""), e)
        note = QLabel("Scrivere un importo in una valuta: le altre si aggiornano con i cambi della tabella valute.")
        note.setWordWrap(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addLayout(form)
        lay.addWidget(bb)

    def _changed(self, src: int):
        try:
            v = parse_amount(self.edits[src].text())
        except ValueError:
            return
        for vid, e in self.edits.items():
            if vid != src:
                e.set_value(round_to(convert(self.arc, v, src, vid), 4))


# --- rendimenti finanziari -------------------------------------------------------------------
class InvestmentsDialog(QDialog):
    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.current: int | None = None
        self.setWindowTitle("Calcolo rendimenti finanziari")
        self.resize(780, 460)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        self.nome = QLineEdit()
        self.ci, self.cf = AmountEdit(arc.decimals), AmountEdit(arc.decimals)
        self.di, self.df = DateEdit(), DateEdit()
        self.rend, self.tasse, self.bolli, self.spese = (AmountEdit(arc.decimals, allow_negative=False)
                                                          for _ in range(4))
        self.cap = QSpinBox()
        self.cap.setRange(1, 365)
        self.cap.setToolTip("Capitalizzazioni degli interessi in un anno (2 = semestrale) per il REN")
        form = QFormLayout()
        for label, w in (("Descrizione", self.nome), ("Capitale iniziale", self.ci), ("Data inizio", self.di),
                         ("Capitale finale", self.cf), ("Data fine", self.df), ("Rendite (interessi, cedole…)", self.rend),
                         ("Tasse", self.tasse), ("Bolli", self.bolli), ("Spese varie", self.spese),
                         ("Capitalizzazioni annue (REN)", self.cap)):
            form.addRow(label, w)
        for w in (self.ci, self.cf, self.rend, self.tasse, self.bolli, self.spese):
            w.textChanged.connect(self._calc)
        for w in (self.di, self.df):
            w.dateChanged.connect(self._calc)
        self.cap.valueChanged.connect(self._calc)
        self.out = QLabel()
        self.out.setTextFormat(Qt.TextFormat.RichText)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addWidget(self.out)
        right.addStretch()
        btns = QHBoxLayout()
        for text, fn in (("&Crea nuovo", self._new), ("&Salva", self._save), ("&Elimina", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        btns.addWidget(close)
        body = QHBoxLayout()
        body.addWidget(self.list, 2)
        body.addLayout(right, 3)
        lay = QVBoxLayout(self)
        lay.addLayout(body)
        lay.addLayout(btns)
        self._reload()

    def _reload(self, select: int | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.arc.rows("investimenti"):
            it = QListWidgetItem(r["nome"])
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.list.addItem(it)
            if r["id"] == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._select(self.list.currentItem())

    def _select(self, item, _prev=None):
        self.current = item.data(Qt.ItemDataRole.UserRole) if item else None
        if self.current is None:
            nome, inv, cap = "", Investment(ZERO, date.today(), ZERO, date.today()), 1
        else:
            nome, inv, cap = tools.load_investment(self.arc, self.current)
        self.nome.setText(nome)
        self.ci.set_value(inv.capitale_iniziale if self.current else None)
        self.cf.set_value(inv.capitale_finale if self.current else None)
        self.di.set_date(inv.data_inizio)
        self.df.set_date(inv.data_fine)
        for w, v in ((self.rend, inv.rendite), (self.tasse, inv.tasse), (self.bolli, inv.bolli),
                     (self.spese, inv.spese)):
            w.set_value(v if v else None)
        self.cap.setValue(cap)
        self._calc()

    def _inv(self) -> Investment:
        return Investment(self.ci.value(), self.di.value(), self.cf.value(), self.df.value(), self.rend.value(),
                          self.tasse.value(), self.bolli.value(), self.spese.value())

    def _calc(self, *_):
        dec = self.arc.decimals
        try:
            inv = self._inv()
            rin = inv.rin
            ren = ren_from_rin(rin, self.cap.value())
            self.out.setText(
                f"<table cellspacing=4><tr><td>Utile netto</td><td align=right><b>{fmt_amount(inv.utile_netto, dec)}</b></td></tr>"
                f"<tr><td>% utile netto</td><td align=right>{fmt_amount(inv.utile_percentuale, 2)}%</td></tr>"
                f"<tr><td>Giorni</td><td align=right>{inv.giorni}</td></tr>"
                f"<tr><td>RIN (tasso annuo di rendimento immediato netto)</td><td align=right><b>"
                f"{fmt_amount(rin, 2)}%</b></td></tr>"
                f"<tr><td>REN con {self.cap.value()} capitalizzazioni l'anno</td><td align=right><b>"
                f"{fmt_amount(ren, 2)}%</b></td></tr></table>")
        except (ValueError, ArithmeticError) as e:
            self.out.setText(f"<i>{e}</i>" if str(e) else "")

    def _new(self):
        self.list.setCurrentItem(None)
        self._select(None)
        self.nome.setFocus()

    def _save(self):
        try:
            self.current = tools.save_investment(self.arc, self.nome.text(), self._inv(), self.cap.value(),
                                                 self.current)
        except (ValueError, ArchiveError) as e:
            error(self, e)
            return
        self._reload(self.current)

    def _delete(self):
        if self.current and ask(self, "Eliminare il calcolo selezionato?"):
            self.arc.delete("investimenti", self.current)
            self._reload()


# --- rubrica ------------------------------------------------------------------------------------
class AddressBookDialog(QDialog):
    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.current: int | None = None
        self.letter: str | None = None
        self.setWindowTitle("Rubrica")
        self.resize(980, 620)
        self.view_for = LookupCombo()
        self.view_for.fill(lookup_items(arc, "soggetti"))
        self.view_for.setItemText(0, "tutti")
        self.view_for.currentIndexChanged.connect(lambda: self._reload())
        letters = QHBoxLayout()
        letters.setSpacing(1)
        for ch in ["Tutti"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)] + ["#"]:
            b = QToolButton()
            b.setText(ch)
            b.clicked.connect(lambda _=False, c=ch: self._set_letter(None if c == "Tutti" else c))
            letters.addWidget(b)
        letters.addStretch()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        self.w: dict[str, QWidget] = {}
        form = QGridLayout()

        def add(key, row, col, span=1, widget=None):
            w = widget or QLineEdit()
            self.w[key] = w
            form.addWidget(QLabel(tools.CONTACT_LABELS[key]), row, col * 2)
            form.addWidget(w, row, col * 2 + 1, 1, span * 2 - 1)

        add("nome", 0, 0, 3)
        add("riferimento", 1, 0, 3)
        add("indirizzo", 2, 0, 3)
        add("cap", 3, 0)
        add("citta", 3, 1)
        add("provincia", 3, 2)
        for i in (1, 2, 3):
            add(f"tel{i}", 3 + i, 0)
            add(f"desc{i}", 3 + i, 1)
            call = QToolButton()
            call.setText("☎")
            call.setToolTip("Copia il numero negli appunti per comporlo")
            call.clicked.connect(lambda _=False, k=f"tel{i}": self._copy_number(k))
            form.addWidget(call, 3 + i, 4)
        add("piva", 7, 0)
        add("libero", 7, 1)
        add("email", 8, 0)
        add("web", 8, 1)
        sogg = LookupCombo()
        add("soggetto_id", 9, 0, widget=sogg)
        note = QPlainTextEdit()
        add("note", 10, 0, 3, note)
        self.w["nome"].setMaxLength(100)

        search = QGroupBox("Cerca")
        sl = QHBoxLayout(search)
        self.s_text = QLineEdit()
        self.s_field = QComboBox()
        self.s_field.addItem("tutti i campi", None)
        for k in tools.SEARCH_FIELDS:
            self.s_field.addItem(tools.CONTACT_LABELS[k], k)
        self.s_match = QComboBox()
        for k, v in (("contiene", "contiene"), ("inizio", "inizia con"), ("uguale", "è uguale a")):
            self.s_match.addItem(v, k)
        b_find = QPushButton("Cerca")
        b_find.clicked.connect(lambda: self._find(False))
        b_next = QPushButton("> Succ.")
        b_next.clicked.connect(lambda: self._find(True))
        for x in (self.s_text, self.s_field, self.s_match, b_find, b_next):
            sl.addWidget(x)

        btns = QHBoxLayout()
        for text, fn in (("&Crea nuovo", self._new), ("&Salva", self._save), ("&Elimina", self._delete),
                         ("Stam&pa…", self._print), ("Esp&orta…", self._export)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        btns.addWidget(close)
        top = QHBoxLayout()
        top.addWidget(QLabel("Visualizza per soggetto"))
        top.addWidget(self.view_for)
        top.addStretch()
        body = QHBoxLayout()
        body.addWidget(self.list, 2)
        detail = QWidget()
        detail.setLayout(form)
        body.addWidget(detail, 5)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(letters)
        lay.addLayout(body)
        lay.addWidget(search)
        lay.addLayout(btns)
        self._reload()

    def _soggetto_filter(self) -> int | None:
        return self.view_for.value() if self.view_for.currentIndex() > 0 else None

    def _set_letter(self, letter: str | None):
        self.letter = letter
        self._reload()

    def _reload(self, select: int | None = None):
        self.w["soggetto_id"].fill(lookup_items(self.arc, "soggetti"))
        self.list.blockSignals(True)
        self.list.clear()
        for r in tools.contacts(self.arc, self._soggetto_filter(), self.letter):
            it = QListWidgetItem(r["nome"])
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.list.addItem(it)
            if r["id"] == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._select(self.list.currentItem())

    def _select(self, item, _prev=None):
        self.current = item.data(Qt.ItemDataRole.UserRole) if item else None
        r = self.arc.row("rubrica", self.current) if self.current else None
        for k, w in self.w.items():
            v = r[k] if r else None
            if k == "soggetto_id":
                w.set_value(v if r else self._soggetto_filter())
            elif isinstance(w, QPlainTextEdit):
                w.setPlainText(v or "")
            else:
                w.setText(v or "")

    def _values(self) -> dict:
        out = {}
        for k, w in self.w.items():
            if k == "soggetto_id":
                out[k] = w.value()
            elif isinstance(w, QPlainTextEdit):
                out[k] = w.toPlainText()
            else:
                out[k] = w.text().strip()
        return out

    def _new(self):
        self.list.setCurrentItem(None)
        self._select(None)
        self.w["nome"].setFocus()

    def _save(self):
        try:
            self.current = tools.save_contact(self.arc, self._values(), self.current)
        except ArchiveError as e:
            error(self, e)
            return
        self._reload(self.current)

    def _delete(self):
        if self.current and ask(self, "Eliminare il nominativo selezionato?"):
            self.arc.delete("rubrica", self.current)
            self._reload()

    def _find(self, again: bool):
        field = self.s_field.currentData()
        r = tools.search_contacts(self.arc, self.s_text.text(), [field] if field else None, self.s_match.currentData(),
                                  self._soggetto_filter(), self.current if again else None)
        if r is None:
            QMessageBox.information(self, "Rubrica", "Nessun nominativo trovato")
            return
        if self.letter:
            self.letter = None
        self._reload(r["id"])

    def _copy_number(self, key: str):
        num = self.w[key].text().strip()
        if num:
            QGuiApplication.clipboard().setText(num)
            QDesktopServices.openUrl(QUrl(f"tel:{''.join(ch for ch in num if ch.isdigit() or ch == '+')}"))

    def _print(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Stampa rubrica")
        kind = QComboBox()
        for k, v in (("completa", "Completa"), ("ridotta", "Ridotta"), ("mini", "Minirubrica telefonica")):
            kind.addItem(v, k)
        sogg = LookupCombo()
        sogg.fill(lookup_items(self.arc, "soggetti"))
        da, a = QLineEdit(), QLineEdit()
        da.setPlaceholderText("es. A")
        a.setPlaceholderText("es. AZZZ")
        f = QFormLayout(dlg)
        f.addRow("Tipo di stampa", kind)
        f.addRow("Solo il soggetto", sogg)
        f.addRow("Dalla denominazione", da)
        f.addRow("Alla denominazione", a)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if not dlg.exec():
            return
        headers, rows = tools.contacts_for_print(self.arc, kind.currentData(), sogg.value(), da.text(), a.text())
        print_table(self, f"Rubrica – {kind.currentText().lower()}", headers, rows, f"rubrica_{kind.currentData()}",
                    landscape=kind.currentData() == "completa")

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Esporta rubrica", "rubrica.csv", "Testo delimitato (*.csv *.txt)")
        if path:
            try:
                tools.export_contacts(self.arc, path, self._soggetto_filter())
            except OSError as e:
                error(self, e)


# --- agenda ----------------------------------------------------------------------------------------
class AgendaDialog(QDialog):
    def __init__(self, arc: Archive, start: date | None = None, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.day = start or date.today()
        self.setWindowTitle("Agenda")
        self.resize(820, 480)
        self.cal = QCalendarWidget()
        self.cal.setGridVisible(True)
        self.cal.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.cal.selectionChanged.connect(self._day_changed)
        self.cal.currentPageChanged.connect(lambda *_: self._mark_days())
        today = QPushButton("Oggi: " + long_date(date.today(), capital=False))
        today.clicked.connect(lambda: self._go(date.today()))
        prev_b, next_b = QPushButton("< Prec."), QPushButton("Succ. >")
        prev_b.setToolTip("Giorno precedente con una nota")
        next_b.setToolTip("Giorno successivo con una nota")
        prev_b.clicked.connect(lambda: self._jump(True))
        next_b.clicked.connect(lambda: self._jump(False))
        self.title = QLabel()
        f = QFont()
        f.setBold(True)
        f.setPointSize(11)
        self.title.setFont(f)
        self.text = QPlainTextEdit()
        self.remind = QCheckBox("Ricorda negli avvisi del giorno")
        self.count = QLabel()
        self.text.textChanged.connect(lambda: self.count.setText(f"{len(self.text.toPlainText())} / {tools.MAX_NOTE}"))
        self.find = QLineEdit()
        self.find.setPlaceholderText("testo da cercare in tutte le note")
        f_prev, f_next = QPushButton("< Cerca"), QPushButton("Cerca >")
        f_prev.clicked.connect(lambda: self._search(True))
        f_next.clicked.connect(lambda: self._search(False))
        left = QVBoxLayout()
        left.addWidget(self.cal)
        left.addWidget(today)
        nav = QHBoxLayout()
        nav.addWidget(prev_b)
        nav.addWidget(next_b)
        left.addLayout(nav)
        sr = QHBoxLayout()
        sr.addWidget(f_prev)
        sr.addWidget(self.find)
        sr.addWidget(f_next)
        left.addLayout(sr)
        right = QVBoxLayout()
        right.addWidget(self.title)
        right.addWidget(self.text)
        rr = QHBoxLayout()
        rr.addWidget(self.remind)
        rr.addStretch()
        rr.addWidget(self.count)
        right.addLayout(rr)
        body = QHBoxLayout()
        body.addLayout(left, 2)
        body.addLayout(right, 3)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(body)
        lay.addWidget(close)
        self._load()
        self.cal.setSelectedDate(to_qdate(self.day))
        self._mark_days()

    def _store(self):
        try:
            tools.agenda_set(self.arc, self.day, self.text.toPlainText(), self.remind.isChecked())
        except ValidationError as e:
            error(self, e)
            return False
        return True

    def _load(self):
        txt, rem = tools.agenda_get(self.arc, self.day)
        self.text.blockSignals(True)
        self.text.setPlainText(txt)
        self.text.blockSignals(False)
        self.count.setText(f"{len(txt)} / {tools.MAX_NOTE}")
        self.remind.setChecked(rem)
        self.title.setText(long_date(self.day))

    def _day_changed(self):
        new = from_qdate(self.cal.selectedDate())
        if new == self.day:
            return
        if not self._store():
            return
        self.day = new
        self._load()
        self._mark_days()

    def _go(self, d: date):
        self.cal.setSelectedDate(to_qdate(d))

    def _jump(self, back: bool):
        self._store()
        d = tools.agenda_neighbour(self.arc, self.day, back)
        if d:
            self._go(d)

    def _search(self, back: bool):
        self._store()
        d = tools.agenda_neighbour(self.arc, self.day, back, self.find.text().strip())
        if d:
            self._go(d)
        else:
            QMessageBox.information(self, "Agenda", "Nessun'altra nota contiene il testo")

    def _mark_days(self):
        y, m = self.cal.yearShown(), self.cal.monthShown()
        self.cal.setDateTextFormat(QDate(), QTextCharFormat())
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Bold)
        fmt.setForeground(QBrush(QColor("#2a78d6")))
        for d in tools.agenda_days(self.arc, y, m):
            self.cal.setDateTextFormat(QDate(y, m, d), fmt)

    def done(self, r):
        self._store()
        super().done(r)


class MonthNotesDialog(QDialog):
    def __init__(self, arc: Archive, year: int, month: int, parent=None):
        super().__init__(parent)
        self.arc, self.year, self.month = arc, year, month
        self.setWindowTitle(f"Annotazioni di {month_name(month)} {year}")
        self.resize(560, 420)
        self.text = QPlainTextEdit(tools.month_note_get(arc, year, month))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.text)
        lay.addWidget(bb)

    def accept(self):
        try:
            tools.month_note_set(self.arc, self.year, self.month, self.text.toPlainText())
        except ValidationError as e:
            error(self, e)
            return
        super().accept()


# --- schede libere ---------------------------------------------------------------------------------
class FreeCardsDialog(QDialog):
    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.current: int | None = None
        self.setWindowTitle("Schede libere")
        self.resize(900, 560)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        self.nome = QLineEdit()
        self.nome.setMaxLength(tools.MAX_CARD_TEXT)
        self.use_date = QCheckBox("Data")
        self.date = DateEdit()
        self.dec = QSpinBox()
        self.dec.setRange(0, 4)
        self.use_mult = QCheckBox("Moltiplicatore")
        self.mult = QLineEdit("1")
        self.mult.setFixedWidth(90)
        self.dec.valueChanged.connect(self._totals)
        self.use_mult.toggled.connect(self._totals)
        self.mult.textChanged.connect(self._totals)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Data", "Descrizione", "Valore"])
        self.table.horizontalHeaderItem(0).setToolTip("gg/mm/aaaa")
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(2, 110)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.table.itemChanged.connect(self._item_changed)
        self.total = QLabel()
        self.total.setTextFormat(Qt.TextFormat.RichText)
        sort_b = QPushButton("Ordina per data")
        sort_b.clicked.connect(self._sort)
        del_b = QPushButton("Elimina righe selezionate")
        del_b.clicked.connect(self._del_rows)
        head = QFormLayout()
        head.addRow("Nome", self.nome)
        hr = QHBoxLayout()
        for w in (self.use_date, self.date, QLabel("Decimali"), self.dec, self.use_mult, self.mult):
            hr.addWidget(w)
        hr.addStretch()
        head.addRow(hr)
        right = QVBoxLayout()
        right.addLayout(head)
        right.addWidget(self.table)
        tr = QHBoxLayout()
        tr.addWidget(sort_b)
        tr.addWidget(del_b)
        tr.addStretch()
        tr.addWidget(self.total)
        right.addLayout(tr)
        btns = QHBoxLayout()
        for text, fn in (("&Crea nuova", self._new), ("&Salva", self._save), ("&Elimina scheda", self._delete),
                         ("Stam&pa…", self._print)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        btns.addWidget(close)
        body = QHBoxLayout()
        body.addWidget(self.list, 2)
        body.addLayout(right, 5)
        lay = QVBoxLayout(self)
        lay.addLayout(body)
        lay.addLayout(btns)
        self._reload()

    def _reload(self, select: int | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.arc.rows("schede"):
            it = QListWidgetItem(r["nome"])
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.list.addItem(it)
            if r["id"] == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._select(self.list.currentItem())

    def _fill_rows(self, rows: list[tools.CardRow]):
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows) + 1)
        dec = self.dec.value()
        for i, r in enumerate(rows + [tools.CardRow()]):
            vals = [r.data.strftime("%d/%m/%Y") if r.data else "", r.descrizione,
                    fmt_amount(r.valore, dec) if r.valore is not None else ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(i, c, it)
        self.table.blockSignals(False)
        self._totals()

    def _select(self, item, _prev=None):
        self.current = item.data(Qt.ItemDataRole.UserRole) if item else None
        r = self.arc.row("schede", self.current) if self.current else None
        self.nome.setText(r["nome"] if r else "")
        self.use_date.setChecked(bool(r and r["data"]))
        self.date.set_date(date.fromisoformat(r["data"]) if r and r["data"] else date.today())
        self.dec.setValue(r["decimali"] if r else 2)
        self.use_mult.setChecked(bool(r and r["usa_moltiplicatore"]))
        self.mult.setText((r["moltiplicatore"] if r else "1").replace(".", ","))
        self._fill_rows(tools.card_rows(self.arc, self.current) if self.current else [])

    def _rows(self) -> list[tools.CardRow]:
        out = []
        for i in range(self.table.rowCount()):
            d, t, v = (self.table.item(i, c).text().strip() if self.table.item(i, c) else "" for c in range(3))
            row = tools.CardRow()
            if d:
                try:
                    row.data = datetime.strptime(d, "%d/%m/%Y").date()
                except ValueError:
                    raise ValidationError(f"Riga {i + 1}: data non valida «{d}» (usare gg/mm/aaaa)") from None
            row.descrizione = t[:tools.MAX_CARD_TEXT]
            if v:
                try:
                    row.valore = parse_amount(v)
                except ValueError as e:
                    raise ValidationError(f"Riga {i + 1}: {e}") from None
            if not row.is_empty():
                out.append(row)
        return out

    def _multiplier(self) -> Decimal | None:
        if not self.use_mult.isChecked():
            return None
        return parse_rate(self.mult.text() or "1")

    def _item_changed(self, item):
        if item.row() == self.table.rowCount() - 1 and item.text().strip():
            if self.table.rowCount() <= tools.MAX_CARD_ROWS:
                self.table.blockSignals(True)
                self.table.insertRow(self.table.rowCount())
                for c in range(3):
                    self.table.setItem(self.table.rowCount() - 1, c, QTableWidgetItem(""))
                self.table.blockSignals(False)
        self._totals()

    def _totals(self, *_):
        try:
            tot, imp = tools.card_totals(self._rows(), self._multiplier())
        except (ValidationError, ValueError):
            self.total.setText("<i>dati non validi</i>")
            return
        dec = self.dec.value()
        text = f"TOTALE <b>{fmt_amount(tot, dec)}</b>"
        if imp is not None:
            text += f"   ·   Importo <b>{fmt_amount(imp, self.arc.decimals)}</b>"
        self.total.setText(text)

    def _sort(self):
        try:
            self._fill_rows(tools.sort_card_by_date(self._rows()))
        except ValidationError as e:
            error(self, e)

    def _del_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            if r < self.table.rowCount() - 1:
                self.table.removeRow(r)
        self._totals()

    def _new(self):
        self.list.setCurrentItem(None)
        self._select(None)
        self.nome.setFocus()

    def _save(self):
        try:
            self.current = tools.save_card(self.arc, self.nome.text(), self._rows(),
                                           self.date.value() if self.use_date.isChecked() else None, self.dec.value(),
                                           self._multiplier(), self.current)
        except (ValueError, ArchiveError) as e:
            error(self, e)
            return
        self._reload(self.current)

    def _delete(self):
        if self.current and ask(self, "Eliminare la scheda con tutte le sue registrazioni?"):
            self.arc.delete("schede", self.current)
            self._reload()

    def _print(self):
        try:
            rows = self._rows()
            tot, imp = tools.card_totals(rows, self._multiplier())
        except (ValidationError, ValueError) as e:
            error(self, e)
            return
        dec = self.dec.value()
        out = [[r.data.strftime("%d/%m/%Y") if r.data else "", r.descrizione,
                fmt_amount(r.valore, dec) if r.valore is not None else ""] for r in rows]
        out.append(["", "TOTALE", fmt_amount(tot, dec)])
        if imp is not None:
            out.append(["", "Importo", fmt_amount(imp, self.arc.decimals)])
        print_table(self, f"Scheda «{self.nome.text()}»", ["Data", "Descrizione", "Valore"], out, "scheda", (2,),
                    bold_rows=tuple(range(len(rows), len(out))))


# --- codice d'accesso ---------------------------------------------------------------------------------
class PasswordDialog(QDialog):
    """Imposta, cambia o toglie il codice d'accesso dell'archivio aperto."""

    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Codice d'accesso")
        self.new1, self.new2 = QLineEdit(), QLineEdit()
        for e in (self.new1, self.new2):
            e.setEchoMode(QLineEdit.EchoMode.Password)
        self.remove = QRadioButton("Togli il codice d'accesso")
        self.change = QRadioButton("Imposta un nuovo codice" if arc.encrypted else "Proteggi l'archivio con un codice")
        g = QButtonGroup(self)
        g.addButton(self.change)
        g.addButton(self.remove)
        self.change.setChecked(True)
        self.remove.setEnabled(arc.encrypted)
        self.remove.toggled.connect(lambda on: (self.new1.setEnabled(not on), self.new2.setEnabled(not on)))
        state = ("L'archivio è <b>protetto</b>: il file è cifrato e non si apre senza il codice."
                 if arc.encrypted else "L'archivio <b>non è protetto</b>.")
        warn = QLabel("Attenzione: senza il codice corretto è impossibile aprire l'archivio, per chiunque. "
                      "Le copie di sicurezza fatte da ora in poi useranno lo stesso codice.")
        warn.setWordWrap(True)
        f = QFormLayout(self)
        f.addRow(QLabel(state))
        f.addRow(self.change)
        f.addRow("Nuovo codice", self.new1)
        f.addRow("Ripeti il codice", self.new2)
        f.addRow(self.remove)
        f.addRow(warn)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def accept(self):
        try:
            if self.remove.isChecked():
                if not ask(self, "Togliere la protezione? Il file tornerà leggibile da qualsiasi programma."):
                    return
                self.arc.remove_password()
            else:
                if self.new1.text() != self.new2.text():
                    raise ValidationError("I due codici non coincidono")
                if len(self.new1.text()) < 4:
                    raise ValidationError("Usare un codice di almeno 4 caratteri")
                self.arc.set_password(self.new1.text())
        except (ValueError, ArchiveError, OSError) as e:
            error(self, e)
            return
        super().accept()
