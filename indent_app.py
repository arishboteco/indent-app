import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
from PIL import Image
from collections import Counter # Import Counter for finding duplicates

# --- Configuration & Setup ---

# Display logo
# ... (Logo display code remains the same) ...
try:
    logo = Image.open("logo.png")
    st.image(logo, width=200)
except FileNotFoundError: st.warning("Logo not found.")
except Exception as e: st.warning(f"Logo error: {e}")

# Google Sheets setup & Credentials Handling
# ... (Google Sheets setup code remains the same) ...
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    if "gcp_service_account" not in st.secrets: st.error("Missing GCP credentials!"); st.stop()
    json_creds_data = st.secrets["gcp_service_account"]
    creds_dict = json.loads(json_creds_data) if isinstance(json_creds_data, str) else json_creds_data
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    try:
        indent_log_spreadsheet = client.open("Indent Log")
        sheet = indent_log_spreadsheet.sheet1
        reference_sheet = indent_log_spreadsheet.worksheet("reference")
    except gspread.exceptions.SpreadsheetNotFound: st.error("'Indent Log' not found."); st.stop()
    except gspread.exceptions.WorksheetNotFound: st.error("'Sheet1' or 'reference' not found."); st.stop()
    except gspread.exceptions.APIError as e: st.error(f"API Error: {e}"); st.stop()
except json.JSONDecodeError: st.error("Error parsing GCP credentials."); st.stop()
except gspread.exceptions.RequestError as e: st.error(f"Network error: {e}"); st.stop()
except Exception as e: st.error(f"Setup error: {e}"); st.exception(e); st.stop()


# --- Reference Data Loading ---
@st.cache_data(ttl=300)
def get_reference_data(_client):
    # ... (get_reference_data function remains the same) ...
    try:
        _reference_sheet = _client.open("Indent Log").worksheet("reference")
        all_data = _reference_sheet.get_all_values()
        item_names = []; item_to_unit_lower = {}; processed_items_lower = set(); header_skipped = False
        for i, row in enumerate(all_data):
            if not any(str(cell).strip() for cell in row): continue
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower() or "unit" in str(row[1]).lower()): header_skipped = True; continue
            if len(row) >= 2:
                item = str(row[0]).strip(); unit = str(row[1]).strip(); item_lower = item.lower()
                if item and item_lower not in processed_items_lower:
                    item_names.append(item); item_to_unit_lower[item_lower] = unit if unit else "N/A"; processed_items_lower.add(item_lower)
        item_names.sort()
        st.session_state['master_item_list'] = item_names
        st.session_state['item_to_unit_lower'] = item_to_unit_lower
        return item_names, item_to_unit_lower
    except Exception as e: st.error(f"Ref data error: {e}"); return [], {}

# --- Ensure data is loaded ---
if 'master_item_list' not in st.session_state or 'item_to_unit_lower' not in st.session_state:
     master_item_names, item_to_unit_lower_map = get_reference_data(client)
else:
    master_item_names = st.session_state['master_item_list']
    item_to_unit_lower = st.session_state['item_to_unit_lower']
if not st.session_state.get('master_item_list'):
    st.error("Item list empty. Cannot proceed."); st.stop()


# --- MRN Generation ---
def generate_mrn():
    # ... (Same MRN function as before) ...
    try:
        all_mrns = sheet.col_values(1); next_number = 1
        if len(all_mrns) > 1:
            last_valid_num = 0
            for mrn_str in reversed(all_mrns):
                if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit(): last_valid_num = int(mrn_str[4:]); break
            if last_valid_num == 0: last_valid_num = max(0, len([v for v in all_mrns if v]) -1)
            next_number = last_valid_num + 1
        return f"MRN-{str(next_number).zfill(3)}"
    except Exception as e: st.error(f"MRN Error: {e}"); return f"MRN-ERR-{datetime.now().strftime('%H%M')}"


# --- Streamlit App UI ---
st.title("Material Indent Form")

# --- Session State Initialization ---
if "item_count" not in st.session_state: st.session_state.item_count = 1
for i in range(st.session_state.item_count):
    st.session_state.setdefault(f"item_{i}", None); st.session_state.setdefault(f"qty_{i}", 1)
    st.session_state.setdefault(f"note_{i}", ""); st.session_state.setdefault(f"unit_display_{i}", "-")

