import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Units that are all normalized to mg in extract_strength_info — safe to compare numerically
_MG_COMPARABLE = {"mg", "g", "mcg"}


def _units_comparable(unit_a, unit_b) -> bool:
    """
    Return True when both units were normalized to mg and can be compared numerically.
    Treats None/NaN as "unknown" and allows the numerical comparison to proceed.
    If one unit is mg-compatible and the other is not (e.g., mg vs units), return False.
    """
    if pd.isna(unit_a) or pd.isna(unit_b):
        return True
    a_compat = unit_a in _MG_COMPARABLE
    b_compat = unit_b in _MG_COMPARABLE
    if a_compat != b_compat:
        return False
    if not a_compat and not b_compat:
        return unit_a == unit_b
    return True


def doses_equal(a, b, tolerance: float = 0.01) -> bool:
    """
    Check whether two dose values are equal within a relative tolerance.
    Two NaN values are considered equal (both unknown → treat as matching).
    """
    a_nan = pd.isna(a)
    b_nan = pd.isna(b)
    if a_nan and b_nan:
        return True
    if a_nan or b_nan:
        return False
    if a == 0 and b == 0:
        return True
    if a == 0 or b == 0:
        return False
    return abs(a - b) / max(abs(a), abs(b)) <= tolerance


def date_diff_days(date_a, date_b) -> int:
    return abs((pd.to_datetime(date_a) - pd.to_datetime(date_b)).days)


def classify_pair(a, b, date_window_days: int = 7, dose_tolerance: float = 0.01):
    """
    Classify two normalized medication records as duplicate, possible_duplicate,
    or not_duplicate.

    Returns (match_status, confidence, reason).
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

    # Block numerical comparison only when units are fundamentally incompatible
    # (e.g., mg vs units). g vs mg is fine — both are already normalized to mg.
    a_unit = a.get("strength_unit") if hasattr(a, "get") else None
    b_unit = b.get("strength_unit") if hasattr(b, "get") else None
    if not _units_comparable(a_unit, b_unit):
        return "possible_duplicate", 0.55, "Same drug but strength units are not comparable"

    # For combo drugs compare the full strength profile instead of a single value
    if bool(a["is_combo_drug"]):
        a_combo = a.get("combo_strengths") if hasattr(a, "get") else None
        b_combo = b.get("combo_strengths") if hasattr(b, "get") else None
        if pd.notna(a_combo) and pd.notna(b_combo):
            if a_combo != b_combo:
                return "not_duplicate", 0.0, "Combo drug strength profiles differ"
            # combo strengths match — fall through to frequency/dose checks below
            # using total_daily_dose_mg as the remaining signal
        else:
            return "possible_duplicate", 0.6, "Combo drug strengths missing in one record"

    same_strength = doses_equal(a["strength_mg"], b["strength_mg"], dose_tolerance)
    same_frequency = doses_equal(a["frequency_per_day"], b["frequency_per_day"], dose_tolerance)
    same_daily_dose = doses_equal(a["total_daily_dose_mg"], b["total_daily_dose_mg"], dose_tolerance)

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


def generate_match_results(
    normalized_df: pd.DataFrame,
    date_window_days: int = 7,
    dose_tolerance: float = 0.01,
) -> pd.DataFrame:
    """
    Compare records across all source systems for the same person.
    Supports any number of source systems — every unique ordered pair is compared.

    Blocking strategy
    -----------------
    Records are grouped by (person_id, ingredient_concept_id) before comparison.
    This means only records for the same patient AND same drug ingredient are ever
    paired — reducing comparisons from O(n²/p) to O(n²/(p·d)) where d is the mean
    number of distinct ingredients per patient.  Records with no mapped ingredient
    (ingredient_concept_id is null) are excluded from blocking and skipped, since
    there is no basis for determining whether they are duplicates.
    """
    systems = normalized_df["source_system"].unique().tolist()

    # All unique unordered pairs of source systems
    system_pairs = [
        (systems[i], systems[j])
        for i in range(len(systems))
        for j in range(i + 1, len(systems))
    ]

    results = []

    for sys_a, sys_b in system_pairs:
        records_a = normalized_df[normalized_df["source_system"] == sys_a]
        records_b = normalized_df[normalized_df["source_system"] == sys_b]

        # Block on (person_id, ingredient_concept_id).
        # dropna=True (default) skips records with null ingredient_concept_id —
        # unmapped drugs cannot be reliably identified as duplicates.
        a_by_block = {
            key: grp
            for key, grp in records_a.groupby(["person_id", "ingredient_concept_id"])
        }
        b_by_block = {
            key: grp
            for key, grp in records_b.groupby(["person_id", "ingredient_concept_id"])
        }

        for block_key in set(a_by_block) & set(b_by_block):
            for _, a in a_by_block[block_key].iterrows():
                for _, b in b_by_block[block_key].iterrows():
                    status, confidence, reason = classify_pair(
                        a, b, date_window_days, dose_tolerance
                    )
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

    if not results:
        return pd.DataFrame(columns=[
            "record_a", "record_b", "person_id", "match_status", "confidence",
            "reason", "a_drug_source_value", "b_drug_source_value",
            "a_daily_dose_mg", "b_daily_dose_mg",
        ])

    return pd.DataFrame(results)


def build_deduped_drug_exposure(
    normalized_df: pd.DataFrame,
    match_results_df: pd.DataFrame,
    canonical_preference: list = None,
) -> pd.DataFrame:
    """
    Build the final deduplicated output.

    canonical_preference: ordered list of source systems; the first system
    found in a duplicate pair becomes the canonical record.
    Defaults to the order source systems appear in the data.

    True duplicates are merged (one canonical row, both source IDs preserved).
    Possible duplicates are kept as-is for human review.
    """
    if canonical_preference is None:
        canonical_preference = normalized_df["source_system"].unique().tolist()

    duplicate_pairs = match_results_df[match_results_df["match_status"] == "duplicate"]

    # Pre-index once for O(1) lookups; iterating duplicate_pairs without this
    # would do an O(n) DataFrame scan per pair.
    normalized_index = normalized_df.set_index("source_record_id")

    merged_record_ids: set = set()
    canonical_rows = []

    for pair in duplicate_pairs.to_dict("records"):
        a_id = pair["record_a"]
        b_id = pair["record_b"]

        # Skip if either record was already merged into an earlier canonical
        if a_id in merged_record_ids or b_id in merged_record_ids:
            continue

        if a_id not in normalized_index.index or b_id not in normalized_index.index:
            logger.warning(
                "Duplicate pair references unknown record IDs: %s, %s", a_id, b_id
            )
            continue

        a = normalized_index.loc[a_id]
        b = normalized_index.loc[b_id]

        candidates = {a["source_system"]: a, b["source_system"]: b}
        canonical_row = next(
            (candidates[sys] for sys in canonical_preference if sys in candidates),
            a,
        )

        canonical = canonical_row.to_dict()
        canonical["source_record_ids"] = f"{a_id},{b_id}"
        canonical["source_systems"] = f"{a['source_system']},{b['source_system']}"
        canonical_rows.append(canonical)

        merged_record_ids.add(a_id)
        merged_record_ids.add(b_id)

    remaining = normalized_df[~normalized_df["source_record_id"].isin(merged_record_ids)]
    for rec in remaining.to_dict("records"):
        rec["source_record_ids"] = rec["source_record_id"]
        rec["source_systems"] = rec["source_system"]
        canonical_rows.append(rec)

    deduped = pd.DataFrame(canonical_rows)
    deduped.insert(0, "canonical_drug_exposure_id", range(1, len(deduped) + 1))

    return deduped
