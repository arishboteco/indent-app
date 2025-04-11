import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
from io import StringIO

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Load credentials from Streamlit Secrets
json_creds = st.secrets["gcp_service_account"]
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# Sheets
sheet = client.open("Indent Log").sheet1
reference_sheet = client.open("Indent Log").worksheet("reference")

# Fetch reference items and units
item_names = reference_sheet.col_values(1)
purchase_units = reference_sheet.col_values(2)
item_to_unit = dict(zip(item_names, purchase_units))

# MRN Generator
def generate_mrn():
    records = sheet.get_all_records()
    next_number = len(records) + 1
    return f"MRN-{str(next_number).zfill(3)}"

# Streamlit App
st.title("Material Indent Form")

# Select department
dept = st.selectbox("Select Department", ["Kitchen", "Bar", "Housekeeping", "Admin"])

# Choose number of items
num_items = st.number_input("How many items do you want to add?", min_value=1, max_value=10, value=5)

items = []

# Dynamic item entry
for i in range(num_items):
    col1, col2 = st.columns([2, 1])

    # Workaround to trigger full list display by forcing rerun
    typed_item = col1.text_input(f"Search item {i+1} (start typing):", key=f"typed_item_{i}")
    match_items = [item for item in item_names if typed_item.lower() in item.lower()] if typed_item else item_names
    selected_item = col1.selectbox(f"Item {i+1}", match_items, key=f"item_{i}")

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
        for item, qty, unit in items:
            row = [mrn, timestamp, dept, item, qty, unit]
            sheet.append_row(row)
        st.success(f"Indent submitted successfully with MRN: {mrn}")
    else:
        st.warning("Please add at least one item to submit.")
