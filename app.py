import os
import streamlit as st
import pandas as pd

st.set_page_config(page_title="OMOP Medication Dedup Demo", layout="wide")

st.title("OMOP-Style Medication Deduplication Demo")

st.markdown("""
Two raw medication datasets are normalized into an OMOP-style `drug_exposure` table,
then classified as **duplicate**, **possible duplicate**, or **not duplicate**.
""")

_HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILES = {
    "normalized": os.path.join(_HERE, "outputs", "normalized_drug_exposure.csv"),
    "matches":    os.path.join(_HERE, "outputs", "match_results.csv"),
    "deduped":    os.path.join(_HERE, "outputs", "deduped_drug_exposure.csv"),
}

missing = [path for path in OUTPUT_FILES.values() if not os.path.exists(path)]
if missing:
    st.error(
        "Pipeline outputs not found. Run the pipeline first:\n\n"
        "```\npython src/main.py\n```"
    )
    st.stop()

normalized = pd.read_csv(OUTPUT_FILES["normalized"])
matches    = pd.read_csv(OUTPUT_FILES["matches"])
deduped    = pd.read_csv(OUTPUT_FILES["deduped"])

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")

    status_options = ["duplicate", "possible_duplicate", "not_duplicate"]
    selected_statuses = st.multiselect(
        "Match Status",
        options=status_options,
        default=status_options,
    )

    all_persons = sorted(matches["person_id"].unique().tolist())
    selected_persons = st.multiselect(
        "Person ID  (empty = all)",
        options=all_persons,
        default=[],
    )

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------
n_dup      = int((matches["match_status"] == "duplicate").sum())
n_possible = int((matches["match_status"] == "possible_duplicate").sum())
n_not      = int((matches["match_status"] == "not_duplicate").sum())
dedup_rate = round((1 - len(deduped) / len(normalized)) * 100, 1) if len(normalized) else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Source Records",     len(normalized))
c2.metric("Duplicate Pairs",    n_dup)
c3.metric("Possible Duplicates", n_possible)
c4.metric("Not Duplicates",     n_not)
c5.metric("Dedup Rate",         f"{dedup_rate}%")

st.divider()

# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------
filtered_matches = matches.copy()
if selected_statuses:
    filtered_matches = filtered_matches[
        filtered_matches["match_status"].isin(selected_statuses)
    ]
if selected_persons:
    filtered_matches = filtered_matches[
        filtered_matches["person_id"].isin(selected_persons)
    ]

filtered_normalized = (
    normalized[normalized["person_id"].isin(selected_persons)]
    if selected_persons else normalized
)
filtered_deduped = (
    deduped[deduped["person_id"].isin(selected_persons)]
    if selected_persons else deduped
)

# ---------------------------------------------------------------------------
# Color coding for match_status column
# ---------------------------------------------------------------------------
_STATUS_COLORS = {
    "duplicate":          "background-color: #d4edda; color: #155724",
    "possible_duplicate": "background-color: #fff3cd; color: #856404",
    "not_duplicate":      "background-color: #f8d7da; color: #721c24",
}

def _color_status(val):
    return _STATUS_COLORS.get(val, "")

# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
st.header("1. Normalized OMOP-style Drug Exposure")
st.caption(f"{len(filtered_normalized)} records")
st.dataframe(filtered_normalized, use_container_width=True)

st.header("2. Match Results")
st.caption(f"Showing {len(filtered_matches)} of {len(matches)} pairs")
st.dataframe(
    filtered_matches.style.map(_color_status, subset=["match_status"]),
    use_container_width=True,
)

st.header("3. Deduplicated Drug Exposure")
st.caption(f"{len(filtered_deduped)} canonical records")
st.dataframe(filtered_deduped, use_container_width=True)
