import os
import pytest
import pandas as pd

from normalize import (
    extract_strength_info,
    extract_frequency,
    extract_prn,
    normalize_route,
    extract_tablet_multiplier,
    extract_combo_strengths,
    map_drug_concept,
    normalize_medication_row,
)

# mapping_df fixture is provided by tests/conftest.py

VOCAB_CONCEPT_PATH = os.path.join(os.path.dirname(__file__), "..", "vocab", "CONCEPT.csv")
VOCAB_REL_PATH = os.path.join(os.path.dirname(__file__), "..", "vocab", "CONCEPT_RELATIONSHIP.csv")


# ---------------------------------------------------------------------------
# extract_strength_info
# ---------------------------------------------------------------------------

class TestExtractStrengthInfo:
    def test_mg_with_space(self):
        r = extract_strength_info("Metformin 500 mg BID")
        assert r["strength_mg"] == 500.0
        assert r["strength_unit"] == "mg"

    def test_mg_no_space(self):
        r = extract_strength_info("metformin 500mg twice daily")
        assert r["strength_mg"] == 500.0
        assert r["strength_unit"] == "mg"

    def test_grams_converted(self):
        r = extract_strength_info("Metformin 0.5 g BID")
        assert r["strength_mg"] == 500.0
        assert r["strength_unit"] == "g"

    def test_mcg_converted(self):
        r = extract_strength_info("Levothyroxine 100 mcg daily")
        assert r["strength_mg"] == pytest.approx(0.1)
        assert r["strength_unit"] == "mcg"

    def test_mcg_not_confused_with_mg(self):
        # "mcg" must not trigger the mg pattern
        r = extract_strength_info("Drug 50 mcg daily")
        assert r["strength_unit"] == "mcg"
        assert r["strength_mg"] == pytest.approx(0.05)

    def test_units_not_converted(self):
        r = extract_strength_info("Insulin 10 units subcutaneous")
        assert r["strength_mg"] is None
        assert r["strength_unit"] == "units"

    def test_meq_not_converted(self):
        r = extract_strength_info("Potassium chloride 20 mEq daily")
        assert r["strength_mg"] is None
        assert r["strength_unit"] == "mEq"

    def test_no_strength(self):
        r = extract_strength_info("Metformin daily")
        assert r["strength_mg"] is None
        assert r["strength_unit"] is None


# ---------------------------------------------------------------------------
# extract_frequency
# ---------------------------------------------------------------------------

class TestExtractPrn:
    @pytest.mark.parametrize("text,expected", [
        ("metformin 500 mg prn",          True),
        ("metformin 500 mg as needed",     True),
        ("metformin 500 mg when needed",   True),
        ("metformin 500 mg if needed",     True),
        ("metformin 500 mg p.r.n.",        True),
        ("metformin 500 mg as required",   True),
        ("metformin 500 mg BID",           False),
        ("metformin 500 mg once daily",    False),
        ("metformin 500 mg",               False),
    ])
    def test_prn(self, text, expected):
        assert extract_prn(text) is expected

    def test_prn_field_in_normalized_row(self, mapping_df):
        row = pd.Series({
            "source_record_id": "X1",
            "person_id": 101,
            "drug_source_value": "metformin 500 mg prn",
            "route_source_value": "oral",
            "drug_exposure_start_date": "2024-01-10",
            "source_system": "EHR",
        })
        result = normalize_medication_row(row, mapping_df)
        assert result["prn"] is True

    def test_scheduled_row_prn_false(self, mapping_df):
        row = pd.Series({
            "source_record_id": "X2",
            "person_id": 101,
            "drug_source_value": "metformin 500 mg BID",
            "route_source_value": "oral",
            "drug_exposure_start_date": "2024-01-10",
            "source_system": "EHR",
        })
        result = normalize_medication_row(row, mapping_df)
        assert result["prn"] is False


class TestExtractFrequency:
    @pytest.mark.parametrize("text,expected", [
        ("Metformin 500 mg BID", 2),
        ("metformin 500mg twice daily", 2),
        ("Metformin 500 mg once daily", 1),
        ("Metformin 500 mg TID", 3),
        ("Metformin 500 mg QID", 4),
        ("metformin 500 mg daily", 1),
        ("metformin 500 mg q12h", 2),
        ("metformin 500 mg q8h", 3),
        ("metformin 500 mg q6h", 4),
        ("metformin 500 mg q4h", 6),
        ("metformin 500 mg every 12 hours", 2),
        ("metformin 500 mg every 8 hours", 3),
        ("metformin 500 mg every other day", 0.5),
        ("metformin 500 mg qhs", 1),
        ("metformin 500 mg qam", 1),
        ("metformin 500 mg", None),
    ])
    def test_frequency(self, text, expected):
        assert extract_frequency(text) == expected

    def test_longer_phrase_wins_over_shorter(self):
        # "twice daily" must not resolve to "daily" (1) — must be 2
        assert extract_frequency("metformin 500 mg twice daily") == 2

    def test_once_daily_not_just_daily(self):
        # "once daily" has the same value as "daily" (1), but must not crash
        assert extract_frequency("metformin 500 mg once daily") == 1


