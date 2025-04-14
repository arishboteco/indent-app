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
    json_creds = st.secrets["gcp_service_account"]
    creds_dict = json.loads(json_creds)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    # Access worksheets
    sheet = client.open("Indent Log").sheet1
    reference_sheet = client.open("Indent Log").worksheet("reference")
except json.JSONDecodeError:
    st.error("Error parsing Google Cloud Service Account credentials. Please check the format in Streamlit secrets.")
    st.stop()
except Exception as e:
    st.error(f"Error accessing Google Sheets or credentials: {e}")
    st.stop()


# Cache the reference data to speed up performance
@st.cache_data
def get_reference_data(_client): # Pass client to ensure cache invalidation if connection changes (though unlikely here)
    try:
        # Get all data from the reference sheet
        all_data = _client.open("Indent Log").worksheet("reference").get_all_values() # Use passed client

        # Create mappings (using lowercase keys for robustness)
        item_names = []
        item_to_unit_lower = {}
        processed_items_lower = set()

        # Start from row 2 if there is a header row (adjust if needed)
        header_skipped = False
        for row in all_data:
            # Simple check for a potential header row (e.g., contains "Item" or "Unit")
            if not header_skipped and any(h.strip().lower() in ["item", "item name", "unit", "uom"] for h in row):
                 header_skipped = True
                 continue # Skip header row

            if len(row) >= 2:  # Ensure there are at least 2 columns
                item = row[0].strip()
                unit = row[1].strip()
                item_lower = item.lower()

                if item and item_lower not in processed_items_lower: # Only add if item name exists and not processed
                    item_names.append(item) # Keep original case for display
                    item_to_unit_lower[item_lower] = unit
                    processed_items_lower.add(item_lower)

        # Sort item names alphabetically for better user experience
        item_names.sort()

        return item_names, item_to_unit_lower
    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error loading reference data: {e}. Check sheet/worksheet names and permissions.")
        return [], {}
    except Exception as e:
        st.error(f"Error loading reference data: {e}")
        return [], {}

# Pass the authorized client to the cached function
item_names, item_to_unit_lower = get_reference_data(client)

# Check if reference data loaded correctly
if not item_names:
    st.error("Failed to load item list from reference sheet. Please check the sheet content and structure.")
    st.stop()


# MRN Generator
def generate_mrn():
    try:
        # Safer: Find the last MRN and increment, or start if empty
        all_mrns = sheet.col_values(1) # Assuming MRN is in column 1
        if len(all_mrns) <= 1: # Only header or empty
            next_number = 1
        else:
            last_mrn = all_mrns[-1]
            if last_mrn.startswith("MRN-") and last_mrn[4:].isdigit():
                next_number = int(last_mrn[4:]) + 1
            else:
                # Fallback if last value isn't a standard MRN
                # Count non-empty rows excluding header as an alternative
                non_empty_rows = len([val for val in all_mrns if val])
                next_number = max(1, non_empty_rows) # Ensure at least 1 if header exists

        return f"MRN-{str(next_number).zfill(3)}"
    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error generating MRN: {e}. Check sheet permissions/structure.")
        return f"MRN-ERR-{datetime.now().strftime('%H%M%S')}" # Error MRN
    except Exception as e:
        st.error(f"Error generating MRN: {e}")
        # Fallback to timestamp-based MRN in case of unexpected errors
        return f"MRN-{datetime.now().strftime('%Y%m%d%H%M')}"

# Initialize session state for item tracking and units
if "item_count" not in st.session_state:
    st.session_state.item_count = 1
# Initialize keys for units within session state if they don't exist
for i in range(st.session_state.item_count):
    if f"unit_display_{i}" not in st.session_state:
        st.session_state[f"unit_display_{i}"] = "-" # Default display unit

st.title("Material Indent Form")

# Select department
dept = st.selectbox("Select Department",
                    ["Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"],
                    index=None,
                    placeholder="Select department...")

# Add delivery date
delivery_date = st.date_input("Date Required",
                              value=date.today(), # Set default to today
                              min_value=date.today(), # Use date object
                              format="DD/MM/YYYY")


# --- Callback Function ---
def update_unit_display(index):
    """
    Callback function to update the unit displayed for a specific item row.
    Reads the selected item from session_state (set by the selectbox)
    and updates the corresponding unit display key in session_state.
    """
    selected_item_key = f"item_{index}"
    unit_display_key = f"unit_display_{index}"

    selected_item = st.session_state.get(selected_item_key) # Get selected item from state

    if selected_item:
        # Lookup unit using the lowercase dictionary
        purchase_unit = item_to_unit_lower.get(selected_item.lower(), "-") # Use lowercase key
        st.session_state[unit_display_key] = purchase_unit
    else:
        st.session_state[unit_display_key] = "-" # Reset if item is deselected

# Add/remove item rows
col1_btn, col2_btn = st.columns(2)
with col1_btn:
    if st.button("+ Add Item"):
        # Initialize unit display state for the new item
        new_index = st.session_state.item_count
        st.session_state[f"unit_display_{new_index}"] = "-"
        st.session_state.item_count += 1
        st.rerun() # Rerun to display the new row
with col2_btn:
    # Prevent removing the last item
    can_remove = st.session_state.item_count > 1
    if st.button("- Remove Item", disabled=not can_remove):
        if can_remove:
            # Clean up state for the removed item (optional but good practice)
            remove_index = st.session_state.item_count - 1
            for key_suffix in ["item_", "qty_", "note_", "unit_display_"]:
                st.session_state.pop(f"{key_suffix}{remove_index}", None)

            st.session_state.item_count -= 1
            st.rerun() # Rerun to remove the row

