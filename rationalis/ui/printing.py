"""Stampa di elenchi e prospetti: impostazioni di pagina, anteprima, stampa, PDF.

Il contenuto è una tabella HTML impaginata con QTextDocument; intestazione e piè di pagina sono disegnati
a parte su ogni pagina con i codici di print_codes. Le impostazioni si salvano per tipo di stampa.
"""
import html
import json
from dataclasses import asdict, dataclass

from PySide6.QtCore import QMarginsF, QRectF, QSettings, QSizeF, Qt
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QRadioButton, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from ..print_codes import parse
from .common import error


@dataclass
class PrintOptions:
    orientamento: str = "verticale"       # 'verticale' | 'orizzontale'
    margine_sup: float = 15
    margine_inf: float = 15
    margine_sx: float = 12
    margine_dx: float = 12
    linee: bool = True
    bianco_nero: bool = False
    centra: bool = False
    adatta_larghezza: bool = True
    percentuale: int = 100
    intestazione: str = "&L&B{titolo}&R&D"
    pie: str = "&CPagina &P di &N"

    @classmethod
    def load(cls, key: str, defaults: "PrintOptions | None" = None) -> "PrintOptions":
        raw = QSettings().value(f"stampa/{key}")
        base = asdict(defaults or cls())
        if raw:
            try:
                base.update({k: v for k, v in json.loads(raw).items() if k in base})
            except (ValueError, TypeError):
                pass
        return cls(**base)

    def save(self, key: str):
        QSettings().setValue(f"stampa/{key}", json.dumps(asdict(self)))


def table_html(headers: list[str], rows: list[list[str]], right_cols=(), bold_rows=(), opts: PrintOptions | None = None,
               subtitle: str = "") -> str:
    opts = opts or PrintOptions()
    head_bg = "" if opts.bianco_nero else "background:#e8e8e4;"
    css = (f"body,table,th,td,p{{color:#000;}} table{{border-collapse:collapse;}} "
           f"th,td{{vertical-align:top;}}"
           f"th{{{head_bg} font-weight:bold; text-align:left;}} .r{{text-align:right;}} .b td{{font-weight:bold;}}")
    out = [f"<html><head><style>{css}</style></head><body>"]
    if subtitle:
        out.append(f"<p>{html.escape(subtitle)}</p>")
    align = " align='center'" if opts.centra else ""
    # il motore HTML di Qt disegna le linee della griglia dagli attributi della tabella, non dal CSS delle celle
    grid = " border='1' style='border-collapse:collapse; border-color:#777777; border-style:solid'" if opts.linee else ""
    # cellpadding è già scalato da Qt alla risoluzione del dispositivo (un padding CSS sulle celle no)
    out.append(f"<table cellspacing='0' cellpadding='3'{grid}{align}><thead><tr>")
    out += [f"<th{' class=r' if i in right_cols else ''}>{html.escape(h)}</th>" for i, h in enumerate(headers)]
    out.append("</tr></thead><tbody>")
    for r, row in enumerate(rows):
        out.append(f"<tr{' class=b' if r in bold_rows else ''}>")
        for i, v in enumerate(row):
            cell = html.escape(str(v)).replace("\n", "<br>")
            out.append(f"<td{' class=r' if i in right_cols else ''}>{cell}</td>")
        out.append("</tr>")
    out.append("</tbody></table></body></html>")
    return "".join(out)


