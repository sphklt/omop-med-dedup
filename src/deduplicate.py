import pandas as pd


def date_diff_days(date_a, date_b):
    """
    Absolute difference between two dates.
    """
    return abs((pd.to_datetime(date_a) - pd.to_datetime(date_b)).days)


def classify_pair(a, b, date_window_days=7):
    """
    Classify two medication records as:
    - duplicate
    - possible_duplicate
    - not_duplicate
    """

    if a["person_id"] != b["person_id"]:
        return "not_duplicate", 0.0, "Different person_id"

    if date_diff_days(a["drug_exposure_start_date"], b["drug_exposure_start_date"]) > date_window_days:
        return "not_duplicate", 0.0, "Start dates are outside allowed window"

    if a["ingredient_concept_id"] != b["ingredient_concept_id"]:
        return "not_duplicate", 0.0, "Different ingredient concept"

    if bool(a["is_combo_drug"]) != bool(b["is_combo_drug"]):
        return "not_duplicate", 0.0, "Combination drug vs single-ingredient drug"

    if a["route_concept_id"] != b["route_concept_id"]:
        return "possible_duplicate", 0.5, "Same drug but route differs or is missing"

    if a["formulation"] != b["formulation"]:
        return "possible_duplicate", 0.65, "Same drug/date but formulation differs"

    same_strength = a["strength_mg"] == b["strength_mg"]
    same_frequency = a["frequency_per_day"] == b["frequency_per_day"]
    same_daily_dose = a["total_daily_dose_mg"] == b["total_daily_dose_mg"]

    if same_strength and same_frequency and same_daily_dose:
        return (
            "duplicate",
            1.0,
            "Same ingredient, formulation, route, strength, frequency, daily dose, and date window",
        )

    if same_daily_dose and pd.notna(a["total_daily_dose_mg"]):
        return (
            "possible_duplicate",
            0.75,
            "Same total daily dose, but strength or frequency differs",
        )

    if pd.isna(a["frequency_per_day"]) or pd.isna(b["frequency_per_day"]):
        return "possible_duplicate", 0.6, "Frequency missing in one record"

    return "not_duplicate", 0.0, "Dose or frequency differs"


def generate_match_results(normalized_df):
    """
    Compare EHR records against Pharmacy records for the same person.
    """
    ehr = normalized_df[normalized_df["source_system"] == "EHR"]
    pharmacy = normalized_df[normalized_df["source_system"] == "Pharmacy"]

    results = []

    for _, a in ehr.iterrows():
        for _, b in pharmacy.iterrows():

            # Only compare records from same person to reduce unnecessary comparisons
            if a["person_id"] != b["person_id"]:
                continue

            status, confidence, reason = classify_pair(a, b)

            results.append({
                "record_a": a["source_record_id"],
                "record_b": b["source_record_id"],
                "person_id": a["person_id"],
                "match_status": status,
                "confidence": confidence,
                "reason": reason,
                "a_drug_source_value": a["drug_source_value"],
                "b_drug_source_value": b["drug_source_value"],
                "a_daily_dose_mg": a["total_daily_dose_mg"],
                "b_daily_dose_mg": b["total_daily_dose_mg"],
            })

    return pd.DataFrame(results)


def build_deduped_drug_exposure(normalized_df, match_results_df):
    """
    Create final deduplicated output.

    For true duplicates:
    - keep one canonical row
    - preserve both source record IDs

    For possible duplicates:
    - do not merge automatically
    - keep both records for review
    """
    duplicate_pairs = match_results_df[match_results_df["match_status"] == "duplicate"]

    merged_record_ids = set()
    canonical_rows = []

    for _, pair in duplicate_pairs.iterrows():
        a_id = pair["record_a"]
        b_id = pair["record_b"]

        a = normalized_df[normalized_df["source_record_id"] == a_id].iloc[0]
        b = normalized_df[normalized_df["source_record_id"] == b_id].iloc[0]

        # Demo rule:
        # Prefer EHR as canonical but keep both source IDs.
        canonical = a.to_dict()
        canonical["source_record_ids"] = f"{a_id},{b_id}"
        canonical["source_systems"] = f"{a['source_system']},{b['source_system']}"

        canonical_rows.append(canonical)

        merged_record_ids.add(a_id)
        merged_record_ids.add(b_id)

    # Keep records that were not merged
    remaining = normalized_df[~normalized_df["source_record_id"].isin(merged_record_ids)]

    for _, row in remaining.iterrows():
        canonical = row.to_dict()
        canonical["source_record_ids"] = row["source_record_id"]
        canonical["source_systems"] = row["source_system"]
        canonical_rows.append(canonical)

    deduped = pd.DataFrame(canonical_rows)
    deduped.insert(0, "canonical_drug_exposure_id", range(1, len(deduped) + 1))

    return deduped