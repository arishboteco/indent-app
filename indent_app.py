import streamlit as st
import pandas as pd
import gspread
from gspread import Client, Spreadsheet, Worksheet
from fpdf import FPDF
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
from PIL import Image
from collections import Counter
from typing import Any, Dict, List, Tuple, Optional
import time # For generating unique IDs

# --- Configuration & Setup ---

# Display logo
try:
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
def connect_gsheets():
    """Connects to Google Sheets and returns client, log sheet, and reference sheet."""
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("Missing GCP credentials in st.secrets!")
            return None, None, None
        json_creds_data: Any = st.secrets["gcp_service_account"]
        creds_dict: Dict[str, Any] = json.loads(json_creds_data) if isinstance(json_creds_data, str) else json_creds_data
        creds: ServiceAccountCredentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client: Client = gspread.authorize(creds)
        # Access worksheets with detailed error handling
        try:
            indent_log_spreadsheet: Spreadsheet = client.open("Indent Log")
            log_sheet: Worksheet = indent_log_spreadsheet.sheet1 # Log Sheet
            reference_sheet: Worksheet = indent_log_spreadsheet.worksheet("reference") # Item Reference Sheet
            return client, log_sheet, reference_sheet
        except gspread.exceptions.SpreadsheetNotFound: st.error("Spreadsheet 'Indent Log' not found."); return None, None, None
        except gspread.exceptions.WorksheetNotFound: st.error("Worksheet 'Sheet1' or 'reference' not found."); return None, None, None
        except gspread.exceptions.APIError as e: st.error(f"Google API Error accessing sheets: {e}"); return None, None, None
    except json.JSONDecodeError: st.error("Error parsing GCP credentials."); return None, None, None
    except gspread.exceptions.RequestError as e: st.error(f"Network error connecting to Google: {e}"); return None, None, None
    except Exception as e: st.error(f"Google Sheets setup error: {e}"); st.exception(e); return None, None, None

client, log_sheet, reference_sheet = connect_gsheets()

if not client or not log_sheet or not reference_sheet:
    st.error("Failed to connect to Google Sheets. Cannot proceed.")
    st.stop() # Halt execution if connection failed

# --- Reference Data Loading Function (CACHED) ---
@st.cache_data(ttl=3600) # Cache reference data for 1 hour
def get_reference_data(_reference_sheet: Worksheet) -> Tuple[List[str], Dict[str, str]]:
    """Fetches and processes reference data from the 'reference' worksheet."""
    st.info("Fetching item reference data...") # Show info when cache misses
    try:
        all_data: List[List[str]] = _reference_sheet.get_all_values()
        item_names: List[str] = []
        item_to_unit_lower: Dict[str, str] = {}
        processed_items_lower: set[str] = set()
        header_skipped: bool = False
        for i, row in enumerate(all_data):
            if not any(str(cell).strip() for cell in row): continue # Skip empty rows
            # Basic header detection
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower() or "unit" in str(row[1]).lower()):
                header_skipped = True
                continue
            if len(row) >= 2:
                item: str = str(row[0]).strip()
                unit: str = str(row[1]).strip()
                item_lower: str = item.lower()
                if item and item_lower not in processed_items_lower:
                    item_names.append(item)
                    item_to_unit_lower[item_lower] = unit if unit else "N/A" # Default unit
                    processed_items_lower.add(item_lower)
        item_names.sort()
        return item_names, item_to_unit_lower
    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error loading reference data: {e}")
        return [], {}
    except Exception as e:
        st.error(f"Unexpected error loading reference data: {e}")
        return [], {}

# --- Load Reference Data into State ---
if 'master_item_list' not in st.session_state or 'item_to_unit_lower' not in st.session_state:
    loaded_item_names, loaded_item_to_unit_lower = get_reference_data(reference_sheet)
    st.session_state['master_item_list'] = loaded_item_names
    st.session_state['item_to_unit_lower'] = loaded_item_to_unit_lower

master_item_names = st.session_state.get('master_item_list', [])
item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})

if not master_item_names:
    st.error("Item list from 'reference' sheet is empty or could not be loaded. Cannot create indents.")
    # Optionally allow viewing past indents even if reference fails
    # st.stop() # Or stop completely


