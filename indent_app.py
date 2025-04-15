# Required Libraries:
# pip install streamlit pandas gspread oauth2client Pillow fpdf2

import streamlit as st
import pandas as pd
import gspread
from gspread import Client, Spreadsheet, Worksheet # For type hinting
from fpdf import FPDF # Ensure fpdf2 is installed: pip install fpdf2
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
from PIL import Image
from collections import Counter
from typing import Any, Dict, List, Tuple, Optional

# --- Configuration & Setup ---

# Display logo
try:
    # Ensure 'logo.png' is in the same directory as the script
    logo = Image.open("logo.png")
    st.image(logo, width=200)
except FileNotFoundError:
    st.warning("Logo image 'logo.png' not found.")
except Exception as e:
    st.warning(f"Could not load logo: {e}")

# --- Main Application Title ---
st.title("Material Indent Form")

# Google Sheets setup & Credentials Handling
scope: List[str] = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    # Check if secrets are loaded
    if "gcp_service_account" not in st.secrets:
        st.error("Missing GCP Service Account credentials in st.secrets! Cannot connect to Google Sheets.")
        st.stop()

    json_creds_data: Any = st.secrets["gcp_service_account"]
    # Handle dictionary or JSON string from secrets
    if isinstance(json_creds_data, str):
        try:
            creds_dict: Dict[str, Any] = json.loads(json_creds_data)
        except json.JSONDecodeError:
            st.error("Error parsing GCP credentials JSON from st.secrets.")
            st.stop()
    else:
         creds_dict: Dict[str, Any] = json_creds_data # Assume it's already a dict

    creds: ServiceAccountCredentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client: Client = gspread.authorize(creds)

    # Access worksheets with detailed error handling
    try:
        indent_log_spreadsheet: Spreadsheet = client.open("Indent Log")
        sheet: Worksheet = indent_log_spreadsheet.sheet1 # Main log Sheet
        reference_sheet: Worksheet = indent_log_spreadsheet.worksheet("reference") # Item Reference Sheet
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("Google Spreadsheet 'Indent Log' not found. Check name and permissions.")
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error("Worksheet 'Sheet1' or 'reference' not found in 'Indent Log'. Check names.")
        st.stop()
    except gspread.exceptions.APIError as e:
         st.error(f"Google API Error accessing sheets: {e}. Check permissions/quota.")
         st.stop()

except json.JSONDecodeError: # Catch error if json.loads fails above
    st.error("Error parsing GCP credentials JSON.")
    st.stop()
# REMOVED: except gspread.exceptions.RequestError as e: because it doesn't exist
except Exception as e: # Generic exception handler catches other issues like network errors
    st.error(f"An unexpected error occurred during Google Sheets setup: {e}")
    st.exception(e) # Log full traceback for debugging
    st.stop()


# --- Reference Data Loading Function (Cached) ---
@st.cache_data(ttl=300) # Cache reference data for 5 minutes
def get_reference_data(_client: Client) -> Tuple[List[str], Dict[str, str]]:
    """
    Fetches item names and units from the 'reference' sheet.
    Stores results in session_state for persistence within the session.
    Returns the fetched data.
    """
    try:
        # st.write("Fetching reference data...") # Uncomment for debug
        _reference_sheet = _client.open("Indent Log").worksheet("reference")
        all_data: List[List[str]] = _reference_sheet.get_all_values()

        item_names: List[str] = []
        item_to_unit_lower: Dict[str, str] = {} # Use lowercase keys for robust lookup
        processed_items_lower: set[str] = set()
        header_skipped: bool = False

        for i, row in enumerate(all_data):
            # Skip fully empty rows
            if not any(str(cell).strip() for cell in row):
                continue
            # Simple header check (assumes header is first row and contains 'item' or 'unit')
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower() or "unit" in str(row[1]).lower()):
                header_skipped = True
                continue
            # Process data rows
            if len(row) >= 2:
                item: str = str(row[0]).strip()
                unit: str = str(row[1]).strip()
                item_lower: str = item.lower()
                # Add item if name exists and it's the first time seeing it (case-insensitive)
                if item and item_lower not in processed_items_lower:
                    item_names.append(item) # Keep original case for display
                    item_to_unit_lower[item_lower] = unit if unit else "N/A" # Use N/A if unit is blank
                    processed_items_lower.add(item_lower)

        item_names.sort() # Sort the display list
        # Store fetched data in session state
        st.session_state['master_item_list'] = item_names
        st.session_state['item_to_unit_lower'] = item_to_unit_lower
        # st.write(f"Loaded {len(item_names)} unique items into state.") # Uncomment for debug
        return item_names, item_to_unit_lower

    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error loading reference data: {e}")
        st.session_state['master_item_list'] = [] # Ensure state is empty on error
        st.session_state['item_to_unit_lower'] = {}
        return [], {}
    except Exception as e:
        st.error(f"Unexpected error loading reference data: {e}")
        st.exception(e)
        st.session_state['master_item_list'] = []
        st.session_state['item_to_unit_lower'] = {}
        return [], {}

