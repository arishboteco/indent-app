import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date # Import date
import json
# from io import StringIO # StringIO not used

# --- Google Sheets Setup ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    # Use st.secrets for credentials
    if "gcp_service_account" not in st.secrets:
        st.error("Missing GCP Service Account credentials in st.secrets!")
        st.stop()
    json_creds_data = st.secrets["gcp_service_account"]
    if isinstance(json_creds_data, str):
        creds_dict = json.loads(json_creds_data)
    else: # Assume it's already a dict
        creds_dict = json_creds_data
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    # Access worksheets with error handling
    try:
        indent_log_spreadsheet = client.open("Indent Log")
        sheet = indent_log_spreadsheet.sheet1
        reference_sheet = indent_log_spreadsheet.worksheet("reference")
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("Spreadsheet 'Indent Log' not found.")
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error("Worksheet 'Sheet1' or 'reference' not found.")
        st.stop()
    except gspread.exceptions.APIError as e:
         st.error(f"Google API Error: {e}")
         st.stop()
except json.JSONDecodeError:
    st.error("Error parsing GCP credentials.")
    st.stop()
except Exception as e:
    st.error(f"Error setting up Google Sheets connection: {e}")
    st.stop()


# --- Reference Data Loading ---
@st.cache_data(ttl=600) # Cache for 10 minutes
def get_reference_data():
    try:
        all_items_data = reference_sheet.get_all_values()
        item_names = []
        item_to_unit = {}
        header_skipped = False

        for i, row in enumerate(all_items_data):
             # Skip empty rows
            if not any(str(cell).strip() for cell in row): continue
            # Simple header check - modify if header differs
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower() or "unit" in str(row[1]).lower()):
                header_skipped = True
                continue
            if len(row) >= 2:
                item = str(row[0]).strip()
                unit = str(row[1]).strip() if len(row) > 1 else "N/A"
                if item: # Only add if item name is not blank
                    item_names.append(item)
                    item_to_unit[item] = unit if unit else "N/A" # Use N/A if unit blank

        # Store in state for access outside cache if needed, though dict lookup is fast
        st.session_state['master_item_list_original'] = sorted(list(item_to_unit.keys()))
        st.session_state['item_to_unit_map_original'] = item_to_unit
        return st.session_state['master_item_list_original'], st.session_state['item_to_unit_map_original']
    except Exception as e:
        st.error(f"Error loading reference data: {e}")
        return [], {}

# Load data using the function
item_names, item_to_unit = get_reference_data()

if not item_names:
    st.error("Item list is empty after loading. Cannot proceed.")
    st.stop()


# --- MRN Generator (More Robust Version) ---
def generate_mrn():
    try:
        all_mrns = sheet.col_values(1) # Assuming MRN is in column 1
        if len(all_mrns) <= 1: # Only header or empty
            next_number = 1
        else:
            last_valid_num = 0
            for mrn_str in reversed(all_mrns):
                 if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit():
                     last_valid_num = int(mrn_str[4:])
                     break
            if last_valid_num == 0 and len(all_mrns) > 1:
                 non_empty_rows = len([val for val in all_mrns if val])
                 last_valid_num = max(0, non_empty_rows -1)
            next_number = last_valid_num + 1
        return f"MRN-{str(next_number).zfill(3)}"
    except Exception as e:
        st.error(f"Error generating MRN: {e}")
        return f"MRN-FALLBACK-{datetime.now().strftime('%Y%m%d%H%M')}"

# --- Session State Initialization ---
if "item_count" not in st.session_state:
    st.session_state.item_count = 1

# Initialize state keys for widgets if they don't exist
for i in range(st.session_state.item_count):
    st.session_state.setdefault(f"item_{i}", None)
    st.session_state.setdefault(f"qty_{i}", 1) # Default qty to 1
    st.session_state.setdefault(f"note_{i}", "")


st.title("Material Indent Form")

# --- Header Inputs ---
dept = st.selectbox("Select Department",
                    ["", "Kitchen", "Bar", "Housekeeping", "Admin"], # Added "" option
                    key="selected_dept") # Use key

delivery_date = st.date_input("Date Required",
                             value=date.today(), # Use date object
                             min_value=date.today(),
                             key="selected_date", # Use key
                             format="DD/MM/YYYY") # Set format

# --- Add/Remove Buttons ---
col1_btn, col2_btn = st.columns(2)
with col1_btn:
    if st.button("+ Add Item"):
        new_index = st.session_state.item_count
        # Initialize state for the new row
        st.session_state[f"item_{new_index}"] = None
        st.session_state[f"qty_{new_index}"] = 1
        st.session_state[f"note_{new_index}"] = ""
        st.session_state.item_count += 1
        st.rerun() # Rerun needed to show the new row
with col2_btn:
    can_remove = st.session_state.item_count > 1
    if st.button("- Remove Item", disabled=not can_remove):
        if can_remove:
            remove_index = st.session_state.item_count - 1
            # Clean up state for the removed item
            for key_prefix in ["item_", "qty_", "note_"]:
                st.session_state.pop(f"{key_prefix}{remove_index}", None)
            st.session_state.item_count -= 1
            st.rerun() # Rerun needed to remove the row


