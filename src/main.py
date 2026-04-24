from normalize import build_normalized_drug_exposure
from deduplicate import generate_match_results, build_deduped_drug_exposure


def main():
    normalized = build_normalized_drug_exposure(
        "data/source_a_medications.csv",
        "data/source_b_medications.csv",
        "data/mock_concept_mapping.csv",
    )

    match_results = generate_match_results(normalized)

    deduped = build_deduped_drug_exposure(normalized, match_results)

    normalized.to_csv("outputs/normalized_drug_exposure.csv", index=False)
    match_results.to_csv("outputs/match_results.csv", index=False)
    deduped.to_csv("outputs/deduped_drug_exposure.csv", index=False)

    print("Created outputs:")
    print("- outputs/normalized_drug_exposure.csv")
    print("- outputs/match_results.csv")
    print("- outputs/deduped_drug_exposure.csv")

    print("\nMatch results preview:")
    print(match_results[[
        "record_a",
        "record_b",
        "match_status",
        "confidence",
        "reason"
    ]])


if __name__ == "__main__":
    main()