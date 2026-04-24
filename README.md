# OMOP-Style Medication Deduplication Demo

## Problem

Two medication datasets may contain overlapping drug exposure records, but the same medication can be represented differently.

Example:

- Metformin 500 mg BID
- metformin 500mg twice daily
- Metformin 0.5 g BID

These strings are different, but they may represent the same medication exposure.

## Goal

Build a small OMOP-style pipeline that:

1. Loads two raw medication datasets.
2. Standardizes both into a simplified `drug_exposure` structure.
3. Maps drug text to mock standard drug concepts.
4. Normalizes dose, unit, frequency, route, and formulation.
5. Classifies pairs as:
   - duplicate
   - possible_duplicate
   - not_duplicate
6. Creates a final deduplicated output.

## Why OMOP-style?

Instead of comparing raw text directly, both sources are transformed into common OMOP-like fields:

- person_id
- drug_concept_id
- drug_exposure_start_date
- drug_source_value
- route_concept_id
- sig
- drug_type_concept_id

Additional derived fields are used for medication deduplication:

- strength_mg
- frequency_per_day
- total_daily_dose_mg
- formulation
- is_combo_drug

## Assumptions

- `person_id` is already harmonized across both sources.
- This demo focuses on metformin examples.
- A mock concept mapping file is used instead of real OMOP Athena vocabulary.
- Possible duplicates are not automatically merged.
- Combination drugs are not merged with single-ingredient drugs.

## Matching Rules

### Duplicate

Same:

- person_id
- ingredient concept
- formulation
- route
- start date window
- strength
- frequency
- total daily dose

### Possible Duplicate

Same patient and ingredient, but one of these is missing or conflicting:

- formulation
- frequency
- exact dose structure

### Not Duplicate

Different:

- patient
- ingredient
- dose
- combination drug status
- start date outside allowed window

## Outputs

Generated files:

- `outputs/normalized_drug_exposure.csv`
- `outputs/match_results.csv`
- `outputs/deduped_drug_exposure.csv`

## How to Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python src/main.py

## Optional Streamlit Demo

A lightweight Streamlit app is included to visually inspect the pipeline outputs:

- Normalized OMOP-style drug exposure records
- Pairwise deduplication match results
- Final deduplicated drug exposure table

To run the app:

```bash
streamlit run app.py