# --- MRN Generation ---
def generate_mrn() -> str:
    """Generates the next MRN based on the log sheet."""
    try:
        all_mrns = log_sheet.col_values(1) # Assuming MRN is in the first column
        next_number = 1
        if len(all_mrns) > 1: # Header + existing MRNs
            last_valid_num = 0
            # Iterate backwards to find the last valid numeric MRN
            for mrn_str in reversed(all_mrns):
                if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit():
                    last_valid_num = int(mrn_str[4:])
                    break
            # Fallback if no valid MRN-xxx found (e.g., sheet only has header or junk)
            if last_valid_num == 0:
                 # Count non-empty cells excluding header as a rough estimate
                 non_empty_count = sum(1 for v in all_mrns if v)
                 last_valid_num = max(0, non_empty_count - 1) # Assume sequential if no format match

            next_number = last_valid_num + 1
        return f"MRN-{str(next_number).zfill(3)}"
    except gspread.exceptions.APIError as e:
        st.error(f"API Error generating MRN: {e}")
        return f"MRN-ERR-{datetime.now().strftime('%H%M%S')}" # Include seconds for uniqueness
    except Exception as e:
        st.error(f"Error generating MRN: {e}")
        return f"MRN-ERR-{datetime.now().strftime('%H%M%S')}"

