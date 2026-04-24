import re
import pandas as pd


FREQUENCY_MAP = {
    "bid": 2,
    "twice daily": 2,
    "two times daily": 2,
    "once daily": 1,
    "daily": 1,
    "qd": 1,
    "tid": 3,
    "three times daily": 3,
}


ROUTE_MAP = {
    "oral": 4132161,
    "po": 4132161,
}


def normalize_text(text: str) -> str:
    """
    Lowercase and clean basic spacing.
    """
    return str(text).lower().replace("mg", " mg").replace("  ", " ").strip()


def normalize_route(route: str):
    """
    Convert raw route values like oral/PO to one demo OMOP route concept.
    """
    if pd.isna(route):
        return None

    route = str(route).strip().lower()
    return ROUTE_MAP.get(route)


def extract_frequency(text: str):
    """
    Convert frequency phrases into times per day.
    Examples:
    BID -> 2
    twice daily -> 2
    once daily -> 1
    """
    text = normalize_text(text)

    for phrase, value in FREQUENCY_MAP.items():
        if phrase in text:
            return value

    return None


def extract_strength_mg(text: str):
    """
    Extract medication strength and convert to mg.

    Handles:
    - 500 mg
    - 500mg
    - 0.5 g
    - 500/50 mg combo: returns first strength for metformin in this demo
    """
    text = normalize_text(text)

    gram_match = re.search(r"(\d+(\.\d+)?)\s*g\b", text)
    if gram_match:
        return float(gram_match.group(1)) * 1000

    mg_match = re.search(r"(\d+(\.\d+)?)\s*mg\b", text)
    if mg_match:
        return float(mg_match.group(1))

    return None


def extract_tablet_multiplier(text: str):
    """
    Handles:
    - take 2 tablets daily
    """
    text = normalize_text(text)

    match = re.search(r"take\s+(\d+)\s+tablet", text)
    if match:
        return int(match.group(1))

    return 1


def map_drug_concept(text: str, mapping_df: pd.DataFrame):
    """
    Map raw drug text to a mock OMOP/RxNorm-like standard concept.

    We sort by keyword length so that:
    - metformin er matches before metformin
    - metformin/sitagliptin matches before metformin
    """
    text_norm = normalize_text(text)

    mapping_df = mapping_df.copy()
    mapping_df["keyword_len"] = mapping_df["keyword"].str.len()
    mapping_df = mapping_df.sort_values("keyword_len", ascending=False)

    for _, row in mapping_df.iterrows():
        if row["keyword"] in text_norm:
            return {
                "drug_concept_id": row["drug_concept_id"],
                "standard_drug_name": row["standard_drug_name"],
                "ingredient_concept_id": row["ingredient_concept_id"],
                "ingredient_name": row["ingredient_name"],
                "formulation": row["formulation"],
                "is_combo_drug": str(row["is_combo_drug"]).lower() == "true",
            }

    return {
        "drug_concept_id": 0,
        "standard_drug_name": None,
        "ingredient_concept_id": None,
        "ingredient_name": None,
        "formulation": None,
        "is_combo_drug": None,
    }


def normalize_medication_row(row, mapping_df):
    """
    Convert one raw medication row into OMOP-style normalized fields.
    """
    drug_text = row["drug_source_value"]

    concept_info = map_drug_concept(drug_text, mapping_df)

    strength_mg = extract_strength_mg(drug_text)
    frequency_per_day = extract_frequency(drug_text)
    tablet_multiplier = extract_tablet_multiplier(drug_text)

    total_daily_dose_mg = None

    if strength_mg is not None:
        if frequency_per_day is not None:
            total_daily_dose_mg = strength_mg * frequency_per_day * tablet_multiplier
        elif tablet_multiplier > 1:
            total_daily_dose_mg = strength_mg * tablet_multiplier

    return {
        **row.to_dict(),
        **concept_info,
        "route_concept_id": normalize_route(row["route_source_value"]),
        "strength_mg": strength_mg,
        "frequency_per_day": frequency_per_day,
        "tablet_multiplier": tablet_multiplier,
        "total_daily_dose_mg": total_daily_dose_mg,
    }


def build_normalized_drug_exposure(source_a_path, source_b_path, mapping_path):
    """
    Main function:
    1. Load raw source A
    2. Load raw source B
    3. Rename both into OMOP-style common columns
    4. Normalize medication fields
    5. Return normalized drug_exposure-like dataframe
    """
    source_a = pd.read_csv(source_a_path)
    source_b = pd.read_csv(source_b_path)
    mapping_df = pd.read_csv(mapping_path)

    # Source A → OMOP-style columns
    a = source_a.rename(columns={
        "med_start_date": "drug_exposure_start_date",
        "med_text": "drug_source_value",
        "route": "route_source_value",
    })

    # Source B → OMOP-style columns
    b = source_b.rename(columns={
        "start_date": "drug_exposure_start_date",
        "medication_description": "drug_source_value",
        "route": "route_source_value",
    })

    common_cols = [
        "source_record_id",
        "person_id",
        "drug_exposure_start_date",
        "drug_source_value",
        "route_source_value",
        "source_system",
    ]

    combined = pd.concat([a[common_cols], b[common_cols]], ignore_index=True)
    combined["drug_exposure_start_date"] = pd.to_datetime(combined["drug_exposure_start_date"])

    normalized_rows = [
        normalize_medication_row(row, mapping_df)
        for _, row in combined.iterrows()
    ]

    normalized = pd.DataFrame(normalized_rows)

    normalized.insert(0, "drug_exposure_id", range(1, len(normalized) + 1))

    # Mock OMOP drug_type_concept_id values
    # In real OMOP, these indicate whether a record came from prescription, dispensing, etc.
    normalized["drug_type_concept_id"] = normalized["source_system"].map({
        "EHR": 32838,
        "Pharmacy": 32869,
    })

    # OMOP drug_exposure has a sig field for dosing instructions.
    normalized["sig"] = normalized["drug_source_value"]

    return normalized