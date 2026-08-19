# Assessment report validator — Test Bed resources

Validator configuration for the Interoperable Europe **Assessment API**, published
through the [Interoperability Test Bed](https://www.itb.ec.europa.eu/) JSON validator.

It lets a public administration check an assessment report payload *before* posting it
to the API, and get back a readable report of what is wrong, rather than a 422 from a
live endpoint.

## What this repository is for

Joinup already validates every submitted report server-side:
`AssessmentReportResource::post()` runs the payload through
`Drupal\joinup_api\OpenApiSchemaValidator` against the `Assessment` schema and returns
422 with the errors before touching any entity. This repository does **not** introduce
validation — it publishes the *same* check as a self-service tool.

That framing matters for maintenance: if the published schemas ever disagree with the
API's, the validator is worse than useless, because it will bless payloads the API then
rejects. Hence everything below about generation.

## Layout

```
resources/assessment/
├── config.properties                       Test Bed validator configuration
├── schemas/
│   ├── Assessment.schema.json              root schema           (generated)
│   ├── Assessment-submit.overlay.json      submission-only rules (hand-written)
│   └── common/                             15 referenced schemas (generated)
└── tests/
    ├── valid/                              payloads that must validate
    └── invalid/                            payloads that must not
```

## The schemas are generated, not written

`bin/generate-schemas.py` derives every file under `schemas/` (except the overlay) from
`web/modules/custom/assessments/openapi/assessments.openapi.yaml` in the Joinup
repository.

This is possible because the spec is **OpenAPI 3.1.1**, and OpenAPI 3.1 schema objects
*are* JSON Schema 2020-12. The conversion is therefore mechanical: split
`components/schemas` into one file each, and rewrite `#/components/schemas/X` pointers
into relative file references.

```bash
bin/generate-schemas.py --spec ../joinup/web/modules/custom/assessments/openapi/assessments.openapi.yaml
```

To verify the committed files still match the spec without writing anything:

```bash
bin/generate-schemas.py --spec <path> --check
```

`--check` exits non-zero on any missing, outdated or orphaned schema. It is the form CI
runs, and it is the only thing standing between a field rename in Joinup and a public
validator that quietly disagrees with the API.

The script needs Python 3.9+ and PyYAML, nothing else. It deliberately does not reuse
Joinup's `devizzent/cebe-php-openapi`, so this repository stays independent of a PHP
toolchain.

## Validation types

| Type | Purpose | Schema |
|---|---|---|
| `submit` | A report being posted to `POST /assessment` | base `allOf` submission overlay |
| `published` | A report as returned by the API | base only — **not enabled**, see below |

`submit` is the one that matters: it is what a Member State runs before integrating.

The overlay exists because `Assessment` describes both directions of the exchange. `id`
and `uri` are server-assigned and marked `readOnly` in the spec, but `readOnly` is an
annotation in JSON Schema and no validator enforces it — so without the overlay a payload
supplying its own `id` would validate. Combining base and overlay with
`combinationApproach = allOf` gets the distinction without forking the schema. The overlay
declares no properties of its own, so it does not interfere with the base schema's
`additionalProperties: false`.

`published` is generated but commented out in `config.properties`. Every real response
currently fails it: `reportToArray()` always emits a `language` property, which the
`Assessment` schema does not declare while setting `additionalProperties: false`.

## Known divergences from the API

Recorded here because a validator that differs from the endpoint it fronts is a support
burden, not a feature.

1. **`language` is undeclared.** Responses always include it; submissions are read for it
   (`$this->langcode = $data['language'] ?? 'en'`) but can never supply it, because schema
   validation runs first and `additionalProperties: false` rejects it. That fallback is
   effectively dead code, and the `published` type is unusable until the property is added
   to the spec.

2. **`id` is unconstrained.** In `Assessment`, `EuropeanUnionOrganisation`,
   `MemberStateOrganisation` and `Asset` the property is written as `id:` → `schema:` →
   `$ref`. Inside a `properties` map the value *is* the schema; there is no `schema:`
   keyword, so the reference to `UUID` never applies and any value passes. Faithfully
   reproduced here — the generator derives, it does not correct.

3. **Dialect gap.** The spec is 2020-12, but Joinup validates with
   `justinrainbow/json-schema` 6.10.0, which implements draft-04/06/07. The Test Bed
   validator does support 2020-12. On any 2020-12-only keyword this validator will be
   stricter than the API.

## Publishing

Test Bed hosts the validator; this repository holds only its configuration. Once the
repository is pushed, ITB configure a webhook so pushes redeploy the validator
automatically — which is why `--check` in CI is not optional.
