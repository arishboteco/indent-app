import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
from io import StringIO

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
json_creds = st.secrets["gcp_service_account"]
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

sheet = client.open("Indent Log").sheet1
reference_sheet = client.open("Indent Log").worksheet("reference")

# Cache the reference data to speed up performance
@st.cache_data
def get_reference_data():
    item_names = reference_sheet.col_values(1)
    purchase_units = reference_sheet.col_values(2)
    item_to_unit = dict(zip(item_names, purchase_units))
    return item_names, item_to_unit

item_names, item_to_unit = get_reference_data()

# MRN Generator
def generate_mrn():
    records = sheet.get_all_records()
    next_number = len(records) + 1
    return f"MRN-{str(next_number).zfill(3)}"

# Initialize session state for item tracking
if "item_count" not in st.session_state:
    st.session_state.item_count = 1

st.title("Material Indent Form")

# Select department
dept = st.selectbox("Select Department", ["Kitchen", "Bar", "Housekeeping", "Admin"])

# Add more item rows
if st.button("+ Add Item"):
    st.session_state.item_count += 1

items = []

# Item entry section
for i in range(st.session_state.item_count):
    col1, col2 = st.columns([2, 1])

    selected_item = col1.selectbox(
        f"Select item {i+1}",
        options=item_names,
        index=None,
        placeholder="Type to search...",
        key=f"item_{i}"
    )

    purchase_unit = item_to_unit.get(selected_item, "")
    col2.write(f"Unit: {purchase_unit}")
    qty = col2.number_input("Qty", min_value=0, step=1, key=f"qty_{i}")

    if selected_item and qty > 0:
        items.append((selected_item, qty, purchase_unit))

# Submit
if st.button("Submit Request"):
    if items:
        mrn = generate_mrn()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows_to_add = [[mrn, timestamp, dept, item, qty, unit] for item, qty, unit in items]
        for row in rows_to_add:
            sheet.append_row(row)
        st.success(f"Indent submitted successfully with MRN: {mrn}")
    else:
        st.warning("Please add at least one item to submit.")