# --- MODIFIED Callback Function ---
def update_unit_and_add_row(index):
    """
    Callback to update unit display AND automatically add a new row
    if an item is selected in the last row.
    """
    selected_item_key = f"item_{index}"
    unit_display_key = f"unit_display_{index}"
    selected_item = st.session_state.get(selected_item_key)
    local_item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})

    # 1. Update Unit Display (always do this)
    if selected_item:
        purchase_unit = local_item_to_unit_lower.get(selected_item.lower(), "N/A")
        st.session_state[unit_display_key] = purchase_unit if purchase_unit else "-"
    else:
        st.session_state[unit_display_key] = "-"

    # 2. Auto-add row logic
    # Check if an item was selected (not blank) AND it was the last row
    if selected_item and index == st.session_state.item_count - 1:
        new_index = st.session_state.item_count # The index for the row to be added
        # Check if state for next row already exists (safety)
        if f"item_{new_index}" not in st.session_state:
            # Increment count
            st.session_state.item_count += 1
            # Initialize state for the new row that will appear on next rerun
            st.session_state[f"item_{new_index}"] = None
            st.session_state[f"qty_{new_index}"] = 1
            st.session_state[f"note_{new_index}"] = ""
            st.session_state[f"unit_display_{new_index}"] = "-"
            # NOTE: No st.rerun() here, relying on natural rerun


# --- Header Inputs ---
dept = st.selectbox("Select Department", ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"],
                    index=0, key="selected_dept", placeholder="Select department...")
delivery_date = st.date_input("Date Required", value=date.today(), min_value=date.today(),
                              format="DD/MM/YYYY", key="selected_date")

# --- Add/Remove Item Buttons (Keep for manual control) ---
col1_btn, col2_btn = st.columns(2)
with col1_btn:
    # The manual button might be less necessary but good for adding blanks or recovery
    if st.button("+ Add Item (Manual)"):
        new_index = st.session_state.item_count
        st.session_state[f"item_{new_index}"]=None; st.session_state[f"qty_{new_index}"]=1
        st.session_state[f"note_{new_index}"]=""; st.session_state[f"unit_display_{new_index}"]="-"
        st.session_state.item_count += 1; st.rerun()
with col2_btn:
    can_remove = st.session_state.item_count > 1
    if st.button("- Remove Item", disabled=not can_remove):
        if can_remove:
            idx = st.session_state.item_count - 1
            for prefix in ["item_", "qty_", "note_", "unit_display_"]: st.session_state.pop(f"{prefix}{idx}", None)
            st.session_state.item_count -= 1; st.rerun()

st.markdown("---")
st.subheader("Enter Items:")

# --- Item Input Rows ---
# Uses the MODIFIED callback 'update_unit_and_add_row'
for i in range(st.session_state.item_count):
    col1, col2 = st.columns([3, 1])
    with col1:
        # Item selection - Use FULL master list
        st.selectbox(
            label=f"Item {i}",
            options=[""] + st.session_state.get('master_item_list', []),
            key=f"item_{i}",
            placeholder="Type or select an item...",
            label_visibility="collapsed",
            on_change=update_unit_and_add_row, # Use the modified callback
            args=(i,)
        )
        # Note input
        st.text_input(f"Note {i}", key=f"note_{i}", placeholder="Special instructions...", label_visibility="collapsed")
    with col2:
        # Dynamic Unit Display
        st.markdown("**Unit:**")
        unit_to_display = st.session_state.get(f"unit_display_{i}", "-")
        st.markdown(f"### {unit_to_display}")
        # Quantity input
        st.number_input(f"Quantity {i}", min_value=1, step=1, key=f"qty_{i}", label_visibility="collapsed")
    st.markdown("---")


# --- Immediate Duplicate Check & Feedback ---
# ... (Duplicate check logic remains the same) ...
current_selected_items = [st.session_state.get(f"item_{k}") for k in range(st.session_state.item_count) if st.session_state.get(f"item_{k}")]
item_counts = Counter(current_selected_items)
duplicates_found = {item: count for item, count in item_counts.items() if count > 1}
has_duplicates_in_state = bool(duplicates_found)

if has_duplicates_in_state:
    dup_list = ", ".join(duplicates_found.keys())
    st.error(f"⚠️ Duplicate items detected: **{dup_list}**. Please remove duplicates before submitting.")