# ---------------------------------------------------------------------------
# normalize_route
# ---------------------------------------------------------------------------

class TestNormalizeRoute:
    @pytest.mark.parametrize("route,expected", [
        ("oral", 4132161),
        ("PO", 4132161),
        ("po", 4132161),
        ("by mouth", 4132161),
        ("IV", 4171047),
        ("intravenous", 4171047),
        ("topical", 4263689),
        ("subcutaneous", 4142048),
        ("SQ", 4142048),
        ("sublingual", 4292110),
        ("inhaled", 4186834),
        ("inhalation", 4186834),
        ("transdermal", 4262099),
        ("intramuscular", 4302612),
        ("nasal", 4262914),
        ("ophthalmic", 4157760),
        ("otic", 4023156),
        ("unknown_route", None),
        (None, None),
    ])
    def test_route(self, route, expected):
        assert normalize_route(route) == expected


# ---------------------------------------------------------------------------
# extract_tablet_multiplier
# ---------------------------------------------------------------------------

class TestExtractTabletMultiplier:
    @pytest.mark.parametrize("text,expected", [
        ("take 2 tablets daily", 2.0),
        ("take 2 tabs bid", 2.0),
        ("take 2 capsules daily", 2.0),
        ("take two tablets daily", 2.0),
        ("2 tablets daily", 2.0),
        ("take 1 tablet daily", 1.0),
        ("metformin 500 mg daily", 1.0),
        ("take ½ tablet daily", 0.5),
        ("take 1/2 tablet daily", 0.5),
    ])
    def test_multiplier(self, text, expected):
        assert extract_tablet_multiplier(text) == expected


# ---------------------------------------------------------------------------
# extract_combo_strengths
# ---------------------------------------------------------------------------

class TestExtractComboStrengths:
    def test_combo_extracted_and_sorted(self):
        result = extract_combo_strengths("Metformin/Sitagliptin 500/50 mg BID", is_combo=True)
        assert result == "50.0|500.0"

    def test_non_combo_returns_none(self):
        result = extract_combo_strengths("Metformin 500 mg BID", is_combo=False)
        assert result is None

    def test_no_slash_strength_returns_none(self):
        result = extract_combo_strengths("Metformin/Sitagliptin 500 mg BID", is_combo=True)
        assert result is None


# ---------------------------------------------------------------------------
# map_drug_concept
# ---------------------------------------------------------------------------

class TestMapDrugConcept:
    def test_metformin_ir(self, mapping_df):
        r = map_drug_concept("Metformin 500 mg BID", mapping_df)
        assert r["drug_concept_id"] == 1503297
        assert r["formulation"] == "IR"
        assert r["is_combo_drug"] is False

    def test_metformin_er_wins_over_metformin(self, mapping_df):
        r = map_drug_concept("Metformin ER 500 mg once daily", mapping_df)
        assert r["drug_concept_id"] == 19019073
        assert r["formulation"] == "ER"

    def test_combo_drug(self, mapping_df):
        r = map_drug_concept("Metformin/Sitagliptin 500/50 mg BID", mapping_df)
        assert r["drug_concept_id"] == 40241331
        assert r["is_combo_drug"] is True

    def test_unknown_drug(self, mapping_df):
        r = map_drug_concept("Aspirin 81 mg daily", mapping_df)
        assert r["drug_concept_id"] == 0
        assert r["standard_drug_name"] is None


# ---------------------------------------------------------------------------
# normalize_medication_row
# ---------------------------------------------------------------------------

