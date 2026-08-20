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
│   └── common/                             15 referenced schemas (generated)
└── tests/
    ├── valid/                              payloads that must validate
    └── invalid/                            payloads that must not

bin/generate-schemas.py                     derives schemas/ from the specification
bin/run-tests.py                            runs tests/ through config.properties
spec/assessments.openapi.yaml               vendored copy of the source spec
```

Everything under `resources/assessment/` is what the Test Bed consumes. The rest exists
to keep it honest.

## The schemas are generated, not written

`bin/generate-schemas.py` derives every file under `schemas/` from
`web/modules/custom/assessments/openapi/assessments.openapi.yaml` in the Joinup
repository.

This is possible because the spec is **OpenAPI 3.1.1**, and OpenAPI 3.1 schema objects
*are* JSON Schema 2020-12. The conversion is therefore mechanical: split
`components/schemas` into one file each, and rewrite `#/components/schemas/X` pointers
into the absolute `$id` URIs described below.

A copy of the spec is vendored at `spec/assessments.openapi.yaml` so that this works — and
so that CI works — without credentials for EC GitLab. See `spec/README.md` for its
provenance and for what that copy does and does not guarantee.

```bash
pip install -r requirements.txt
bin/generate-schemas.py --spec spec/assessments.openapi.yaml
```

To verify the committed files still match the spec without writing anything:

```bash
bin/generate-schemas.py --spec spec/assessments.openapi.yaml --check
```

`--check` exits non-zero on any missing, outdated or orphaned schema. It is the only thing
standing between a field rename in Joinup and a public validator that quietly disagrees
with the API.

The script needs Python 3.9+ and PyYAML, nothing else. It deliberately does not reuse
Joinup's `devizzent/cebe-php-openapi`, so this repository stays independent of a PHP
toolchain.

## Tests

```bash
bin/run-tests.py
```

Payloads in `tests/valid/` must validate and payloads in `tests/invalid/` must not. A
file is routed to a validation type by its filename prefix, so `report-missing-name.json`
is checked against `report`; a payload whose type is not enabled is skipped rather than
failed.

The runner assembles each type's schema by reading `config.properties` — including
`combinationApproach` — rather than hardcoding it, so it exercises the configuration the
Test Bed will actually load instead of a restatement of it. Change the configuration
wrongly and the tests notice.

The valid payloads are the specification's own `examples`, not invented ones. The invalid
ones are each derived from a valid payload with a single mutation, so a failure points at
one rule.

`invalid/report-as-returned-by-the-api.json` is the exception, and is not a mutation: it is
the spec's own `201` response example, unaltered. It sits in `invalid/` because it does not
validate — that is the `language` defect below, encoded as a test. When the spec is fixed
this test will start failing, which is the point: move it to `valid/` at that moment.

## Running the validator locally

This is step one of what ITB asked for, and the only way to be sure the configuration is
right — the schemas can be perfectly valid JSON Schema and still not load.

```bash
docker run -d --name assessment-validator -p 8899:8080 \
  -v "$PWD/resources":/validator/resources/ \
  -e validator.resourceRoot=/validator/resources/ \
  isaitb/json-validator
```

Web form: <http://localhost:8899/json/assessment/upload>

REST, with the content base64-encoded:

```bash
curl -s -X POST http://localhost:8899/json/assessment/api/validate \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d "{\"contentToValidate\":\"$(base64 -w0 resources/assessment/tests/valid/report-create-or-refer-sub-objects.json)\",
       \"embeddingMethod\":\"BASE64\",\"validationType\":\"report\",\"locationAsPointer\":true}"
```

Without `Accept: application/json` the response is a GITB TAR report in XML, which is the
default and is not an error.

Check the startup log for `Preloaded 15 shared schema(s)`. A line reading
`Unable to read schema ID from file configured as shared schema` means a referenced schema
is missing its `$id` and will not resolve.

