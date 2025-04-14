import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
from PIL import Image # Import PIL

# --- Configuration & Setup ---

# Display logo
try:
    # Make sure 'logo.png' is in the same directory as your script
    logo = Image.open("logo.png")
    st.image(logo, width=200)
except FileNotFoundError:
    st.warning("Logo image 'logo.png' not found in the script directory.")
except Exception as e:
    st.warning(f"Could not load logo: {e}")


# Google Sheets setup & Credentials Handling
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
try:
    # Use st.secrets for credentials
    if "gcp_service_account" not in st.secrets:
        st.error("Missing GCP Service Account credentials in st.secrets! Cannot connect to Google Sheets.")
        st.stop()
    json_creds_data = st.secrets["gcp_service_account"]
    # Handle if secrets provides dict or string
    if isinstance(json_creds_data, str):
        creds_dict = json.loads(json_creds_data)
    else: # Assume it's already a dict
        creds_dict = json_creds_data
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    # Access worksheets with detailed error handling
    try:
        indent_log_spreadsheet = client.open("Indent Log") # Use variable
        sheet = indent_log_spreadsheet.sheet1
        reference_sheet = indent_log_spreadsheet.worksheet("reference")
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("Google Spreadsheet 'Indent Log' not found. Please check the name and ensure the service account has access.")
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error("Worksheet 'Sheet1' or 'reference' not found within 'Indent Log'. Please check worksheet names.")
        st.stop()
    except gspread.exceptions.APIError as e:
         st.error(f"Google API Error accessing sheets: {e}. Check permissions and sheet names.")
         st.stop()

except json.JSONDecodeError:
    st.error("Error parsing GCP Service Account credentials from st.secrets. Check the JSON format.")
    st.stop()
except gspread.exceptions.RequestError as e:
    st.error(f"Network error connecting to Google Sheets: {e}")
    st.stop()
except Exception as e:
    st.error(f"Error setting up Google Sheets connection: {e}")
    st.exception(e) # Show full traceback in logs/console for debugging
    st.stop()

# --- Reference Data Loading ---

@st.cache_data(ttl=300) # Cache reference data for 5 minutes
def get_reference_data(_client):
    try:
        st.write("Fetching reference data...") # Debug message
        _reference_sheet = _client.open("Indent Log").worksheet("reference")
        all_data = _reference_sheet.get_all_values()
        st.write(f"Read {len(all_data)} rows from reference sheet.") # Debug

        item_names = []
        item_to_unit_lower = {} # Use lowercase keys for lookup
        processed_items_lower = set()
        header_skipped = False

        for i, row in enumerate(all_data):
            if not any(str(cell).strip() for cell in row): continue # Skip fully empty rows
            # Simple header check
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower() or "unit" in str(row[1]).lower()):
                st.write("Skipping header row in reference.") # Debug
                header_skipped = True
                continue

            if len(row) >= 2:
                item = str(row[0]).strip()
                unit = str(row[1]).strip()
                item_lower = item.lower()

                if item and item_lower not in processed_items_lower:
                    item_names.append(item)
                    item_to_unit_lower[item_lower] = unit if unit else "N/A"
                    processed_items_lower.add(item_lower)

        item_names.sort()
        st.write(f"Loaded {len(item_names)} unique items.") # Debug

        # Store in state for easier access by callback
        st.session_state['master_item_list'] = item_names
        st.session_state['item_to_unit_lower'] = item_to_unit_lower
        return item_names, item_to_unit_lower

    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error loading reference data: {e}")
        return [], {}
    except Exception as e:
        st.error(f"Unexpected error loading reference data: {e}")
        st.exception(e)
        return [], {}

# --- Ensure data is loaded and in session state ---
if 'master_item_list' not in st.session_state or 'item_to_unit_lower' not in st.session_state:
     master_item_names, item_to_unit_lower_map = get_reference_data(client)
     # Data is stored in state by the function now
else:
    master_item_names = st.session_state['master_item_list']
    item_to_unit_lower = st.session_state['item_to_unit_lower']

# Check again if loading failed critically
if not st.session_state.get('master_item_list'):
    st.error("Item list could not be loaded. Cannot proceed.")
    st.stop()


# --- MRN Generation ---
def generate_mrn():
    # ... (MRN generation code remains the same) ...
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
                 last_valid_num = max(0, non_empty_rows -1) # Subtract potential header
            next_number = last_valid_num + 1
        return f"MRN-{str(next_number).zfill(3)}"
    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error generating MRN: {e}.")
        return f"MRN-ERR-{datetime.now().strftime('%H%M%S')}"
    except Exception as e:
        st.error(f"Error generating MRN: {e}")
        return f"MRN-FALLBACK-{datetime.now().strftime('%Y%m%d%H%M')}"


