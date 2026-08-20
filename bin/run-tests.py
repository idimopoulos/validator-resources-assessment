#!/usr/bin/env python3
"""Validate the sample payloads under resources/assessment/tests/.

Payloads in `tests/valid/` must validate; payloads in `tests/invalid/` must not. Each
file is assigned to a validation type by its filename prefix, so
`submit-missing-name.json` is checked against the `submit` type.

The schemas for a type are read from `config.properties` rather than hardcoded, so that
this exercises the configuration the Test Bed will actually load. A type that is present
in the tests but not enabled in the configuration is reported as skipped, not as a
failure.

Usage:
    bin/run-tests.py [--domain resources/assessment]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    sys.exit("error: jsonschema is not installed (pip install -r requirements.txt)")


def read_properties(path: Path) -> dict[str, str]:
    """Reads a Java-style .properties file into a dict.

    Only the subset the validator configuration uses: `key = value` lines, `#` comments,
    no line continuations or escapes.
    """
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def build_schema(domain: Path, config: dict[str, str], vtype: str) -> dict:
    """Assembles the schema for one validation type, the way the Test Bed does."""
    files = [
        f.strip()
        for f in config[f"validator.schemaFile.{vtype}"].split(",")
        if f.strip()
    ]
    schemas = [json.loads((domain / f).read_text(encoding="utf-8")) for f in files]

    if len(schemas) == 1:
        return schemas[0]

    approach = config.get(f"validator.schemaFile.{vtype}.combinationApproach", "allOf")
    return {approach: schemas}


def make_validator(domain: Path, schema: dict):
    """Returns a validator that resolves this repository's relative file references.

    jsonschema replaced RefResolver with the `referencing` library in 4.18. Both paths
    are supported so the suite runs on whatever the environment provides — CI pins a
    modern version, but a developer's system package is often older.
    """
    base = (domain / "schemas").resolve()

    # Keyed by each schema's own `$id`, which is what its references use. This mirrors
    # how the Test Bed registers the files named in `validator.referencedSchemas`: it
    # reads their `$id` and resolves `$ref` against that, never against the file path.
    store = {}
    for path in base.rglob("*.json"):
        contents = json.loads(path.read_text(encoding="utf-8"))
        identifier = contents.get("$id")
        if identifier:
            store[identifier] = contents
        store[path.as_uri()] = contents

    base_uri = base.as_uri() + "/"
    validator_cls = jsonschema.validators.validator_for(schema)

    try:
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012

        registry = Registry().with_resources(
            (uri, Resource.from_contents(contents, default_specification=DRAFT202012))
            for uri, contents in store.items()
        )
        return validator_cls(schema, registry=registry)
    except ImportError:
        resolver = jsonschema.RefResolver(
            base_uri=base_uri, referrer=schema, store=store
        )
        return validator_cls(schema, resolver=resolver)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--domain",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "resources" / "assessment",
    )
    args = parser.parse_args()

    domain = args.domain
    config = read_properties(domain / "config.properties")
    enabled = [t.strip() for t in config.get("validator.type", "").split(",") if t.strip()]

    validators = {t: make_validator(domain, build_schema(domain, config, t)) for t in enabled}
    print(f"enabled validation types: {', '.join(enabled) or '(none)'}\n")

    failures = 0
    skipped = 0

    for expectation in ("valid", "invalid"):
        for path in sorted((domain / "tests" / expectation).glob("*.json")):
            vtype = path.stem.split("-")[0]
            label = f"{expectation}/{path.name}"

            if vtype not in validators:
                print(f"SKIP  {label}  (type '{vtype}' is not enabled)")
                skipped += 1
                continue

            errors = list(validators[vtype].iter_errors(json.loads(path.read_text())))
            passed = not errors

            if passed == (expectation == "valid"):
                print(f"OK    {label}")
            else:
                failures += 1
                if expectation == "valid":
                    print(f"FAIL  {label}  — expected to validate, but:")
                    for error in errors[:3]:
                        where = "/".join(str(p) for p in error.path) or "(root)"
                        print(f"          {where}: {error.message}")
                else:
                    print(f"FAIL  {label}  — expected to be rejected, but it validated")

    print()
    if skipped:
        print(f"{skipped} skipped")
    if failures:
        print(f"{failures} failed")
        return 1

    print("all payloads behaved as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
