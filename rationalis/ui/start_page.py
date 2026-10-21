"""Pagina d'avvio dell'archivio: benvenuto, situazione, avvisi del giorno, prossime scadenze, per iniziare."""
import html

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTextBrowser

from .. import tools
from ..db import Archive
from ..money import fmt_amount
from ..ui_text import long_date, plural
from .common import colors, is_dark

DEFAULT_SECTIONS = "situazione,avvisi,scadenze,iniziare"


def sections(arc: Archive) -> list[str]:
    return [s for s in (arc.setting("avvio_sezioni", DEFAULT_SECTIONS) or "").split(",") if s]


class StartPage(QTextBrowser):
    """Le azioni sono collegamenti «azione:…» che emettono il segnale action."""

    action = Signal(str)

    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setOpenLinks(False)
        self.anchorClicked.connect(lambda url: self.action.emit(url.toString().removeprefix("azione:")))
        self.refresh()

    def refresh(self):
        a = self.arc
        d = tools.start_page_data(a)
        dec = a.decimals
        c = colors(is_dark(self))
        p = a.principal()["sigla"]

        def money(v):
            col = c["out"] if v < 0 else c["in"]
            return f"<span style='color:{col}'>{fmt_amount(v, dec)}</span>"

        def mov_line(m):
            what = "giroconto" if m.is_transfer else a.name_of("gruppi", m.gruppo_id)
            desc = f" – {html.escape(m.descrizione)}" if m.descrizione else ""
            return (f"<tr><td>{m.data:%d/%m/%Y}</td><td>{html.escape(what)}{desc}</td>"
                    f"<td>{html.escape(a.name_of('risorse', m.risorsa_id))}</td><td align=right>{money(m.importo)}</td></tr>")

        msg1 = a.setting("avvio_msg1", "") or f"Benvenuto in {html.escape(a.path.stem if a.path else 'Rationalis')}"
        msg2 = a.setting("avvio_msg2", "") or ""
        out = [f"<h2>{html.escape(msg1)}</h2>"]
        if msg2:
            out.append(f"<p>{html.escape(msg2)}</p>")
        out.append(f"<p>{long_date(d['oggi'])} · "
                   "<a href='azione:movimenti'><b>Vai all'elenco dei movimenti</b></a> · "
                   "<a href='azione:nuovo'>Nuovo movimento</a> · <a href='azione:giroconto'>Nuovo giroconto</a></p>")
        sec = sections(a)
        if "situazione" in sec:
            out.append("<h3>Situazione delle risorse</h3><table cellspacing=0 cellpadding=3>")
            for r in d["risorse"]:
                extra = f" <small>({fmt_amount(r['in_principale'], dec)} {p})</small>" if r["valuta"] != p else ""
                out.append(f"<tr><td>{html.escape(r['risorsa'])}</td><td align=right>{money(r['disponibilita'])} "
                           f"{r['valuta']}{extra}</td></tr>")
            out.append(f"<tr><td><b>Totale</b></td><td align=right><b>{money(d['totale'])} {p}</b></td></tr></table>")
        if "avvisi" in sec:
            out.append("<h3>Avvisi del giorno</h3>")
            items = []
            for _day, text in d["promemoria"]:
                items.append(f"<li>📌 {html.escape(text).replace(chr(10), '<br>')} "
                             "<small>(<a href='azione:agenda'>agenda</a>)</small></li>")
            if d["scadute"]:
                n = len(d["scadute"])
                items.append(f"<li><b>{n}</b> {'movimento' if n == 1 else 'movimenti'} con data passata non ancora "
                             f"{'saldato' if n == 1 else 'saldati'} "
                             "<small>(<a href='azione:scadute'>vedi</a>)</small></li>")
            out.append("<ul>" + "".join(items) + "</ul>" if items else "<p>Nessun avviso per oggi.</p>")
        if "scadenze" in sec:
            out.append("<h3>Prossime scadenze (7 giorni)</h3>")
            if d["in_scadenza"]:
                out.append("<table cellspacing=0 cellpadding=3>" + "".join(mov_line(m) for m in d["in_scadenza"][:30])
                           + "</table>")
            else:
                out.append("<p>Nessun movimento da saldare nei prossimi giorni.</p>")
        if "iniziare" in sec:
            s = d["statistiche"]
            out.append("<h3>Per iniziare</h3><ul>"
                       "<li>Controllare <a href='azione:risorse'>risorse e saldi iniziali</a> e "
                       "<a href='azione:gruppi'>gruppi e sottogruppi</a>.</li>"
                       "<li>Le spese ricorrenti (affitto, rate, stipendio) si inseriscono una volta sola con lo "
                       "<a href='azione:scadenzario'>scadenzario</a>.</li>"
                       "<li>I dati di Danea Professional Manager si importano da File › Importa.</li>"
                       f"<li>Archivio: {plural(s['movimenti'], 'movimento', 'movimenti')}, "
                       f"{plural(s['giroconti'], 'giroconto', 'giroconti')}, "
                       f"{plural(s['scadenze'], 'scadenza', 'scadenze')}, {plural(s['risorse'], 'risorsa', 'risorse')}, "
                       f"{plural(s['gruppi'], 'gruppo', 'gruppi')}.</li></ul>"
                       "<p><small>Le sezioni di questa pagina si scelgono in Varie › Impostazioni.</small></p>")
        self.setHtml("".join(out))
