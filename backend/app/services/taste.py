"""Lo que el algoritmo ha aprendido de los gustos del usuario (Fase 3, primera versión).

Cada valoración («me gusta» / «no me gusta», con sus motivos) se reparte entre lo que tiene en
común la combinación valorada:

  · la combinación exacta          (estas cuatro prendas juntas)
  · parejas de prendas concretas   (esta sudadera con este vaquero)
  · cada prenda por su cuenta      (la que el usuario señala una y otra vez)
  · parejas de colores             (verde con negro) — sirve también para prendas futuras
  · parejas de estilos             (casual con deportivo)
  · parejas de tipos de prenda     (camisa con chándal, chaqueta sobre sudadera)
  · rasgos de las palabras clave   (ancho arriba y ajustado abajo, capucha bajo una chaqueta)
  · lo cargado que va el conjunto  (cuántos colores fuertes y estampados lleva)

Si gusta, gustan todas sus parejas. Si no gusta y el usuario dice por qué, solo se penaliza lo que
señala (y si marca prendas, solo esas prendas y sus parejas); si no dice nada, la culpa se reparte,
y menos por pareja cuantas más prendas haya. Una misma cosa nunca cuenta dos veces en un voto.
No importa quién valora: solo si la combinación pega o no.
"""
import itertools
from dataclasses import dataclass, field

from .style_rules import blend, loudness, pair_key, relations, remember, tone, traits

REASONS = ("colores", "calzado", "estilo", "soso", "recargado")

# Cuánto mueve cada cosa aprendida la nota de una combinación cuando la opinión es rotunda (±1).
# Juntas pesan más que todas las reglas generales (style_rules): lo que el usuario valora acaba mandando.
L_COMBO, L_GARMENT, L_SINGLE, L_COLOR, L_STYLE, L_TYPE, L_TRAIT, L_LOUD = 2.0, 2.0, 1.0, 1.5, 0.6, 0.6, 0.5, 1.0
# Votos "de relleno" neutros: con pocas valoraciones la opinión se queda cerca de 0. Para la combinación
# exacta hacen falta menos: si el usuario ya dijo que esas mismas prendas juntas no, un voto basta.
PRIOR_VOTES = 1.5
COMBO_PRIOR_VOTES = 0.5
# A partir de qué opinión (de -1 a 1) una pareja de colores se enseña en «Lo que voy aprendiendo».
CLEAR_OPINION = 0.35


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
    hood: bool | None = None


@dataclass
class Vote:
    pieces: list[Piece]
    liked: bool
    weight: float = 1.0
    reasons: tuple[str, ...] = ()
    culprit_ids: frozenset[int] = frozenset()  # las prendas que estropean el conjunto


def _features(pairs, related, garments=0.0, colors=0.0, styles=0.0, types=0.0):
    """Lo que tienen en común unas parejas de prendas, con lo que se le apunta a cada cosa."""
    for a, b in pairs:
        yield "garments", pair_key(a.id, b.id), garments
        yield "colors", pair_key(tone(a), tone(b)), colors
        yield "styles", pair_key(a.style, b.style), styles
    for a, b in related:
        yield "types", pair_key(a.type, b.type), types


