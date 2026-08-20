#!/usr/bin/env python3
"""Generate the validator's JSON Schema files from the Assessment API OpenAPI spec.

The schemas served by this validator are not maintained by hand. They are derived
from `assessments.openapi.yaml` in the Joinup repository, so that the public
validator cannot drift away from what the API actually enforces.

OpenAPI 3.1 schema objects are JSON Schema 2020-12, so the conversion is mostly a
matter of splitting `components/schemas` into one file per schema and rewriting the
internal `$ref` pointers to file references the validator can resolve.

Usage:
    bin/generate-schemas.py --spec /path/to/assessments.openapi.yaml [--check]

With --check the script writes nothing and exits non-zero if the committed files
differ from what the spec would produce. That is the form CI runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

# The schema used as the entry point for validation. Everything else it reaches is
# emitted alongside it as a referenced schema.
ROOT_SCHEMA = "Assessment"

DIALECT = "https://json-schema.org/draft/2020-12/schema"

REF_PREFIX = "#/components/schemas/"

# Base URI for the `$id` of every generated schema.
#
# The Test Bed validator registers shared schemas by their `$id` and resolves `$ref`
# as a URI, so each schema needs a stable absolute identifier and references must use
# it. These URIs are identifiers, not locations — the validator maps them to the local
# files listed in `validator.referencedSchemas` and never dereferences them over the
# network.
DEFAULT_BASE_URI = "https://interoperable-europe.ec.europa.eu/schemas/assessment/"

# OpenAPI-only keywords that carry no meaning for a standalone JSON Schema
# validator. They are dropped so the published schemas stay readable; JSON Schema
# would ignore them, but leaving them in invites the reader to think they do
# something.
OPENAPI_ONLY_KEYWORDS = frozenset({"discriminator", "xml", "externalDocs"})


def schema_id(base_uri: str, name: str) -> str:
    """The `$id` a generated schema is published under."""
    return f"{base_uri}{name}.schema.json"


def rewrite_refs(node, base_uri: str):
    """Rewrites `#/components/schemas/X` pointers into absolute `$id` references.

    Absolute rather than relative on purpose: the Test Bed resolves `$ref` as a URI,
    and a relative path is not one — it raises `IllegalArgumentException` from
    `URLReader` before validation begins. Using the `$id` also makes the reference
    independent of where the file happens to sit on disk.
    """
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in OPENAPI_ONLY_KEYWORDS:
                continue
            if key == "$ref" and isinstance(value, str) and value.startswith(REF_PREFIX):
                out[key] = schema_id(base_uri, value[len(REF_PREFIX):])
            else:
                out[key] = rewrite_refs(value, base_uri)
        return out
    if isinstance(node, list):
        return [rewrite_refs(item, base_uri) for item in node]
    return node


def build(spec_path: Path, base_uri: str) -> dict[str, str]:
    """Returns a mapping of output path (relative to the domain dir) to file body."""
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))

    try:
        schemas = spec["components"]["schemas"]
    except (KeyError, TypeError):
        sys.exit(f"error: {spec_path} has no components.schemas section")

    if ROOT_SCHEMA not in schemas:
        sys.exit(f"error: {spec_path} does not define a '{ROOT_SCHEMA}' schema")

    files: dict[str, str] = {}
    for name, schema in schemas.items():
        is_root = name == ROOT_SCHEMA
        relative = (
            f"schemas/{name}.schema.json" if is_root
            else f"schemas/common/{name}.schema.json"
        )
        body = {
            "$schema": DIALECT,
            "$id": schema_id(base_uri, name),
            **rewrite_refs(schema, base_uri),
        }
        files[relative] = json.dumps(body, indent=2, ensure_ascii=False) + "\n"

    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        required=True,
        type=Path,
        help="path to assessments.openapi.yaml in the Joinup checkout",
    )
    parser.add_argument(
        "--domain",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "resources" / "assessment",
        help="the validator domain directory to write into",
    )
    parser.add_argument(
        "--base-uri",
        default=DEFAULT_BASE_URI,
        help=f"base URI for generated $id values (default: {DEFAULT_BASE_URI})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed schemas match the spec instead of writing them",
    )
    args = parser.parse_args()

    if not args.spec.is_file():
        sys.exit(f"error: spec not found: {args.spec}")

    files = build(args.spec, args.base_uri)

    if args.check:
        stale = []
        for relative, body in sorted(files.items()):
            target = args.domain / relative
            if not target.is_file():
                stale.append(f"missing: {relative}")
            elif target.read_text(encoding="utf-8") != body:
                stale.append(f"outdated: {relative}")

        generated = {args.domain / r for r in files}
        for existing in sorted((args.domain / "schemas").rglob("*.schema.json")):
            # The submit overlay is hand-written and has no counterpart in the spec.
            if existing not in generated and not existing.name.endswith(".overlay.json"):
                stale.append(f"orphaned: {existing.relative_to(args.domain)}")

        if stale:
            print("Schemas are out of sync with the OpenAPI spec:", file=sys.stderr)
            for line in stale:
                print(f"  {line}", file=sys.stderr)
            print(
                "\nRegenerate with: bin/generate-schemas.py --spec <path>",
                file=sys.stderr,
            )
            return 1

        print(f"{len(files)} schemas are up to date with {args.spec.name}")
        return 0

    for relative, body in sorted(files.items()):
        target = args.domain / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    print(f"wrote {len(files)} schemas to {args.domain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
