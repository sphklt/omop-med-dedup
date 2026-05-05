import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from normalize import build_normalized_drug_exposure
from deduplicate import generate_match_results, build_deduped_drug_exposure

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser(
        description="OMOP-style medication deduplication pipeline"
    )
    p.add_argument(
        "--source-a", default="data/source_a_medications.csv", metavar="PATH",
        help="Path to source A CSV (default: data/source_a_medications.csv)",
    )
    p.add_argument(
        "--source-b", default="data/source_b_medications.csv", metavar="PATH",
        help="Path to source B CSV (default: data/source_b_medications.csv)",
    )
    p.add_argument(
        "--vocab", default=None, metavar="PATH",
        help=(
            "Path to Athena CONCEPT.csv for real RxNorm concept IDs. "
            "Auto-detected at vocab/CONCEPT.csv if present. "
            "Falls back to --mapping when not provided."
        ),
    )
    p.add_argument(
        "--mapping", default="data/mock_concept_mapping.csv", metavar="PATH",
        help="Path to mock concept mapping CSV, used when --vocab is not set "
             "(default: data/mock_concept_mapping.csv)",
    )
    p.add_argument(
        "--output-dir", default="outputs", metavar="DIR",
        help="Directory to write output CSVs (default: outputs)",
    )
    p.add_argument(
        "--date-window", type=int, default=7, metavar="DAYS",
        help="Max days between start dates to be considered duplicate (default: 7)",
    )
    p.add_argument(
        "--dose-tolerance", type=float, default=0.01, metavar="FRAC",
        help="Relative tolerance for dose comparisons, e.g. 0.01 = 1%% (default: 0.01)",
    )
    p.add_argument(
        "--canonical-preference", default="EHR,Pharmacy", metavar="SYS1,SYS2,...",
        help="Comma-separated source system preference for canonical record (default: EHR,Pharmacy)",
    )
    return p.parse_args()


def _resolve_vocab_paths(args) -> tuple[str | None, str | None]:
    """
    Return (concept_path, relationship_path) for Athena vocab, or (None, None)
    to fall back to the mock mapping CSV.
    """
    vocab_dir = os.path.join(os.path.dirname(__file__), "..", "vocab")

    concept_path = args.vocab or os.path.join(vocab_dir, "CONCEPT.csv")
    if not os.path.exists(concept_path):
        return None, None

    logger.info("Auto-detected Athena vocabulary at %s", os.path.normpath(concept_path))
    concept_path = os.path.normpath(concept_path)

    rel_path = os.path.join(vocab_dir, "CONCEPT_RELATIONSHIP.csv")
    if os.path.exists(rel_path):
        logger.info("Brand name lookup enabled via %s", os.path.normpath(rel_path))
        return concept_path, os.path.normpath(rel_path)

    return concept_path, None


def main():
    args = parse_args()
    canonical_preference = [s.strip() for s in args.canonical_preference.split(",")]

    os.makedirs(args.output_dir, exist_ok=True)

    logger.info("Starting OMOP medication deduplication pipeline")

    vocab_path, rel_path = _resolve_vocab_paths(args)
    mapping_path = None if vocab_path else args.mapping

    normalized = build_normalized_drug_exposure(
        args.source_a, args.source_b,
        mapping_path=mapping_path,
        vocab_concept_path=vocab_path,
        vocab_relationship_path=rel_path,
    )
    logger.info("Normalized %d records", len(normalized))

    match_results = generate_match_results(
        normalized,
        date_window_days=args.date_window,
        dose_tolerance=args.dose_tolerance,
    )
    logger.info("Generated %d match pairs", len(match_results))

    deduped = build_deduped_drug_exposure(
        normalized,
        match_results,
        canonical_preference=canonical_preference,
    )
    logger.info("Deduplicated to %d canonical records", len(deduped))

    out_normalized = os.path.join(args.output_dir, "normalized_drug_exposure.csv")
    out_matches    = os.path.join(args.output_dir, "match_results.csv")
    out_deduped    = os.path.join(args.output_dir, "deduped_drug_exposure.csv")

    normalized.to_csv(out_normalized, index=False)
    match_results.to_csv(out_matches, index=False)
    deduped.to_csv(out_deduped, index=False)

    print("Created outputs:")
    print(f"- {out_normalized}")
    print(f"- {out_matches}")
    print(f"- {out_deduped}")

    print("\nMatch results preview:")
    print(match_results[["record_a", "record_b", "match_status", "confidence", "reason"]])


if __name__ == "__main__":
    main()
