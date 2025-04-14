import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
from PIL import Image

# Display logo
try:
    logo = Image.open("logo.png")
    st.image(logo, width=200)
except FileNotFoundError:
    st.warning("Logo image not found. Please ensure 'logo.png' exists in the same directory.")

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", 
         "https://www.googleapis.com/auth/drive"]
json_creds = st.secrets["gcp_service_account"]
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# Access worksheets
try:
    sheet = client.open("Indent Log").sheet1
    reference_sheet = client.open("Indent Log").worksheet("reference")
except Exception as e:
    st.error(f"Error accessing Google Sheets: {e}")
    st.stop()

# Cache the reference data to speed up performance
@st.cache_data
def get_reference_data():
    try:
        # Get all data from the reference sheet
        all_data = reference_sheet.get_all_values()
        
        # Skip header if exists (assuming first row is header)
        data_rows = all_data[1:] if len(all_data) > 1 else all_data
        
        # Create mappings, filtering out empty rows
        item_names = []
        item_to_unit = {}
        
        for row in data_rows:
            if len(row) >= 2:  # Ensure there are at least 2 columns
                item = row[0].strip()
                unit = row[1].strip()
                if item:  # Only add if item name exists
                    item_names.append(item)
                    item_to_unit[item] = unit if unit else "N/A"  # Default if unit is empty
        
        # Remove duplicates while preserving order
        seen = set()
        item_names = [x for x in item_names if not (x in seen or seen.add(x))]
        
        return item_names, item_to_unit
    except Exception as e:
        st.error(f"Error loading reference data: {e}")
        return [], {}

item_names, item_to_unit = get_reference_data()

# Debug output (can be removed after testing)
st.sidebar.write("Debug Info:")
st.sidebar.write(f"Total items loaded: {len(item_names)}")
if len(item_names) > 0:
    st.sidebar.write("Sample items:", item_names[:5])
    st.sidebar.write("Sample units:", [item_to_unit.get(item) for item in item_names[:5]])

# MRN Generator
def generate_mrn():
    try:
        records = sheet.get_all_records()
        next_number = len(records) + 1
        return f"MRN-{str(next_number).zfill(3)}"
    except Exception as e:
        st.error(f"Error generating MRN: {e}")
        return f"MRN-{datetime.now().strftime('%Y%m%d%H%M')}"

# Initialize session state for item tracking
if "item_count" not in st.session_state:
    st.session_state.item_count = 1

st.title("Material Indent Form")

# Select department
dept = st.selectbox("Select Department", 
                   ["Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"],
                   index=None,
                   placeholder="Select department...")

# Add delivery date
delivery_date = st.date_input("Date Required", 
                             min_value=datetime.now().date(),
                             format="DD/MM/YYYY")

# Add more item rows
if st.button("+ Add Item"):
    st.session_state.item_count += 1
    st.rerun()

# Remove item row
if st.button("- Remove Item") and st.session_state.item_count > 1:
    st.session_state.item_count -= 1
    st.rerun()

items = []

# Indent form
with st.form("indent_form"):
    for i in range(st.session_state.item_count):
        col1, col2 = st.columns([3, 1])
        
        # Item selection
        selected_item = col1.selectbox(
            f"Item {i+1}",
            options=item_names,
            index=None,
            placeholder="Type to search...",
            key=f"item_{i}"
        )
        
        # Note field
        note = col1.text_input("Note (optional)", 
                             key=f"note_{i}",
                             placeholder="Special instructions...")
        
        # Unit and quantity
        if selected_item:
            purchase_unit = item_to_unit.get(selected_item, "Unit not specified")
            col2.markdown(f"**Unit:** {purchase_unit}")
        else:
            col2.markdown("**Unit:** -")
            
        qty = col2.number_input("Quantity", 
                               min_value=1, 
                               step=1, 
                               key=f"qty_{i}",
                               value=1)
        
        if selected_item and qty > 0:
            items.append((selected_item, qty, purchase_unit, note))

    # Show summary table
    if items:
        st.markdown("### Review your indent:")
        df = pd.DataFrame(items, columns=["Item", "Quantity", "Unit", "Note"])
        st.dataframe(df, hide_index=True, use_container_width=True)
        
        # Calculate total items
        total_items = sum(item[1] for item in items)
        st.markdown(f"**Total Items:** {total_items}")

    submitted = st.form_submit_button("Submit Request", type="primary")

    if submitted:
        if not dept:
            st.warning("Please select a department")
            st.stop()
            
        if not delivery_date:
            st.warning("Please select a delivery date")
            st.stop()
            
        if not items:
            st.warning("Please add at least one item to submit")
            st.stop()

        item_names_only = [item[0] for item in items]
        if len(item_names_only) != len(set(item_names_only)):
            st.warning("Duplicate items found. Please ensure each item is unique.")
            st.stop()

        try:
            mrn = generate_mrn()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formatted_date = delivery_date.strftime("%d-%m-%Y")
            
            rows_to_add = []
            for item, qty, unit, note in items:
                rows_to_add.append([
                    mrn,
                    timestamp,
                    dept,
                    formatted_date,
                    item,
                    str(qty),  # Convert to string to avoid number formatting issues
                    unit,
                    note if note else "N/A"
                ])
            
            # Add all rows in a single API call
            if rows_to_add:
                sheet.append_rows(rows_to_add)
                st.success(f"Indent submitted successfully! MRN: {mrn}")
                st.balloons()
                
                # Reset form after successful submission
                st.session_state.item_count = 1
                st.rerun()
                
        except Exception as e:
            st.error(f"Error submitting indent: {e}")
