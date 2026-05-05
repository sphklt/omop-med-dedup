import pandas as pd

from deduplicate import (
    doses_equal,
    classify_pair,
    generate_match_results,
    build_deduped_drug_exposure,
)


# ---------------------------------------------------------------------------
# doses_equal
# ---------------------------------------------------------------------------

class TestDosesEqual:
    def test_both_nan(self):
        assert doses_equal(float("nan"), float("nan")) is True

    def test_one_nan(self):
        assert doses_equal(500.0, float("nan")) is False
        assert doses_equal(float("nan"), 500.0) is False

    def test_exact_equal(self):
        assert doses_equal(500.0, 500.0) is True

    def test_within_tolerance(self):
        # 500 vs 504.9 ≈ 0.98% difference — within 1%
        assert doses_equal(500.0, 504.9) is True

    def test_outside_tolerance(self):
        # 500 vs 510 = 2% difference — outside 1%
        assert doses_equal(500.0, 510.0) is False

    def test_both_zero(self):
        assert doses_equal(0.0, 0.0) is True

    def test_one_zero(self):
        assert doses_equal(0.0, 500.0) is False

    def test_custom_tolerance(self):
        assert doses_equal(500.0, 510.0, tolerance=0.05) is True
        assert doses_equal(500.0, 560.0, tolerance=0.05) is False


# ---------------------------------------------------------------------------
# classify_pair
# ---------------------------------------------------------------------------

class TestClassifyPair:
    def _rec(self, **kwargs):
        defaults = {
            "person_id": 101,
            "drug_exposure_start_date": "2024-01-10",
            "ingredient_concept_id": 1503297,
            "is_combo_drug": False,
            "route_concept_id": 4132161,
            "formulation": "IR",
            "strength_mg": 500.0,
            "strength_unit": "mg",
            "combo_strengths": None,
            "frequency_per_day": 2.0,
            "total_daily_dose_mg": 1000.0,
            "prn": False,
        }
        defaults.update(kwargs)
        return pd.Series(defaults)

    def test_duplicate(self):
        status, conf, _ = classify_pair(self._rec(), self._rec())
        assert status == "duplicate"
        assert conf == 1.0

    def test_different_person(self):
        status, conf, _ = classify_pair(self._rec(person_id=101), self._rec(person_id=102))
        assert status == "not_duplicate"
        assert conf == 0.0

    def test_outside_date_window(self):
        a = self._rec(drug_exposure_start_date="2024-01-01")
        b = self._rec(drug_exposure_start_date="2024-02-01")
        status, _, _ = classify_pair(a, b, date_window_days=7)
        assert status == "not_duplicate"

    def test_within_date_window(self):
        a = self._rec(drug_exposure_start_date="2024-01-01")
        b = self._rec(drug_exposure_start_date="2024-01-05")
        status, _, _ = classify_pair(a, b, date_window_days=7)
        assert status == "duplicate"

    def test_different_ingredient(self):
        status, _, _ = classify_pair(
            self._rec(ingredient_concept_id=1503297),
            self._rec(ingredient_concept_id=9999999),
        )
        assert status == "not_duplicate"

    def test_combo_vs_single(self):
        status, _, _ = classify_pair(
            self._rec(is_combo_drug=True),
            self._rec(is_combo_drug=False),
        )
        assert status == "not_duplicate"

    def test_route_mismatch(self):
        status, conf, _ = classify_pair(
            self._rec(route_concept_id=4132161),
            self._rec(route_concept_id=4171047),
        )
        assert status == "possible_duplicate"
        assert conf == 0.5

    def test_formulation_mismatch(self):
        status, conf, _ = classify_pair(
            self._rec(formulation="IR"),
            self._rec(formulation="ER"),
        )
        assert status == "possible_duplicate"
        assert conf == 0.65

    def test_prn_vs_scheduled_not_duplicate(self):
        # One record is PRN, the other is scheduled — fundamentally different regimens
        status, conf, reason = classify_pair(
            self._rec(prn=True),
            self._rec(prn=False),
        )
        assert status == "not_duplicate"
        assert conf == 0.0
        assert "PRN" in reason

    def test_both_prn_same_dose_duplicate(self):
        # Both PRN, identical dose — still a duplicate
        status, conf, _ = classify_pair(
            self._rec(prn=True),
            self._rec(prn=True),
        )
        assert status == "duplicate"

    def test_strength_unit_mismatch_incompatible(self):
        # mg vs units — fundamentally incompatible, cannot compare numerically
        status, conf, _ = classify_pair(
            self._rec(strength_unit="mg"),
            self._rec(strength_unit="units"),
        )
        assert status == "possible_duplicate"
        assert conf == 0.55

    def test_strength_unit_g_vs_mg_comparable(self):
        # g and mg are both normalized to mg — should proceed to numerical comparison
        a = self._rec(strength_mg=500.0, strength_unit="g", total_daily_dose_mg=1000.0)
        b = self._rec(strength_mg=500.0, strength_unit="mg", total_daily_dose_mg=1000.0)
        status, conf, _ = classify_pair(a, b)
        assert status == "duplicate"
        assert conf == 1.0

    def test_same_daily_dose_different_regimen(self):
        # 500 mg BID vs 1000 mg QD — same total daily dose
        a = self._rec(strength_mg=500.0, frequency_per_day=2.0, total_daily_dose_mg=1000.0)
        b = self._rec(strength_mg=1000.0, frequency_per_day=1.0, total_daily_dose_mg=1000.0)
        status, conf, _ = classify_pair(a, b)
        assert status == "possible_duplicate"
        assert conf == 0.75

    def test_missing_frequency(self):
        a = self._rec(frequency_per_day=float("nan"), total_daily_dose_mg=float("nan"))
        status, conf, _ = classify_pair(a, self._rec())
        assert status == "possible_duplicate"
        assert conf == 0.6

    def test_dose_within_tolerance_is_duplicate(self):
        # 500 vs 504.9 mg — within 1% tolerance
        a = self._rec(strength_mg=500.0, total_daily_dose_mg=1000.0)
        b = self._rec(strength_mg=504.9, total_daily_dose_mg=1009.8)
        status, _, _ = classify_pair(a, b, dose_tolerance=0.01)
        assert status == "duplicate"

    def test_dose_outside_tolerance_not_duplicate(self):
        a = self._rec(strength_mg=500.0, total_daily_dose_mg=1000.0)
        b = self._rec(strength_mg=600.0, total_daily_dose_mg=1200.0)
        status, _, _ = classify_pair(a, b, dose_tolerance=0.01)
        assert status == "not_duplicate"

    def test_combo_different_strengths(self):
        a = self._rec(is_combo_drug=True, combo_strengths="50.0|500.0", strength_mg=None)
        b = self._rec(is_combo_drug=True, combo_strengths="50.0|250.0", strength_mg=None)
        status, _, _ = classify_pair(a, b)
        assert status == "not_duplicate"


