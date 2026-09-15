# Security Policy

## Supported Scope

This repository is a local synthetic-data MVP. Security reports are in scope
when they affect:

- committed source code;
- local development configuration;
- API redaction boundaries;
- workflow persistence;
- provider adapter credential handling;
- synthetic data or guideline ingestion scripts.

Production deployment, authentication, authorization, SMART on FHIR, and
internet-facing hardening are not implemented yet.

## Reporting a Vulnerability

Report vulnerabilities privately to the repository maintainers. Do not open a
public issue containing secrets, exploit details, real patient data, or live
provider credentials.

Please include:

- affected component;
- reproduction steps using synthetic data;
- expected and observed behavior;
- impact;
- suggested fix, if known.

## Secret Handling

- Never commit `.env`, provider API keys, database dumps, real patient data,
  generated FHIR bundles, downloaded guideline documents, SQLite files, or
  vector-store data.
- Run `make phase6-quality-gate` before sharing changes.
- Rotate any credential that was accidentally committed or exposed in logs.

## Clinical Safety Boundary

This project is not a medical device. Reports about unsafe claims, missing
citations, prompt-injection exposure, or failures to preserve synthetic-only
boundaries are treated as security-relevant for this MVP.
