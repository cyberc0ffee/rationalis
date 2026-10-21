"""Importazioni ed esportazioni."""
from dataclasses import dataclass, field


@dataclass
class ImportReport:
    """Esito di un'importazione: conteggi per tipo di dato e avvisi leggibili."""
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add(self, what: str, n: int = 1):
        self.counts[what] = self.counts.get(what, 0) + n

    def warn(self, text: str):
        if text not in self.warnings:
            self.warnings.append(text)

    def summary(self) -> str:
        lines = [f"{k}: {v}" for k, v in self.counts.items()]
        if self.warnings:
            lines.append("")
            lines.append("Avvisi:")
            lines += [f"- {w}" for w in self.warnings]
        return "\n".join(lines)