# ---------------------------------------------------------------------------
# generate_match_results
# ---------------------------------------------------------------------------

class TestGenerateMatchResults:
    def _base_record(self, record_id, source_system, person_id=101):
        return {
            "source_record_id": record_id,
            "person_id": person_id,
            "source_system": source_system,
            "drug_source_value": "Metformin 500 mg BID",
            "drug_exposure_start_date": pd.Timestamp("2024-01-10"),
            "ingredient_concept_id": 1503297,
            "is_combo_drug": False,
            "route_concept_id": 4132161,
            "formulation": "IR",
            "strength_mg": 500.0,
            "strength_unit": "mg",
            "combo_strengths": None,
            "frequency_per_day": 2.0,
            "total_daily_dose_mg": 1000.0,
        }

    def test_two_systems_finds_duplicate(self):
        df = pd.DataFrame([
            self._base_record("A1", "EHR"),
            self._base_record("B1", "Pharmacy"),
        ])
        results = generate_match_results(df)
        assert len(results) == 1
        assert results.iloc[0]["match_status"] == "duplicate"

    def test_different_person_no_comparison(self):
        df = pd.DataFrame([
            self._base_record("A1", "EHR", person_id=101),
            self._base_record("B1", "Pharmacy", person_id=102),
        ])
        results = generate_match_results(df)
        assert len(results) == 0

    def test_three_source_systems_generates_three_pairs(self):
        df = pd.DataFrame([
            self._base_record("A1", "EHR"),
            self._base_record("B1", "Pharmacy"),
            self._base_record("C1", "Claims"),
        ])
        results = generate_match_results(df)
        # EHR-Pharmacy, EHR-Claims, Pharmacy-Claims
        assert len(results) == 3
        assert all(r == "duplicate" for r in results["match_status"])

    def test_empty_result_has_correct_columns(self):
        df = pd.DataFrame([self._base_record("A1", "EHR")])
        results = generate_match_results(df)
        assert "match_status" in results.columns
        assert len(results) == 0

    def test_different_ingredient_not_compared(self):
        # Records for the same patient but different ingredients should not be paired
        rec_a = self._base_record("A1", "EHR")
        rec_a["ingredient_concept_id"] = 1503297  # metformin
        rec_b = self._base_record("B1", "Pharmacy")
        rec_b["ingredient_concept_id"] = 1308216  # lisinopril — different drug
        df = pd.DataFrame([rec_a, rec_b])
        results = generate_match_results(df)
        assert len(results) == 0  # blocking prevents cross-ingredient comparison

    def test_within_source_duplicate_detected(self):
        # Same drug entered twice in the same system for the same patient on the same day
        rec = self._base_record
        df = pd.DataFrame([
            rec("A1", "EHR"),
            rec("A2", "EHR"),  # same system, same patient, same drug
        ])
        results = generate_match_results(df)
        assert len(results) == 1
        assert results.iloc[0]["match_status"] == "duplicate"
        assert set([results.iloc[0]["record_a"], results.iloc[0]["record_b"]]) == {"A1", "A2"}

    def test_within_source_no_self_comparison(self):
        # A single record should never be compared with itself
        df = pd.DataFrame([self._base_record("A1", "EHR")])
        results = generate_match_results(df)
        assert len(results) == 0

    def test_within_and_cross_source_combined(self):
        # 2 EHR records + 1 Pharmacy record → 1 within-EHR pair + 2 cross-source pairs
        rec = self._base_record
        df = pd.DataFrame([
            rec("A1", "EHR"),
            rec("A2", "EHR"),
            rec("B1", "Pharmacy"),
        ])
        results = generate_match_results(df)
        assert len(results) == 3  # A1-A2 (within), A1-B1 (cross), A2-B1 (cross)

    def test_unmapped_records_excluded_from_blocking(self):
        # Records with None ingredient_concept_id (unmapped) should not be compared
        rec_a = self._base_record("A1", "EHR")
        rec_a["ingredient_concept_id"] = None
        rec_b = self._base_record("B1", "Pharmacy")
        rec_b["ingredient_concept_id"] = None
        df = pd.DataFrame([rec_a, rec_b])
        results = generate_match_results(df)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# build_deduped_drug_exposure
