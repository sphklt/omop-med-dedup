# Athena Vocabulary Files

The CSV files in this directory are not tracked in git because they exceed
GitHub's 100 MB file size limit.

## How to download

1. Create a free account at https://athena.ohdsi.org
2. Click **Download** and select the **RxNorm** vocabulary (and optionally NDC).
3. Extract the downloaded archive and copy the following files here:

```
vocab/CONCEPT.csv
vocab/CONCEPT_RELATIONSHIP.csv
vocab/CONCEPT_ANCESTOR.csv
vocab/DRUG_STRENGTH.csv
```

The pipeline auto-detects `vocab/CONCEPT.csv` at startup and uses it for
real RxNorm concept IDs. `CONCEPT_RELATIONSHIP.csv` is required for brand
name lookup (e.g. Glucophage → metformin). The other files are not used
by the pipeline currently but are included for completeness.

Without these files the pipeline falls back to the mock keyword mapping in
`data/mock_concept_mapping.csv`.
