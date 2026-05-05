import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)

FREQUENCY_MAP = {
    "four times daily": 4,
    "three times daily": 3,
    "two times daily": 2,
    "twice weekly": 2 / 7,
    "twice daily": 2,
    "once weekly": 1 / 7,
    "once daily": 1,
    "every 12 hours": 2,
    "every 8 hours": 3,
    "every 6 hours": 4,
    "every 4 hours": 6,
    "every other day": 0.5,
    "daily": 1,
    "weekly": 1 / 7,
    "monthly": 1 / 30,
    "qid": 4,
    "tid": 3,
    "bid": 2,
    "qod": 0.5,
    "qhs": 1,
    "qam": 1,
    "qpm": 1,
    "qd": 1,
    "q12h": 2,
    "q8h": 3,
    "q6h": 4,
    "q4h": 6,
}

ROUTE_MAP = {
    "oral": 4132161,
    "po": 4132161,
    "by mouth": 4132161,
    "intravenous": 4171047,
    "iv": 4171047,
    "topical": 4263689,
    "inhalation": 4186834,
    "inhaled": 4186834,
    "subcutaneous": 4142048,
    "sq": 4142048,
    "sc": 4142048,
    "sublingual": 4292110,
    "sl": 4292110,
    "transdermal": 4262099,
    "patch": 4262099,
    "rectal": 4115462,
    "pr": 4115462,
    "intramuscular": 4302612,
    "im": 4302612,
    "nasal": 4262914,
    "intranasal": 4262914,
    "ophthalmic": 4157760,
    "otic": 4023156,
}

WORD_TO_NUMBER = {
    "four": 4,
    "three": 3,
    "two": 2,
    "one": 1,
    "half": 0.5,
    "one-half": 0.5,
}

# Pre-sorted once at module load — avoids re-sorting on every extract_frequency call
_FREQUENCY_PHRASES = sorted(FREQUENCY_MAP, key=len, reverse=True)


