import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
from PIL import Image
from collections import Counter

# --- Configuration & Setup ---

# Display logo
# ... (logo code remains the same) ...
try:
    logo = Image.open("logo.png")
    st.image(logo, width=200)
except FileNotFoundError: st.warning("Logo image 'logo.png' not found.")
except Exception as e: st.warning(f"Could not load logo: {e}")

# Google Sheets setup & Credentials Handling
# ... (setup code remains the same) ...
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
    except gspread.exceptions.SpreadsheetNotFound: st.error("Spreadsheet 'Indent Log' not found."); st.stop()
    except gspread.exceptions.WorksheetNotFound: st.error("Worksheet 'Sheet1' or 'reference' not found."); st.stop()
    except gspread.exceptions.APIError as e: st.error(f"Google API Error: {e}"); st.stop()
except json.JSONDecodeError: st.error("Error parsing GCP credentials."); st.stop()
except gspread.exceptions.RequestError as e: st.error(f"Network error connecting to Google: {e}"); st.stop()
except Exception as e: st.error(f"Google Sheets setup error: {e}"); st.exception(e); st.stop()


# --- Reference Data Loading (REVISED Cache/State Interaction) ---
@st.cache_data(ttl=300)
def get_reference_data_cached(_client): # Renamed
    """Fetches and processes reference data, returns it."""
    try:
        # st.write("DEBUG: Fetching reference data from source...") # Uncomment for cache debug
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
        # *** RETURN the data, DO NOT set session state inside cache ***
        return item_names, item_to_unit_lower
    except Exception as e:
        st.error(f"Error loading reference data inside cache function: {e}")
        return [], {} # Return empty on error

# --- Populate State from Cached/Loaded Data ---
# Check if state needs initial population OR if cache might have expired (optional check)
if 'master_item_list' not in st.session_state or 'item_to_unit_lower' not in st.session_state:
     # Call the cached function to get data
     loaded_item_names, loaded_item_to_unit_lower = get_reference_data_cached(client)
     # Populate session state
     st.session_state['master_item_list'] = loaded_item_names
     st.session_state['item_to_unit_lower'] = loaded_item_to_unit_lower
     st.write("DEBUG: Populated session state from loaded reference data.") # Debug

# Use the maps/lists from session state from now on reliably
master_item_names = st.session_state.get('master_item_list', [])
item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})

# Critical check after attempting to load/retrieve
if not master_item_names:
    st.error("Item list empty/not loaded after check. Cannot proceed."); st.stop()


# --- MRN Generation ---
def generate_mrn():
    # ... (MRN generation code remains the same) ...
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
# Initialize state *only if keys are missing* using setdefault
for i in range(st.session_state.item_count):
    st.session_state.setdefault(f"item_{i}", None)
    st.session_state.setdefault(f"qty_{i}", 1)
    st.session_state.setdefault(f"note_{i}", "")
    st.session_state.setdefault(f"unit_display_{i}", "-")

# --- Callback Function ---
def update_unit_display(index):
    # ... (Callback function remains the same) ...
    selected_item = st.session_state.get(f"item_{index}")
    local_map = st.session_state.get('item_to_unit_lower', {})
    unit = local_map.get(selected_item.lower(), "N/A") if selected_item else "-"
    st.session_state[f"unit_display_{index}"] = unit if unit else "-"


# --- Header Inputs ---
# ... (Header inputs remain the same) ...
dept = st.selectbox("Select Department", ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"],
                    index=0, key="selected_dept", placeholder="Select department...")
delivery_date = st.date_input("Date Required", value=date.today(), min_value=date.today(),
                              format="DD/MM/YYYY", key="selected_date")


# --- Add/Remove Buttons ---
col1_btn, col2_btn = st.columns(2)
with col1_btn:
    if st.button("+ Add Item"):
        st.write("DEBUG: Add Item clicked. Current count:", st.session_state.item_count) # Debug
        new_index = st.session_state.item_count
        st.session_state[f"item_{new_index}"] = None
        st.session_state[f"qty_{new_index}"] = 1
        st.session_state[f"note_{new_index}"] = ""
        st.session_state[f"unit_display_{new_index}"] = "-"
        st.session_state.item_count += 1
        st.write("DEBUG: State after Add Item logic:", st.session_state.to_dict()) # Debug
        st.rerun()
with col2_btn:
    can_remove = st.session_state.item_count > 1
    if st.button("- Remove Item", disabled=not can_remove):
        if can_remove:
            # ... (Remove item logic remains the same) ...
            remove_index = st.session_state.item_count - 1
            for key_prefix in ["item_", "qty_", "note_", "unit_display_"]: st.session_state.pop(f"{key_prefix}{remove_index}", None)
            st.session_state.item_count -= 1; st.rerun()