# --- Populate State from Loaded Data (Only if state is empty) ---
# Ensures data is loaded once per session and available
if 'master_item_list' not in st.session_state or 'item_to_unit_lower' not in st.session_state:
     # Call function to load data and populate state via cache/direct call
     master_item_names, item_to_unit_lower_map = get_reference_data(client)
# Use data from session state ensuring it's populated
master_item_names = st.session_state.get('master_item_list', [])
item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})
# Stop if loading failed critically
if not master_item_names:
    st.error("Item list is empty or could not be loaded from the 'reference' sheet. Cannot proceed.")
    st.stop()


# --- MRN Generation ---
def generate_mrn() -> str:
    """Generates the next sequential MRN (e.g., MRN-001) based on existing log entries."""
    try:
        all_mrns = sheet.col_values(1) # Assuming MRN is in the first column
        next_number = 1
        if len(all_mrns) > 1: # Check if there's more than just a potential header
            last_valid_num = 0
            # Iterate backwards to find the last valid MRN number
            for mrn_str in reversed(all_mrns):
                if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit():
                    last_valid_num = int(mrn_str[4:])
                    break # Found the last valid one
            # Fallback: If no valid MRN found, estimate based on non-empty rows
            if last_valid_num == 0:
                 non_empty_rows = len([v for v in all_mrns if v])
                 last_valid_num = max(0, non_empty_rows -1) # Subtract 1 for potential header
            next_number = last_valid_num + 1
        return f"MRN-{str(next_number).zfill(3)}" # Pad with leading zeros
    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error generating MRN: {e}.")
        return f"MRN-ERR-{datetime.now().strftime('%H%M%S')}" # Return error MRN
    except Exception as e:
        st.error(f"Error generating MRN: {e}")
        return f"MRN-ERR-{datetime.now().strftime('%H%M%S')}" # Return error MRN


