"""Grafici (QtCharts) con la palette validata per tema chiaro e scuro.

Regole seguite:
- una sola serie = un solo colore (nessun arcobaleno per voce);
- valori con segno (entrate − uscite): coppia divergente blu (positivo) / rosso (negativo);
- torta solo per poche parti di un intero: al massimo 7 fette più «Altro», colori in ordine fisso, legenda
  ed etichette sempre visibili;
- griglia e assi discreti, testi negli inchiostri del tema e mai nel colore della serie;
- tooltip al passaggio del mouse su ogni barra, fetta o punto; la vista tabellare resta sempre disponibile.
"""
from decimal import Decimal

from PySide6.QtCharts import (QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QHorizontalBarSeries,
                              QLineSeries, QPieSeries, QStackedBarSeries, QValueAxis)
from PySide6.QtCore import QMargins, QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip

from ..money import fmt_amount
from .common import is_dark

CATEGORICAL = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
OTHER_COLOR = {"light": "#a8a7a1", "dark": "#6f6e69"}
DIVERGING = {"light": ("#2a78d6", "#e34948"), "dark": ("#3987e5", "#e66767")}
CHROME = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
              "axis": "#c3c2b7"},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
             "axis": "#383835"},
}
MAX_PIE_SLICES = 8  # 7 voci + «Altro»


def _mode() -> str:
    return "dark" if is_dark() else "light"


def _fmt(v, decimals: int) -> str:
    return fmt_amount(Decimal(str(v)), decimals)


