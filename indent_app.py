import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date # Import date specifically
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
try:
    # Use st.secrets for credentials
    if "gcp_service_account" not in st.secrets:
        st.error("Missing GCP Service Account credentials in st.secrets!")
        st.stop()
    json_creds = st.secrets["gcp_service_account"]
    # Ensure json_creds is a string before loading
    if isinstance(json_creds, str):
        creds_dict = json.loads(json_creds)
    else:
        # If it's already a dict (common in newer Streamlit versions)
        creds_dict = json_creds
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    # Access worksheets - add error handling for sheet/worksheet not found
    try:
        indent_log_spreadheet = client.open("Indent Log")
        sheet = indent_log_spreadheet.sheet1
        reference_sheet = indent_log_spreadheet.worksheet("reference")
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("Spreadsheet 'Indent Log' not found. Please check the name.")
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error("Worksheet 'Sheet1' or 'reference' not found within 'Indent Log'. Please check worksheet names.")
        st.stop()

except json.JSONDecodeError:
    st.error("Error parsing Google Cloud Service Account credentials. Please check the format in Streamlit secrets.")
    st.stop()
except Exception as e:
    st.error(f"Error accessing Google Sheets or credentials: {e}")
    st.stop()


# Cache the reference data to speed up performance
# Pass client object to ensure cache recognizes if the connection changes
# Use _client argument convention for cached functions modifying external resources
@st.cache_data(ttl=600) # Cache for 10 minutes
def get_reference_data(_client):
    try:
        # Re-fetch worksheet object inside cached function for robustness
        _reference_sheet = _client.open("Indent Log").worksheet("reference")
        all_data = _reference_sheet.get_all_values()

        item_names = []
        item_to_unit_lower = {}
        processed_items_lower = set()
        header_skipped = False

        for i, row in enumerate(all_data):
            # Skip empty rows
            if not any(row):
                continue
            # Simple header check (adjust if header is complex)
            if not header_skipped and i == 0 and ("item" in row[0].lower() or "unit" in row[1].lower()):
                header_skipped = True
                continue

            if len(row) >= 2:
                item = str(row[0]).strip() # Ensure string conversion
                unit = str(row[1]).strip() # Ensure string conversion
                item_lower = item.lower()

                if item and item_lower not in processed_items_lower:
                    item_names.append(item) # Keep original case for display
                    item_to_unit_lower[item_lower] = unit
                    processed_items_lower.add(item_lower)

        item_names.sort() # Sort for better UX
        return item_names, item_to_unit_lower

    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error loading reference data: {e}. Check sheet/worksheet names and permissions.")
        return [], {}
    except Exception as e:
        st.error(f"Error loading reference data: {e}")
        return [], {}

# Fetch reference data using the authorized client
item_names, item_to_unit_lower = get_reference_data(client)

# Check if reference data loaded correctly
if not item_names:
    st.error("Failed to load item list from reference sheet. Cannot proceed.")
    st.stop() # Stop execution if items cannot be loaded


# MRN Generator
def generate_mrn():
    try:
        # Assuming MRN is in column 1 (index 0)
        all_mrns = sheet.col_values(1)
        if len(all_mrns) <= 1: # Only header or empty
            next_number = 1
        else:
            # Find the last valid MRN-XXX entry and increment
            last_valid_num = 0
            for mrn_str in reversed(all_mrns):
                 if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit():
                     last_valid_num = int(mrn_str[4:])
                     break
            # If no valid MRN found, but rows exist, start from row count (approx)
            if last_valid_num == 0 and len(all_mrns) > 1:
                 last_valid_num = len(all_mrns) -1 # Estimate based on row count

            next_number = last_valid_num + 1

        return f"MRN-{str(next_number).zfill(3)}"

    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error generating MRN: {e}. Check permissions/structure.")
        return f"MRN-ERR-{datetime.now().strftime('%H%M%S')}" # Error MRN
    except Exception as e:
        st.error(f"Error generating MRN: {e}")
        return f"MRN-{datetime.now().strftime('%Y%m%d%H%M')}" # Fallback MRN

# Initialize session state for item tracking
if "item_count" not in st.session_state:
    st.session_state.item_count = 1

