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

## How to Run the Pipeline

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the deduplication pipeline:

```bash
python src/main.py
```

## Optional Streamlit App

This project also includes a lightweight Streamlit app for visually inspecting the pipeline outputs.

The app helps review:

- Normalized OMOP-style drug exposure records
- Pairwise deduplication match results
- Final deduplicated drug exposure table

This is useful for quickly validating how the raw medication records were standardized, matched, and deduplicated.

### Run the Streamlit App

After installing the dependencies, start the app with:

```bash
streamlit run app.py
```

Then open the local URL shown in the terminal, usually:

```text
http://localhost:8501
```

## Project Structure

A typical project structure may look like this:

```text
omop-medication-deduplication/
├── app.py
├── requirements.txt
├── README.md
├── data/
│   ├── source_a_medications.csv
│   ├── source_b_medications.csv
│   └── mock_concept_mapping.csv
├── outputs/
│   ├── normalized_drug_exposure.csv
│   ├── match_results.csv
│   └── deduped_drug_exposure.csv
└── src/
    ├── main.py
    ├── normalize.py
    ├── matcher.py
    └── deduplicate.py
```

## Notes

This is a simplified demo inspired by OMOP-style medication normalization and deduplication. It is not a full OMOP CDM implementation and does not use official OMOP Athena vocabularies.

The goal is to demonstrate how medication text from multiple sources can be standardized into common fields before applying rule-based deduplication logic.