# --- Streamlit App UI ---

st.title("Material Indent Form")

# --- Session State Initialization ---
if "item_count" not in st.session_state:
    st.session_state.item_count = 1

# Initialize state for widgets FOR EACH ITEM ROW if they don't exist yet
for i in range(st.session_state.item_count):
    st.session_state.setdefault(f"item_{i}", None)
    st.session_state.setdefault(f"qty_{i}", 1)
    st.session_state.setdefault(f"note_{i}", "")
    st.session_state.setdefault(f"unit_display_{i}", "-") # State for the dynamic unit display

# --- Callback Function for Dynamic Unit Update ---
def update_unit_display(index):
    """Callback to update the unit display state when an item is selected."""
    selected_item_key = f"item_{index}"
    unit_display_key = f"unit_display_{index}"
    selected_item = st.session_state.get(selected_item_key)

    # Use item_to_unit_lower from session state
    local_item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})

    if selected_item:
        purchase_unit = local_item_to_unit_lower.get(selected_item.lower(), "N/A")
        st.session_state[unit_display_key] = purchase_unit if purchase_unit else "-"
    else:
        st.session_state[unit_display_key] = "-"


# --- Header Inputs (Dept, Date) ---
dept = st.selectbox("Select Department",
                    ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"], # Added Maintenance back
                    index=0,
                    key="selected_dept",
                    placeholder="Select department...")

delivery_date = st.date_input("Date Required",
                              value=date.today(),
                              min_value=date.today(),
                              format="DD/MM/YYYY",
                              key="selected_date")

# --- Add/Remove Item Buttons ---
col1_btn, col2_btn = st.columns(2)
with col1_btn:
    if st.button("+ Add Item"):
        new_index = st.session_state.item_count
        st.session_state[f"item_{new_index}"] = None
        st.session_state[f"qty_{new_index}"] = 1
        st.session_state[f"note_{new_index}"] = ""
        st.session_state[f"unit_display_{new_index}"] = "-"
        st.session_state.item_count += 1
        st.rerun()
with col2_btn:
    can_remove = st.session_state.item_count > 1
    if st.button("- Remove Item", disabled=not can_remove):
        if can_remove:
            remove_index = st.session_state.item_count - 1
            for key_prefix in ["item_", "qty_", "note_", "unit_display_"]:
                st.session_state.pop(f"{key_prefix}{remove_index}", None)
            st.session_state.item_count -= 1
            st.rerun()

st.markdown("---")
st.subheader("Enter Items:")


# --- Item Input Rows (NO st.form HERE) ---
for i in range(st.session_state.item_count):

    # --- Determine items selected in OTHER rows ---
    items_selected_elsewhere = set()
    for k in range(st.session_state.item_count):
        if i == k: continue
        item_in_row_k = st.session_state.get(f"item_{k}")
        if item_in_row_k:
            items_selected_elsewhere.add(item_in_row_k)

    # --- Filter the master list based on items selected elsewhere ---
    # Use master list from state
    current_master_list = st.session_state.get('master_item_list', [])
    available_options_for_this_row = [""] + [
        item for item in current_master_list if item not in items_selected_elsewhere
    ]

    # --- Render the widgets for row i ---
    col1, col2 = st.columns([3, 1])
    with col1:
        # Item selection - Use the correctly filtered options list
        st.selectbox(
            label=f"Item {i}", # Numbering starts from 0
            options=available_options_for_this_row,
            key=f"item_{i}",
            placeholder="Type or select an item...",
            label_visibility="collapsed",
            on_change=update_unit_display, # Trigger unit update
            args=(i,) # Pass index to callback
        )

        # Note field: Uses key
        st.text_input(
            label=f"Note {i}", # Numbering starts from 0
            key=f"note_{i}",
            placeholder="Special instructions...",
            label_visibility="collapsed"
        )

    with col2:
        # Unit Display: Reads state updated by callback - THIS IS DYNAMIC
        st.markdown("**Unit:**")
        unit_to_display = st.session_state.get(f"unit_display_{i}", "-")
        st.markdown(f"### {unit_to_display}")

        # Quantity: Uses key
        st.number_input(
            label=f"Quantity {i}", # Numbering starts from 0
            min_value=1,
            step=1,
            key=f"qty_{i}",
            label_visibility="collapsed"
        )
    st.markdown("---") # Separator between items


# --- Dynamic Indent Summary Section ---
st.markdown("---")
st.subheader("Current Indent Summary")

items_for_summary = []
summary_item_names_processed = set()
summary_has_duplicates_in_state = False

