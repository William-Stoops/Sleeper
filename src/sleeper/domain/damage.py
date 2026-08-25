"""Body-damage classification.

On Domaine sales, **nearly every description mentions a knock**. "Coups,
chocs, rayures et frottements d'usage" is administrative boilerplate, not a
finding. Making it grounds for exclusion throws away the seam: the best file
of the run of 2026-08-25 — a 2021 Ford Transit with 27 798 km, starting at
800 € — carries "choc AR" and "multiples chocs et impacts sur carrosserie".

So this module **never excludes**. It grades, and the grade feeds the repair
budget and the score. Three levels, plus the absence of any mention:

* `usage`       — boilerplate wear. No effect.
* `cosmetique`  — a knock on a named panel. Repair budget.
* `structurel`  — load-bearing structure, corrosion, or a crash severe enough
                  to deploy an airbag. Budget and score malus.

The levels are ordered: the worst wording present wins.
"""

from __future__ import annotations

import re
from typing import Final, Literal

from sleeper.domain.text import normalize

#: Grade of the body damage a description declares.
BodyDamage = Literal["aucun", "usage", "cosmetique", "structurel"]

#: Panels whose name turns a knock into a costed repair rather than wear.
_PANELS: Final = (
    r"aile|porti[eè]re|portiere|bouclier|pare[- ]?chocs?|hayon|capot|coffre"
    r"|bas de caisse|retroviseur|r[ée]troviseur"
)

#: Words that describe an impact. Alone they mean nothing — it is their
#: pairing with a panel, or with a structural part, that grades them.
_IMPACT: Final = (
    r"choc|chocs|enfoncement|enfonce|enfoncee|frottement|frottements"
    r"|abime|abimee|casse|cassee|accidente|accidentee|sinistre|degat|degats"
)

#: Ordered from worst to mildest: the first family that matches decides.
_RULES: Final[tuple[tuple[BodyDamage, re.Pattern[str]], ...]] = (
    (
        "structurel",
        re.compile(
            r"\b(?:traverse|longeron|berceau|chassis|montant|pavillon perce"
            # « déformation », le substantif — pas le participe : un capot
            # déformé par un choc est cosmétique, un longeron déformé ne l'est
            # pas, et c'est la pièce nommée qui tranche, pas le verbe.
            r"|toit perce|corrosion|grele|grelee|deformation|structure"
            # Un airbag déclenché signe un choc qui a dépassé la tôle. Cette
            # formulation ne figure pas dans la table fournie : elle a été
            # ajoutée parce qu'un Renault Master « accidenté AVG, dégâts non
            # expertisés, airbag déclenché » ressortait sans dommage.
            r"|airbag declenche|airbags declenches|degats non expertises)\b"
        ),
    ),
    (
        "cosmetique",
        re.compile(
            rf"\b(?:{_IMPACT})\b[^.]{{0,40}}?\b(?:{_PANELS})\b"
            rf"|\b(?:{_PANELS})\b[^.]{{0,40}}?\b(?:{_IMPACT})\b"
        ),
    ),
    (
        "usage",
        re.compile(
            r"\b(?:rayures?|eclats? de peinture|frottements? d usage"
            r"|coups chocs rayures et frottements d usage)\b"
        ),
    ),
)

#: A last resort: an impact mentioned without a panel and without a structural
#: part is still an impact. It grades as cosmetic — never as nothing, never as
#: grounds for exclusion.
_BARE_IMPACT: Final = re.compile(rf"\b(?:{_IMPACT})\b")


#: Public view of the graded families, for the generated documentation.
DAMAGE_PATTERNS: Final[dict[BodyDamage, str]] = {level: p.pattern for level, p in _RULES}


def classify_damage(description: str | None) -> BodyDamage:
    """Grade the body damage a description declares. Never excludes."""
    flattened = normalize(description)
    if not flattened:
        return "aucun"
    for level, pattern in _RULES:
        if pattern.search(flattened):
            return level
    return "cosmetique" if _BARE_IMPACT.search(flattened) else "aucun"
