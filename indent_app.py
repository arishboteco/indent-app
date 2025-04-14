import streamlit as st
import pandas as pd
import gspread
# *** ADD Type Hinting Imports ***
from gspread import Client, Spreadsheet, Worksheet
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
from PIL import Image
from collections import Counter
# *** ADD Type Hinting Imports ***
from typing import Any, Dict, List, Tuple, Optional

# --- Configuration & Setup ---

# Display logo
try:
    logo = Image.open("logo.png")
    st.image(logo, width=200)
except FileNotFoundError:
    st.warning("Logo image 'logo.png' not found.")
except Exception as e:
    st.warning(f"Could not load logo: {e}")

# Google Sheets setup & Credentials Handling
scope: List[str] = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    if "gcp_service_account" not in st.secrets: st.error("Missing GCP credentials!"); st.stop()
    json_creds_data: Any = st.secrets["gcp_service_account"]
    creds_dict: Dict[str, Any] = json.loads(json_creds_data) if isinstance(json_creds_data, str) else json_creds_data
    creds: ServiceAccountCredentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client: Client = gspread.authorize(creds)
    # Access worksheets with detailed error handling
    try:
        indent_log_spreadsheet: Spreadsheet = client.open("Indent Log")
        sheet: Worksheet = indent_log_spreadsheet.sheet1
        reference_sheet: Worksheet = indent_log_spreadsheet.worksheet("reference")
    except gspread.exceptions.SpreadsheetNotFound: st.error("Spreadsheet 'Indent Log' not found."); st.stop()
    except gspread.exceptions.WorksheetNotFound: st.error("Worksheet 'Sheet1' or 'reference' not found."); st.stop()
    # *** More Specific Error Handling ***
    except gspread.exceptions.APIError as e: st.error(f"Google API Error accessing sheets: {e}. Check permissions/names."); st.stop()
except json.JSONDecodeError: st.error("Error parsing GCP credentials."); st.stop()
except gspread.exceptions.RequestError as e: st.error(f"Network error connecting to Google: {e}"); st.stop()
except Exception as e: st.error(f"Google Sheets setup error: {e}"); st.exception(e); st.stop()


# --- Reference Data Loading Function (NO CACHING, returns data) ---
# *** Added Type Hints ***
def get_reference_data(_client: Client) -> Tuple[List[str], Dict[str, str]]:
    """Fetches and processes reference data, returns it. Does NOT modify state."""
    try:
        _reference_sheet = _client.open("Indent Log").worksheet("reference")
        all_data: List[List[str]] = _reference_sheet.get_all_values()
        item_names: List[str] = []
        item_to_unit_lower: Dict[str, str] = {}
        processed_items_lower: set[str] = set()
        header_skipped: bool = False
        for i, row in enumerate(all_data):
            if not any(str(cell).strip() for cell in row): continue
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower() or "unit" in str(row[1]).lower()):
                header_skipped = True; continue
            if len(row) >= 2:
                item: str = str(row[0]).strip(); unit: str = str(row[1]).strip(); item_lower: str = item.lower()
                if item and item_lower not in processed_items_lower:
                    item_names.append(item); item_to_unit_lower[item_lower] = unit if unit else "N/A"; processed_items_lower.add(item_lower)
        item_names.sort()
        return item_names, item_to_unit_lower
    # *** More Specific Error Handling ***
    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error loading reference data: {e}")
        return [], {}
    except Exception as e:
        st.error(f"Unexpected error loading reference data: {e}")
        return [], {}

# --- Populate State from Loaded Data (Only if state is empty) ---
if 'master_item_list' not in st.session_state or 'item_to_unit_lower' not in st.session_state:
     loaded_item_names, loaded_item_to_unit_lower = get_reference_data(client)
     st.session_state['master_item_list'] = loaded_item_names
     st.session_state['item_to_unit_lower'] = loaded_item_to_unit_lower

master_item_names = st.session_state.get('master_item_list', [])
item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})

if not master_item_names: st.error("Item list empty/not loaded. Cannot proceed."); st.stop()


# --- MRN Generation ---
def generate_mrn() -> str: # Added type hint
    # ... (MRN generation logic remains the same) ...
    try:
        all_mrns = sheet.col_values(1); next_number = 1
        if len(all_mrns) > 1:
            last_valid_num = 0
            for mrn_str in reversed(all_mrns):
                if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit(): last_valid_num = int(mrn_str[4:]); break
            if last_valid_num == 0: last_valid_num = max(0, len([v for v in all_mrns if v]) -1)
            next_number = last_valid_num + 1
        return f"MRN-{str(next_number).zfill(3)}"
    except gspread.exceptions.APIError as e: # More specific error
        st.error(f"API Error generating MRN from sheet: {e}"); return f"MRN-ERR-{datetime.now().strftime('%H%M')}"
    except Exception as e: st.error(f"MRN Error: {e}"); return f"MRN-ERR-{datetime.now().strftime('%H%M')}"


