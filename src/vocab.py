"""
Athena-backed RxNorm ingredient concept lookup.

Matching is attempted in three stages, in order:
  1. Exact ingredient name match (word-boundary checked, longest wins).
  2. Brand name → ingredient lookup via Athena CONCEPT_RELATIONSHIP.
  3. Fuzzy ingredient name match via rapidfuzz (≥ FUZZY_THRESHOLD similarity).

Salt/form suffixes (hydrochloride, sodium, phosphate, …) are stripped from
the drug text before each stage so "metformin hydrochloride" matches the
"metformin" ingredient concept.
"""
import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_FORMULATION_RE = re.compile(
    r"\b(?:extended[-\s]?release|er\b|xr\b|sr\b|xl\b)", re.IGNORECASE
)

# Salt and form qualifiers that should be stripped before matching.
# Ordered longest-first so "hydrochloride" is removed before "chloride".
_SALT_SUFFIXES = [
    "hydrochloride", "monohydrate", "hemihydrate", "trihydrate",
    "sesquihydrate", "anhydrous", "dihydrate", "monosodium",
    "dipotassium", "disodium", "trisodium", "monopotassium",
    "potassium", "sodium", "calcium", "magnesium", "aluminum",
    "zinc", "iron", "phosphate", "sulfate", "sulphate",
    "succinate", "fumarate", "maleate", "tartrate", "acetate",
    "citrate", "gluconate", "lactate", "bromide", "chloride",
    "mesylate", "tosylate", "besylate", "valerate", "propionate",
    "butyrate", "decanoate", "enanthate", "hcl",
]
_SALT_RE = re.compile(
    r"\b(?:" + "|".join(_SALT_SUFFIXES) + r")\b", re.IGNORECASE
)

FUZZY_THRESHOLD = 88  # minimum similarity score (0–100) for a fuzzy match


def _detect_formulation(text: str) -> str:
    return "ER" if _FORMULATION_RE.search(text) else "IR"


