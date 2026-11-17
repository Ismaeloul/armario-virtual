"""Lo que el algoritmo ha aprendido de los gustos del usuario (Fase 3, primera versión).

Cada valoración («me gusta» / «no me gusta», con sus motivos) se reparte entre lo que tiene en
común la combinación valorada:

  · parejas de prendas concretas  (esta sudadera con este vaquero)
  · parejas de colores            (verde con negro) — sirve también para prendas futuras
  · parejas de estilos            (casual con deportivo)
  · lo cargado que va el conjunto (cuántos colores fuertes y estampados lleva)

Cuando el usuario dice por qué no le gusta, solo se penaliza lo que señala; si no dice nada,
se reparte un poco entre todo. No importa quién valora: solo si la combinación pega o no.
"""
import itertools
from dataclasses import dataclass, field

REASONS = ("colores", "calzado", "estilo", "soso", "recargado")

# Colores que no cuentan como "fuertes" (igual que en outfits.py; se repite para no cruzar imports).
_NEUTRALS = {"negro", "blanco", "gris", "beige", "crudo", "azul marino", "marrón"}


@dataclass
class Piece:
    id: int
    type: str
    category: str
    color: str
    style: str
    pattern: str
    details: str = ""
    closure: str | None = None
    fit: str | None = None
    thickness: str | None = None


@dataclass
class Vote:
    pieces: list[Piece]
    liked: bool
    weight: float = 1.0
    reasons: tuple[str, ...] = ()
    culprit_ids: frozenset[int] = frozenset()  # las prendas que estropean el conjunto


def loudness(pieces: list[Piece]) -> int:
    """De 0 (todo liso y neutro) a 3 (muy cargado)."""
    loud_colors = len({
        p.color for p in pieces
        if p.color not in _NEUTRALS and not (p.type == "vaquero" and p.color in {"azul", "celeste"})
    })
    patterns = sum(1 for p in pieces if p.pattern not in ("liso", "texturizado"))
    return min(3, loud_colors + patterns)


def _key(a, b) -> tuple:
    return tuple(sorted((a, b)))


@dataclass
class Taste:
    """Sumas de votos por cada cosa aprendida: clave -> [neto, total]."""

    garments: dict[tuple, list[float]] = field(default_factory=dict)
    colors: dict[tuple, list[float]] = field(default_factory=dict)
    styles: dict[tuple, list[float]] = field(default_factory=dict)
    loud: dict[int, list[float]] = field(default_factory=dict)
    votes: int = 0

    @staticmethod
    def _add(table: dict, key, amount: float) -> None:
        entry = table.setdefault(key, [0.0, 0.0])
        entry[0] += amount
        entry[1] += abs(amount)

    def learn(self, vote: Vote) -> None:
        self.votes += 1
        w = vote.weight
        pairs = list(itertools.combinations(vote.pieces, 2))

        if vote.liked:
            for a, b in pairs:
                self._add(self.garments, _key(a.id, b.id), w)
                self._add(self.colors, _key(a.color, b.color), 0.7 * w)
                self._add(self.styles, _key(a.style, b.style), 0.5 * w)
            self._add(self.loud, loudness(vote.pieces), 0.5 * w)
            return

        reasons = set(vote.reasons)
        if not reasons and not vote.culprit_ids:
            # No dijo por qué: un poco de culpa para todo.
            for a, b in pairs:
                self._add(self.garments, _key(a.id, b.id), -w)
                self._add(self.colors, _key(a.color, b.color), -0.4 * w)
                self._add(self.styles, _key(a.style, b.style), -0.2 * w)
            return

        for a, b in pairs:
            with_shoe = "calzado" in (a.category, b.category)
            with_culprit = a.id in vote.culprit_ids or b.id in vote.culprit_ids
            if "colores" in reasons:
                self._add(self.colors, _key(a.color, b.color), -w)
                self._add(self.garments, _key(a.id, b.id), -0.5 * w)
            if "estilo" in reasons:
                self._add(self.styles, _key(a.style, b.style), -w)
                self._add(self.garments, _key(a.id, b.id), -0.5 * w)
            if "calzado" in reasons and with_shoe:
                self._add(self.garments, _key(a.id, b.id), -w)
                self._add(self.colors, _key(a.color, b.color), -0.4 * w)
            if with_culprit:
                self._add(self.garments, _key(a.id, b.id), -w)
        if reasons & {"soso", "recargado"}:
            self._add(self.loud, loudness(vote.pieces), -w)

    @staticmethod
    def _opinion(table: dict, key) -> float:
        """De -1 a 1. Con pocos votos se queda cerca de 0: una sola opinión no decide."""
        net, total = table.get(key, (0.0, 0.0))
        return net / (total + 1.5)

    def adjust(self, pieces: list[Piece]) -> float:
        """Cuánto sube o baja la puntuación de una combinación según lo aprendido."""
        total = 0.0
        for a, b in itertools.combinations(pieces, 2):
            total += 2.0 * self._opinion(self.garments, _key(a.id, b.id))
            total += 1.2 * self._opinion(self.colors, _key(a.color, b.color))
            total += 0.6 * self._opinion(self.styles, _key(a.style, b.style))
        return total + 1.5 * self._opinion(self.loud, loudness(pieces))

    def summary(self, top: int = 3) -> dict:
        """Lo más claro que ha aprendido, para enseñarlo en la pestaña Gustos."""
        ranked = sorted(
            ((key, self._opinion(self.colors, key)) for key in self.colors if key[0] != key[1]),
            key=lambda kv: kv[1],
        )
        return {
            "likes": [list(k) for k, v in reversed(ranked) if v > 0.2][:top],
            "dislikes": [list(k) for k, v in ranked if v < -0.2][:top],
        }


def build(votes: list[Vote]) -> Taste:
    taste = Taste()
    for vote in votes:
        taste.learn(vote)
    return taste