## Why the schemas carry absolute `$id`s

The Test Bed registers each file in `validator.referencedSchemas` under its `$id`, and
resolves every `$ref` as a **URI**. A relative path such as `common/UUID.schema.json` is
not a URI: `LocalSchemaResolver` hands it to `URLReader`, which rejects it, and the request
fails with *"An unexpected error was raised during validation"* before any validation runs.

So each schema declares an absolute `$id` under

```
https://interoperable-europe.ec.europa.eu/schemas/assessment/
```

and references use those URIs. They are **identifiers, not locations** — the validator maps
them to the local files and never fetches anything over the network. Change the base with
`--base-uri` if a different namespace is agreed; it is a published identifier, so it is
worth agreeing before the validator goes live rather than after.

## CI

`.github/workflows/ci.yml` runs both of the above on every push and pull request.

This is a **self-contained** check: it verifies the schemas against the vendored copy of
the spec. It catches hand-edited schemas and a spec refresh without a regeneration. It
cannot see Joinup changing the upstream spec — that drift stays invisible until somebody
refreshes `spec/`.

Closing that gap needs CI that reads the spec from GitLab, either pushed from Joinup's own
pipeline when the spec changes, or pulled here on a schedule to open a pull request. Both
need a cross-organisation credential, which is why neither is set up yet. Given that ITB's
webhook redeploys the validator on push, the pull-and-review shape is the safer of the two:
a human sees each schema change before Member States do.

## Validation types

One type, `report`, validating against the generated `Assessment` schema. Nothing is
customised: no schema combination, no overlays, no message or report tuning. This is
deliberately the plainest configuration the Test Bed accepts, so that what you see is the
validator's own behaviour rather than ours.

`Assessment` describes **both** directions of the exchange — the body posted to
`POST /assessment` and the body returned by it — so `report` currently accepts either. Two
consequences worth knowing before reading a report:

- A payload may legally carry `id` and `uri`, even though the server assigns them. They are
  marked `readOnly` in the spec, but `readOnly` is an annotation in JSON Schema and no
  validator enforces it.
- A response payload fails, because responses carry `language` and the schema does not
  declare it while setting `additionalProperties: false`. See the divergences below.

An earlier revision added a submission-only overlay that made `id` and `uri` illegal on
input, combined with `combinationApproach = allOf`. It worked, but it changed the reported
errors into ones the stock validator would never produce, which is the opposite of what a
first evaluation needs. It is in the history at `4827e93` if it is wanted back.

## Known divergences from the API

Recorded here because a validator that differs from the endpoint it fronts is a support
burden, not a feature.

1. **`language` is undeclared.** Responses always include it; submissions are read for it
   (`$this->langcode = $data['language'] ?? 'en'`) but can never supply it, because schema
   validation runs first and `additionalProperties: false` rejects it. That fallback is
   effectively dead code. Confirmed against the real validator, which reports
   `Property 'language' not defined in the schema and additional properties are not
   allowed.` for the spec's own response example.

2. **`id` is unconstrained.** In `Assessment`, `EuropeanUnionOrganisation`,
   `MemberStateOrganisation` and `Asset` the property is written as `id:` → `schema:` →
   `$ref`. Inside a `properties` map the value *is* the schema; there is no `schema:`
   keyword, so the reference to `UUID` never applies and any value passes. Faithfully
   reproduced here — the generator derives, it does not correct.

3. **Dialect gap.** The spec is 2020-12, but Joinup validates with
   `justinrainbow/json-schema` 6.10.0, which implements draft-04/06/07. The Test Bed runs
   `networknt/json-schema-validator`, which does support 2020-12. On any 2020-12-only
   keyword this validator will be stricter than the API.

## Publishing

Test Bed hosts the validator; this repository holds only its configuration. Once the
repository is pushed, ITB configure a webhook so pushes redeploy the validator
automatically — which is why `--check` in CI is not optional.
