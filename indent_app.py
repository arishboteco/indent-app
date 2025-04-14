import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
from io import StringIO
from PIL import Image

# Display logo
logo = Image.open("logo.png")
st.image(logo, width=200)

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
    items = reference_sheet.get_all_values()
    item_names = [row[0] for row in items if row[0]]
    item_to_unit = {row[0]: row[1] for row in items if len(row) > 1 and row[0] and row[1]}
    return item_names, item_to_unit

item_names, item_to_unit = get_reference_data()

# MRN Generator
def generate_mrn():
    records = sheet.get_all_records()
    next_number = len(records) + 1
    return f"MRN-{str(next_number).zfill(3)}"

# Initialize session state for item tracking
if "item_count" not in st.session_state:
    st.session_state.item_count = 0

# Store inputs before adding item to preserve on rerun
if st.button("+ Add Item"):
    for i in range(st.session_state.item_count):
        st.session_state[f"item_saved_{i}"] = st.session_state.get(f"item_{i}", "")
        st.session_state[f"qty_saved_{i}"] = st.session_state.get(f"qty_{i}", 0)
        st.session_state[f"note_saved_{i}"] = st.session_state.get(f"note_{i}", "")
    st.session_state.item_count += 1

st.title("Material Indent Form")

# Select department
dept = st.selectbox("Select Department", ["Kitchen", "Bar", "Housekeeping", "Admin"])

# Add delivery date
delivery_date = st.date_input("Date Required", min_value=datetime.now().date())

items = []

# Indent form
with st.form("indent_form"):
    for i in range(st.session_state.item_count):
        col1, col2 = st.columns([2, 1])

        selected_item = col1.selectbox(
            f"Select item {i+1}",
            options=item_names,
            index=item_names.index(st.session_state.get(f"item_saved_{i}", item_names[0]))
            if st.session_state.get(f"item_saved_{i}") in item_names else None,
            placeholder="Type to search...",
            key=f"item_{i}"
        )

        note = col1.text_input("Note (optional)", value=st.session_state.get(f"note_saved_{i}", ""), key=f"note_{i}")

        purchase_unit = item_to_unit[selected_item] if selected_item in item_to_unit else ""
        col2.text_input("Unit", value=purchase_unit, key=f"unit_{i}", disabled=True)

        qty = col2.number_input("Qty", min_value=0, step=1, value=st.session_state.get(f"qty_saved_{i}", 0), key=f"qty_{i}")

        if selected_item and qty > 0:
            items.append((selected_item, qty, purchase_unit, note))

    # Show summary table
    if items:
        st.markdown("### Review your indent:")
        df = pd.DataFrame(items, columns=["Item", "Qty", "Unit", "Note"])
        st.dataframe(df)

    submitted = st.form_submit_button("Submit Request")

    if submitted:
        item_names_only = [item[0] for item in items]
        if len(item_names_only) != len(set(item_names_only)):
            st.warning("Duplicate items found. Please ensure each item is unique.")
            st.stop()

        if items:
            mrn = generate_mrn()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows_to_add = [[mrn, timestamp, dept, delivery_date.strftime("%d-%m-%y"), item, qty, unit, note] for item, qty, unit, note in items]
            for row in rows_to_add:
                sheet.append_row(row)
            st.success(f"Indent submitted successfully with MRN: {mrn}")
        else:
            st.warning("Please add at least one item to submit.")