# --- Indent Form ---
# Collects inputs, review happens *after* submit is clicked
with st.form("indent_form"):
    st.info("Select items and quantities. Units and summary will be shown for review after clicking 'Review & Submit'.")
    for i in range(st.session_state.item_count):
        col1, col2 = st.columns([3, 1]) # Adjusted column ratio

        with col1:
             # Select item - Uses key, placeholder for better UX
            selected_item_widget = col1.selectbox(
                label=f"Select item {i+1}", # Original numbering
                options=[""] + item_names, # Add "" for placeholder
                key=f"item_{i}", # State managed by key
                placeholder="Type or select an item...",
                label_visibility="collapsed"
            )
            # Note input - Uses key
            note_widget = col1.text_input(
                label=f"Note {i+1} (optional)",
                key=f"note_{i}", # State managed by key
                placeholder="Special instructions...",
                label_visibility="collapsed"
                )

        with col2:
             # **No dynamic unit display here** - Limitation of st.form
             # We only show the quantity input field
             st.markdown("**Quantity:**") # Label for qty
             qty_widget = col2.number_input(
                 label=f"Qty {i+1}",
                 min_value=1, # Changed min_value to 1, assuming 0 is not useful
                 step=1,
                 key=f"qty_{i}", # State managed by key
                 label_visibility="collapsed"
                 )
        st.markdown("---", unsafe_allow_html=False) # Add separator

    # Submit button for the form
    # This button now primarily triggers the data collection and review step
    submitted = st.form_submit_button("Review & Submit Request")

# --- Logic AFTER Form Submission ---
if submitted:
    # --- Collect Data from Session State ---
    items_collected = []
    all_item_names_in_form = set()
    has_duplicates = False

    current_dept = st.session_state.get("selected_dept") # Get dept from state
    current_date = st.session_state.get("selected_date") # Get date from state

    # Basic Validation before collecting items
    if not current_dept:
        st.warning("Please select a department.")
        st.stop()
    if not current_date: # Should have a default
        st.warning("Please select a delivery date.")
        st.stop()

    for i in range(st.session_state.item_count):
        selected_item = st.session_state.get(f"item_{i}")
        qty = st.session_state.get(f"qty_{i}")
        note = st.session_state.get(f"note_{i}", "") # Default note to ""

        # Validate and collect valid items
        if selected_item and qty is not None and qty > 0:
            # Look up the purchase unit NOW using the collected item
            purchase_unit = item_to_unit.get(selected_item, "N/A") # Use original map

            # Check for duplicates
            if selected_item in all_item_names_in_form:
                has_duplicates = True
            all_item_names_in_form.add(selected_item)

            items_collected.append((selected_item, qty, purchase_unit, note))

    # --- Validation on Collected Items ---
    if not items_collected:
        st.warning("No valid items entered (ensure item is selected and quantity > 0).")
        st.stop()

    if has_duplicates:
        st.warning("Duplicate items found. Please ensure each item is unique before final submission.")
        # Display summary but maybe prevent final submission? Or let user confirm?
        # For now, we will show summary but block final submit button below

    # --- Show Summary Table (Review Step) ---
    st.markdown("### Review Your Indent Request:")
    st.info(f"**Department:** {current_dept} | **Date Required:** {current_date.strftime('%d-%b-%Y')}")
    df = pd.DataFrame(items_collected, columns=["Item", "Qty", "Unit", "Note"])
    st.dataframe(df, hide_index=True, use_container_width=True) # Use container width

    total_qty = sum(item[1] for item in items_collected)
    st.markdown(f"**Total Quantity:** {total_qty} | **Item Types:** {len(items_collected)}")

    # --- Final Confirmation Button ---
    st.markdown("---")
    # Disable final submit if duplicates were found
    final_submit_disabled = has_duplicates
    tooltip = "Correct duplicate items before submitting." if final_submit_disabled else "Submit to Google Sheets"

    if st.button("Confirm and Submit to Google Sheet", disabled=final_submit_disabled, help=tooltip):
        try:
            mrn = generate_mrn()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Format data for sheet (ensure date is string)
            rows_to_add = [
                [mrn, timestamp, current_dept, current_date.strftime("%Y-%m-%d"), item, str(qty), unit, note if note else "N/A"]
                for item, qty, unit, note in items_collected # Use collected items
            ]

            # Use append_rows for efficiency
            with st.spinner(f"Submitting indent {mrn}..."):
                sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
            st.success(f"Indent submitted successfully! MRN: {mrn}")
            st.balloons()

            # --- Reset Form State ---
            keys_to_clear = ["selected_dept", "selected_date"]
            keys_to_clear.extend([f"{prefix}{i}" for prefix in ["item_", "qty_", "note_"] for i in range(st.session_state.item_count)])
            for key in keys_to_clear:
                 if key in st.session_state:
                     # Resetting selectbox/date needs care, often deleting key is enough
                     # For robustness, could set specific defaults, but deletion usually works
                     del st.session_state[key]

            st.session_state.item_count = 1 # Reset to one item row
            st.rerun() # Rerun to show the cleared form

        except gspread.exceptions.APIError as e:
            st.error(f"Google Sheets API Error during submission: {e}.")
        except Exception as e:
            st.error(f"An unexpected error occurred during submission: {e}")
