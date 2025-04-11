import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- Google Sheets Setup ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    "C:\\Users\\arish\\OneDrive\\Boteco Restaurants\\Indent App Project\\indentappproject-0d38dc5b7987.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Indent Log").sheet1  # Your sheet name
reference_sheet = client.open("Indent Log").worksheet("reference")  # Reference sheet with item names and purchase units

# Get the item names and associated purchase units from the "reference" sheet
item_names = reference_sheet.col_values(1)  # Assuming item names are in the first column
purchase_units = reference_sheet.col_values(2)  # Assuming purchase units are in the second column

# Map the item names to purchase units
item_to_unit = dict(zip(item_names, purchase_units))

# --- MRN Generator ---
def generate_mrn():
    records = sheet.get_all_records()
    next_number = len(records) + 1
    return f"MRN-{str(next_number).zfill(3)}"

# --- Streamlit App ---
st.title("Material Indent Form")

# Department Selection
dept = st.selectbox("Select Department", ["Kitchen", "Bar", "Housekeeping", "Admin"])

# Dynamic Input for Items
st.markdown("### Add Items")

num_items = st.number_input('How many items do you want to add?', min_value=1, max_value=10, value=5)

items = []

# Loop through to add dynamic item entries
for i in range(num_items):
    col1, col2 = st.columns([2, 1])
    
    # Item selection with validation from the reference sheet
    selected_item = col1.selectbox(f"Item {i+1}", item_names, key=f"item_{i}")
    
    # Auto-populate purchase unit for the selected item
    purchase_unit = item_to_unit[selected_item]
    col2.write(f"Purchase Unit: {purchase_unit}")
    
    # Quantity input
    qty = col2.number_input("Qty", min_value=0, step=1, key=f"qty_{i}")
    
    # Store the item and quantity if both are selected
    if selected_item and qty > 0:
        items.append((selected_item, qty, purchase_unit))

# Submit Button
if st.button("Submit Request"):
    if items:
        mrn = generate_mrn()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Add the entries to the Google Sheet
        for item, qty, unit in items:
            row = [mrn, timestamp, dept, item, qty, unit]
            sheet.append_row(row)
        
        st.success(f"Indent submitted successfully with MRN: {mrn}")
    else:
        st.warning("Please add at least one item to submit.")
