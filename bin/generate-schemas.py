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

# OpenAPI-only keywords that carry no meaning for a standalone JSON Schema
# validator. They are dropped so the published schemas stay readable; JSON Schema
# would ignore them, but leaving them in invites the reader to think they do
# something.
OPENAPI_ONLY_KEYWORDS = frozenset({"discriminator", "xml", "externalDocs"})


def rewrite_refs(node, from_common: bool):
    """Rewrites `#/components/schemas/X` pointers into file references.

    The root schema sits one directory above the rest, so the path it needs to
    reach a referenced schema differs from the path its siblings need.
    """
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in OPENAPI_ONLY_KEYWORDS:
                continue
            if key == "$ref" and isinstance(value, str) and value.startswith(REF_PREFIX):
                target = value[len(REF_PREFIX):]
                if from_common:
                    out[key] = f"{target}.schema.json"
                else:
                    out[key] = f"common/{target}.schema.json"
            else:
                out[key] = rewrite_refs(value, from_common)
        return out
    if isinstance(node, list):
        return [rewrite_refs(item, from_common) for item in node]
    return node


def build(spec_path: Path) -> dict[str, str]:
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
        # No `$id` is emitted. References between these files are relative paths that
        # the validator resolves against each file's own location, which is also how
        # the Test Bed loads `validator.referencedSchemas`. A bare-filename `$id` would
        # declare a base URI that disagrees with where the file actually sits, and
        # resolvers are inconsistent about which of the two wins.
        body = {
            "$schema": DIALECT,
            **rewrite_refs(schema, from_common=not is_root),
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
        "--check",
        action="store_true",
        help="verify the committed schemas match the spec instead of writing them",
    )
    args = parser.parse_args()

    if not args.spec.is_file():
        sys.exit(f"error: spec not found: {args.spec}")

    files = build(args.spec)

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