# --- Streamlit App UI ---
st.title("Material Indent Form")

# --- Session State Initialization ---
if "item_count" not in st.session_state: st.session_state.item_count = 1
for i in range(st.session_state.item_count):
    st.session_state.setdefault(f"item_{i}", None); st.session_state.setdefault(f"qty_{i}", 1)
    st.session_state.setdefault(f"note_{i}", ""); st.session_state.setdefault(f"unit_display_{i}", "-")
# Initialize last used department if not present
st.session_state.setdefault('last_dept', None)


# --- Callback Function ---
def update_unit_display(index: int) -> None: # Added type hints
    selected_item = st.session_state.get(f"item_{index}")
    local_map = st.session_state.get('item_to_unit_lower', {})
    unit = local_map.get(selected_item.lower(), "N/A") if selected_item else "-"
    st.session_state[f"unit_display_{index}"] = unit if unit else "-"


# --- Header Inputs ---
DEPARTMENTS = ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"] # Use constant
# *** Remember Last Department ***
last_dept = st.session_state.get('last_dept')
dept_index = 0 # Default to ""
if last_dept and last_dept in DEPARTMENTS:
    try:
        dept_index = DEPARTMENTS.index(last_dept)
    except ValueError:
        dept_index = 0 # Fallback if last_dept somehow invalid

dept = st.selectbox("Select Department", DEPARTMENTS,
                    index=dept_index, # Set default index based on last submission
                    key="selected_dept", placeholder="Select department...")
delivery_date = st.date_input("Date Required", value=date.today(), min_value=date.today(),
                              format="DD/MM/YYYY", key="selected_date")

# --- Add/Remove/Clear Buttons ---
# Changed layout slightly for clear button
col1_btn, col2_btn, col3_btn = st.columns([1, 1, 1])
with col1_btn:
    if st.button("➕ Add Item"):
        idx = st.session_state.item_count
        st.session_state[f"item_{idx}"]=None; st.session_state[f"qty_{idx}"]=1
        st.session_state[f"note_{idx}"]=""; st.session_state[f"unit_display_{idx}"]="-"
        st.session_state.item_count += 1
        # IMPLICIT rerun
with col2_btn:
    can_remove = st.session_state.item_count > 1
    if st.button("➖ Remove Last", disabled=not can_remove):
        if can_remove:
            idx = st.session_state.item_count - 1
            for prefix in ["item_", "qty_", "note_", "unit_display_"]: st.session_state.pop(f"{prefix}{idx}", None)
            st.session_state.item_count -= 1
            # IMPLICIT rerun
with col3_btn:
    # *** Clear Form Button ***
    if st.button("🔄 Clear All Items"):
        keys_to_delete = []
        # Find all keys related to the item rows
        for i in range(st.session_state.item_count):
             keys_to_delete.extend([f"item_{i}", f"qty_{i}", f"note_{i}", f"unit_display_{i}"])
        # Remove the keys
        for key in keys_to_delete:
            if key in st.session_state: del st.session_state[key]
        # Reset item count and re-initialize row 0 state
        st.session_state.item_count = 1
        st.session_state.setdefault("item_0", None); st.session_state.setdefault("qty_0", 1)
        st.session_state.setdefault("note_0", ""); st.session_state.setdefault("unit_display_0", "-")
        # Keep selected_dept and selected_date
        st.rerun() # Explicit rerun needed here to clear visuals


st.markdown("---")
st.subheader("Enter Items:")

# --- Item Input Rows (NO Filtering, WITH Expander) ---
for i in range(st.session_state.item_count):
    item_label = st.session_state.get(f"item_{i}", "New")
    # *** Use Expander for Each Item ***
    with st.expander(label=f"Item {i}: {item_label}", expanded=True): # Expanded by default
        col1, col2 = st.columns([3, 1])
        with col1:
            st.selectbox( # Item selection
                label=f"Item Select {i}", # Need unique label even if hidden
                options=[""] + master_item_names, # Use full list from state
                key=f"item_{i}",
                placeholder="Type or select an item...",
                label_visibility="collapsed",
                on_change=update_unit_display, # Dynamic unit update is ON
                args=(i,)
            )
            st.text_input(f"Note {i}", key=f"note_{i}", placeholder="Special instructions...", label_visibility="collapsed") # Note
        with col2:
            st.markdown("**Unit:**"); unit_to_display = st.session_state.get(f"unit_display_{i}", "-"); st.markdown(f"### {unit_to_display}") # Dynamic Unit
            st.number_input(f"Quantity {i}", min_value=1, step=1, key=f"qty_{i}", label_visibility="collapsed") # Qty
        # Removed divider inside expander, expander provides separation