class Chart(QChartView):
    """Vista di un grafico con il tema applicato e tooltip; `title` descrive cosa è mostrato."""

    def __init__(self, title: str = "", decimals: int = 2, parent=None):
        super().__init__(parent)
        self.decimals = decimals
        self.mode = _mode()
        self.c = CHROME[self.mode]
        self.setChart(self._new_chart(title))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(260)

    def _new_chart(self, title: str) -> QChart:
        ch = QChart()
        ch.setBackgroundBrush(QBrush(QColor(self.c["surface"])))
        ch.setBackgroundRoundness(0)
        ch.setMargins(QMargins(8, 8, 8, 8))
        ch.setTitle(title)
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        ch.setTitleFont(f)
        ch.setTitleBrush(QBrush(QColor(self.c["ink"])))
        ch.legend().setLabelColor(QColor(self.c["ink2"]))
        ch.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        return ch

    # --- assi --------------------------------------------------------------------
    def _value_axis(self, values) -> QValueAxis:
        ax = QValueAxis()
        lo = min([0.0] + [float(v) for v in values])
        hi = max([0.0] + [float(v) for v in values])
        if lo == hi:
            hi = lo + 1
        ax.setRange(lo, hi)
        ax.applyNiceNumbers()
        ax.setLabelFormat("%.0f")
        self._style_axis(ax)
        return ax

    def _style_axis(self, ax):
        ax.setLabelsColor(QColor(self.c["muted"]))
        ax.setLinePen(QPen(QColor(self.c["axis"]), 1))
        ax.setGridLinePen(QPen(QColor(self.c["grid"]), 1))
        ax.setShadesVisible(False)
        if isinstance(ax, QBarCategoryAxis):
            ax.setGridLineVisible(False)

    def _tip(self, text: str):
        QToolTip.showText(QCursor.pos(), text, self)

    # --- barre --------------------------------------------------------------------
    def _reset(self):
        old = self.chart()
        ch = self._new_chart(old.title())
        self.setChart(ch)
        old.deleteLater()
        return ch

    def set_title(self, title: str):
        self.chart().setTitle(title)

    def bars(self, labels: list[str], values: list[Decimal], horizontal: bool = False, series_name: str = ""):
        """Una sola serie di barre in un solo colore. horizontal=True per classifiche di voci
        (la prima voce in alto)."""
        ch = self._reset()
        if horizontal:
            labels, values = labels[::-1], values[::-1]
        series = QHorizontalBarSeries() if horizontal else QBarSeries()
        s = QBarSet(series_name)
        for v in values:
            s.append(float(v))
        s.setColor(QColor(CATEGORICAL[self.mode][0]))
        s.setBorderColor(QColor(self.c["surface"]))
        series.append(s)
        series.setBarWidth(0.6)
        ch.addSeries(series)
        ch.legend().setVisible(False)
        cat = QBarCategoryAxis()
        cat.append(labels)
        self._style_axis(cat)
        val = self._value_axis(values)
        ch.addAxis(cat, Qt.AlignmentFlag.AlignLeft if horizontal else Qt.AlignmentFlag.AlignBottom)
        ch.addAxis(val, Qt.AlignmentFlag.AlignBottom if horizontal else Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(cat)
        series.attachAxis(val)

        def hovered(status, index, _barset):
            if status:
                self._tip(f"{labels[index]}: {_fmt(values[index], self.decimals)}")
            else:
                QToolTip.hideText()
        series.hovered.connect(hovered)

    def signed_bars(self, labels: list[str], values: list[Decimal]):
        """Barre verticali con segno: una barra per periodo, blu se positiva e rossa se negativa."""
        ch = self._reset()
        pos, neg = DIVERGING[self.mode]
        series = QStackedBarSeries()   # positivi sopra e negativi sotto lo zero: nessuna sovrapposizione
        sp, sn = QBarSet("Entrate maggiori"), QBarSet("Uscite maggiori")
        for v in values:
            sp.append(float(v) if v > 0 else 0.0)
            sn.append(float(v) if v < 0 else 0.0)
        for s, col in ((sp, pos), (sn, neg)):
            s.setColor(QColor(col))
            s.setBorderColor(QColor(self.c["surface"]))
            series.append(s)
        series.setBarWidth(0.55)
        ch.addSeries(series)
        ch.legend().setVisible(True)
        ch.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        cat = QBarCategoryAxis()
        cat.append(labels)
        self._style_axis(cat)
        val = self._value_axis(values)
        ch.addAxis(cat, Qt.AlignmentFlag.AlignBottom)
        ch.addAxis(val, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(cat)
        series.attachAxis(val)

        def hovered(status, index, _barset):
            if status:
                self._tip(f"{labels[index]}: {_fmt(values[index], self.decimals)}")
            else:
                QToolTip.hideText()
        series.hovered.connect(hovered)

    # --- torta ----------------------------------------------------------------------
    def pie(self, pairs: list[tuple[str, Decimal]]):
        """Parti di un intero. Oltre MAX_PIE_SLICES voci le ultime vengono riunite in «Altro»."""
        ch = self._reset()
        if len(pairs) > MAX_PIE_SLICES:
            rest = sum((v for _, v in pairs[MAX_PIE_SLICES - 1:]), Decimal(0))
            pairs = pairs[:MAX_PIE_SLICES - 1] + [("Altro", rest)]
        total = sum((v for _, v in pairs), Decimal(0)) or Decimal(1)
        s = QPieSeries()
        s.setPieSize(0.68)
        colors = CATEGORICAL[self.mode]
        for i, (label, v) in enumerate(pairs):
            pct = v / total * 100
            sl = s.append(f"{label}  {pct:.0f}%", float(v))
            col = OTHER_COLOR[self.mode] if label == "Altro" else colors[i % len(colors)]
            sl.setColor(QColor(col))
            sl.setBorderColor(QColor(self.c["surface"]))
            sl.setBorderWidth(2)
            sl.setLabelVisible(pct >= 4)
            sl.setLabelColor(QColor(self.c["ink2"]))
            sl.hovered.connect(lambda state, lb=label, val=v, p=pct: self._tip(
                f"{lb}: {_fmt(val, self.decimals)} ({p:.1f}%)") if state else QToolTip.hideText())
        ch.addSeries(s)
        ch.legend().setVisible(True)
        ch.legend().setAlignment(Qt.AlignmentFlag.AlignRight)

    # --- linea -----------------------------------------------------------------------
    def line(self, labels: list[str], values: list[Decimal], series_name: str = ""):
        """Andamento nel tempo: una linea di 2 px con punti, tooltip sul punto più vicino."""
        ch = self._reset()
        s = QLineSeries()
        s.setName(series_name)
        for i, v in enumerate(values):
            s.append(QPointF(i, float(v)))
        pen = QPen(QColor(CATEGORICAL[self.mode][0]), 2)
        s.setPen(pen)
        s.setPointsVisible(True)
        s.setMarkerSize(8)
        ch.addSeries(s)
        ch.legend().setVisible(False)
        cat = QBarCategoryAxis()
        cat.append(labels)
        self._style_axis(cat)
        val = self._value_axis(values)
        ch.addAxis(cat, Qt.AlignmentFlag.AlignBottom)
        ch.addAxis(val, Qt.AlignmentFlag.AlignLeft)
        # la linea usa coordinate 0..n-1: un asse numerico nascosto le allinea alle categorie
        x = QValueAxis()
        x.setRange(-0.5, len(values) - 0.5)
        x.setVisible(False)
        ch.addAxis(x, Qt.AlignmentFlag.AlignBottom)
        s.attachAxis(x)
        s.attachAxis(val)

        def hovered(point, state):
            if state:
                i = max(0, min(len(values) - 1, round(point.x())))
                self._tip(f"{labels[i]}: {_fmt(values[i], self.decimals)}")
            else:
                QToolTip.hideText()
        s.hovered.connect(hovered)
