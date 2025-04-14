import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
from PIL import Image

# --- Configuration & Setup ---

# Display logo
try:
    logo = Image.open("logo.png")
    st.image(logo, width=200)
except FileNotFoundError:
    st.warning("Logo image 'logo.png' not found in the script directory.")

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
except Exception as e:
    st.error(f"Error setting up Google Sheets connection: {e}")
    st.exception(e) # Show full traceback in logs/console for debugging
    st.stop()

# --- Reference Data Loading ---

@st.cache_data(ttl=600) # Cache reference data for 10 minutes
def get_reference_data(_client):
    try:
        # Fetch within function for cache consistency if sheet object changes
        _reference_sheet = _client.open("Indent Log").worksheet("reference")
        all_data = _reference_sheet.get_all_values()

        item_names = []
        item_to_unit_lower = {} # Use lowercase keys for lookup
        processed_items_lower = set()
        header_skipped = False

        for i, row in enumerate(all_data):
            if not any(str(cell).strip() for cell in row): # Skip fully empty rows
                continue
            # Simple header check (adjust if header is complex or absent)
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower() or "unit" in str(row[1]).lower()):
                header_skipped = True
                continue

            if len(row) >= 2:
                item = str(row[0]).strip()
                unit = str(row[1]).strip()
                item_lower = item.lower()

                # Add if item name exists and hasn't been processed (first occurrence wins)
                if item and item_lower not in processed_items_lower:
                    item_names.append(item) # Keep original case for display list
                    item_to_unit_lower[item_lower] = unit if unit else "N/A" # Store unit, use N/A if blank
                    processed_items_lower.add(item_lower)

        item_names.sort() # Sort display list alphabetically
        return item_names, item_to_unit_lower

    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error loading reference data: {e}. Check permissions/names.")
        return [], {} # Return empty structures on error
    except Exception as e:
        st.error(f"Unexpected error loading reference data: {e}")
        st.exception(e)
        return [], {}

item_names, item_to_unit_lower = get_reference_data(client)

if not item_names:
    st.error("Failed to load item list from the 'reference' sheet. Cannot proceed.")
    st.stop()

# --- MRN Generation ---
# (Keep the MRN function as before)
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
            # Fallback if no valid MRN found, estimate based on non-empty rows
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

    if selected_item:
        # Lookup unit using the lowercase dictionary
        purchase_unit = item_to_unit_lower.get(selected_item.lower(), "N/A") # Default to N/A if not found
        st.session_state[unit_display_key] = purchase_unit if purchase_unit else "-" # Ensure '-' if unit is blank
    else:
        st.session_state[unit_display_key] = "-" # Reset to placeholder if item deselected