# --- Initialize keys for form elements if they don't exist ---
# This prevents errors if items are added/removed before first submission
for i in range(st.session_state.item_count):
    st.session_state.setdefault(f"item_{i}", None)
    st.session_state.setdefault(f"qty_{i}", 1)
    st.session_state.setdefault(f"note_{i}", "")


st.title("Material Indent Form")

# Select department
dept = st.selectbox("Select Department",
                    ["Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"],
                    index=None, # Default to no selection
                    placeholder="Select department...")

# Add delivery date
delivery_date = st.date_input("Date Required",
                              value=date.today(), # Default to today
                              min_value=date.today(),
                              format="DD/MM/YYYY")


# Add/remove item rows
col1_btn, col2_btn = st.columns(2)
with col1_btn:
    if st.button("+ Add Item"):
        # Increment count and initialize state for the new item row
        new_index = st.session_state.item_count
        st.session_state[f"item_{new_index}"] = None
        st.session_state[f"qty_{new_index}"] = 1
        st.session_state[f"note_{new_index}"] = ""
        st.session_state.item_count += 1
        st.rerun()
with col2_btn:
    can_remove = st.session_state.item_count > 1
    if st.button("- Remove Item", disabled=not can_remove):
        if can_remove:
            remove_index = st.session_state.item_count - 1
            # Clean up state for the removed item
            for key_prefix in ["item_", "qty_", "note_"]:
                st.session_state.pop(f"{key_prefix}{remove_index}", None)
            st.session_state.item_count -= 1
            st.rerun()

# --- Indent Form ---
items_to_submit = [] # Collect items here ONLY on submission

with st.form("indent_form"):
    # Loop to create item rows based on session state count
    for i in range(st.session_state.item_count):
        st.markdown(f"---") # Separator
        col1, col2 = st.columns([3, 1])

        with col1:
            # Item selection - NO on_change here
            selected_item = st.selectbox(
                f"Item {i+1}",
                options=[""] + item_names, # Add empty option to allow deselecting
                # Use get to access state safely, provide default index 0 (for "") if key missing
                index= ([""] + item_names).index(st.session_state.get(f"item_{i}", "")) if st.session_state.get(f"item_{i}") in ([""]+item_names) else 0,
                placeholder="Type or select an item...",
                key=f"item_{i}", # Key to store value in session state
            )

            # Note field
            note = st.text_input(
                "Note (optional)",
                value=st.session_state.get(f"note_{i}", ""), # Use state value
                key=f"note_{i}",
                placeholder="Special instructions..."
            )

        with col2:
            # Unit Display: Show placeholder as it cannot update dynamically here
            st.markdown(f"**Unit:**")
            st.markdown(f"### -") # Placeholder

            # Quantity
            qty = st.number_input(
                "Quantity",
                min_value=1,
                step=1,
                value=st.session_state.get(f"qty_{i}", 1), # Use state value
                key=f"qty_{i}"
            )

    st.markdown("---")

    # Submit button for the form (triggers collection and review)
    submitted = st.form_submit_button("Review Indent", type="primary")