# --- Immediate Duplicate Check & Feedback ---
# ... (Duplicate check logic remains the same) ...
current_selected_items = [st.session_state.get(f"item_{k}") for k in range(st.session_state.item_count) if st.session_state.get(f"item_{k}")]
item_counts = Counter(current_selected_items); duplicates_found = {item: count for item, count in item_counts.items() if count > 1}
has_duplicates_in_state = bool(duplicates_found)
# Error message moved down closer to button

# --- Pre-Submission Check for Button Disabling ---
has_valid_items = any(st.session_state.get(f"item_{k}") and st.session_state.get(f"qty_{k}", 0) > 0 for k in range(st.session_state.item_count))
current_dept = st.session_state.get("selected_dept", "")
submit_disabled = not has_valid_items or has_duplicates_in_state or not current_dept
tooltip_message = ""; error_messages = []
if not has_valid_items: error_messages.append("Add at least one valid item.")
if has_duplicates_in_state: error_messages.append("Remove duplicate item entries.")
if not current_dept: error_messages.append("Select a department.")
tooltip_message = " ".join(error_messages)


# --- Final Submission Button & Prominent Disabled Info ---
st.markdown("---")
# *** Display prominent message if button is disabled ***
if submit_disabled and tooltip_message:
    st.warning(f"⚠️ Cannot submit: {tooltip_message}")

if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message if submit_disabled else "Submit the current indent"):

    # --- Final Data Collection & Validation ---
    items_to_submit_final: List[Tuple] = []; final_item_names = set(); final_has_duplicates = False
    local_item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})
    for i in range(st.session_state.item_count):
        selected_item = st.session_state.get(f"item_{i}"); qty = st.session_state.get(f"qty_{i}", 0); note = st.session_state.get(f"note_{i}", "")
        if selected_item and qty > 0:
            purchase_unit = local_item_to_unit_lower.get(selected_item.lower(), "N/A")
            if selected_item in final_item_names: final_has_duplicates = True; continue
            final_item_names.add(selected_item); items_to_submit_final.append((selected_item, qty, purchase_unit, note))
    if not items_to_submit_final: st.error("No valid items to submit."); st.stop()
    if final_has_duplicates: st.error("Duplicates detected. Aborted."); st.stop()

    # --- Submit to Google Sheets ---
    try:
        mrn = generate_mrn(); timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_date_obj = st.session_state.get("selected_date", date.today()); formatted_date = current_date_obj.strftime("%d-%m-%Y")
        rows_to_add = [[mrn, timestamp, current_dept, formatted_date, item, str(qty), unit, note if note else "N/A"]
                       for item, qty, unit, note in items_to_submit_final]
        if rows_to_add:
            with st.spinner(f"Submitting indent {mrn}..."):
                # *** More Specific Error Handling ***
                try:
                    sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
                except gspread.exceptions.APIError as api_error:
                    st.error(f"Google API Error during submission: {api_error}. Check permissions/quota.")
                    st.stop() # Stop execution if submission fails

            # Store submitted data temporarily for display
            st.session_state['submitted_data_for_summary'] = { 'mrn': mrn, 'dept': current_dept, 'date': formatted_date, 'items': items_to_submit_final }
            # *** Remember Last Department ***
            st.session_state['last_dept'] = current_dept

            # --- Clean up FORM state ONLY ---
            keys_to_delete = []
            keys_to_delete.extend([f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)])
            keys_to_delete.extend(["selected_dept", "selected_date"]) # Clear current selections
            for key in keys_to_delete:
                if key in st.session_state: del st.session_state[key]
            st.session_state.item_count = 1
            st.session_state.setdefault("item_0", None); st.session_state.setdefault("qty_0", 1)
            st.session_state.setdefault("note_0", ""); st.session_state.setdefault("unit_display_0", "-")

            st.rerun() # Rerun to show success/summary

    except Exception as e: st.error(f"Error during submission process: {e}"); st.exception(e)

# --- Display Post-Submission Summary ---
if 'submitted_data_for_summary' in st.session_state:
    submitted_data = st.session_state['submitted_data_for_summary']
    st.success(f"Indent submitted successfully! MRN: {submitted_data['mrn']}")
    st.balloons(); st.markdown("---")
    st.subheader("Submitted Indent Summary")
    st.info(f"**MRN:** {submitted_data['mrn']} | **Department:** {submitted_data['dept']} | **Date Required:** {submitted_data['date']}")
    submitted_df = pd.DataFrame(submitted_data['items'], columns=["Item", "Qty", "Unit", "Note"])
    st.dataframe(submitted_df, hide_index=True, use_container_width=True)
    total_submitted_qty = sum(item[1] for item in submitted_data['items'])
    st.markdown(f"**Total Submitted Quantity:** {total_submitted_qty}"); st.markdown("---")
    if st.button("Start New Indent"):
        del st.session_state['submitted_data_for_summary']; st.rerun()

# --- Optional Full State Debug ---
# st.sidebar.write("### Session State")
# st.sidebar.json(st.session_state.to_dict())
