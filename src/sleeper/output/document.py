"""Serialisation and validation of the output document.

The JSON Schema derives from the pydantic models, is published under
`schemas/`, and the document is validated against THAT FILE before anything is
written. Going through the file is deliberate: it fails the run when the
published schema and the models have drifted apart, rather than delivering a
document that is only consistent with itself.

Serialisation always uses `by_alias=True`: identifiers are English, the wire
format stays the French contract specified for the downstream system.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema

from sleeper.domain.models import OutputDocument
from sleeper.errors import OutputError

#: Version of the output contract. Any change is documented in docs/api.md and
#: gives rise to a new schema file.
SCHEMA_VERSION: Final = "1.0"

SCHEMA_DIRECTORY: Final = Path("schemas")
SCHEMA_NAME: Final = f"sortie-{SCHEMA_VERSION}.json"


def current_schema() -> dict[str, Any]:
    """JSON Schema derived from the models: the source of truth."""
    schema = OutputDocument.model_json_schema(by_alias=True, mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://github.com/William-Stoops/Sleeper/schemas/{SCHEMA_NAME}"
    return schema


def publish_schema(directory: Path = SCHEMA_DIRECTORY) -> Path:
    """Write the JSON Schema to disk and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SCHEMA_NAME
    path.write_text(
        json.dumps(current_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def serialize(document: OutputDocument) -> bytes:
    """Render the document as indented UTF-8 JSON, accents intact."""
    payload = document.model_dump(mode="json", by_alias=True)
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def validate(document: OutputDocument, directory: Path = SCHEMA_DIRECTORY) -> None:
    """Validate the document against the PUBLISHED schema. Fails loudly otherwise."""
    path = directory / SCHEMA_NAME
    if not path.is_file():
        raise OutputError(
            f"schéma de sortie absent : {path}. "
            "Le régénérer avec « sleeper schema » avant d'écrire un document."
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OutputError(f"schéma de sortie illisible : {path} ({exc})") from exc

    try:
        jsonschema.validate(document.model_dump(mode="json", by_alias=True), schema)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "(racine)"
        raise OutputError(
            f"document non conforme au schéma {SCHEMA_VERSION} en « {location} » : {exc.message}"
        ) from exc