# --- PDF Generation Function ---
def create_indent_pdf(data: Dict[str, Any]) -> bytes:
    """Generates a PDF representation of the submitted indent data."""
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_margins(10, 10, 10)
        pdf.set_auto_page_break(auto=True, margin=15)

        # Title
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "Material Indent Request", ln=True, align='C')
        pdf.ln(10)

        # Header Info
        pdf.set_font("Helvetica", "", 12)
        pdf.cell(95, 7, f"MRN: {data.get('mrn', 'N/A')}", ln=0)
        pdf.cell(95, 7, f"Date Required: {data.get('date', 'N/A')}", ln=1, align='R')
        pdf.cell(0, 7, f"Department: {data.get('dept', 'N/A')}", ln=1)
        pdf.ln(7)

        # Table Header
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(230, 230, 230) # Light grey background
        col_widths = {'item': 90, 'qty': 15, 'unit': 25, 'note': 60} # Adjust widths as needed
        pdf.cell(col_widths['item'], 7, "Item", border=1, ln=0, align='C', fill=True)
        pdf.cell(col_widths['qty'], 7, "Qty", border=1, ln=0, align='C', fill=True)
        pdf.cell(col_widths['unit'], 7, "Unit", border=1, ln=0, align='C', fill=True)
        pdf.cell(col_widths['note'], 7, "Note", border=1, ln=1, align='C', fill=True)

        # Table Rows
        pdf.set_font("Helvetica", "", 9)
        line_height = 6 # Adjust line height for readability
        for item_data in data.get('items', []):
            if isinstance(item_data, tuple) and len(item_data) == 4:
               item, qty, unit, note = item_data
               start_y = pdf.get_y()
               current_x = pdf.l_margin

               # Use multi_cell for potentially long item names and notes
               pdf.multi_cell(col_widths['item'], line_height, str(item), border='LR', align='L', ln=3)
               item_y = pdf.get_y() # Y position after item cell potentially wraps

               # Calculate Y position for other cells based on start_y
               current_x += col_widths['item']
               pdf.set_xy(current_x, start_y)
               pdf.multi_cell(col_widths['qty'], line_height, str(qty), border='R', align='C', ln=3)
               qty_y = pdf.get_y() # Y after qty cell

               current_x += col_widths['qty']
               pdf.set_xy(current_x, start_y)
               pdf.multi_cell(col_widths['unit'], line_height, str(unit), border='R', align='C', ln=3)
               unit_y = pdf.get_y() # Y after unit cell

               current_x += col_widths['unit']
               pdf.set_xy(current_x, start_y)
               pdf.multi_cell(col_widths['note'], line_height, str(note if note else "-"), border='R', align='L', ln=3)
               note_y = pdf.get_y() # Y after note cell

               # Determine the maximum height needed for this row
               max_y = max(item_y, qty_y, unit_y, note_y)
               # Ensure minimum row height
               max_y = max(max_y, start_y + line_height)

               # Redraw side borders to full row height if multi_cell was used
               pdf.line(pdf.l_margin, start_y, pdf.l_margin, max_y) # Left border of item cell
               pdf.line(pdf.l_margin + col_widths['item'], start_y, pdf.l_margin + col_widths['item'], max_y) # Right border of item cell / Left of Qty
               pdf.line(pdf.l_margin + col_widths['item'] + col_widths['qty'], start_y, pdf.l_margin + col_widths['item'] + col_widths['qty'], max_y) # Right of Qty / Left of Unit
               pdf.line(pdf.l_margin + col_widths['item'] + col_widths['qty'] + col_widths['unit'], start_y, pdf.l_margin + col_widths['item'] + col_widths['qty'] + col_widths['unit'], max_y) # Right of Unit / Left of Note
               pdf.line(pdf.l_margin + sum(col_widths.values()), start_y, pdf.l_margin + sum(col_widths.values()), max_y) # Right border of note cell

               # Draw bottom border
               pdf.line(pdf.l_margin, max_y, pdf.l_margin + sum(col_widths.values()), max_y)
               pdf.set_y(max_y) # Move cursor below the drawn line for the next row
            else:
                # Log or warn about invalid data structure if needed
                st.warning(f"Skipping invalid item data structure in PDF generation: {item_data}")

        # Output the PDF content as bytes
        return pdf.output()
    except Exception as pdf_e:
        st.error(f"Error generating PDF: {pdf_e}")
        st.exception(pdf_e) # Log full traceback for debugging PDF issues
        return b'' # Return empty bytes to indicate failure


# --- Function to Load and Clean Log Data (Cached) ---
@st.cache_data(ttl=60) # Cache log data for 1 minute
def load_indent_log_data() -> pd.DataFrame:
    """Loads and cleans data from the main indent log sheet ('Sheet1')."""
    expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
    try:
        # Fetch all records, preventing gspread from converting types prematurely
        records = sheet.get_all_records(numericise_ignore=['all'])
        if not records:
            return pd.DataFrame(columns=expected_cols) # Return empty DF with columns if sheet is empty

        df = pd.DataFrame(records)

        # Ensure all expected columns exist, add if missing
        for col in expected_cols:
             if col not in df.columns:
                 st.warning(f"Log sheet missing expected column: '{col}'. Adding it as empty.")
                 df[col] = pd.NA

        # Clean data types robustly
        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        if 'Date Required' in df.columns:
            # Try multiple common date formats found in sheets
            try:
                 # Attempt DD-MM-YYYY first (as used in submission)
                 df['Date Required'] = pd.to_datetime(df['Date Required'], format='%d-%m-%Y', errors='coerce')
                 mask = df['Date Required'].isna()
                 # Attempt YYYY-MM-DD for rows that failed the first format
                 if mask.any():
                     df.loc[mask, 'Date Required'] = pd.to_datetime(df.loc[mask, 'Date Required'], format='%Y-%m-%d', errors='coerce')
                 # Add more formats here if needed (e.g., '%m/%d/%Y')
            except Exception: # Fallback if specific formats fail or column has mixed types badly
                 df['Date Required'] = pd.to_datetime(df['Date Required'], errors='coerce')

        if 'Qty' in df.columns:
            # Convert Qty to numeric, coercing errors, filling NA with 0, then to integer
            df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0).astype(int)

        # Reorder columns for consistency
        df = df[expected_cols]
        return df
    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error loading indent log: {e}")
        return pd.DataFrame(columns=expected_cols) # Return empty DF on error
    except Exception as e:
        st.error(f"Error loading or cleaning indent log data: {e}")
        st.exception(e)
        return pd.DataFrame(columns=expected_cols) # Return empty DF on error