# ---------------------------------------------------------------------------

class TestBuildDedupedDrugExposure:
    def _normalized(self):
        return pd.DataFrame([
            {
                "source_record_id": "A1", "person_id": 101, "source_system": "EHR",
                "drug_exposure_start_date": pd.Timestamp("2024-01-10"),
                "drug_source_value": "Metformin 500 mg BID",
            },
            {
                "source_record_id": "B1", "person_id": 101, "source_system": "Pharmacy",
                "drug_exposure_start_date": pd.Timestamp("2024-01-10"),
                "drug_source_value": "metformin 500mg twice daily",
            },
        ])

    def _matches(self, status="duplicate"):
        return pd.DataFrame([{
            "record_a": "A1", "record_b": "B1", "person_id": 101, "match_status": status,
        }])

    def test_duplicates_merged_to_one_row(self):
        deduped = build_deduped_drug_exposure(self._normalized(), self._matches())
        assert len(deduped) == 1

    def test_merged_row_contains_both_source_ids(self):
        deduped = build_deduped_drug_exposure(self._normalized(), self._matches())
        ids = deduped.iloc[0]["source_record_ids"]
        assert "A1" in ids and "B1" in ids

    def test_canonical_preference_ehr_first(self):
        deduped = build_deduped_drug_exposure(
            self._normalized(), self._matches(), canonical_preference=["EHR", "Pharmacy"]
        )
        assert deduped.iloc[0]["source_system"] == "EHR"

    def test_canonical_preference_pharmacy_first(self):
        deduped = build_deduped_drug_exposure(
            self._normalized(), self._matches(), canonical_preference=["Pharmacy", "EHR"]
        )
        assert deduped.iloc[0]["source_system"] == "Pharmacy"

    def test_possible_duplicate_keeps_both_rows(self):
        deduped = build_deduped_drug_exposure(
            self._normalized(), self._matches(status="possible_duplicate")
        )
        assert len(deduped) == 2

    def test_no_matches_keeps_all_rows(self):
        empty_matches = pd.DataFrame(
            columns=["record_a", "record_b", "person_id", "match_status"]
        )
        deduped = build_deduped_drug_exposure(self._normalized(), empty_matches)
        assert len(deduped) == 2