st.markdown("---")
st.subheader("Enter Items:")

# --- DEBUG: Show state before rendering items ---
# st.write("DEBUG: State before rendering items:", st.session_state.to_dict())


# --- Item Input Rows (NO Filtering on options) ---
for i in range(st.session_state.item_count):
    # --- DEBUG: Show state for this specific row ---
    # if i == 0: # Only for the first row to avoid too much output
    #     st.write(f"DEBUG: Rendering row {i}. item_0 state:", st.session_state.get(f"item_{i}"), "qty_0 state:", st.session_state.get(f"qty_{i}"))

    col1, col2 = st.columns([3, 1])
    with col1:
        st.selectbox( # Item selection
            label=f"Item {i}",
            options=[""] + st.session_state.get('master_item_list', []),
            key=f"item_{i}",
            placeholder="Type or select an item...",
            label_visibility="collapsed",
            on_change=update_unit_display,
            args=(i,)
        )
        st.text_input(f"Note {i}", key=f"note_{i}", placeholder="Special instructions...", label_visibility="collapsed") # Note
    with col2:
        st.markdown("**Unit:**"); unit_to_display = st.session_state.get(f"unit_display_{i}", "-"); st.markdown(f"### {unit_to_display}") # Unit
        st.number_input(f"Quantity {i}", min_value=1, step=1, key=f"qty_{i}", label_visibility="collapsed") # Qty
    st.markdown("---")

# --- Immediate Duplicate Check & Feedback ---
# ... (Duplicate check logic remains the same) ...
current_selected_items = [st.session_state.get(f"item_{k}") for k in range(st.session_state.item_count) if st.session_state.get(f"item_{k}")]
item_counts = Counter(current_selected_items); duplicates_found = {item: count for item, count in item_counts.items() if count > 1}
has_duplicates_in_state = bool(duplicates_found)
if has_duplicates_in_state:
    dup_list = ", ".join(duplicates_found.keys()); st.error(f"⚠️ Duplicate items detected: **{dup_list}**. Please remove duplicates.")

# --- Pre-Submission Check for Button Disabling ---
# ... (Button disabling logic remains the same) ...
has_valid_items = any(st.session_state.get(f"item_{k}") and st.session_state.get(f"qty_{k}", 0) > 0 for k in range(st.session_state.item_count))
current_dept = st.session_state.get("selected_dept", "")
submit_disabled = not has_valid_items or has_duplicates_in_state or not current_dept
tooltip_message = "";
if not has_valid_items: tooltip_message += "Add item(s). "
if has_duplicates_in_state: tooltip_message += "Remove duplicates. "
if not current_dept: tooltip_message += "Select department."


# --- Final Submission Button ---
st.markdown("---")
if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message if submit_disabled else "Submit the current indent"):

    # --- Final Data Collection & Validation ---
    # ... (Final collection and validation logic remains the same) ...
    items_to_submit_final = []; final_item_names = set(); final_has_duplicates = False
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
        # ... (Submission logic remains the same) ...
        mrn = generate_mrn(); timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_date_obj = st.session_state.get("selected_date", date.today()); formatted_date = current_date_obj.strftime("%d-%m-%Y")
        rows_to_add = [[mrn, timestamp, current_dept, formatted_date, item, str(qty), unit, note if note else "N/A"]
                       for item, qty, unit, note in items_to_submit_final]
        if rows_to_add:
            with st.spinner(f"Submitting indent {mrn}..."):
                sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')

            # Store for post-submission summary display
            st.session_state['submitted_data_for_summary'] = { 'mrn': mrn, 'dept': current_dept, 'date': formatted_date, 'items': items_to_submit_final }

            # --- Clean up FORM state ONLY ---
            # ... (Cleanup logic remains the same) ...
            keys_to_delete = []
            keys_to_delete.extend([f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)])
            keys_to_delete.extend(["selected_dept", "selected_date"])
            for key in keys_to_delete:
                if key in st.session_state: del st.session_state[key]
            st.session_state.item_count = 1
            st.session_state.setdefault("item_0", None); st.session_state.setdefault("qty_0", 1)
            st.session_state.setdefault("note_0", ""); st.session_state.setdefault("unit_display_0", "-")

            st.rerun() # Rerun to show success/summary

    except gspread.exceptions.APIError as e: st.error(f"API Error submitting: {e}"); st.exception(e)
    except Exception as e: st.error(f"Error during submission: {e}"); st.exception(e)

# --- Display Post-Submission Summary ---
if 'submitted_data_for_summary' in st.session_state:
    # ... (Post-submission summary display logic remains the same) ...
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
    else: st.stop()


# --- Optional Full State Debug ---
# st.sidebar.write("### Session State")
# st.sidebar.json(st.session_state.to_dict())
