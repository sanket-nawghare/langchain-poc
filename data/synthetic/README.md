# Synthetic Patient Data

This directory must contain synthetic data only.

The [cohort contract](COHORT_CONTRACT.md) pins generator provenance,
reproducible inputs, four scenario-driven aliases, FHIR R4 resource scope, and
the review gate for Phase 1 fixtures.

No patient fixture has been generated or approved yet. Unreviewed generator
output belongs under the ignored `data/generated/` directory. Only fixtures
that pass the cohort contract may be added here during sub-phase 1.2.
