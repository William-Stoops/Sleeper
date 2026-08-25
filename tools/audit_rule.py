"""Audit one exclusion rule against a real run.

Produces a Markdown table of the lots a rule rejected, each with the exact
fragment of its description that fired. A reason without its evidence cannot
be checked by a human, and this rule rejected 155 lots.

    uv run python tools/audit_rule.py sans_cle --limit 30 > docs/audit_sans_cle.md
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

from sleeper.domain import text
from sleeper.domain.exclusions import DEFAULT_RULES, ExclusionEngine
from sleeper.domain.segment import classify_segment

_PHONE = re.compile(r"\b0[1-9](?:[ .\-]?\d{2}){4}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
_CIVIL = re.compile(r"\b(?:M\.|Mr|Mme|Monsieur|Madame)\s+[A-ZÉÈÀ][\w'-]+(?:\s+[A-ZÉÈÀ][\w'-]+)?")

#: Characters of context kept on either side of the triggering phrase.
_CONTEXT = 90


def _scrub(value: str) -> str:
    """Strip the personal data the source mixes into its descriptions."""
    return _CIVIL.sub("[EXPURGE]", _EMAIL.sub("[EXPURGE]", _PHONE.sub("[EXPURGE]", value)))


def _excerpt(description: str, phrase: str) -> str:
    """The phrase in its sentence, so the reader can judge the context."""
    words = [re.escape(w) for w in phrase.split()]
    pattern = re.compile(r"\W+".join(words), re.IGNORECASE)
    found = pattern.search(_strip_accents(description))
    if not found:
        return "—"
    start = max(found.start() - _CONTEXT, 0)
    end = min(found.end() + _CONTEXT, len(description))
    prefix = "…" if start else ""
    suffix = "…" if end < len(description) else ""
    return f"{prefix}{' '.join(description[start:end].split())}{suffix}"


def _strip_accents(value: str) -> str:
    """Accent-insensitive view, so the phrase matches the original text."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _listings(database: Path) -> dict[str, dict[str, Any]]:
    """Every memorised listing, keyed by lot id."""
    cnx = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    return {
        str(lot_id): json.loads(payload)
        for lot_id, payload in cnx.execute("SELECT lot_id, payload FROM listing_cache")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rule", help="code de la règle à auditer, par exemple sans_cle")
    parser.add_argument("--run", type=Path, default=Path("var/sorties/latest.json"))
    parser.add_argument("--state", type=Path, default=Path("var/etat/sleeper.sqlite3"))
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    engine = ExclusionEngine(DEFAULT_RULES)
    document = json.loads(args.run.read_text(encoding="utf-8"))
    listings = _listings(args.state)
    rejected = [e for e in document["ecartes"] if e["motif"] == args.rule][: args.limit]
    total = sum(1 for e in document["ecartes"] if e["motif"] == args.rule)

    print(f"# Audit de la règle `{args.rule}`\n")
    print(
        f"> Run du {document['run']['horodatage'][:10]} · **{total} lots écartés** "
        f"pour ce motif, dont les {len(rejected)} premiers ci-dessous.\n"
    )
    print(
        "Chaque ligne porte **le fragment exact de la description qui a déclenché la\n"
        "règle**. Un motif sans sa preuve n'est pas vérifiable.\n"
    )
    print(
        "Quand la colonne « déclencheur » indique *(attribut)*, la règle n'a pas\n"
        "lu de texte : elle a tranché sur un attribut structuré de la fiche, qui\n"
        "est fiable. Ces cas-là ne sont pas discutables.\n"
    )
    print(
        "Un segment `engin` signale un lot **mal attribué** : il n'est pas\n"
        "immatriculable et n'aurait jamais dû atteindre un filtre d'état. Le\n"
        "prédicat corrigé le range désormais en `hors_categorie_vehicule`.\n"
    )
    print("| Lot | Titre | Segment | Déclencheur | Extrait |")
    print("|---|---|---|---|---|")
    misattributed = 0
    for entry in rejected:
        listing = listings.get(entry["id"], {})
        description = _scrub(listing.get("description", ""))
        phrase = engine.evidence(args.rule, description)
        # Le cache peut avoir été écrit avant que plaque et VIN entrent dans
        # les attributs : on lit alors le VIN dans la description, comme le
        # pipeline le fait.
        segment = classify_segment(
            kind=listing.get("kind", ""),
            plate=listing.get("plate", ""),
            vin=listing.get("vin") or text.extract_vin(description) or "",
            title=entry["titre"],
        )
        trigger = f"`{phrase}`" if phrase else "*(attribut)*"
        excerpt = _excerpt(description, phrase) if phrase else "—"
        flag = " ⚠️" if segment == "engin" else ""
        misattributed += segment == "engin"
        print(
            f"| [{entry['id']}]({entry['url']}) | {entry['titre'][:38]} | `{segment}`{flag} "
            f"| {trigger} | {excerpt} |"
        )
    on_attribute = sum(
        1
        for entry in rejected
        if not engine.evidence(
            args.rule, _scrub(listings.get(entry["id"], {}).get("description", ""))
        )
    )
    print(
        f"\n## Bilan\n\n"
        f"- **{misattributed} lot(s) mal attribué(s)** sur les {len(rejected)} audités :\n"
        f"  ce sont des engins non immatriculables, désormais rangés en\n"
        f"  `hors_categorie_vehicule`.\n"
        f"- **{on_attribute} lot(s)** ont déclenché sur un **attribut structuré** de la\n"
        f"  fiche, pas sur du texte : ces verdicts-là ne sont pas discutables.\n"
        f"- **{len(rejected) - on_attribute} lot(s)** ont déclenché sur une expression.\n\n"
        f"À valider à la main : ces derniers, quand l'extrait ne justifie pas\n"
        f"l'écartement.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