# --- --- --- --- --- --- --- ---

# --- Initialize Flags ---
# These flags help manage multi-step interactions like confirmations
st.session_state.setdefault('show_clear_confirmation', False)
st.session_state.setdefault('reset_filters_flag', False)

# Define constants
DEPARTMENTS = ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"]

# --- UI divided into Tabs ---
tab1, tab2 = st.tabs(["📝 New Indent", "📊 View Indents"])

# --- TAB 1: New Indent Form ---
with tab1:
    # --- Session State Initialization for Tab 1 ---
    if "item_count" not in st.session_state:
        st.session_state.item_count = 5 # Default 5 rows on first load
    else:
        # Ensure count is at least 1 after potential clears/removals
        st.session_state.item_count = max(1, st.session_state.item_count)

    # Initialize state for each potential item row widget
    for i in range(st.session_state.item_count):
        st.session_state.setdefault(f"item_{i}", None)
        st.session_state.setdefault(f"qty_{i}", 1)
        st.session_state.setdefault(f"note_{i}", "")
        st.session_state.setdefault(f"unit_display_{i}", "-") # For dynamic unit display

    # Remember last used department within the session
    st.session_state.setdefault('last_dept', None)

    # --- Callback Function ---
    def update_unit_display(index: int) -> None:
        """Callback triggered on item selection to update the displayed unit."""
        selected_item = st.session_state.get(f"item_{index}")
        # Access the unit map stored in session state
        local_map = st.session_state.get('item_to_unit_lower', {})
        # Look up unit (case-insensitive), default to "N/A" or "-"
        unit = local_map.get(selected_item.lower(), "N/A") if selected_item else "-"
        st.session_state[f"unit_display_{index}"] = unit if unit else "-"

    # --- Header Inputs ---
    # Set default department based on last submission if available
    last_dept = st.session_state.get('last_dept')
    dept_index = 0
    if last_dept and last_dept in DEPARTMENTS:
        try: dept_index = DEPARTMENTS.index(last_dept)
        except ValueError: dept_index = 0 # Default if last_dept is somehow invalid
    # Department selector
    dept = st.selectbox(
        "Select Department",
        DEPARTMENTS,
        index=dept_index, # Pre-select last used department
        key="selected_dept", # Link to session state
        placeholder="Select department..."
    )
    # Date selector
    delivery_date = st.date_input(
        "Date Required",
        value=st.session_state.get("selected_date", date.today()), # Persist selected date
        min_value=date.today(),
        format="DD/MM/YYYY",
        key="selected_date" # Link to session state
    )

    # --- Item Input Section ---
    st.divider()
    st.subheader("Enter Items:")
    # Loop through the current number of item rows
    for i in range(st.session_state.item_count):
        # Get current item name for expander label, default to row index
        item_label = st.session_state.get(f"item_{i}", f"Item {i}")
        # Use an expander for each row, start collapsed
        with st.expander(label=f"Item {i}: {item_label}", expanded=False):
            col1, col2 = st.columns([3, 1]) # Define layout columns
            with col1:
                # Item Selector Dropdown (Uses full list for stability)
                st.selectbox(
                    label=f"Item Select {i}", # Unique label
                    options=[""] + master_item_names, # Use full item list
                    key=f"item_{i}", # Link to state
                    placeholder="Select item...",
                    label_visibility="collapsed", # Hide label visually
                    on_change=update_unit_display, # Trigger callback on change
                    args=(i,) # Pass row index to callback
                )
                # Note Input Text Box
                st.text_input(
                    f"Note {i}",
                    key=f"note_{i}", # Link to state
                    placeholder="Special instructions...",
                    label_visibility="collapsed"
                )
            with col2:
                # Dynamic Unit Display Area
                st.markdown("**Unit:**")
                unit_to_display = st.session_state.get(f"unit_display_{i}", "-")
                st.markdown(f"### {unit_to_display}") # Display unit dynamically
                # Quantity Input Number Box
                st.number_input(
                    f"Quantity {i}",
                    min_value=1, # Minimum quantity allowed
                    step=1, # Increment step
                    key=f"qty_{i}", # Link to state
                    label_visibility="collapsed"
                )

    # --- Add/Remove/Clear Buttons ---
    st.divider()
    col1_btn, col2_btn, col3_btn = st.columns([1, 1, 1]) # Equal columns for buttons
    with col1_btn:
        # Button to add a new item row
        if st.button("➕ Add Row", key="add_item_tab1", help="Add another item row"):
            idx = st.session_state.item_count
            # Initialize state for the new row
            st.session_state[f"item_{idx}"]=None; st.session_state[f"qty_{idx}"]=1
            st.session_state[f"note_{idx}"]=""; st.session_state[f"unit_display_{idx}"]="-"
            st.session_state.item_count += 1
            st.rerun() # Rerun to show the newly added row
    with col2_btn:
        # Button to remove the last item row
        can_remove = st.session_state.item_count > 1 # Can only remove if more than 1 row exists
        if st.button("➖ Remove Last", disabled=not can_remove, key="remove_item_tab1", help="Remove the last item row"):
            if can_remove:
                idx = st.session_state.item_count - 1
                # Remove state keys associated with the removed row
                for prefix in ["item_", "qty_", "note_", "unit_display_"]:
                    st.session_state.pop(f"{prefix}{idx}", None)
                st.session_state.item_count -= 1
                st.rerun() # Rerun to reflect the removal
    with col3_btn:
        # Button to initiate clearing the form (sets confirmation flag)
        if st.button("🔄 Clear Form", key="clear_items_tab1", help="Remove all items and reset the form"):
             st.session_state['show_clear_confirmation'] = True # Set flag
             st.rerun() # Rerun to show confirmation options

    # Display confirmation buttons if the 'Clear Form' flag is set
    if st.session_state.get('show_clear_confirmation', False):
        st.warning("Are you sure you want to clear all entered items?")
        confirm_col_yes, confirm_col_no, _ = st.columns([1,1,3]) # Layout confirmation buttons
        with confirm_col_yes:
            # Button to confirm clearing
            if st.button("Yes, Clear All", type="primary", key="confirm_clear_yes"):
                # --- Actual Clearing Logic ---
                keys_to_delete = [f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)]
                for key in keys_to_delete:
                    if key in st.session_state: del st.session_state[key]
                st.session_state.item_count = 5 # Reset to default number of rows
                # Re-initialize default state for the cleared rows
                for i in range(st.session_state.item_count):
                     st.session_state.setdefault(f"item_{i}", None); st.session_state.setdefault(f"qty_{i}", 1)
                     st.session_state.setdefault(f"note_{i}", ""); st.session_state.setdefault(f"unit_display_{i}", "-")
                # --- End Clearing Logic ---
                del st.session_state['show_clear_confirmation'] # Clear the confirmation flag
                st.success("Form Cleared.")
                st.rerun() # Rerun to show the cleared form state
        with confirm_col_no:
            # Button to cancel clearing
            if st.button("Cancel", key="confirm_clear_no"):
                del st.session_state['show_clear_confirmation'] # Clear the confirmation flag
                st.rerun() # Rerun to hide confirmation buttons

    # --- Immediate Duplicate Check & Feedback ---
    # Check for duplicate items selected in the current form state
    current_selected_items = [st.session_state.get(f"item_{k}") for k in range(st.session_state.item_count) if st.session_state.get(f"item_{k}")]
    item_counts = Counter(current_selected_items)
    duplicates_found = {item: count for item, count in item_counts.items() if count > 1}
    has_duplicates_in_state = bool(duplicates_found)

    # --- Pre-Submission Check & Button Disabling Info ---
    # Determine if the form is ready for submission
    has_valid_items = any(st.session_state.get(f"item_{k}") and st.session_state.get(f"qty_{k}", 0) > 0 for k in range(st.session_state.item_count))
    current_dept_tab1 = st.session_state.get("selected_dept", "")
    submit_disabled = not has_valid_items or has_duplicates_in_state or not current_dept_tab1
    # Prepare tooltip/error messages based on validation state
    tooltip_message = ""; error_messages = []
    if not has_valid_items: error_messages.append("Add at least one valid item (with quantity > 0).")
    if has_duplicates_in_state: error_messages.append("Remove duplicate item entries.")
    if not current_dept_tab1: error_messages.append("Select a department.")
    tooltip_message = " ".join(error_messages)

    st.divider()
    # Display validation feedback above the submit button if disabled
    if submit_disabled and error_messages:
        # Show specific error for duplicates, general warning otherwise
        if has_duplicates_in_state:
            dup_list = ", ".join(duplicates_found.keys())
            st.error(f"⚠️ Cannot submit: Duplicate items detected ({dup_list}). Please fix.")
        else:
            st.warning(f"⚠️ Cannot submit: {' '.join(error_messages)}")

    # --- Final Submission Button ---
    if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message if submit_disabled else "Submit the current indent", key="submit_indent_tab1"):

        # --- Final Data Collection & Validation ---
        # Collect data again, ensuring integrity before submission
        items_to_submit_final: List[Tuple] = []
        final_item_names = set()
        final_has_duplicates = False # Rigorous final check
        local_item_to_unit_lower = st.session_state.get('item_to_unit_lower', {}) # Get map from state

        for i in range(st.session_state.item_count):
            selected_item = st.session_state.get(f"item_{i}")
            qty = st.session_state.get(f"qty_{i}", 0)
            note = st.session_state.get(f"note_{i}", "")
            # Include item only if selected and quantity is positive
            if selected_item and qty > 0:
                # Get definitive unit from map for submission
                purchase_unit = local_item_to_unit_lower.get(selected_item.lower(), "N/A")
                # Final check for duplicates before adding to submission list
                if selected_item in final_item_names:
                    final_has_duplicates = True
                    continue # Skip adding duplicate
                final_item_names.add(selected_item)
                # Append data as a tuple
                items_to_submit_final.append(tuple([selected_item, qty, purchase_unit, note]))

        # Abort if final checks fail (should be redundant due to disabled button, but good safeguard)
        if not items_to_submit_final: st.error("No valid items found to submit."); st.stop()
        if final_has_duplicates: st.error("Duplicates detected on final check. Submission aborted."); st.stop()

        # --- Submit to Google Sheets ---
        try:
            mrn = generate_mrn()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            current_date_obj = st.session_state.get("selected_date", date.today())
            formatted_date = current_date_obj.strftime("%d-%m-%Y") # DD-MM-YYYY format

            # Prepare rows for batch append
            rows_to_add = [
                [mrn, timestamp, current_dept_tab1, formatted_date, item, str(qty), unit, note if note else "N/A"]
                for item, qty, unit, note in items_to_submit_final
            ]

            if rows_to_add:
                with st.spinner(f"Submitting indent {mrn}..."):
                    try:
                        # Append all rows in a single API call
                        sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
                    except gspread.exceptions.APIError as api_error:
                        st.error(f"API Error submitting to Google Sheets: {api_error}.")
                        st.stop() # Stop execution if submission fails

                # Store submitted data in state to display summary after rerun
                st.session_state['submitted_data_for_summary'] = {
                    'mrn': mrn,
                    'dept': current_dept_tab1,
                    'date': formatted_date,
                    'items': items_to_submit_final # Store the list of tuples
                }
                st.session_state['last_dept'] = current_dept_tab1 # Remember department

                # --- Clean up FORM state ONLY ---
                # Prepare list of keys related to form inputs
                keys_to_delete = [f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)]
                keys_to_delete.extend(["selected_dept", "selected_date"])
                # Delete the keys from session state
                for key in keys_to_delete:
                    if key in st.session_state: del st.session_state[key]
                # Reset item count for the next form
                st.session_state.item_count = 5 # Default to 5 rows
                # Re-initialize state for the new empty rows
                for i in range(st.session_state.item_count):
                     st.session_state.setdefault(f"item_{i}", None); st.session_state.setdefault(f"qty_{i}", 1)
                     st.session_state.setdefault(f"note_{i}", ""); st.session_state.setdefault(f"unit_display_{i}", "-")

                # Rerun the script to clear the form inputs and show the post-submission summary
                st.rerun()

        except Exception as e:
            st.error(f"An unexpected error occurred during submission: {e}")
            st.exception(e)

    # --- Display Post-Submission Summary (within Tab 1, shown after rerun) ---
    if 'submitted_data_for_summary' in st.session_state:
        submitted_data = st.session_state['submitted_data_for_summary']

        # Display success message and confetti
        st.success(f"Indent submitted successfully! MRN: {submitted_data['mrn']}")
        st.balloons()
        st.divider()
        st.subheader("Submitted Indent Summary")
        # Display key details of the submitted indent
        st.info(f"**MRN:** {submitted_data['mrn']} | **Department:** {submitted_data['dept']} | **Date Required:** {submitted_data['date']}")

        # Prepare and display the DataFrame summary
        items_for_df = submitted_data.get('items', [])
        # Check if data is in the expected format (list of tuples)
        if items_for_df and isinstance(items_for_df[0], tuple) and len(items_for_df[0]) == 4:
             submitted_df = pd.DataFrame(items_for_df, columns=["Item", "Qty", "Unit", "Note"])
             st.dataframe(submitted_df, hide_index=True, use_container_width=True)
             # Calculate and display total quantity
             total_submitted_qty = sum(item[1] for item in items_for_df)
             st.markdown(f"**Total Submitted Quantity:** {total_submitted_qty}")
        else:
             st.warning("Could not display submitted items summary due to unexpected data format.")
        st.divider()

        # PDF Download Button
        try:
            pdf_output: bytes = create_indent_pdf(submitted_data)
            if pdf_output: # Check if PDF generation returned bytes
                 st.download_button(
                     label="📄 Download Indent PDF",
                     data=pdf_output,
                     file_name=f"Indent_{submitted_data['mrn']}.pdf",
                     mime="application/pdf",
                     key='pdf_download_button'
                 )
            else:
                 st.warning("PDF generation failed, download unavailable.") # Inform user if PDF failed
        except Exception as pdf_error:
            st.error(f"Could not generate or download PDF: {pdf_error}")
            st.exception(pdf_error)

        # Button to clear the summary and start a new indent form
        if st.button("Start New Indent", key='new_indent_button'):
            # Remove the summary data from state
            if 'submitted_data_for_summary' in st.session_state:
                del st.session_state['submitted_data_for_summary']
            # Rerun the script to show the fresh, empty form
            st.rerun()


