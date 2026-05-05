"""
Integration tests: run the full pipeline on the existing mock data
and assert on known outcomes.
"""
import os
import pytest
import pandas as pd

from normalize import build_normalized_drug_exposure
from deduplicate import generate_match_results, build_deduped_drug_exposure

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
VOCAB_PATH = os.path.join(os.path.dirname(__file__), "..", "vocab", "CONCEPT.csv")


@pytest.fixture(scope="module")
def pipeline():
    normalized = build_normalized_drug_exposure(
        os.path.join(DATA_DIR, "source_a_medications.csv"),
        os.path.join(DATA_DIR, "source_b_medications.csv"),
        mapping_path=os.path.join(DATA_DIR, "mock_concept_mapping.csv"),
    )
    match_results = generate_match_results(normalized, date_window_days=7, dose_tolerance=0.01)
    deduped = build_deduped_drug_exposure(
        normalized, match_results, canonical_preference=["EHR", "Pharmacy"]
    )
    return normalized, match_results, deduped


class TestNormalization:
    def test_total_record_count(self, pipeline):
        normalized, _, _ = pipeline
        assert len(normalized) == 16  # 8 source A + 8 source B

    def test_required_columns_present(self, pipeline):
        normalized, _, _ = pipeline
        for col in [
            "drug_exposure_id", "person_id", "drug_exposure_start_date",
            "drug_concept_id", "strength_mg", "strength_unit",
            "frequency_per_day", "total_daily_dose_mg", "route_concept_id",
            "combo_strengths",
        ]:
            assert col in normalized.columns, f"Missing column: {col}"

    def test_no_rows_dropped_on_error(self, pipeline):
        normalized, _, _ = pipeline
        assert normalized["drug_exposure_id"].notna().all()

    def test_grams_converted_to_mg(self, pipeline):
        # A7: "Metformin 0.5 g BID" → 500 mg
        normalized, _, _ = pipeline
        rec = normalized[normalized["source_record_id"] == "A7"].iloc[0]
        assert rec["strength_mg"] == 500.0
        assert rec["strength_unit"] == "g"

    def test_combo_drug_has_combo_strengths(self, pipeline):
        # A6: "Metformin/Sitagliptin 500/50 mg BID"
        normalized, _, _ = pipeline
        rec = normalized[normalized["source_record_id"] == "A6"].iloc[0]
        assert pd.isna(rec["strength_mg"])
        assert rec["combo_strengths"] == "50.0|500.0"

    def test_tablet_multiplier_applied(self, pipeline):
        # A4: "Metformin 500 mg tablet take 2 tablets daily" → 1000 mg/day
        normalized, _, _ = pipeline
        rec = normalized[normalized["source_record_id"] == "A4"].iloc[0]
        assert rec["tablet_multiplier"] == 2.0
        assert rec["total_daily_dose_mg"] == 1000.0


class TestMatching:
    def _pair(self, match_results, a_id, b_id):
        return match_results[
            (match_results["record_a"] == a_id) & (match_results["record_b"] == b_id)
        ]

    def test_person_101_duplicate(self, pipeline):
        # A1 "Metformin 500 mg BID" vs B1 "metformin 500mg twice daily"
        _, match_results, _ = pipeline
        pair = self._pair(match_results, "A1", "B1")
        assert len(pair) == 1
        assert pair.iloc[0]["match_status"] == "duplicate"

    def test_person_107_grams_vs_mg_duplicate(self, pipeline):
        # A7 "Metformin 0.5 g BID" (→500 mg) vs B7 "metformin 500 mg twice daily"
        _, match_results, _ = pipeline
        pair = self._pair(match_results, "A7", "B7")
        assert len(pair) == 1
        assert pair.iloc[0]["match_status"] == "duplicate"

    def test_person_108_date_outside_window_not_duplicate(self, pipeline):
        # A8 2024-01-28 vs B8 2024-03-28 → 60 days apart
        _, match_results, _ = pipeline
        pair = self._pair(match_results, "A8", "B8")
        assert len(pair) == 1
        assert pair.iloc[0]["match_status"] == "not_duplicate"

    def test_person_104_tablet_multiplier_possible_duplicate(self, pipeline):
        # A4 "500 mg take 2 tablets daily" (1000 mg/day) vs B4 "1000 mg daily"
        # Same total daily dose but different per-tablet strength → possible_duplicate
        _, match_results, _ = pipeline
        pair = self._pair(match_results, "A4", "B4")
        assert len(pair) == 1
        assert pair.iloc[0]["match_status"] == "possible_duplicate"