@dataclass
class Taste:
    """Sumas de votos por cada cosa aprendida: clave -> [neto, total]."""

    combos: dict[frozenset, list[float]] = field(default_factory=dict)
    garments: dict[tuple, list[float]] = field(default_factory=dict)
    singles: dict[int, list[float]] = field(default_factory=dict)
    colors: dict[tuple, list[float]] = field(default_factory=dict)
    styles: dict[tuple, list[float]] = field(default_factory=dict)
    types: dict[tuple, list[float]] = field(default_factory=dict)
    traits: dict[tuple, list[float]] = field(default_factory=dict)
    loud: dict[int, list[float]] = field(default_factory=dict)
    votes: int = 0

    def _credit(self, entries) -> None:
        """Apunta (tabla, clave, cantidad). Si una clave sale varias veces en el voto, cuenta la más fuerte."""
        strongest: dict[tuple, float] = {}
        for table, key, amount in entries:
            if abs(amount) > abs(strongest.get((table, key), 0.0)):
                strongest[(table, key)] = amount
        for (table, key), amount in strongest.items():
            entry = getattr(self, table).setdefault(key, [0.0, 0.0])
            entry[0] += amount
            entry[1] += abs(amount)

    def learn(self, vote: Vote) -> None:
        self.votes += 1
        w, pieces = vote.weight, vote.pieces
        pairs = list(itertools.combinations(pieces, 2))
        related = relations(pieces)
        level = loudness(pieces)
        entries = [("combos", frozenset(p.id for p in pieces), w if vote.liked else -w)]

        reasons = set(vote.reasons)
        if vote.liked:
            entries += _features(pairs, related, garments=w, colors=0.7 * w, styles=0.5 * w, types=0.5 * w)
            entries += [("traits", key, 0.5 * w) for key in traits(pieces)]
            entries += [("singles", p.id, 0.3 * w) for p in pieces]
            entries.append(("loud", level, 0.5 * w))
        elif not reasons and not vote.culprit_ids:
            # No dijo por qué: un poco de culpa para todo, menos cuantas más parejas haya donde buscarla.
            share = w * 2 / len(pieces)
            entries += _features(
                pairs, related, garments=-share, colors=-0.4 * share, styles=-0.2 * share, types=-0.2 * share
            )
            entries += [("traits", key, -0.2 * share) for key in traits(pieces)]
            entries += [("singles", p.id, -0.3 * share) for p in pieces]
            entries.append(("loud", level, -0.2 * share))
        else:
            # Dijo qué falla. Si señaló prendas, solo cuentan las parejas en las que están.
            def blamed(pair) -> bool:
                return not vote.culprit_ids or pair[0].id in vote.culprit_ids or pair[1].id in vote.culprit_ids

            def with_shoe(pair) -> bool:
                return "calzado" in (pair[0].category, pair[1].category)

            pairs, related = list(filter(blamed, pairs)), list(filter(blamed, related))
            # Sin prendas señaladas no se sabe qué pareja es la del problema: la culpa se reparte.
            share = w if vote.culprit_ids else w * 2 / len(pieces)
            if vote.culprit_ids:
                entries += _features(pairs, [], garments=-w)
                # La prenda señalada baja también por su cuenta; del todo si no hay otro motivo que lo explique.
                alone = -w if not reasons else -0.3 * w
                entries += [("singles", p.id, alone) for p in pieces if p.id in vote.culprit_ids]
            if "colores" in reasons:
                entries += _features(pairs, [], garments=-0.5 * share, colors=-share)
            if "estilo" in reasons:
                entries += _features(pairs, related, garments=-0.5 * share, styles=-share, types=-0.5 * share)
            if "calzado" in reasons:
                entries += _features(
                    filter(with_shoe, pairs), filter(with_shoe, related), garments=-w, colors=-0.4 * w, types=-0.5 * w
                )
            # «Soso» también habla de lo que vaya aún menos cargado; «recargado», de lo que vaya aún más.
            if "soso" in reasons and "recargado" not in reasons:
                entries += [("loud", lower, -w) for lower in range(level + 1)]
            elif "recargado" in reasons and "soso" not in reasons:
                entries += [("loud", higher, -w) for higher in range(level, 4)]
            elif reasons & {"soso", "recargado"}:
                entries.append(("loud", level, -w))
        self._credit(entry for entry in entries if entry[2])

    def seen(self, table: str, key) -> float:
        """Cuántos votos (con su peso) hay sobre una cosa. Las reglas generales lo usan para ceder el paso."""
        return getattr(self, table).get(key, (0.0, 0.0))[1]

    def _opinion(self, table: dict, key, prior_votes: float = PRIOR_VOTES) -> float:
        """De -1 a 1. Con pocos votos se queda cerca de 0: una sola opinión no decide."""
        net, total = table.get(key, (0.0, 0.0))
        return net / (total + prior_votes)

    def pair_opinion(self, a: Piece, b: Piece) -> float:
        return (
            L_GARMENT * self._opinion(self.garments, pair_key(a.id, b.id))
            + L_COLOR * self._opinion(self.colors, pair_key(tone(a), tone(b)))
            + L_STYLE * self._opinion(self.styles, pair_key(a.style, b.style))
        )

    def adjust(self, pieces: list[Piece], memo: dict | None = None) -> float:
        """Cuánto sube o baja la nota de una combinación según lo aprendido (0 si no se sabe nada de ella).

        Igual que las reglas, hace la media por pareja: no depende de cuántas prendas lleve el conjunto.
        """
        if not self.votes:
            return 0.0
        total = blend([remember(memo, "gusto", a, b, self.pair_opinion) for a, b in itertools.combinations(pieces, 2)])
        if self.singles:
            total += L_SINGLE * blend([self._opinion(self.singles, p.id) for p in pieces])
        if self.types:
            total += L_TYPE * blend([self._opinion(self.types, pair_key(a.type, b.type)) for a, b in relations(pieces)])
        if self.traits:
            total += L_TRAIT * blend([self._opinion(self.traits, key) for key in traits(pieces)])
        if self.loud:
            total += L_LOUD * self._opinion(self.loud, loudness(pieces))
        ids = frozenset(p.id for p in pieces)
        if ids not in self.combos:
            # Nunca se valoró tal cual: vale lo que se dijo del mismo conjunto sin la capa de encima. Un
            # conjunto que gusta sigue gustando con una chaqueta (si esta no pega, ya lo dicen sus parejas).
            ids = frozenset(p.id for p in pieces if p.category != "capa_exterior")
        return total + L_COMBO * self._opinion(self.combos, ids, COMBO_PRIOR_VOTES)

    def novelty(self, pieces: list[Piece]) -> float:
        """De 0 a 1: cuánto de esta combinación está aún sin valorar. Gustos pregunta antes lo que más enseña."""
        known = [self.seen(table, key) for table, key, _ in _features(
            list(itertools.combinations(pieces, 2)), relations(pieces)
        )]
        return sum(1 / (1 + votes) for votes in known) / len(known) if known else 0.0

    def summary(self, top: int = 3) -> dict:
        """Lo más claro que ha aprendido, para enseñarlo en la pestaña Gustos."""
        ranked = sorted(
            ((key, self._opinion(self.colors, key)) for key in self.colors if key[0] != key[1]),
            key=lambda kv: kv[1],
        )
        return {
            "likes": [list(k) for k, v in reversed(ranked) if v >= CLEAR_OPINION][:top],
            "dislikes": [list(k) for k, v in ranked if v <= -CLEAR_OPINION][:top],
        }


def build(votes: list[Vote]) -> Taste:
    taste = Taste()
    for vote in votes:
        taste.learn(vote)
    return taste