# --- Pre-Submission Check for Button Disabling ---
# ... (Button disabling logic remains the same) ...
has_valid_items = any(st.session_state.get(f"item_{k}") and st.session_state.get(f"qty_{k}", 0) > 0 for k in range(st.session_state.item_count))
current_dept = st.session_state.get("selected_dept", "")
submit_disabled = not has_valid_items or has_duplicates_in_state or not current_dept
tooltip_message = ""
if not has_valid_items: tooltip_message += "Add at least one valid item. "
if has_duplicates_in_state: tooltip_message += "Remove duplicate item entries. "
if not current_dept: tooltip_message += "Select a department."


# --- Final Submission Button ---
st.markdown("---")
if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message if submit_disabled else "Submit the current indent"):

    # --- Final Data Collection & Validation ---
    # ... (Data collection and validation remain the same) ...
    items_to_submit_final = []; final_item_names = set(); final_has_duplicates = False
    local_item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})
    for i in range(st.session_state.item_count):
        selected_item = st.session_state.get(f"item_{i}"); qty = st.session_state.get(f"qty_{i}", 0); note = st.session_state.get(f"note_{i}", "")
        if selected_item and qty > 0:
            purchase_unit = local_item_to_unit_lower.get(selected_item.lower(), "N/A")
            if selected_item in final_item_names: final_has_duplicates = True; continue
            final_item_names.add(selected_item)
            items_to_submit_final.append((selected_item, qty, purchase_unit, note))
    if not items_to_submit_final: st.error("No valid items to submit."); st.stop()
    if final_has_duplicates: st.error("Duplicates detected on final check."); st.stop()

    # --- Submit to Google Sheets ---
    # ... (Submission logic remains the same) ...
    try:
        mrn = generate_mrn(); timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_date_obj = st.session_state.get("selected_date", date.today()); formatted_date = current_date_obj.strftime("%d-%m-%Y")
        rows_to_add = [[mrn, timestamp, current_dept, formatted_date, item, str(qty), unit, note if note else "N/A"]
                       for item, qty, unit, note in items_to_submit_final]
        if rows_to_add:
            with st.spinner(f"Submitting indent {mrn}..."):
                sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
            # Store submitted data for display
            st.session_state['submitted_data_for_summary'] = {'mrn': mrn,'dept': current_dept,'date': formatted_date,'items': items_to_submit_final}
            # Clean up FORM state ONLY
            keys_to_delete = []
            keys_to_delete.extend([f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)])
            keys_to_delete.extend(["selected_dept", "selected_date"])
            for key in keys_to_delete:
                if key in st.session_state: del st.session_state[key]
            st.session_state.item_count = 1
            # Re-initialize state for the single remaining row
            st.session_state.setdefault("item_0", None); st.session_state.setdefault("qty_0", 1)
            st.session_state.setdefault("note_0", ""); st.session_state.setdefault("unit_display_0", "-")
            st.rerun() # Rerun to show success/summary
    except gspread.exceptions.APIError as e: st.error(f"API Error submitting: {e}"); st.exception(e)
    except Exception as e: st.error(f"Error during submission: {e}"); st.exception(e)


# --- Display Post-Submission Summary (if available) ---
if 'submitted_data_for_summary' in st.session_state:
    # ... (Post-submission summary display code remains the same) ...
    submitted_data = st.session_state['submitted_data_for_summary']
    st.success(f"Indent submitted successfully! MRN: {submitted_data['mrn']}")
    st.balloons(); st.markdown("---"); st.subheader("Submitted Indent Summary")
    st.info(f"**MRN:** {submitted_data['mrn']} | **Dept:** {submitted_data['dept']} | **Date:** {submitted_data['date']}")
    submitted_df = pd.DataFrame(submitted_data['items'], columns=["Item", "Qty", "Unit", "Note"])
    st.dataframe(submitted_df, hide_index=True, use_container_width=True)
    total_submitted_qty = sum(item[1] for item in submitted_data['items'])
    st.markdown(f"**Total Submitted Qty:** {total_submitted_qty}"); st.markdown("---")
    if st.button("Start New Indent"):
        del st.session_state['submitted_data_for_summary']; st.rerun()
    else: st.stop() # Keep showing summary


# --- Optional Sidebar Debug ---
# (Keep sidebar code as before if needed)