def normalize_text(text: str) -> str:
    text = str(text).lower()
    # Insert space before standalone "mg" — negative lookbehind avoids matching "mcg"
    text = re.sub(r"(?<![a-z])mg\b", " mg", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def normalize_route(route: str):
    if pd.isna(route):
        return None
    return ROUTE_MAP.get(str(route).strip().lower())


def extract_frequency(text: str):
    """
    Convert frequency phrases to times-per-day.
    Sorts by phrase length descending so "twice daily" matches before "daily".
    Returns None when no frequency phrase is recognized (e.g., prn / as needed).
    """
    text = normalize_text(text)
    for phrase in _FREQUENCY_PHRASES:
        if phrase in text:
            return FREQUENCY_MAP[phrase]
    return None


def extract_strength_info(text: str) -> dict:
    """
    Extract medication strength and normalize to mg where possible.

    Supported conversions:
      mcg  → mg (÷ 1000)
      g    → mg (× 1000)
      mg   → mg (as-is)
      units / mEq → not convertible; strength_mg is set to None

    Returns {"strength_mg": float|None, "strength_unit": str|None}.
    """
    text_lower = str(text).lower().strip()

    # mcg — must check before mg so "100 mcg" isn't confused with "mg"
    m = re.search(r"(\d+(?:\.\d+)?)\s*mcg\b", text_lower)
    if m:
        return {"strength_mg": float(m.group(1)) / 1000, "strength_unit": "mcg"}

    # mg — explicit milligrams
    m = re.search(r"(\d+(?:\.\d+)?)\s*mg\b", text_lower)
    if m:
        return {"strength_mg": float(m.group(1)), "strength_unit": "mg"}

    # g (grams) — won't accidentally match "mg" because we already returned above
    m = re.search(r"(\d+(?:\.\d+)?)\s*g\b", text_lower)
    if m:
        return {"strength_mg": float(m.group(1)) * 1000, "strength_unit": "g"}

    # units (insulin, heparin, etc.)
    m = re.search(r"(\d+(?:\.\d+)?)\s*units?\b", text_lower)
    if m:
        return {"strength_mg": None, "strength_unit": "units"}

    # mEq (electrolytes — not convertible to mg without molecular weight)
    m = re.search(r"(\d+(?:\.\d+)?)\s*meq\b", text_lower, re.IGNORECASE)
    if m:
        return {"strength_mg": None, "strength_unit": "mEq"}

    return {"strength_mg": None, "strength_unit": None}


def extract_strength_mg(text: str):
    """Backward-compatible wrapper around extract_strength_info."""
    return extract_strength_info(text)["strength_mg"]


def extract_combo_strengths(text: str, is_combo: bool):
    """
    For combo drugs, extract all slash-separated strengths as a sorted
    pipe-delimited string so they can be compared symmetrically.
    Example: 'Metformin/Sitagliptin 500/50 mg BID' → '50.0|500.0'
    Returns None for non-combo drugs.
    """
    if not is_combo:
        return None
    text_lower = str(text).lower().strip()
    m = re.search(r"([\d.]+(?:/[\d.]+)+)\s*mg\b", text_lower)
    if m:
        parts = sorted(float(x) for x in m.group(1).split("/"))
        return "|".join(str(p) for p in parts)
    return None


def extract_tablet_multiplier(text: str) -> float:
    """
    Extract the per-dose tablet/capsule count.

    Handles:
      - "take 2 tablets daily", "take 2 tabs BID", "take 2 capsules"
      - "2 tablets daily" (without "take")
      - word forms: "take two tablets"
      - fractions: "½ tablet", "1/2 tab"
    """
    text = normalize_text(text)

    # Fractions first — must precede the digit pattern to avoid matching the "2" in "1/2"
    if re.search(r"(?:½|1/2)\s+(?:tablet|tab|capsule|cap)s?", text):
        return 0.5

    # Numeric with "take": "take 2 tablet(s)"
    m = re.search(r"take\s+(\d+(?:\.\d+)?)\s+(?:tablet|tab|capsule|cap)s?", text)
    if m:
        return float(m.group(1))

    # Numeric without "take": "2 tablets daily"
    m = re.search(r"(\d+(?:\.\d+)?)\s+(?:tablet|tab|capsule|cap)s?", text)
    if m:
        return float(m.group(1))

    # Word forms: "take two tablets", "two tabs"
    for word, num in WORD_TO_NUMBER.items():
        if re.search(rf"(?:take\s+)?{word}\s+(?:tablet|tab|capsule|cap)s?", text):
            return num

    return 1.0


def _validate_columns(df: pd.DataFrame, required: list, source_name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"{source_name} is missing required columns: {missing}. "
            f"Found: {list(df.columns)}"
        )


def _prepare_mapping(mapping_df: pd.DataFrame) -> pd.DataFrame:
    """
    Sort mapping by keyword length descending so longest keyword wins during lookup.
    Call once at load time and pass the result to map_drug_concept / normalize_medication_row.
    """
    df = mapping_df.copy()
    df["keyword_len"] = df["keyword"].str.len()
    return df.sort_values("keyword_len", ascending=False).reset_index(drop=True)


def map_drug_concept(text: str, concept_mapper) -> dict:
    """
    Map raw drug text to an OMOP-style concept.

    concept_mapper may be either:
      - an AthenaVocab instance (real RxNorm vocabulary), or
      - a pre-sorted DataFrame from _prepare_mapping() (mock/legacy mapping).

    AthenaVocab is used when available; the DataFrame path is retained for
    backward compatibility with existing tests and the mock data pipeline.
    """
    if hasattr(concept_mapper, "lookup"):
        return concept_mapper.lookup(text)

    # Legacy DataFrame path: longest keyword wins (df pre-sorted by keyword length)
    text_norm = normalize_text(text)
    for _, row in concept_mapper.iterrows():
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


def normalize_medication_row(row, concept_mapper) -> dict:
    """Convert one raw medication row into OMOP-style normalized fields."""
    try:
        drug_text = row["drug_source_value"]
        concept_info = map_drug_concept(drug_text, concept_mapper)
        is_combo = bool(concept_info.get("is_combo_drug"))

        combo_strengths = extract_combo_strengths(drug_text, is_combo)
        frequency_per_day = extract_frequency(drug_text)
        tablet_multiplier = extract_tablet_multiplier(drug_text)

        if is_combo:
            # Slash-notation strength is ambiguous per ingredient; use combo_strengths instead
            strength_mg = None
            strength_unit = None
        else:
            strength_info = extract_strength_info(drug_text)
            strength_mg = strength_info["strength_mg"]
            strength_unit = strength_info["strength_unit"]

        total_daily_dose_mg = None
        if strength_mg is not None:
            if frequency_per_day is not None:
                total_daily_dose_mg = strength_mg * frequency_per_day * tablet_multiplier
            elif tablet_multiplier > 1:
                total_daily_dose_mg = strength_mg * tablet_multiplier

        return {
            **row.to_dict(),
            **concept_info,
            "route_concept_id": normalize_route(row.get("route_source_value")),
            "strength_mg": strength_mg,
            "strength_unit": strength_unit,
            "combo_strengths": combo_strengths,
            "frequency_per_day": frequency_per_day,
            "tablet_multiplier": tablet_multiplier,
            "total_daily_dose_mg": total_daily_dose_mg,
        }
    except Exception as e:
        logger.warning(
            "Failed to normalize record %s: %s",
            row.get("source_record_id", "unknown"),
            e,
        )
        return {
            **row.to_dict(),
            "drug_concept_id": 0,
            "standard_drug_name": None,
            "ingredient_concept_id": None,
            "ingredient_name": None,
            "formulation": None,
            "is_combo_drug": None,
            "route_concept_id": None,
            "strength_mg": None,
            "strength_unit": None,
            "combo_strengths": None,
            "frequency_per_day": None,
            "tablet_multiplier": 1.0,
            "total_daily_dose_mg": None,
        }


def build_normalized_drug_exposure(
    source_a_path,
    source_b_path,
    mapping_path=None,
    *,
    vocab_concept_path=None,
    vocab_relationship_path=None,
):
    """
    Build a normalized OMOP-style drug_exposure table from two source CSVs.

    Concept mapping precedence:
      1. vocab_concept_path — path to Athena CONCEPT.csv; uses real RxNorm IDs.
         vocab_relationship_path (optional) enables brand name lookup.
      2. mapping_path       — legacy mock keyword-mapping CSV.

    At least one of the two must be provided.
    """
    if vocab_concept_path is None and mapping_path is None:
        raise ValueError("Provide either vocab_concept_path (Athena) or mapping_path (mock).")

    source_a = pd.read_csv(source_a_path)
    source_b = pd.read_csv(source_b_path)

    _validate_columns(
        source_a, ["source_record_id", "person_id", "med_start_date", "med_text", "route", "source_system"],
        "source_a",
    )
    _validate_columns(
        source_b, ["source_record_id", "person_id", "start_date", "medication_description", "route", "source_system"],
        "source_b",
    )

    if vocab_concept_path is not None:
        from vocab import AthenaVocab
        concept_mapper = AthenaVocab(vocab_concept_path, vocab_relationship_path)
    else:
        mapping_raw = pd.read_csv(mapping_path)
        _validate_columns(
            mapping_raw,
            ["keyword", "drug_concept_id", "standard_drug_name", "ingredient_concept_id",
             "ingredient_name", "formulation", "is_combo_drug"],
            "concept_mapping",
        )
        concept_mapper = _prepare_mapping(mapping_raw)

    a = source_a.rename(columns={
        "med_start_date": "drug_exposure_start_date",
        "med_text": "drug_source_value",
        "route": "route_source_value",
    })

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

    normalized_rows = combined.apply(
        lambda row: normalize_medication_row(row, concept_mapper), axis=1
    ).tolist()

    normalized = pd.DataFrame(normalized_rows)
    normalized.insert(0, "drug_exposure_id", range(1, len(normalized) + 1))

    normalized["drug_type_concept_id"] = normalized["source_system"].map({
        "EHR": 32838,
        "Pharmacy": 32869,
    })

    normalized["sig"] = normalized["drug_source_value"]

    return normalized