# --- Post-Form Logic (Executes ONLY after "Review Indent" is clicked) ---
if submitted:
    # --- Basic Validation ---
    if not dept:
        st.warning("Please select a department.")
        st.stop()
    if not delivery_date:
        st.warning("Please select a delivery date.")
        st.stop()

    # --- Collect items from session state NOW ---
    items_to_submit = []
    item_names_in_submission = set()
    has_duplicates = False
    has_missing_items = False

    for i in range(st.session_state.item_count):
        # Retrieve values from session state using their keys
        selected_item = st.session_state.get(f"item_{i}")
        qty = st.session_state.get(f"qty_{i}", 0)
        note = st.session_state.get(f"note_{i}", "")

        # Process only if an item is actually selected and quantity is valid
        if selected_item and qty > 0:
            # Fetch the unit based on the selected item
            purchase_unit = item_to_unit_lower.get(selected_item.lower(), "N/A") # Use lowercase lookup

            # Check for duplicates within this submission
            if selected_item in item_names_in_submission:
                has_duplicates = True
                # Don't add duplicates to the list to submit
                continue
            item_names_in_submission.add(selected_item)

            items_to_submit.append((selected_item, qty, purchase_unit, note))
        elif not selected_item and st.session_state.item_count > 1: # Check if a row was left blank (ignore if only 1 row)
            has_missing_items = True


    # --- Validation Checks on Collected Items ---
    if not items_to_submit:
        st.warning("Please add at least one valid item (select an item and ensure quantity > 0).")
        st.stop()

    if has_duplicates:
        st.warning("Duplicate items were selected. Please ensure each item is listed only once.")
        # The duplicates were already skipped, so we can proceed to show the unique ones.
        # Optionally add st.stop() here if duplicates should halt submission entirely.

    if has_missing_items:
        st.info("One or more empty item rows were ignored.")


    # --- Display Review Table ---
    st.markdown("### Confirm Your Indent Request:")
    st.info(f"**Department:** {dept} | **Date Required:** {delivery_date.strftime('%d-%b-%Y')}")
    df = pd.DataFrame(items_to_submit, columns=["Item", "Quantity", "Unit", "Note"])
    st.dataframe(df, hide_index=True, use_container_width=True)

    total_items_quantity = sum(item[1] for item in items_to_submit)
    st.markdown(f"**Total Quantity:** {total_items_quantity} | **Number of Item Types:** {len(items_to_submit)}")

    # --- Store collected items in session state for the final submit button ---
    st.session_state['items_ready_for_submission'] = items_to_submit
    st.session_state['dept_for_submission'] = dept
    st.session_state['date_for_submission'] = delivery_date

# --- Final Submit Button (Outside the form) ---
# This button appears only after the form's "Review Indent" button has been clicked
# and items have been collected into st.session_state['items_ready_for_submission']
if 'items_ready_for_submission' in st.session_state and st.session_state['items_ready_for_submission']:

    if st.button("Confirm and Submit to Google Sheet", type="primary"):
        # Retrieve data stored in session state by the form submission logic
        final_items = st.session_state['items_ready_for_submission']
        final_dept = st.session_state['dept_for_submission']
        final_date = st.session_state['date_for_submission']

        try:
            mrn = generate_mrn()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formatted_date = final_date.strftime("%d-%m-%Y")

            rows_to_add = []
            for item, qty, unit, note in final_items:
                rows_to_add.append([
                    mrn, timestamp, final_dept, formatted_date,
                    item, str(qty), unit, note if note else "N/A"
                ])

            if rows_to_add:
                with st.spinner(f"Submitting indent {mrn}..."):
                    sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
                st.success(f"Indent submitted successfully! MRN: {mrn}")
                st.balloons()

                # Clean up session state after successful submission
                del st.session_state['items_ready_for_submission']
                del st.session_state['dept_for_submission']
                del st.session_state['date_for_submission']
                # Reset item count and clear form fields state
                st.session_state.item_count = 1
                for i in range(50): # Clear potential leftover state keys up to a reasonable max
                    st.session_state.pop(f"item_{i}", None)
                    st.session_state.pop(f"qty_{i}", None)
                    st.session_state.pop(f"note_{i}", None)
                # Re-initialize state for the first row for the next indent
                st.session_state.setdefault(f"item_0", None)
                st.session_state.setdefault(f"qty_0", 1)
                st.session_state.setdefault(f"note_0", "")


                st.rerun() # Rerun to reset the form view

        except gspread.exceptions.APIError as e:
            st.error(f"Google Sheets API Error during final submission: {e}. Please try again.")
        except Exception as e:
            st.error(f"An unexpected error occurred during final submission: {e}")
            # Maybe keep items in state so user doesn't lose them?
            # Consider adding st.exception(e) for detailed debugging logs

# Cleanup submission state if the user navigates away or reruns before final submit
elif 'items_ready_for_submission' in st.session_state and not submitted:
     # If 'submitted' is False now, but we had items ready, clear them to avoid showing the final submit button wrongly.
     # This can happen if the user clicks Review, then changes something causing a rerun before clicking Confirm.
     del st.session_state['items_ready_for_submission']
     if 'dept_for_submission' in st.session_state: del st.session_state['dept_for_submission']
     if 'date_for_submission' in st.session_state: del st.session_state['date_for_submission']


# --- Sidebar Debug (Optional) ---
# with st.sidebar:
#     st.write("Debug Info:")
#     st.write("Session State:", st.session_state)
