# Phase 7 - Packaging, Documentation, and First Release

Phase 7 turns the completed MVP into a reproducible local demo package.

## Completed Packaging Surface

- `make demo-up` prepares dependencies, starts infrastructure, seeds FHIR,
  fetches/indexes guidelines, and starts both development apps.
- `README.md` is the contributor entry point.
- `docs/GUIDED_DEMO.md` provides seeded patient IDs, supported questions,
  expected outcomes, and screenshot/recording capture points.
- `docs/EXTENDING_THE_SYSTEM.md` documents how to add a tool, graph node, model
  provider, and guideline.
- `docs/RELEASE_CHECKLIST.md` defines the first MVP release gate.
- `RELEASE_NOTES.md` summarizes the MVP candidate and known limitations.
- `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SECURITY.md` are
  present.

## Documentation Map

| Need | Document |
|---|---|
| Quick start | `README.md` |
| Local setup and configuration | `docs/DEVELOPMENT.md` |
| Architecture | `docs/ARCHITECTURE.md` |
| Contracts and provider boundaries | `docs/CONTRACTS_AND_CONFIGURATION.md` |
| Demo script | `docs/GUIDED_DEMO.md` |
| Current capabilities | `docs/CURRENT_SYSTEM_CAPABILITIES.md` |
| Troubleshooting | `docs/PHASE_6_QUALITY_SECURITY_OBSERVABILITY.md` |
| Quality gates | `docs/QUALITY_GATES.md` |
| Extension points | `docs/EXTENDING_THE_SYSTEM.md` |
| Release checklist | `docs/RELEASE_CHECKLIST.md` |

## Screenshot and Recording Notes

Generated screenshots are not committed by default because they depend on the
operator's current local ports, provider mode, seeded services, and browser
theme. The release package instead defines exact capture points in
`docs/GUIDED_DEMO.md` so screenshots or a short recording can be produced from
the same verified local environment used for the demo.

Do not capture secrets, `.env` files, provider dashboards, raw FHIR bundles,
downloaded guideline PDFs, or any real patient data.

## Release Boundary

The MVP is ready to tag when:

- `make check` passes;
- `make phase6-quality-gate` passes;
- local infrastructure gates in `docs/RELEASE_CHECKLIST.md` pass;
- the maintainer accepts the current known limitations;
- the tag name is chosen.

Recommended local tag for this MVP candidate:

```bash
git tag v0.1.0
```