@pytest.fixture(scope="module")
def athena_pipeline():
    """Full pipeline using real Athena RxNorm vocabulary."""
    pytest.importorskip("vocab")  # skip if vocab module unavailable
    if not os.path.exists(VOCAB_PATH):
        pytest.skip("Athena CONCEPT.csv not present — skipping Athena vocab tests")
    normalized = build_normalized_drug_exposure(
        os.path.join(DATA_DIR, "source_a_medications.csv"),
        os.path.join(DATA_DIR, "source_b_medications.csv"),
        vocab_concept_path=VOCAB_PATH,
    )
    match_results = generate_match_results(normalized, date_window_days=7, dose_tolerance=0.01)
    deduped = build_deduped_drug_exposure(
        normalized, match_results, canonical_preference=["EHR", "Pharmacy"]
    )
    return normalized, match_results, deduped


class TestAthenaVocab:
    def test_total_record_count(self, athena_pipeline):
        normalized, _, _ = athena_pipeline
        assert len(normalized) == 16

    def test_metformin_gets_real_rxnorm_id(self, athena_pipeline):
        normalized, _, _ = athena_pipeline
        metformin_rows = normalized[normalized["source_record_id"] == "A1"]
        assert metformin_rows.iloc[0]["ingredient_concept_id"] == 1503297

    def test_combo_drug_real_rxnorm_ids(self, athena_pipeline):
        normalized, _, _ = athena_pipeline
        rec = normalized[normalized["source_record_id"] == "A6"].iloc[0]
        assert rec["is_combo_drug"] == True  # noqa: E712 — pandas bool vs Python bool
        # Both metformin (1503297) and sitagliptin (1580747) should be in the string
        assert "1503297" in str(rec["ingredient_concept_id"])
        assert "1580747" in str(rec["ingredient_concept_id"])

    def test_er_formulation_detected(self, athena_pipeline):
        normalized, _, _ = athena_pipeline
        rec = normalized[normalized["source_record_id"] == "A3"].iloc[0]
        assert rec["formulation"] == "ER"

    def test_duplicate_pair_a1_b1(self, athena_pipeline):
        _, match_results, _ = athena_pipeline
        pair = match_results[(match_results["record_a"] == "A1") & (match_results["record_b"] == "B1")]
        assert pair.iloc[0]["match_status"] == "duplicate"

    def test_grams_vs_mg_duplicate(self, athena_pipeline):
        _, match_results, _ = athena_pipeline
        pair = match_results[(match_results["record_a"] == "A7") & (match_results["record_b"] == "B7")]
        assert pair.iloc[0]["match_status"] == "duplicate"


class TestDeduplication:
    def test_deduped_fewer_than_normalized(self, pipeline):
        normalized, _, deduped = pipeline
        assert len(deduped) < len(normalized)

    def test_deduped_has_source_record_ids_column(self, pipeline):
        _, _, deduped = pipeline
        assert "source_record_ids" in deduped.columns

    def test_canonical_is_ehr_record(self, pipeline):
        # EHR preferred — all merged rows should list EHR as source_system
        _, match_results, deduped = pipeline
        duplicate_ids = set()
        for _, row in match_results[match_results["match_status"] == "duplicate"].iterrows():
            duplicate_ids.add(row["record_a"])
            duplicate_ids.add(row["record_b"])

        merged = deduped[deduped["source_record_ids"].str.contains(",", na=False)]
        assert all(merged["source_system"] == "EHR")