# --- Indent Form ---
items_to_submit = [] # Use a separate list to collect items *during* submission

with st.form("indent_form"):
    # Ensure state keys exist before rendering widgets inside the loop
    for i in range(st.session_state.item_count):
        if f"unit_display_{i}" not in st.session_state:
             st.session_state[f"unit_display_{i}"] = "-"

    for i in range(st.session_state.item_count):
        st.markdown(f"---") # Separator for item rows
        col1, col2 = st.columns([3, 1])

        with col1:
            # Item selection - ADD on_change CALLBACK HERE
            selected_item = st.selectbox(
                f"Item {i+1}",
                options=item_names, # Use original case names for display
                index=None,
                placeholder="Type or select an item...",
                key=f"item_{i}", # Key for accessing value in state
                on_change=update_unit_display, # *** The Fix ***
                args=(i,) # Pass the index to the callback
            )

            # Note field
            note = st.text_input(
                "Note (optional)",
                key=f"note_{i}",
                placeholder="Special instructions..."
            )

        with col2:
            # Unit display - READS FROM SESSION STATE updated by callback
            unit_display = st.session_state.get(f"unit_display_{i}", "-") # Read from state
            st.markdown(f"**Unit:**")
            st.markdown(f"### {unit_display}") # Display unit prominently

            # Quantity
            qty = st.number_input(
                "Quantity",
                min_value=1,
                step=1,
                value=1,
                key=f"qty_{i}"
            )

    st.markdown("---") # Final separator

    # Submit button for the form
    submitted = st.form_submit_button("Review & Submit Request", type="primary")

# --- Post-Form Logic (After Submit Button is Clicked) ---
if submitted:
    # Re-validate essential inputs
    if not dept:
        st.warning("Please select a department.")
        st.stop()

    if not delivery_date:
        st.warning("Please select a delivery date.")
        st.stop()

    # --- Collect items from session state ---
    items_to_submit = [] # Reset list for this submission attempt
    item_names_in_submission = set()
    has_duplicates = False

    for i in range(st.session_state.item_count):
        selected_item = st.session_state.get(f"item_{i}")
        qty = st.session_state.get(f"qty_{i}", 0) # Default to 0 if not found
        note = st.session_state.get(f"note_{i}", "")

        if selected_item and qty > 0:
            # Re-fetch unit reliably based on the selected item at submission time
            purchase_unit = item_to_unit_lower.get(selected_item.lower(), "N/A") # Use lowercase lookup

            # Check for duplicates within this submission
            if selected_item in item_names_in_submission:
                has_duplicates = True
            item_names_in_submission.add(selected_item)

            items_to_submit.append((selected_item, qty, purchase_unit, note))

    # --- Validation Checks on Collected Items ---
    if not items_to_submit:
        st.warning("Please add at least one valid item (with quantity > 0) to submit.")
        st.stop()

    if has_duplicates:
        st.warning("Duplicate items found in the request. Please ensure each item is listed only once.")
        st.stop()

    # --- Display Review Table ---
    st.markdown("### Review Your Indent:")
    df = pd.DataFrame(items_to_submit, columns=["Item", "Quantity", "Unit", "Note"])
    st.dataframe(df, hide_index=True, use_container_width=True)

    # Calculate total items (sum of quantities)
    total_items_quantity = sum(item[1] for item in items_to_submit)
    st.markdown(f"**Total Quantity:** {total_items_quantity}")
    st.markdown(f"**Number of Item Types:** {len(items_to_submit)}")

    # --- Confirmation Button (Optional but recommended) ---
    st.warning("Please review the items above carefully before final submission.")
    if st.button("Confirm and Submit Indent"):
        try:
            mrn = generate_mrn()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formatted_date = delivery_date.strftime("%d-%m-%Y") # Format selected date

            rows_to_add = []
            for item, qty, unit, note in items_to_submit:
                rows_to_add.append([
                    mrn,
                    timestamp,
                    dept,
                    formatted_date,
                    item,
                    str(qty), # Ensure quantity is string for Sheets
                    unit,
                    note if note else "N/A" # Use N/A if note is empty
                ])

            # Add all rows in a single API call
            if rows_to_add:
                with st.spinner(f"Submitting indent {mrn}..."):
                    sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED') # USER_ENTERED treats values like typed
                st.success(f"Indent submitted successfully! MRN: {mrn}")
                st.balloons()

                # Clear form fields by resetting item count and relevant state keys
                # (This part might need adjustment based on exact desired reset behavior)
                # Keep essential state like 'item_count' but clear item specifics
                for i in range(st.session_state.item_count):
                    st.session_state.pop(f"item_{i}", None)
                    st.session_state.pop(f"qty_{i}", None)
                    st.session_state.pop(f"note_{i}", None)
                    st.session_state.pop(f"unit_display_{i}", None)

                # Reset item count to 1 for the next indent
                st.session_state.item_count = 1
                st.session_state["unit_display_0"] = "-" # Re-initialize state for the first row

                # Use st.rerun() to effectively refresh the page state post-submission
                st.rerun()

        except gspread.exceptions.APIError as e:
            st.error(f"Google Sheets API Error during submission: {e}. Please try again.")
        except Exception as e:
            st.error(f"An unexpected error occurred during submission: {e}")

# --- Sidebar Debug (Optional) ---
# Can be removed or commented out for production
# with st.sidebar:
#     st.write("Debug Info:")
#     st.write("Session State:", st.session_state)
#     st.write("Reference Items (First 5):", item_names[:5])
#     st.write("Reference Map Sample (Lowercased):", dict(list(item_to_unit_lower.items())[:5]))