class Job:
    """Un lavoro di stampa: titolo, HTML del contenuto, opzioni."""

    def __init__(self, title: str, body_html: str, opts: PrintOptions):
        self.title = title
        self.body_html = body_html
        self.opts = opts

    def configure(self, printer: QPrinter):
        o = self.opts
        printer.setPageOrientation(QPageLayout.Orientation.Landscape if o.orientamento == "orizzontale"
                                   else QPageLayout.Orientation.Portrait)
        printer.setPageMargins(QMarginsF(o.margine_sx, o.margine_sup, o.margine_dx, o.margine_inf),
                               QPageLayout.Unit.Millimeter)
        if o.bianco_nero:
            printer.setColorMode(QPrinter.ColorMode.GrayScale)

    def render(self, printer: QPrinter):
        painter = QPainter()
        if not painter.begin(printer):
            raise RuntimeError("Impossibile avviare la stampa")
        try:
            self._paint(painter, printer)
        finally:
            painter.end()

    def _paint(self, painter: QPainter, printer: QPrinter):
        page = printer.pageLayout().paintRectPixels(printer.resolution())
        dpi = printer.resolution()
        pt = dpi / 72.0
        band = 14 * pt                              # altezza di intestazione e piè di pagina
        body = QRectF(0, band * 1.6, page.width(), page.height() - band * 3.2)
        doc = QTextDocument()
        doc.documentLayout().setPaintDevice(printer)   # impaginazione in pixel della stampante
        base = QFont()
        base.setPointSizeF(9)
        doc.setDefaultFont(base)
        doc.setDefaultStyleSheet("body { color: #000000; }")
        doc.setDocumentMargin(0)
        doc.setHtml(self.body_html)
        scale = 1.0 if self.opts.adatta_larghezza else self.opts.percentuale / 100.0
        doc.setTextWidth(body.width() / scale)
        if self.opts.adatta_larghezza and doc.idealWidth() > doc.textWidth():
            # la tabella non entra nemmeno andando a capo: riduco quanto basta
            scale *= doc.textWidth() / doc.idealWidth()
            doc.setTextWidth(body.width() / scale)
        page_w, page_h = body.width() / scale, body.height() / scale
        doc.setPageSize(QSizeF(page_w, page_h))
        pages = max(1, doc.pageCount())
        for n in range(pages):
            if n:
                printer.newPage()
            self._band(painter, self.opts.intestazione, QRectF(0, 0, page.width(), band), n + 1, pages, pt)
            self._band(painter, self.opts.pie, QRectF(0, page.height() - band, page.width(), band), n + 1, pages, pt)
            painter.save()
            painter.translate(body.left(), body.top())
            painter.scale(scale, scale)
            painter.translate(0, -n * page_h)
            doc.drawContents(painter, QRectF(0, n * page_h, page_w, page_h))
            painter.restore()
        self.page_count = pages

    def _band(self, painter: QPainter, spec: str, rect: QRectF, page: int, pages: int, pt: float):
        spec = spec.replace("{titolo}", self.title)
        for key, sec in parse(spec, page, pages).items():
            if not sec.text:
                continue
            f = QFont()
            f.setPointSizeF((sec.size or 8) * pt / (painter.device().logicalDpiY() / 72.0))
            f.setBold(sec.bold)
            f.setItalic(sec.italic)
            f.setUnderline(sec.underline)
            painter.setFont(f)
            painter.setPen(Qt.GlobalColor.black)
            align = {"L": Qt.AlignmentFlag.AlignLeft, "C": Qt.AlignmentFlag.AlignHCenter,
                     "R": Qt.AlignmentFlag.AlignRight}[key] | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(rect, int(align), sec.text)


def save_pdf(job: Job, path: str) -> int:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    job.configure(printer)
    job.render(printer)
    return job.page_count