# --- Header Inputs (Dept, Date) ---
dept = st.selectbox("Select Department",
                    ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"],
                    index=0, # Default to empty selection
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
        # Initialize state for the new row's widgets including unit display
        st.session_state[f"item_{new_index}"] = None
        st.session_state[f"qty_{new_index}"] = 1
        st.session_state[f"note_{new_index}"] = ""
        st.session_state[f"unit_display_{new_index}"] = "-" # Initialize unit display state
        st.session_state.item_count += 1
        st.rerun()
with col2_btn:
    can_remove = st.session_state.item_count > 1
    if st.button("- Remove Item", disabled=not can_remove):
        if can_remove:
            remove_index = st.session_state.item_count - 1
            # Clean up state for the removed item's widgets
            for key_prefix in ["item_", "qty_", "note_", "unit_display_"]: # Remove unit display state too
                st.session_state.pop(f"{key_prefix}{remove_index}", None)
            st.session_state.item_count -= 1
            st.rerun()

st.markdown("---")
st.subheader("Enter Items:")

# --- Item Input Rows (NO st.form HERE) ---
# Loop to create item rows based on session state count
for i in range(st.session_state.item_count):
    col1, col2 = st.columns([3, 1])

    with col1:
        # Item selection - ADD on_change CALLBACK
        selected_item = st.selectbox(
            label=f"Item {i+1}",
            options=[""] + item_names, # "" allows placeholder/deselection
            key=f"item_{i}", # Let Streamlit manage state via key
            placeholder="Type or select an item...",
            label_visibility="collapsed",
            on_change=update_unit_display, # *** ADD CALLBACK HERE ***
            args=(i,) # Pass index to callback
        )

        # Note field: Uses key
        note = st.text_input(
            label=f"Note {i+1} (optional)",
            key=f"note_{i}", # Let Streamlit manage state via key
            placeholder="Special instructions...",
            label_visibility="collapsed"
        )

    with col2:
        # Unit Display: Reads from state updated by the callback
        st.markdown("**Unit:**")
        # Display the unit stored in session state by the callback
        unit_to_display = st.session_state.get(f"unit_display_{i}", "-")
        st.markdown(f"### {unit_to_display}")

        # Quantity: Uses key
        qty = st.number_input(
            label=f"Quantity {i+1}",
            min_value=1,
            step=1,
            key=f"qty_{i}", # Let Streamlit manage state via key
            label_visibility="collapsed"
        )
    st.markdown("---") # Separator between items


# --- Final Submission Button (Outside loop, NO form) ---
st.markdown("---")
if st.button("Submit Indent Request", type="primary", use_container_width=True):

    # --- Validation and Data Collection on Final Submit ---
    current_dept = st.session_state.get("selected_dept", "")
    current_date = st.session_state.get("selected_date", date.today())

    if not current_dept:
        st.warning("Please select a department before submitting.")
        st.stop()
    # Date should always have a value

    items_to_submit = []
    item_names_in_submission = set()
    has_duplicates = False
    has_missing_items = False

    for i in range(st.session_state.item_count):
        selected_item = st.session_state.get(f"item_{i}")
        qty = st.session_state.get(f"qty_{i}", 0)
        note = st.session_state.get(f"note_{i}", "")

        if selected_item and qty > 0:
            # Fetch the unit again for final submission data integrity
            purchase_unit = item_to_unit_lower.get(selected_item.lower(), "N/A")

            if selected_item in item_names_in_submission:
                has_duplicates = True
                continue # Skip duplicates
            item_names_in_submission.add(selected_item)
            items_to_submit.append((selected_item, qty, purchase_unit, note))
        elif not selected_item:
            has_missing_items = True

    # --- Validation Checks ---
    if not items_to_submit:
        st.warning("No valid items entered. Please select items and ensure quantity is at least 1.")
        st.stop()

    if has_duplicates:
        st.warning("Duplicate items were selected and ignored in the final submission.")

    # Optional: Display a final confirmation before sending?
    # st.markdown("### Final Review:")
    # df_final = pd.DataFrame(items_to_submit, columns=["Item", "Quantity", "Unit", "Note"])
    # st.dataframe(df_final)
    # if not st.button("Confirm Submission"):
    #      st.stop()

    # --- Submit to Google Sheets ---
    try:
        mrn = generate_mrn()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_date = current_date.strftime("%d-%m-%Y")

        rows_to_add = []
        for item, qty_val, unit, note_val in items_to_submit:
            rows_to_add.append([
                mrn, timestamp, current_dept, formatted_date,
                item, str(qty_val), unit, note_val if note_val else "N/A"
            ])

        if rows_to_add:
            with st.spinner(f"Submitting indent {mrn} to Google Sheet..."):
                sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
            st.success(f"Indent submitted successfully! MRN: {mrn}")
            st.balloons()

            # --- Clean up Session State after successful submission ---
            keys_to_delete = []
            # Collect keys for form widgets and dynamic display state
            keys_to_delete.extend([f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)])
            keys_to_delete.extend(["selected_dept", "selected_date"]) # Add header input keys

            for key in keys_to_delete:
                if key in st.session_state:
                    del st.session_state[key]

            st.session_state.item_count = 1 # Reset item count for next form
            # No need to initialize state here, will happen at script start

            st.rerun() # Rerun to show fresh form

    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error during submission: {e}. Please check permissions/quota and try again.")
        st.exception(e)
    except Exception as e:
        st.error(f"An unexpected error occurred during submission: {e}")
        st.exception(e)


# --- Optional Sidebar Debug ---
# with st.sidebar:
#     st.write("### Debug Info")
#     st.write("Item Count:", st.session_state.get("item_count", "N/A"))
#     # Uncomment below to see all session state details
#     # st.write("Session State:", st.session_state)
#     st.write("---")
#     st.write("Reference Items Loaded:", len(item_names) if item_names else 0)
#     st.write("Reference Map (Lowercased):", len(item_to_unit_lower) if item_to_unit_lower else 0)
