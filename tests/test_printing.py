import os
from datetime import datetime

import pytest

from rationalis.print_codes import parse


def test_header_codes_example():
    """Esempio della guida: «&LProva &B&RPagina &P» → Prova a sinistra, Pagina N in grassetto a destra."""
    s = parse("&LProva &B&RPagina &P", 3, 9)
    assert s["L"].text == "Prova" and not s["L"].bold
    assert s["R"].text == "Pagina 3" and s["R"].bold


def test_header_codes_all():
    now = datetime(2026, 10, 20, 9, 5)
    s = parse("&12&CEstratto &D &T&RPag. &P/&N &I&& co.", 2, 5, now)
    assert s["C"].text == "Estratto 20/10/2026 09:05" and s["C"].size == 12
    assert s["R"].text == "Pag. 2/5 & co." and s["R"].italic
    assert parse("senza codici", 1, 1)["L"].text == "senza codici"


def test_pdf_render(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtPrintSupport")
    from PySide6.QtWidgets import QApplication
    from rationalis.ui.printing import Job, PrintOptions, save_pdf, table_html
    QApplication.instance() or QApplication([])
    rows = [[f"Riga {i}", "Descrizione piuttosto lunga che va a capo " * 2, f"{i},00"] for i in range(300)]
    opts = PrintOptions()
    job = Job("Prova", table_html(["Voce", "Descrizione", "Importo"], rows, (2,), opts=opts), opts)
    out = tmp_path / "prova.pdf"
    pages = save_pdf(job, str(out))
    assert pages > 3 and out.read_bytes().startswith(b"%PDF")
    opts.adatta_larghezza, opts.percentuale = False, 50
    assert save_pdf(Job("Prova", table_html(["Voce"], rows, opts=opts), opts), str(tmp_path / "b.pdf")) < pages