class PrintSetupDialog(QDialog):
    """Impostazioni di pagina con anteprima, stampa e salvataggio PDF."""

    def __init__(self, title: str, body_html: str, key: str, parent=None, defaults: PrintOptions | None = None):
        super().__init__(parent)
        self.key = key
        self.job = Job(title, body_html, PrintOptions.load(key, defaults))
        self.setWindowTitle(f"Stampa – {title}")
        o = self.job.opts
        tabs = QTabWidget()

        p1 = QWidget()
        f1 = QFormLayout(p1)
        self.lines = QCheckBox("Linee della griglia")
        self.bw = QCheckBox("Bianco e nero")
        self.center = QCheckBox("Centra orizzontalmente")
        self.fit = QRadioButton("Adatta alla larghezza della pagina")
        self.pct_on = QRadioButton("Percentuale")
        self.pct = QSpinBox()
        self.pct.setRange(20, 400)
        self.pct.setSuffix(" %")
        for w in (self.lines, self.bw, self.center):
            f1.addRow(w)
        row = QHBoxLayout()
        row.addWidget(self.pct_on)
        row.addWidget(self.pct)
        row.addStretch()
        f1.addRow(self.fit)
        f1.addRow(row)
        tabs.addTab(p1, "Opzioni di stampa")

        p2 = QWidget()
        f2 = QFormLayout(p2)
        self.orient = QComboBox()
        self.orient.addItem("Verticale", "verticale")
        self.orient.addItem("Orizzontale", "orizzontale")
        f2.addRow("Orientamento", self.orient)
        self.margins = []
        for label in ("Margine superiore", "Margine inferiore", "Margine sinistro", "Margine destro"):
            s = QDoubleSpinBox()
            s.setRange(0, 60)
            s.setSuffix(" mm")
            self.margins.append(s)
            f2.addRow(label, s)
        tabs.addTab(p2, "Formato")

        p3 = QWidget()
        f3 = QFormLayout(p3)
        self.header = QLineEdit()
        self.footer = QLineEdit()
        f3.addRow("Intestazione", self.header)
        f3.addRow("Piè di pagina", self.footer)
        help_ = QLabel("Codici: &L &C &R allineamento · &D data · &T ora · &P pagina · &N totale pagine · "
                       "&B grassetto · &I corsivo · &U sottolineato · &nn dimensione · {titolo} titolo della stampa")
        help_.setWordWrap(True)
        f3.addRow(help_)
        tabs.addTab(p3, "Intestazione e piè di pagina")

        self.lines.setChecked(o.linee)
        self.bw.setChecked(o.bianco_nero)
        self.center.setChecked(o.centra)
        (self.fit if o.adatta_larghezza else self.pct_on).setChecked(True)
        self.pct.setValue(o.percentuale)
        self.orient.setCurrentIndex(max(0, self.orient.findData(o.orientamento)))
        for s, v in zip(self.margins, (o.margine_sup, o.margine_inf, o.margine_sx, o.margine_dx)):
            s.setValue(v)
        self.header.setText(o.intestazione)
        self.footer.setText(o.pie)

        buttons = QHBoxLayout()
        for text, fn in (("&Anteprima…", self.preview), ("&Stampa…", self.print_), ("Salva &PDF…", self.pdf),
                         ("Salva &impostazioni", self.save_settings)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        buttons.addStretch()
        close = QPushButton("Chiudi")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addLayout(buttons)

    def options(self) -> PrintOptions:
        m = [s.value() for s in self.margins]
        return PrintOptions(self.orient.currentData(), m[0], m[1], m[2], m[3], self.lines.isChecked(),
                            self.bw.isChecked(), self.center.isChecked(), self.fit.isChecked(), self.pct.value(),
                            self.header.text(), self.footer.text())

    def _job(self) -> Job:
        self.job.opts = self.options()
        return self.job

    def preview(self):
        job = self._job()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        job.configure(printer)
        dlg = QPrintPreviewDialog(printer, self)
        dlg.setWindowTitle(f"Anteprima – {job.title}")
        dlg.paintRequested.connect(job.render)
        dlg.exec()

    def print_(self):
        job = self._job()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        job.configure(printer)
        dlg = QPrintDialog(printer, self)
        if dlg.exec():
            try:
                job.render(printer)
            except RuntimeError as e:
                error(self, e)

    def pdf(self):
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in self.job.title)[:60].strip()
        path, _ = QFileDialog.getSaveFileName(self, "Salva PDF", safe + ".pdf", "PDF (*.pdf)")
        if path:
            try:
                save_pdf(self._job(), path)
            except (RuntimeError, OSError) as e:
                error(self, e)

    def save_settings(self):
        self.options().save(self.key)


def print_table(parent, title: str, headers: list[str], rows: list[list[str]], key: str, right_cols=(),
                bold_rows=(), subtitle: str = "", landscape: bool = False):
    defaults = PrintOptions(orientamento="orizzontale" if landscape else "verticale")
    opts = PrintOptions.load(key, defaults)
    body = table_html(headers, rows, right_cols, bold_rows, opts, subtitle)
    PrintSetupDialog(title, body, key, parent, defaults).exec()


def blank_grid_html(headers: list[str], n_rows: int, opts: PrintOptions) -> str:
    """Griglia vuota per annotare a mano le spese prima di inserirle."""
    return table_html(headers, [[" "] * len(headers) for _ in range(n_rows)], opts=opts)
