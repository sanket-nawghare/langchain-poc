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

Acquisition alone is not parsing or ingestion. The bounded parser, versioned
Weaviate index, and retrieval evaluation remain separate explicit commands.

## Deterministic Local Chunks

Build the ignored local chunk output after acquiring the exact PDFs:

```bash
make guidelines-chunk
```

The pinned strict parser normalizes Unicode and whitespace, keeps every chunk
within one PDF page, limits chunks to 2,400 characters, and records document,
page, section hint, sequence, text checksum, and stable chunk ID. It rejects
encrypted files, active content, attachments, checksum/page-count drift,
empty text, and bounded-resource violations.

The generated `processed/chunks.json` contains extracted text and is ignored.
The committed [`chunk-lock.json`](chunk-lock.json) contains only parser
version, source hashes, chunk counts, aggregate chunk hashes, and boundary IDs.
For `deterministic-pypdf-v1`, the reviewed output is 40 HEARTS-D chunks and 95
hypertension chunks.

PDFs do not contain a reliable semantic layer. `section` is therefore a
deterministic heading hint for inspection; the exact source checksum and PDF
page number remain the authoritative citation lineage.

## Retrieval Evaluation

The committed [`retrieval-evaluation.json`](retrieval-evaluation.json) contains
nine deidentified questions and expected assessments, top source/chunk IDs,
and minimum scores. It contains no patient data, guideline text, excerpts, or
vectors. Run the read-only live evaluation after indexing:

```bash
make phase3-retrieval-live-gate
```

The gate first verifies the exact local chunks and Weaviate index. It then
checks four in-scope sufficient cases, three unrelated insufficient cases, a
publisher exclusion, a historical cutoff, citation identity, policy version,
and result redaction. Output contains aggregate counts only.