class TestNormalizeMedicationRow:
    def _make_row(self, drug_text, route="oral", record_id="A1", person_id=101):
        return pd.Series({
            "source_record_id": record_id,
            "person_id": person_id,
            "drug_exposure_start_date": "2024-01-10",
            "drug_source_value": drug_text,
            "route_source_value": route,
            "source_system": "EHR",
        })

    def test_standard_row(self, mapping_df):
        row = self._make_row("Metformin 500 mg BID")
        r = normalize_medication_row(row, mapping_df)
        assert r["strength_mg"] == 500.0
        assert r["strength_unit"] == "mg"
        assert r["frequency_per_day"] == 2
        assert r["total_daily_dose_mg"] == 1000.0
        assert r["route_concept_id"] == 4132161

    def test_grams_normalized(self, mapping_df):
        row = self._make_row("Metformin 0.5 g BID")
        r = normalize_medication_row(row, mapping_df)
        assert r["strength_mg"] == 500.0
        assert r["strength_unit"] == "g"
        assert r["total_daily_dose_mg"] == 1000.0

    def test_tablet_multiplier_applied(self, mapping_df):
        row = self._make_row("Metformin 500 mg tablet take 2 tablets daily")
        r = normalize_medication_row(row, mapping_df)
        assert r["tablet_multiplier"] == 2.0
        assert r["total_daily_dose_mg"] == 1000.0

    def test_combo_drug_has_no_strength_mg(self, mapping_df):
        row = self._make_row("Metformin/Sitagliptin 500/50 mg BID")
        r = normalize_medication_row(row, mapping_df)
        assert r["strength_mg"] is None
        assert r["combo_strengths"] == "50.0|500.0"

    def test_error_handling_returns_fallback(self, mapping_df):
        # Row missing drug_source_value should not crash
        row = pd.Series({"source_record_id": "X1"})
        r = normalize_medication_row(row, mapping_df)
        assert r["drug_concept_id"] == 0
        assert r["strength_mg"] is None


# ---------------------------------------------------------------------------
# AthenaVocab matching stages
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def athena_vocab():
    pytest.importorskip("vocab")
    if not os.path.exists(VOCAB_CONCEPT_PATH):
        pytest.skip("vocab/CONCEPT.csv not present")
    from vocab import AthenaVocab
    rel_path = VOCAB_REL_PATH if os.path.exists(VOCAB_REL_PATH) else None
    return AthenaVocab(VOCAB_CONCEPT_PATH, rel_path)


class TestAthenaVocabExact:
    def test_exact_ingredient_match(self, athena_vocab):
        result = athena_vocab.lookup("Metformin 500 mg BID")
        assert result["ingredient_concept_id"] == 1503297
        assert result["ingredient_name"] == "metformin"
        assert result["is_combo_drug"] is False

    def test_salt_stripped_match(self, athena_vocab):
        # "metformin hydrochloride" — salt suffix stripped before matching
        result = athena_vocab.lookup("metformin hydrochloride 500 mg daily")
        assert result["ingredient_concept_id"] == 1503297

    def test_er_formulation_detected(self, athena_vocab):
        result = athena_vocab.lookup("Metformin ER 500 mg once daily")
        assert result["formulation"] == "ER"
        assert result["ingredient_concept_id"] == 1503297

    def test_ir_formulation_default(self, athena_vocab):
        result = athena_vocab.lookup("Metformin 500 mg BID")
        assert result["formulation"] == "IR"

    def test_combo_drug_detected(self, athena_vocab):
        result = athena_vocab.lookup("Metformin/Sitagliptin 500/50 mg BID")
        assert result["is_combo_drug"] is True
        assert "1503297" in str(result["ingredient_concept_id"])
        assert "1580747" in str(result["ingredient_concept_id"])

    def test_unknown_drug_returns_zero(self, athena_vocab):
        result = athena_vocab.lookup("Zorgonite 50 mg daily")
        assert result["drug_concept_id"] == 0
        assert result["ingredient_concept_id"] is None


class TestAthenaVocabBrandName:
    def test_brand_name_maps_to_ingredient(self, athena_vocab):
        if not athena_vocab._brand_to_ingredient:
            pytest.skip("Brand name lookup not loaded (CONCEPT_RELATIONSHIP.csv absent)")
        # Glucophage is the brand name for metformin
        result = athena_vocab.lookup("Glucophage 500 mg BID")
        assert result["ingredient_concept_id"] == 1503297
        assert result["ingredient_name"] == "metformin"

    def test_lipitor_maps_to_atorvastatin(self, athena_vocab):
        if not athena_vocab._brand_to_ingredient:
            pytest.skip("Brand name lookup not loaded")
        result = athena_vocab.lookup("Lipitor 10 mg daily")
        assert result["ingredient_concept_id"] == 1545958
        assert result["ingredient_name"] == "atorvastatin"


class TestAthenaVocabFuzzy:
    def test_misspelled_drug_matches(self, athena_vocab):
        # "metfromin" is a common transposition misspelling
        result = athena_vocab.lookup("metfromin 500 mg bid")
        assert result["ingredient_concept_id"] == 1503297

    def test_low_similarity_returns_no_match(self, athena_vocab):
        # Completely unrelated string should not fuzzy-match anything meaningful
        result = athena_vocab.lookup("xyzqwerty 50 mg")
        assert result["drug_concept_id"] == 0
