# Synthetic FHIR Cohort Contract

## Purpose and Safety Boundary

The Phase 1 development cohort contains exactly four reviewed synthetic
patients. Each patient supports a specific clinical-QA or failure-handling
scenario. The cohort is not intended to represent prevalence, provide a
statistically meaningful sample, train a model, or support medical decisions.

Generated FHIR resources are local-only and must not be committed. Git retains
only generator inputs, review automation, and non-clinical content
fingerprints. No real patient record, production export, organization-derived
fixture, or manually de-identified clinical data is permitted.

## Generator Provenance

| Field | Pinned value |
|---|---|
| Generator | Synthea |
| Repository | `https://github.com/synthetichealth/synthea` |
| Release | `v4.0.0` |
| Release date | 2026-03-05 |
| Git commit | `0185c09ea9d10a822c6f5f3ef9bdcbcbe960c813` |
| License | Apache License 2.0 |
| FHIR version | R4 |
| Export form | Pretty-printed FHIR transaction Bundle JSON |
| Geography | Massachusetts, United States |

The numbered release is pinned instead of the moving `master-branch-latest`
artifact. Phase 1.2 uses the official `synthea-with-dependencies.jar` with
SHA-256 digest
`ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1`.
The generation script verifies that digest before execution.

Official references:

- [Synthea repository and usage](https://github.com/synthetichealth/synthea)
- [Synthea v4.0.0 release](https://github.com/synthetichealth/synthea/releases/tag/v4.0.0)
- [Synthea Apache-2.0 license](https://github.com/synthetichealth/synthea/blob/v4.0.0/LICENSE)

## Reproducible Candidate Generation

Phase 1.2 implements these pinned inputs:

| Input | Value | Reason |
|---|---|---|
| Population | `100` candidates | Large enough to select four focused scenarios without committing unrelated records |
| Overflow population | `false` | Keeps the candidate count exact and prevents extra deceased attempts from being exported |
| Patient seed | `20260727` | Stable population generation |
| Clinician seed | `104729` | Stable provider references |
| Reference date | `20260727` | Prevents patient ages and clinical histories changing with wall-clock time |
| Age range | `45-80` | Focuses the first clinical-QA slice on adult chronic-care records |
| Location | `Massachusetts` | Uses Synthea's built-in US demographics without organization data |
| History window | `10` years | Retains enough longitudinal context while bounding bundle size |

Required explicit exporter settings:

```properties
exporter.fhir.export=true
exporter.fhir_stu3.export=false
exporter.fhir_dstu2.export=false
exporter.fhir.transaction_bundle=true
exporter.fhir.bulk_data=false
exporter.fhir.use_us_core_ig=false
exporter.use_uuid_filenames=true
exporter.pretty_print=true
exporter.metadata.export=true
exporter.years_of_history=10
generate.log_patients.detail=none
```

The implemented command is equivalent to:

```bash
./run_synthea \
  -s 20260727 \
  -cs 104729 \
  -r 20260727 \
  -p 100 \
  -o false \
  -a 45-80 \
  --exporter.baseDirectory=./data/generated/synthea-v4.0.0 \
  --exporter.fhir.export=true \
  --exporter.fhir_stu3.export=false \
  --exporter.fhir_dstu2.export=false \
  --exporter.fhir.transaction_bundle=true \
  --exporter.fhir.bulk_data=false \
  --exporter.fhir.use_us_core_ig=false \
  --exporter.use_uuid_filenames=true \
  --exporter.pretty_print=true \
  --exporter.metadata.export=true \
  --exporter.years_of_history=10 \
  Massachusetts
```

Phase 1.2 may wrap this command in a pinned container or script, but it must not
change the logical inputs without updating this contract and stopping for
review.

Unreviewed output must be written under `data/generated/`, which is ignored by
Git. Generation metadata must record:

- Synthea release, full commit, and execution artifact digest.
- Complete command and configuration checksum.
- Patient and clinician seeds.
- Reference date, population, age range, and geography.
- Actual UTC generation timestamp.
- Runtime and container or Java versions.
- Candidate count and selected fixture count.
- SHA-256 checksum and byte size for every selected fixture.

The actual generation timestamp records provenance but is not an input to
patient generation. Reproducibility is determined by the pinned release,
artifact, seeds, reference date, configuration, and fixture checksums.

## Reviewed Local Cohort

The reproducibly selected local cohort contains one patient for each alias:

| Stable alias | Required record characteristics | Representative read-only question |
|---|---|---|
| `metabolic-01` | Type 2 diabetes condition, glucose or HbA1c observations, and at least one related medication request | What recent glucose-related observations and recorded diabetes treatments are present? |
| `cardiovascular-01` | Hypertension condition, blood-pressure observations, and at least one related medication request | What recent blood-pressure observations and recorded hypertension treatments are present? |
| `allergy-respiratory-01` | A documented allergy plus a respiratory condition, observation, or medication request | What allergies and relevant respiratory records are documented? |
| `sparse-control-01` | A valid adult record with at least one encounter and observation, while one or more optional clinical categories are absent | What relevant data are present, and which expected categories are not documented? |

Aliases are application-owned labels stored in the cohort manifest. They must
not replace or modify the generated FHIR `Patient.id`, and tests must not depend
on generated names. If the pinned candidate pool does not contain one patient
for every scenario, Phase 1.2 must stop for review and change the generation
contract explicitly rather than substituting an unrelated patient.

Selection must be deterministic:

1. Parse every candidate as a FHIR R4 transaction Bundle.
2. Evaluate documented resource and code criteria for each scenario.
3. Sort matching candidates by FHIR `Patient.id`.
4. Select the first unused match for each alias in the table order.
5. Record the alias-to-patient-ID mapping and selection evidence in the
   manifest.

Selection evidence contains resource types, coding systems and codes, and
resource IDs only. It must not duplicate full resources or patient narratives.

## FHIR Resource Scope

Required application retrieval types:

- `Patient`
- `Condition`
- `AllergyIntolerance`
- `MedicationRequest`
- `Encounter`
- `Observation`, including vital signs and laboratory results
- `Procedure`
- `DiagnosticReport`

Supporting types such as `Organization`, `Practitioner`, `PractitionerRole`,
`Location`, or `CarePlan` may remain in a generated transaction Bundle when
needed for valid references. They are not part of the Phase 1 normalized
patient summary.

Intentionally excluded from Phase 1 application retrieval:

- Financial and insurance resources such as `Claim`, `ExplanationOfBenefit`,
  and `Coverage`.
- Binary or media payloads, clinical notes, and document attachments.
- Imaging content, devices, supplies, genomics, and questionnaire responses.
- Immunizations and care-team details.
- Write, update, or delete operations for every resource type.

Phase 1.2 may use exporter inclusion settings to reduce fixtures only after
verifying that transaction references remain valid. Otherwise out-of-scope
supporting resources may remain in the fixture but must not be retrieved or
normalized by application code.

## Fixture Review Gate

Every selected local fixture must pass all checks before it is loaded into
HAPI:

### Structure and Integrity

- Valid UTF-8 JSON with `resourceType: Bundle` and `type: transaction`.
- Exactly one primary `Patient` resource.
- All entries are FHIR R4 resources with unique `fullUrl` values.
- Transaction requests and internal references are structurally valid.
- The bundle imports into the pinned local HAPI FHIR server without a partial
  transaction.
- The selected patient satisfies the documented alias criteria.

### Safety and Provenance

- Generated only from the pinned Synthea inputs above.
- Contains no real person, organization, credential, hostname, access token, or
  copied clinical narrative.
- Synthetic status and source are explicit in the manifest and documentation.
- File name uses the stable alias, not a generated patient name.
- Logs, reviews, and checksums do not reproduce full patient resources.

### Size and Scope

- Exactly four locally selected patient Bundles.
- No individual Bundle exceeds 8 MiB or 1,000 entries.
- The complete local cohort does not exceed 24 MiB.
- No base64 binary, media, or document attachment is retained.
- Only resources necessary for scenario evidence or valid transaction
  references remain.

If a hard size or integrity limit cannot be met without unsafe manual edits,
stop and revise the generation/export configuration at the Phase 1.2 review
checkpoint.

## Required Runtime Manifest and Committed Lock

Phase 1.2 creates an ignored machine-readable runtime manifest beside the local
fixtures. At minimum it contains:

- Schema version and explicit `synthetic_data: true`.
- Generator provenance and license.
- Full reproducible generation inputs and actual generation timestamp.
- Candidate and selected counts.
- One entry per stable alias with FHIR patient ID, relative fixture path,
  SHA-256 checksum, byte size, entry count, and selection evidence.
- Review status, reviewer identifier suitable for the repository, and review
  date.

The manifest must contain no generated patient display names, addresses,
telecom values, narratives, or complete resource bodies.

Git retains only `cohort-lock.json`, which contains:

- A schema version and marker that it contains checksums only.
- Generator version, commit, execution artifact digest, deterministic inputs,
  and configuration checksum.
- One entry per stable alias with SHA-256 checksum, byte size, and entry count.
- Two supporting-batch entries with aliases, checksums, sizes, entry counts,
  and resource-type counts for Organization, Location, and Practitioner
  dependencies.

The lock must not contain patient IDs, display names, addresses, clinical
codes, resource IDs, selection evidence, narratives, or complete resources.
Selection and verification must fail if local output differs from the lock.
