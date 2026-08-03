# Reviewed Guideline Inputs

This directory commits provenance and checksums only. The reviewed starter
corpus supports the checksum-locked `metabolic-01` and `cardiovascular-01`
synthetic scenarios with two English WHO documents:

| Document | Version | Scenario | Local artifact |
|---|---|---|---|
| [Diagnosis and management of type 2 diabetes (HEARTS-D)](https://www.who.int/southeastasia/publications/i/item/who-ucn-ncd-20.1) | WHO/UCN/NCD/20.1, 2020 | `metabolic-01` | 35-page PDF |
| [Guideline for the pharmacological treatment of hypertension in adults](https://www.who.int/publications/i/item/9789240033986) | ISBN 978-92-4-003398-6, 2021 | `cardiovascular-01` | 61-page PDF artifact |

Both documents state the CC BY-NC-SA 3.0 IGO license. This project records the
more conservative `local_index_only` decision: downloaded PDFs, later
extracted text, chunks, and embeddings remain ignored and must not be
committed. Attribution is required, WHO endorsement must not be implied, the
WHO logo is not reused, and third-party materials must be excluded unless
separately approved.

The committed [`corpus-lock.json`](corpus-lock.json) contains exact source,
version, access, license-review, lifecycle, scenario, byte-size, page-count,
and SHA-256 metadata. It contains no guideline text or patient data.

## Acquire and Verify

Download missing reviewed artifacts and verify the complete set:

```bash
make guidelines-fetch
```

Verify already-downloaded artifacts without network access:

```bash
make guidelines-verify
```

The commands accept only the committed lock and the fixed local document
directory. Verification rejects missing or extra files, unsafe filenames,
unapproved download hosts or permissions, non-current sources, malformed PDF
envelopes, files over 4 MiB, byte-size drift, and checksum drift.

Acquisition is not parsing or ingestion. Sub-phase 3.3 must define bounded PDF
parsing and exclude unapproved third-party material before any text is
produced. Sub-phase 3.4 must define the Weaviate schema before indexing.