# --- PDF Generation Function ---
def create_indent_pdf(data: Dict[str, Any]) -> bytes:
    """Creates a PDF document for the indent request."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Material Indent Request", ln=True, align='C')
    pdf.ln(10)

    # Basic Info
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(95, 7, f"MRN: {data['mrn']}", ln=0)
    pdf.cell(95, 7, f"Date Required: {data['date']}", ln=1, align='R')
    pdf.cell(0, 7, f"Department: {data['dept']}", ln=1)
    pdf.ln(7)

    # Table Header
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 230, 230)
    col_widths = {'item': 90, 'qty': 15, 'unit': 25, 'note': 60} # Adjust widths as needed
    pdf.cell(col_widths['item'], 7, "Item", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['qty'], 7, "Qty", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['unit'], 7, "Unit", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['note'], 7, "Note", border=1, ln=1, align='C', fill=True)

    # Table Rows (with multi-cell handling for wrapping)
    pdf.set_font("Helvetica", "", 9)
    line_height = 6 # Adjust line height
    for item_data in data['items']:
        item, qty, unit, note = item_data # Unpack the tuple

        start_y = pdf.get_y()
        current_x = pdf.l_margin

        # Use multi_cell for potentially long item names and notes
        pdf.multi_cell(col_widths['item'], line_height, str(item), border='LR', align='L', ln=3)
        item_end_y = pdf.get_y()
        pdf.set_xy(current_x + col_widths['item'], start_y) # Move to Qty column

        pdf.cell(col_widths['qty'], line_height, str(qty), border='R', align='C', ln=3)
        qty_end_y = pdf.get_y()
        pdf.set_xy(current_x + col_widths['item'] + col_widths['qty'], start_y) # Move to Unit column

        pdf.cell(col_widths['unit'], line_height, str(unit), border='R', align='C', ln=3)
        unit_end_y = pdf.get_y()
        pdf.set_xy(current_x + col_widths['item'] + col_widths['qty'] + col_widths['unit'], start_y) # Move to Note column

        pdf.multi_cell(col_widths['note'], line_height, str(note if note else "-"), border='R', align='L', ln=3)
        note_end_y = pdf.get_y()

        # Determine max height of the row and draw bottom border
        max_y = max(item_end_y, qty_end_y, unit_end_y, note_end_y)
        pdf.line(pdf.l_margin, max_y, pdf.l_margin + sum(col_widths.values()), max_y) # Draw bottom border
        pdf.set_y(max_y) # Move cursor below the drawn line
        pdf.ln(0.1) # Small gap before next row

    # Output the PDF as bytes
    return pdf.output(dest='S').encode('latin-1') # Use 'S' for string output, then encode

# --- Function to Load and Clean Log Data (Cached) ---
@st.cache_data(ttl=60) # Cache log data for 1 minute
def load_indent_log_data() -> pd.DataFrame:
    """Loads and cleans data from the main indent log sheet."""
    try:
        records = log_sheet.get_all_records()
        if not records:
            # Return empty DataFrame with expected columns if sheet is empty
            expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
            return pd.DataFrame(columns=expected_cols)

        df = pd.DataFrame(records)

        # Define expected columns - adjust if your sheet headers are different
        expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']

        # Ensure essential columns exist, fill with NA if missing
        for col in expected_cols:
            if col not in df.columns:
                df[col] = pd.NA
                st.warning(f"Log sheet missing expected column: '{col}'. Added as empty.")

        # Convert data types with error handling
        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        if 'Date Required' in df.columns:
             # Try multiple formats if necessary, be specific if possible
             df['Date Required'] = pd.to_datetime(df['Date Required'], format='%d-%m-%Y', errors='coerce')
        if 'Qty' in df.columns:
            df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0).astype(int) # Coerce errors to NaN, fill with 0, convert to int

        # Select and potentially reorder columns for consistency
        # df = df[expected_cols] # Uncomment to enforce column order

        return df.sort_values(by='Timestamp', ascending=False) # Default sort by newest first

    except gspread.exceptions.APIError as e:
        st.error(f"API Error loading indent log: {e}")
        return pd.DataFrame() # Return empty DataFrame on error
    except Exception as e:
        st.error(f"Error loading/cleaning indent log: {e}")
        return pd.DataFrame()

# --- --- --- --- --- --- --- ---

# --- UI divided into Tabs ---
tab1, tab2 = st.tabs(["📝 New Indent", "📊 View Indents"])

# --- TAB 1: New Indent Form ---
with tab1:
    # --- Session State Initialization (Using List of Dicts) ---
    if "form_items" not in st.session_state:
        # Initialize with one empty item row
        st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-'}]
    if "item_id_counter" not in st.session_state:
         st.session_state.item_id_counter = 0 # Simple counter for unique keys if needed

    if 'last_dept' not in st.session_state:
        st.session_state.last_dept = None
    if 'submitted_data_for_summary' not in st.session_state:
         st.session_state.submitted_data_for_summary = None


    # --- Helper Functions for Item Row Management ---
    def add_item():
        new_id = f"item_{time.time_ns()}" # Use nanoseconds for higher chance of uniqueness
        st.session_state.form_items.append({'id': new_id, 'item': None, 'qty': 1, 'note': '', 'unit': '-'})

    def remove_item(item_id_to_remove):
        st.session_state.form_items = [item for item in st.session_state.form_items if item['id'] != item_id_to_remove]
        # Ensure at least one row remains
        if not st.session_state.form_items:
             add_item() # Add a blank row if the list becomes empty

    def clear_all_items():
        st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-'}]
        # Optionally reset department and date here if desired
        # st.session_state.selected_dept = "" # Reset dept?
        # st.session_state.selected_date = date.today() # Reset date?


    def update_unit_display(item_id):
        """Callback to update the unit when an item is selected."""
        for item_dict in st.session_state.form_items:
            if item_dict['id'] == item_id:
                selected_item_name = item_dict.get('item')
                if selected_item_name:
                    unit = item_to_unit_lower.get(selected_item_name.lower(), "N/A")
                    item_dict['unit'] = unit if unit else "-"
                else:
                    item_dict['unit'] = "-"
                break # Found the item, exit loop

    # --- Header Inputs ---
    DEPARTMENTS = ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"] # Keep "" as first option for placeholder
    last_dept = st.session_state.get('last_dept')
    dept_index = 0
    if last_dept and last_dept in DEPARTMENTS:
        try:
            dept_index = DEPARTMENTS.index(last_dept)
        except ValueError:
            dept_index = 0 # Default to placeholder if last_dept is somehow invalid

    dept = st.selectbox(
        "Select Department*",
        DEPARTMENTS,
        index=dept_index,
        key="selected_dept",
        help="Select the department requesting materials."
    )
    delivery_date = st.date_input(
        "Date Required*",
        value=date.today(),
        min_value=date.today(),
        format="DD/MM/YYYY",
        key="selected_date",
        help="Select the date materials are needed."
    )

    st.divider() # Use divider
    st.subheader("Enter Items:")

    # --- Item Input Rows (Looping through list in state) ---
    for i, item_dict in enumerate(st.session_state.form_items):
        item_id = item_dict['id']
        item_label = item_dict.get('item') or f"Item #{i+1}" # Use item name or number

        with st.expander(label=f"{item_label} (Qty: {item_dict.get('qty', 1)})", expanded=True):
            col1, col2, col3, col4 = st.columns([4, 2, 1, 1]) # Adjust ratios as needed

            with col1:
                # Item Selection - Update item in the dictionary directly
                st.session_state.form_items[i]['item'] = st.selectbox(
                    label="Item Select",
                    options=[""] + master_item_names, # Add blank option for easy clearing/unselecting
                    key=f"item_select_{item_id}", # Unique key using item_id
                    index= (master_item_names.index(item_dict['item']) + 1) if item_dict.get('item') in master_item_names else 0,
                    placeholder="Type or select an item...",
                    label_visibility="collapsed",
                    on_change=update_unit_display, args=(item_id,) # Pass item_id to callback
                 )

            with col2:
                # Note Input - Update note in the dictionary
                st.session_state.form_items[i]['note'] = st.text_input(
                    f"Note",
                    key=f"note_{item_id}",
                    value=item_dict.get('note', ''),
                    placeholder="Optional note...",
                    label_visibility="collapsed"
                )

            with col3:
                 # Quantity Input - Update qty in the dictionary
                 st.session_state.form_items[i]['qty'] = st.number_input(
                     f"Quantity",
                     min_value=1,
                     step=1,
                     key=f"qty_{item_id}",
                     value=item_dict.get('qty', 1),
                     label_visibility="collapsed"
                 )

            with col4:
                 # Display Unit & Remove Button
                 st.markdown("**Unit:**")
                 unit_to_display = item_dict.get('unit', '-')
                 st.markdown(f"##### {unit_to_display}") # Dynamic Unit Display
                 if len(st.session_state.form_items) > 1: # Show remove button only if more than one item
                     st.button("❌", key=f"remove_{item_id}", on_click=remove_item, args=(item_id,), help="Remove this item")


    st.divider() # Use divider

    # --- Add/Clear Buttons ---
    col1_btn, col2_btn = st.columns(2)
    with col1_btn:
        st.button("➕ Add Another Item", on_click=add_item, use_container_width=True, key="add_item_button")
    with col2_btn:
        st.button("🔄 Clear All Items", on_click=clear_all_items, use_container_width=True, key="clear_items_button")


    # --- Validation Checks (Before Submit Button) ---
    items_for_validation = [item['item'] for item in st.session_state.form_items if item.get('item')]
    item_counts = Counter(items_for_validation)
    duplicates_found = {item: count for item, count in item_counts.items() if count > 1}
    has_duplicates = bool(duplicates_found)
    has_valid_items = any(item.get('item') and item.get('qty', 0) > 0 for item in st.session_state.form_items)
    current_dept_tab1 = st.session_state.get("selected_dept", "")

    submit_disabled = not has_valid_items or has_duplicates or not current_dept_tab1
    error_messages = []
    tooltip_message = "Submit the current indent request."

    if not has_valid_items: error_messages.append("At least one item must be selected with quantity > 0.")
    if has_duplicates:
        dup_list_str = ", ".join(duplicates_found.keys())
        error_messages.append(f"Duplicate items detected: {dup_list_str}.")
    if not current_dept_tab1: error_messages.append("Department must be selected.")

    st.divider() # Use divider

    # Display Validation Errors Clearly
    if error_messages:
        for msg in error_messages:
            st.warning(f"⚠️ {msg}")
        tooltip_message = "Please fix the issues listed above before submitting."


    # --- Final Submission Button ---
    if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message, key="submit_indent_button"):

        # Re-validate just before submission (belt-and-suspenders)
        final_items_to_submit: List[Tuple] = []
        final_item_names = set()
        final_has_duplicates = False

        for item_dict in st.session_state.form_items:
            selected_item = item_dict.get('item')
            qty = item_dict.get('qty', 0)
            note = item_dict.get('note', '')
            unit = item_dict.get('unit', 'N/A') # Get the unit stored in the dict

            if selected_item and qty > 0:
                if selected_item in final_item_names:
                    final_has_duplicates = True
                    st.error(f"Duplicate item '{selected_item}' found during final check. Please remove duplicates.")
                    break # Stop processing on first duplicate found
                final_item_names.add(selected_item)
                final_items_to_submit.append((selected_item, qty, unit, note))

        if final_has_duplicates:
            st.stop() # Abort submission if duplicates somehow got through

        if not final_items_to_submit:
            st.error("No valid items to submit. Please add at least one item with a quantity greater than 0.")
            st.stop()

        # Proceed with submission if validation passes
        try:
            mrn = generate_mrn()
            if "ERR" in mrn: # Check if MRN generation failed
                 st.error(f"Failed to generate MRN. Cannot submit indent. Error: {mrn}")
                 st.stop()

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            current_date_obj = st.session_state.get("selected_date", date.today())
            formatted_date = current_date_obj.strftime("%d-%m-%Y") # DD-MM-YYYY format

            # Prepare rows for Google Sheet
            rows_to_add = [
                [mrn, timestamp, current_dept_tab1, formatted_date, item, str(qty), unit, note if note else "N/A"]
                for item, qty, unit, note in final_items_to_submit
            ]

            if rows_to_add:
                with st.spinner(f"Submitting indent {mrn}..."):
                    try:
                        log_sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
                        # Clear cache for log data so the new entry appears in Tab 2
                        load_indent_log_data.clear()
                    except gspread.exceptions.APIError as api_error:
                        st.error(f"API Error submitting to Google Sheets: {api_error}. Please try again.")
                        st.stop()
                    except Exception as submit_e:
                         st.error(f"An unexpected error occurred during submission: {submit_e}")
                         st.exception(submit_e)
                         st.stop()

                # Store submitted data for summary display
                st.session_state['submitted_data_for_summary'] = {
                    'mrn': mrn,
                    'dept': current_dept_tab1,
                    'date': formatted_date,
                    'items': final_items_to_submit # Already includes unit
                }
                st.session_state['last_dept'] = current_dept_tab1 # Remember department

                # --- Cleanup session state for the form ---
                clear_all_items() # Reset item list
                # Keep last_dept, clear submitted_data after displaying it
                # st.session_state.selected_dept = "" # Optionally reset dept selection
                # st.session_state.selected_date = date.today() # Optionally reset date

                st.rerun() # Rerun to show the summary section

        except Exception as e:
            st.error(f"Error during submission process: {e}")
            st.exception(e)


    # --- Display Post-Submission Summary (if data exists) ---
    if st.session_state.get('submitted_data_for_summary'):
        submitted_data = st.session_state['submitted_data_for_summary']

        st.success(f"Indent submitted successfully! MRN: {submitted_data['mrn']}")
        st.balloons()
        st.divider()
        st.subheader("Submitted Indent Summary")

        st.info(f"**MRN:** {submitted_data['mrn']} | **Department:** {submitted_data['dept']} | **Date Required:** {submitted_data['date']}")

        # Create DataFrame from the submitted items list (which are tuples)
        submitted_df = pd.DataFrame(submitted_data['items'], columns=["Item", "Qty", "Unit", "Note"])
        st.dataframe(submitted_df, hide_index=True, use_container_width=True)

        total_submitted_qty = sum(item[1] for item in submitted_data['items']) # item[1] is quantity
        st.markdown(f"**Total Submitted Quantity:** {total_submitted_qty}")
        st.divider()

        # PDF Generation and Download Button
        try:
            pdf_output: bytes = create_indent_pdf(submitted_data)
            st.download_button(
                label="📄 Download Indent PDF",
                data=pdf_output, # Should be bytes
                file_name=f"Indent_{submitted_data['mrn']}.pdf",
                mime="application/pdf",
                key='pdf_download_button'
            )
        except Exception as pdf_error:
            st.error(f"Could not generate PDF: {pdf_error}")
            st.exception(pdf_error)

        # Button to clear the summary and start a new indent
        if st.button("Start New Indent", key='new_indent_button'):
            del st.session_state['submitted_data_for_summary'] # Clear the summary flag
            st.rerun()


# --- TAB 2: View Indents ---
with tab2:
    st.subheader("View Past Indent Requests")

    # Load data with spinner
    with st.spinner("Fetching indent records..."):
        log_df = load_indent_log_data() # Function now includes cleaning and sorting

    # --- Filtering Widgets ---
    if not log_df.empty:
        st.divider()
        with st.expander("Filter Options", expanded=True):
            # Use available data for sensible filter defaults
            dept_options = sorted([d for d in log_df['Department'].unique() if d])
            min_date_log = date.today() - pd.Timedelta(days=30) # Default fallback: last 30 days
            max_date_log = date.today()

            # Try to get min/max from actual data
            if 'Date Required' in log_df.columns and not log_df['Date Required'].isnull().all():
                min_dt_val = log_df['Date Required'].dropna().min()
                max_dt_val = log_df['Date Required'].dropna().max()
                if pd.notna(min_dt_val): min_date_log = min_dt_val.date()
                if pd.notna(max_dt_val): max_date_log = max_dt_val.date()
                # Ensure min_date is not after max_date
                if min_date_log > max_date_log: min_date_log = max_date_log


            filt_col1, filt_col2, filt_col3 = st.columns([1, 1, 2])
            with filt_col1:
                filt_start_date = st.date_input("Reqd. From", value=min_date_log, min_value=min_date_log, max_value=max_date_log, key="filt_start")
                # Ensure end date is not before start date
                valid_end_date = max(filt_start_date, max_date_log) if filt_start_date <= max_date_log else filt_start_date
                filt_end_date = st.date_input("Reqd. To", value=valid_end_date, min_value=filt_start_date, max_value=max_date_log, key="filt_end")

            with filt_col2:
                selected_depts = st.multiselect("Filter by Department", options=dept_options, default=[], key="filt_dept")
                mrn_search = st.text_input("Search by MRN", key="filt_mrn", placeholder="e.g., MRN-005")

            with filt_col3:
                item_search = st.text_input("Search by Item Name", key="filt_item", placeholder="e.g., Salt")

        # --- Apply Filters ---
        filtered_df = log_df.copy()
        try:
            # Date Range Filter (handle NaT safely)
            if 'Date Required' in filtered_df.columns:
                 start_ts = pd.Timestamp(filt_start_date)
                 end_ts = pd.Timestamp(filt_end_date)
                 # Ensure comparison works with potential NaT values
                 date_filt_condition = (
                     filtered_df['Date Required'].notna() &
                     (filtered_df['Date Required'].dt.normalize() >= start_ts) &
                     (filtered_df['Date Required'].dt.normalize() <= end_ts)
                 )
                 filtered_df = filtered_df[date_filt_condition]

            # Department Filter
            if selected_depts and 'Department' in filtered_df.columns:
                filtered_df = filtered_df[filtered_df['Department'].isin(selected_depts)]

            # MRN Filter (case-insensitive text search)
            if mrn_search and 'MRN' in filtered_df.columns:
                filtered_df = filtered_df[filtered_df['MRN'].astype(str).str.contains(mrn_search, case=False, na=False)]

            # Item Filter (case-insensitive text search)
            if item_search and 'Item' in filtered_df.columns:
                filtered_df = filtered_df[filtered_df['Item'].astype(str).str.contains(item_search, case=False, na=False)]

        except Exception as filter_e:
            st.error(f"Error applying filters: {filter_e}")
            filtered_df = log_df.copy() # Reset to unfiltered on error

        # --- Display Section ---
        st.divider()
        st.write(f"Displaying {len(filtered_df)} matching records (sorted by newest submission first):")
        st.dataframe(
            filtered_df,
            use_container_width=True,
            hide_index=True,
            column_config={ # Use column_config for better formatting
                "Date Required": st.column_config.DateColumn("Date Reqd.", format="DD-MM-YYYY"),
                "Timestamp": st.column_config.DatetimeColumn("Submitted On", format="YYYY-MM-DD HH:mm"),
                "Qty": st.column_config.NumberColumn("Quantity", format="%d"),
                "MRN": st.column_config.TextColumn("MRN"),
                "Department": st.column_config.TextColumn("Dept."),
                "Item": st.column_config.TextColumn("Item Name", width="medium"), # Adjust width
                "Unit": st.column_config.TextColumn("Unit"),
                "Note": st.column_config.TextColumn("Notes", width="large"), # Adjust width
            },
            # Set default sort (already done in load function, but can reinforce here)
            # column_order = [...] # Optionally enforce column display order
        )
    else:
        st.info("No indent records found or unable to load data. Submit a new indent using the 'New Indent' tab.")

# --- Optional Full State Debug (Uncomment for troubleshooting) ---
# st.sidebar.write("### Session State Debug")
# st.sidebar.json(st.session_state.to_dict())
