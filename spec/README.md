# Vendored OpenAPI specification

`assessments.openapi.yaml` is a **copy** of

```
web/modules/custom/assessments/openapi/assessments.openapi.yaml
```

from the Joinup repository. It is vendored so that CI can verify the generated schemas
without needing credentials for EC GitLab.

| | |
|---|---|
| Source commit | `32a49ff3ba17590dd2b3382c7253cc9d19f2f6a2` |
| Commit date | 2026-03-10 |
| SHA-256 | `7cc5b10863b0d19886965ac6b5ba1165e8510eab6b458c4a78929617cfd01a6a` |

## What this does and does not guarantee

CI checks that `resources/assessment/schemas/` matches **this copy**. So it catches a
hand-edited schema, and it catches someone updating the copy without regenerating.

It does **not** catch Joinup changing the upstream spec — that drift is invisible here
until somebody refreshes this file. Closing that gap needs CI that reads the spec from
GitLab directly; see the CI section of the root README.

## Refreshing

```bash
cp ../joinup/web/modules/custom/assessments/openapi/assessments.openapi.yaml spec/
bin/generate-schemas.py --spec spec/assessments.openapi.yaml
bin/run-tests.py
```

Update the table above with the new commit and hash in the same commit as the refresh, so
the provenance is never a guess.