# --- TAB 2: View Indents ---
with tab2:
    st.subheader("View Past Indent Requests")

    # --- Handle Filter Reset Flag ---
    # Calculate default date range based on actual data BEFORE potential reset
    # Load data once for date range calculation (cache helps subsequent load)
    log_df_for_dates = load_indent_log_data()
    min_date_log = date.today() - pd.Timedelta(days=30) # Default fallback
    max_date_log = date.today() # Default fallback
    if not log_df_for_dates.empty and 'Date Required' in log_df_for_dates.columns and not log_df_for_dates['Date Required'].isnull().all():
         min_dt_val = log_df_for_dates['Date Required'].dropna().min()
         max_dt_val = log_df_for_dates['Date Required'].dropna().max()
         # Check if min/max dates are valid Timestamps before converting to date
         if pd.notna(min_dt_val) and isinstance(min_dt_val, pd.Timestamp): min_date_log = min_dt_val.date()
         if pd.notna(max_dt_val) and isinstance(max_dt_val, pd.Timestamp): max_date_log = max_dt_val.date()
         # Ensure min_date is not after max_date (can happen with limited data)
         if min_date_log > max_date_log: min_date_log = max_date_log - pd.Timedelta(days=1)

    # Check and apply reset BEFORE rendering widgets
    if st.session_state.get('reset_filters_flag', False):
        # Set state keys to default values
        st.session_state["filt_start"] = min_date_log
        st.session_state["filt_end"] = max_date_log
        st.session_state["filt_dept"] = []
        st.session_state["filt_mrn"] = ""
        st.session_state["filt_item"] = ""
        del st.session_state['reset_filters_flag'] # Unset flag immediately

    # Initialize filter state keys if they don't exist
    st.session_state.setdefault("filt_start", min_date_log)
    st.session_state.setdefault("filt_end", max_date_log)
    st.session_state.setdefault("filt_dept", [])
    st.session_state.setdefault("filt_mrn", "")
    st.session_state.setdefault("filt_item", "")

    # Load data (use already loaded df if possible, cache helps here)
    with st.spinner("Loading indent history..."):
        log_df = log_df_for_dates if 'log_df_for_dates' in locals() and not log_df_for_dates.empty else load_indent_log_data()

    # --- Filtering Widgets ---
    if not log_df.empty:
        with st.expander("Filter Options", expanded=True):
            filt_col_main, filt_col_reset = st.columns([8,1]) # Layout columns
            with filt_col_main:
                 filt_col1, filt_col2, filt_col3 = st.columns([1, 1, 2]) # Inner layout
                 with filt_col1:
                     # Date Inputs (rely on key and initialized state)
                     st.date_input("Reqd. From", min_value=min_date_log, max_value=max_date_log, key="filt_start")
                     current_start_date = st.session_state.get("filt_start", min_date_log) # Get current start for end's min
                     st.date_input("Reqd. To", min_value=current_start_date, max_value=max_date_log, key="filt_end")
                 with filt_col2:
                     # Department MultiSelect
                     dept_options = sorted([d for d in DEPARTMENTS if d]) # Exclude blank option
                     st.multiselect("Filter by Department", options=dept_options, key="filt_dept")
                     # MRN Search Text Input
                     st.text_input("Search by MRN", key="filt_mrn")
                 with filt_col3:
                     # Item Search Text Input
                     st.text_input("Search by Item Name", key="filt_item")

            # Reset Button - Sets flag and reruns
            with filt_col_reset:
                 st.write("") # Vertical alignment hack
                 st.write("")
                 if st.button("Reset", key="reset_filters_tab2_button", help="Clear all filters"):
                     st.session_state['reset_filters_flag'] = True # Set flag
                     st.rerun() # Trigger rerun to apply reset

            # --- Apply Filters ---
            # Filter logic reads directly from session state keys
            filtered_df = log_df.copy()
            try:
                # Retrieve filter values from state safely using .get()
                start_ts_filt = pd.Timestamp(st.session_state.get("filt_start"))
                end_ts_filt = pd.Timestamp(st.session_state.get("filt_end"))
                sel_depts_filt = st.session_state.get("filt_dept", [])
                mrn_s_filt = st.session_state.get("filt_mrn", "")
                item_s_filt = st.session_state.get("filt_item", "")

                # Apply date filter
                if 'Date Required' in filtered_df.columns and not filtered_df['Date Required'].isnull().all():
                    # Ensure column is datetime before comparison
                    filtered_df['Date Required'] = pd.to_datetime(filtered_df['Date Required'], errors='coerce')
                    date_filt_condition = (filtered_df['Date Required'].notna() &
                                           (filtered_df['Date Required'].dt.normalize() >= start_ts_filt) &
                                           (filtered_df['Date Required'].dt.normalize() <= end_ts_filt))
                    filtered_df = filtered_df[date_filt_condition]

                # Apply department filter
                if sel_depts_filt and 'Department' in filtered_df.columns:
                    filtered_df = filtered_df[filtered_df['Department'].isin(sel_depts_filt)]

                # Apply MRN filter (case-insensitive contains)
                if mrn_s_filt and 'MRN' in filtered_df.columns:
                     filtered_df = filtered_df[filtered_df['MRN'].astype(str).str.contains(mrn_s_filt, case=False, na=False)]

                # Apply Item filter (case-insensitive contains)
                if item_s_filt and 'Item' in filtered_df.columns:
                     filtered_df = filtered_df[filtered_df['Item'].astype(str).str.contains(item_s_filt, case=False, na=False)]

            except Exception as filter_e:
                st.error(f"Error applying filters: {filter_e}")
                # Optionally display full log if filtering fails, or keep showing previous filtered view
                # filtered_df = log_df.copy() # Uncomment to show full log on filter error

        # --- Display Section ---
        st.divider()
        st.write(f"Displaying {len(filtered_df)} matching records:")
        # Display the filtered data in a formatted table
        st.dataframe(
            filtered_df,
            use_container_width=True,
            hide_index=True,
            column_config={ # Define how columns should be displayed
                "Date Required": st.column_config.DatetimeColumn("Date Reqd.", format="DD-MM-YYYY"),
                "Timestamp": st.column_config.DatetimeColumn("Submitted On", format="YYYY-MM-DD HH:mm"),
                "Qty": st.column_config.NumberColumn("Quantity", format="%d"),
                "MRN": st.column_config.TextColumn("MRN"),
                "Department": st.column_config.TextColumn("Dept."),
                "Item": st.column_config.TextColumn("Item Name", width="medium"), # Adjust width
                "Unit": st.column_config.TextColumn("Unit"),
                "Note": st.column_config.TextColumn("Notes", width="medium"), # Adjust width
            }
        )
    else:
        # Message if no log data is found or loaded
        st.info("No indent records found or unable to load data.")

# --- Optional Full State Debug ---
# Uncomment below to show the session state in the sidebar for debugging
# with st.sidebar:
#     st.write("### Session State Debug")
#     st.json(st.session_state.to_dict())
