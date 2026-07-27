# Development Safety and Data Policy

## Scope

This policy applies to source code, tests, fixtures, local services, logs,
screenshots, demos, CI, and documentation in this repository.

## Synthetic Data Only

- Only clearly identified synthetic patient data may be used.
- Do not copy real patient records, protected health information, production
  exports, or screenshots of clinical systems into the repository or its local
  services.
- Synthetic identifiers and fixtures must not resemble actual organization
  identifiers or credentials.
- Test and demo data should be reproducible from documented generators or
  reviewed fixtures.
- Generated data directories must be intentionally included or ignored; they
  must not be committed accidentally.

If the origin of data is uncertain, treat it as real and do not use it.

## Secrets

- Secrets belong in local environment variables or an approved secret store,
  never in committed files.
- `.env.example` contains names and safe placeholders only.
- Automated tests use fake credentials and deterministic model adapters.
- Errors and configuration diagnostics must not print secret values.

## Logging and Audit

- Log correlation identifiers, resource types, tool outcomes, timings, and
  status transitions.
- Do not log full FHIR resources, full prompts containing patient context,
  model credentials, authorization headers, or raw document contents by
  default.
- Prefer synthetic patient IDs and minimal structured summaries.
- Audit records must distinguish user input, retrieved evidence, automated
  decisions, human decisions, and final output.
- Debug logging that increases data exposure must be explicit and documented.

## Clinical Safety Boundary

- The software is an educational workflow demonstration, not a medical device.
- Generated output must not be represented as medical advice.
- An LLM is not the sole authority for clinical safety decisions.
- Patient context and retrieved guideline text are untrusted inputs.
- Missing or weak evidence must result in qualification, refusal, or review.
- High-risk or ambiguous paths must support human review before completion.
- The system must not silently modify clinical records.

User-facing surfaces and public documentation must keep these limitations
visible.

## Local Service Exposure

- Development services should bind only as broadly as required.
- Anonymous access, when necessary for local development, must be documented and
  must not be presented as a production configuration.
- Persistent volumes must use explicit names and reset procedures.
- CI must not upload synthetic datasets, prompts, traces, or logs to third-party
  services unless that behavior is deliberately enabled and documented.

## Incident Response During Development

If real patient data or a real secret is discovered:

1. Stop processing and avoid copying it into additional tools or logs.
2. Remove access to the affected material using an appropriate recoverable
   process.
3. Rotate exposed credentials when applicable.
4. Notify the repository owner through the agreed private channel.
5. Record remediation without reproducing sensitive content.