for i in range(st.session_state.item_count):
    item_name = st.session_state.get(f"item_{i}")
    item_qty = st.session_state.get(f"qty_{i}", 1)
    item_unit = st.session_state.get(f"unit_display_{i}", "-") # Use dynamic display unit
    item_note = st.session_state.get(f"note_{i}", "")

    if item_name:
        if item_name in summary_item_names_processed:
            summary_has_duplicates_in_state = True
            continue # Skip duplicates for summary display
        summary_item_names_processed.add(item_name)
        items_for_summary.append({
            "Item": item_name, "Quantity": item_qty,
            "Unit": item_unit, "Note": item_note
        })

if items_for_summary:
    summary_df = pd.DataFrame(items_for_summary)
    st.dataframe(summary_df, hide_index=True, use_container_width=True)
    total_qty = sum(item['Quantity'] for item in items_for_summary)
    st.markdown(f"**Total Quantity:** {total_qty} | **Item Types:** {len(items_for_summary)}")
    if summary_has_duplicates_in_state:
         st.warning("Note: Duplicate items detected; only unique items shown. Fix duplicates to enable submission.")
else:
    st.info("No items added to the indent yet.")


# --- Final Submission Button ---
st.markdown("---")
# Disable button conditions
current_dept = st.session_state.get("selected_dept", "")
submit_disabled = (
    not items_for_summary or
    summary_has_duplicates_in_state or
    not current_dept
)
tooltip_message = ""
if not items_for_summary: tooltip_message += "Add at least one item. "
if summary_has_duplicates_in_state: tooltip_message += "Remove duplicate item entries. "
if not current_dept: tooltip_message += "Select a department."

# Final Submit Button with dynamic tooltip
if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message if submit_disabled else "Submit the current indent"):

    # --- Final Data Collection & Validation ---
    items_to_submit_final = []
    final_item_names = set()
    final_has_duplicates = False # Should be caught by disable, but check again

    # Use map from state
    local_item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})

    for i in range(st.session_state.item_count):
        selected_item = st.session_state.get(f"item_{i}")
        qty = st.session_state.get(f"qty_{i}", 0)
        note = st.session_state.get(f"note_{i}", "")

        if selected_item and qty > 0:
            # Fetch the definitive unit from master map for submission data
            purchase_unit = local_item_to_unit_lower.get(selected_item.lower(), "N/A")

            if selected_item in final_item_names:
                final_has_duplicates = True
                continue # Skip duplicates for submission
            final_item_names.add(selected_item)
            items_to_submit_final.append((selected_item, qty, purchase_unit, note))

    if not items_to_submit_final:
         st.error("No valid, unique items found for submission after final check.")
         st.stop()
    if final_has_duplicates:
         st.error("Error: Duplicates detected during final submission check. Please correct.")
         st.stop()

    # --- Submit to Google Sheets ---
    try:
        mrn = generate_mrn()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_date = st.session_state.get("selected_date", date.today())
        formatted_date = current_date.strftime("%d-%m-%Y") # Use DD-MM-YYYY

        rows_to_add = []
        for item, qty_val, unit, note_val in items_to_submit_final:
            rows_to_add.append([
                mrn, timestamp, current_dept, formatted_date,
                item, str(qty_val), unit, note_val if note_val else "N/A"
            ])

        if rows_to_add:
            with st.spinner(f"Submitting indent {mrn} to Google Sheet..."):
                sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
            st.success(f"Indent submitted successfully! MRN: {mrn}")
            st.balloons()

            # --- Clean up Session State ---
            keys_to_delete = []
            keys_to_delete.extend([f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)])
            keys_to_delete.extend(["selected_dept", "selected_date"])
            # Keep master_item_list and item_to_unit_lower in state
            for key in keys_to_delete:
                if key in st.session_state: del st.session_state[key]
            st.session_state.item_count = 1
            # Re-initialize state for the single remaining row
            st.session_state.setdefault("item_0", None)
            st.session_state.setdefault("qty_0", 1)
            st.session_state.setdefault("note_0", "")
            st.session_state.setdefault("unit_display_0", "-")
            st.rerun()

    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error during submission: {e}.")
        st.exception(e)
    except Exception as e:
        st.error(f"An unexpected error occurred during submission: {e}")
        st.exception(e)

# --- Optional Sidebar Debug ---
# Add this section at the very end if you need detailed debugging
# with st.sidebar:
#     st.write("### Debug Info")
#     st.write("Item Count:", st.session_state.get("item_count", "N/A"))
#     st.write("Master Item List Loaded:", len(st.session_state.get('master_item_list', [])))
#     st.write("Item->Unit Map Loaded:", len(st.session_state.get('item_to_unit_lower', {})))
#     st.write("---")
#     st.write("Session State Keys:")
#     st.json(st.session_state.to_dict()) # Show all state keys and values

