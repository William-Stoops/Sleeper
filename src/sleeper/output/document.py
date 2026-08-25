"""Serialisation et validation du document de sortie.

Le schema JSON est derive des modeles pydantic, publie dans `schemas/`, et le
document est valide contre CE fichier avant toute ecriture. Le detour par le
fichier est volontaire : il fait echouer le run si le schema publie et les
modeles divergent, plutot que de livrer un document conforme a lui-meme.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema

from sleeper.domain.models import DocumentSortie
from sleeper.errors import SortieError

#: Version du contrat de sortie. Toute evolution incrementale est documentee
#: dans docs/api.md et donne lieu a un nouveau fichier de schema.
VERSION_SCHEMA: Final = "1.0"

REPERTOIRE_SCHEMAS: Final = Path("schemas")
NOM_SCHEMA: Final = f"sortie-{VERSION_SCHEMA}.json"


def schema_courant() -> dict[str, Any]:
    """Schema JSON derive des modeles, source de verite."""
    schema = DocumentSortie.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://github.com/William-Stoops/Sleeper/schemas/{NOM_SCHEMA}"
    return schema


def publier_schema(repertoire: Path = REPERTOIRE_SCHEMAS) -> Path:
    """Ecrit le schema JSON sur disque et rend son chemin."""
    repertoire.mkdir(parents=True, exist_ok=True)
    chemin = repertoire / NOM_SCHEMA
    chemin.write_text(
        json.dumps(schema_courant(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return chemin


def serialiser(document: DocumentSortie) -> bytes:
    """Rend le document en JSON UTF-8 indente, avec ses accents intacts."""
    charge = document.model_dump(mode="json")
    return (json.dumps(charge, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def valider(document: DocumentSortie, repertoire: Path = REPERTOIRE_SCHEMAS) -> None:
    """Valide le document contre le schema PUBLIE. Echoue bruyamment sinon."""
    chemin = repertoire / NOM_SCHEMA
    if not chemin.is_file():
        raise SortieError(
            f"schema de sortie absent : {chemin}. "
            "Le regenerer avec « sleeper schema » avant d'ecrire un document."
        )
    try:
        schema = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SortieError(f"schema de sortie illisible : {chemin} ({exc})") from exc

    try:
        jsonschema.validate(document.model_dump(mode="json"), schema)
    except jsonschema.ValidationError as exc:
        emplacement = "/".join(str(p) for p in exc.absolute_path) or "(racine)"
        raise SortieError(
            f"document non conforme au schema {VERSION_SCHEMA} en '{emplacement}' : {exc.message}"
        ) from exc
