import streamlit as st
import pandas as pd


st.set_page_config(page_title="OMOP Medication Dedup Demo", layout="wide")

st.title("OMOP-Style Medication Deduplication Demo")

st.markdown("""
This demo takes two raw medication datasets, transforms them into an OMOP-style
`drug_exposure` table, normalizes metformin dose representations, and classifies
records as duplicate, possible duplicate, or not duplicate.
""")


normalized = pd.read_csv("outputs/normalized_drug_exposure.csv")
matches = pd.read_csv("outputs/match_results.csv")
deduped = pd.read_csv("outputs/deduped_drug_exposure.csv")


st.header("1. Normalized OMOP-style Drug Exposure")
st.dataframe(normalized, use_container_width=True)

st.header("2. Match Results")
st.dataframe(matches, use_container_width=True)

st.header("3. Deduplicated Drug Exposure")
st.dataframe(deduped, use_container_width=True)