def _strip_salts(text: str) -> str:
    """Remove salt/form qualifiers and collapse extra whitespace."""
    return re.sub(r"\s{2,}", " ", _SALT_RE.sub(" ", text)).strip()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class AthenaVocab:
    """
    Ingredient-level RxNorm concept lookup backed by Athena vocabulary files.

    Parameters
    ----------
    concept_path : str
        Path to Athena CONCEPT.csv (tab-separated).
    concept_relationship_path : str, optional
        Path to Athena CONCEPT_RELATIONSHIP.csv.  Required for brand name
        lookup; if omitted that stage is skipped.

    Matching stages (in order)
    --------------------------
    1. Exact match against ingredient names (salt-stripped, word-boundary).
    2. Brand name alias lookup via CONCEPT_RELATIONSHIP "Brand name of".
    3. Fuzzy match against ingredient names using rapidfuzz.
    """

    def __init__(
        self,
        concept_path: str,
        concept_relationship_path: str | None = None,
    ):
        raw = pd.read_csv(
            concept_path,
            sep="\t",
            dtype=str,
            low_memory=False,
            usecols=[
                "concept_id", "concept_name", "vocabulary_id",
                "concept_class_id", "standard_concept", "invalid_reason",
            ],
        )

        valid_rxnorm = raw[
            (raw["vocabulary_id"] == "RxNorm") & (raw["invalid_reason"].isna())
        ]

        # ── Ingredient records (exact + fuzzy matching) ───────────────────
        ingredients = valid_rxnorm[
            (valid_rxnorm["concept_class_id"] == "Ingredient")
            & (valid_rxnorm["standard_concept"] == "S")
        ].copy()
        ingredients["name_lower"] = ingredients["concept_name"].str.lower().str.strip()

        # Pre-sort longest-first so the longest match wins
        self._records: list[dict] = (
            ingredients
            .sort_values("name_lower", key=lambda s: s.str.len(), ascending=False)
            [["concept_id", "concept_name", "name_lower"]]
            .to_dict("records")
        )

        # Index for fuzzy matching: list of (name_lower, concept_id, concept_name)
        self._fuzzy_names = [r["name_lower"] for r in self._records]

        logger.info("Loaded %d RxNorm ingredient concepts", len(self._records))

        # ── Brand name → ingredient map ────────────────────────────────────
        self._brand_to_ingredient: dict[str, dict] = {}

        if concept_relationship_path:
            brand_concepts = valid_rxnorm[
                valid_rxnorm["concept_class_id"] == "Brand Name"
            ].set_index("concept_id")

            ingredient_index = (
                ingredients
                .set_index("concept_id")
                [["concept_name", "name_lower"]]
            )

            rel = pd.read_csv(
                concept_relationship_path,
                sep="\t",
                dtype=str,
                usecols=["concept_id_1", "concept_id_2", "relationship_id", "invalid_reason"],
            )
            # Direct "Brand name of" links from Brand Name concepts to Ingredients
            brand_to_ing = rel[
                (rel["relationship_id"] == "Brand name of")
                & (rel["invalid_reason"].isna())
                & (rel["concept_id_1"].isin(brand_concepts.index))
                & (rel["concept_id_2"].isin(ingredient_index.index))
            ]

            for _, row in brand_to_ing.iterrows():
                brand_name = brand_concepts.loc[row["concept_id_1"], "concept_name"].lower().strip()
                ing_row = ingredient_index.loc[row["concept_id_2"]]
                self._brand_to_ingredient[brand_name] = {
                    "concept_id": row["concept_id_2"],
                    "concept_name": ing_row["concept_name"],
                    "name_lower": ing_row["name_lower"],
                }

            logger.info(
                "Loaded %d brand name → ingredient mappings", len(self._brand_to_ingredient)
            )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def lookup(self, text: str) -> dict:
        """
        Map raw drug text to OMOP-style concept fields.

        Returns a dict with keys: drug_concept_id, standard_drug_name,
        ingredient_concept_id, ingredient_name, formulation, is_combo_drug.
        """
        text_lower = str(text).lower().strip()
        formulation = _detect_formulation(text_lower)

        # Combo detection: "metformin/sitagliptin 500/50 mg"
        slash_idx = text_lower.find("/")
        if slash_idx != -1:
            pre = re.sub(r"\s*\d.*$", "", text_lower[:slash_idx]).strip()
            post = re.sub(r"\s*\d.*$", "", text_lower[slash_idx + 1:]).strip()
            if pre and post:
                ing_a = self._resolve(pre)
                ing_b = self._resolve(post)
                if ing_a and ing_b:
                    return {
                        "drug_concept_id": int(ing_a["concept_id"]),
                        "standard_drug_name": f"{ing_a['concept_name']} / {ing_b['concept_name']}",
                        "ingredient_concept_id": f"{ing_a['concept_id']}|{ing_b['concept_id']}",
                        "ingredient_name": f"{ing_a['concept_name']}|{ing_b['concept_name']}",
                        "formulation": formulation,
                        "is_combo_drug": True,
                    }

        ing = self._resolve(text_lower)
        if ing:
            return {
                "drug_concept_id": int(ing["concept_id"]),
                "standard_drug_name": ing["concept_name"],
                "ingredient_concept_id": int(ing["concept_id"]),
                "ingredient_name": ing["concept_name"],
                "formulation": formulation,
                "is_combo_drug": False,
            }

        return {
            "drug_concept_id": 0,
            "standard_drug_name": None,
            "ingredient_concept_id": None,
            "ingredient_name": None,
            "formulation": None,
            "is_combo_drug": None,
        }

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _resolve(self, text: str) -> dict | None:
        """
        Try all three matching stages in order; return first hit or None.
        """
        # Stage 1: exact ingredient match (with and without salt stripping)
        hit = self._find_ingredient(text)
        if hit:
            return hit
        stripped = _strip_salts(text)
        if stripped != text:
            hit = self._find_ingredient(stripped)
            if hit:
                return hit

        # Stage 2: brand name lookup
        hit = self._find_brand(text)
        if hit:
            return hit

        # Stage 3: fuzzy match (salt-stripped text for better signal)
        return self._fuzzy_match(stripped or text)

    def _find_ingredient(self, text: str) -> dict | None:
        """Exact word-boundary substring match, longest name wins."""
        for row in self._records:
            name = row["name_lower"]
            idx = text.find(name)
            if idx == -1:
                continue
            before_ok = idx == 0 or not text[idx - 1].isalnum()
            after_ok = (
                idx + len(name) == len(text) or not text[idx + len(name)].isalnum()
            )
            if before_ok and after_ok:
                return row
        return None

    def _find_brand(self, text: str) -> dict | None:
        """Check if any known brand name appears as a whole word in the text."""
        for brand, ing in self._brand_to_ingredient.items():
            idx = text.find(brand)
            if idx == -1:
                continue
            before_ok = idx == 0 or not text[idx - 1].isalnum()
            after_ok = (
                idx + len(brand) == len(text) or not text[idx + len(brand)].isalnum()
            )
            if before_ok and after_ok:
                return ing
        return None

    def _fuzzy_match(self, text: str) -> dict | None:
        """
        Find the ingredient whose name is most similar to text, using
        RapidFuzz token-sort ratio.  Returns None if best score is below
        FUZZY_THRESHOLD.

        Token-sort ratio normalises word order so "hydrochloride metformin"
        still matches "metformin".
        """
        try:
            from rapidfuzz import process, fuzz
        except ImportError:
            return None

        # Only match against the first whitespace-delimited token in text
        # (avoids matching "metformin 500 mg bid" fuzzily against "500")
        token = text.split()[0] if text.split() else text

        result = process.extractOne(
            token,
            self._fuzzy_names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=FUZZY_THRESHOLD,
        )
        if result is None:
            return None

        best_name, score, idx = result
        logger.debug("Fuzzy match %r → %r (score %d)", token, best_name, score)
        return self._records[idx]
