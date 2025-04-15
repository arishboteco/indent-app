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
@st.cache_resource(show_spinner="Connecting to Google Sheets...") # Cache the connection resources
def connect_gsheets():
    """Connects to Google Sheets and returns client, log sheet, and reference sheet."""
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("Missing GCP credentials in st.secrets!")
            return None, None, None
        json_creds_data: Any = st.secrets["gcp_service_account"]
        # Ensure json_creds_data is a dict
        if isinstance(json_creds_data, str):
            try:
                creds_dict: Dict[str, Any] = json.loads(json_creds_data)
            except json.JSONDecodeError:
                st.error("Error parsing GCP credentials string.")
                return None, None, None
        elif isinstance(json_creds_data, dict):
             creds_dict = json_creds_data
        else:
             st.error("GCP credentials in secrets are not in a recognizable format (string or dict).")
             return None, None, None

        creds: ServiceAccountCredentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client: Client = gspread.authorize(creds)
        # Access worksheets with detailed error handling
        try:
            indent_log_spreadsheet: Spreadsheet = client.open("Indent Log")
            log_sheet: Worksheet = indent_log_spreadsheet.sheet1 # Log Sheet
            reference_sheet: Worksheet = indent_log_spreadsheet.worksheet("reference") # Item Reference Sheet
            return client, log_sheet, reference_sheet
        except gspread.exceptions.SpreadsheetNotFound: st.error("Spreadsheet 'Indent Log' not found."); return None, None, None
        except gspread.exceptions.WorksheetNotFound: st.error("Worksheet 'Sheet1' or 'reference' not found in 'Indent Log'."); return None, None, None
        except gspread.exceptions.APIError as e: st.error(f"Google API Error accessing sheets: {e}"); return None, None, None
    except json.JSONDecodeError: st.error("Error parsing GCP credentials during ServiceAccountCredentials creation."); return None, None, None # Should be caught earlier now
    except gspread.exceptions.RequestError as e: st.error(f"Network error connecting to Google: {e}"); return None, None, None
    except Exception as e: st.error(f"An unexpected error occurred during Google Sheets setup: {e}"); st.exception(e); return None, None, None

client, log_sheet, reference_sheet = connect_gsheets()

if not client or not log_sheet or not reference_sheet:
    st.error("Failed to initialize Google Sheets connection. Cannot proceed.")
    st.stop() # Halt execution if connection failed

# --- Reference Data Loading Function (CACHED) ---
@st.cache_data(ttl=3600, show_spinner="Fetching item reference data...") # Cache reference data for 1 hour
def get_reference_data(_reference_sheet: Worksheet) -> Tuple[List[str], Dict[str, str]]:
    """Fetches and processes reference data from the 'reference' worksheet."""
    try:
        all_data: List[List[str]] = _reference_sheet.get_all_values()
        item_names: List[str] = [""] # Start with blank option
        item_to_unit_lower: Dict[str, str] = {}
        processed_items_lower: set[str] = set()
        header_skipped: bool = False
        for i, row in enumerate(all_data):
            if not any(str(cell).strip() for cell in row): continue # Skip empty rows
            # Basic header detection (assuming 'item' or 'name' in first col, 'unit' in second)
            if not header_skipped and i == 0 and (("item" in str(row[0]).lower() or "name" in str(row[0]).lower()) and "unit" in str(row[1]).lower()):
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
        # item_names.sort() # Keep blank at top, sort rest? Or sort all? Let's sort all except blank
        other_items = sorted([name for name in item_names if name])
        item_names = [""] + other_items
        return item_names, item_to_unit_lower
    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error loading reference data: {e}")
        return [""], {}
    except Exception as e:
        st.error(f"Unexpected error loading reference data: {e}")
        return [""], {}

# --- Load Reference Data into State ---
# Use function scope for sheets to ensure they are valid
if reference_sheet:
     master_item_names, item_to_unit_lower = get_reference_data(reference_sheet)
     st.session_state['master_item_list'] = master_item_names
     st.session_state['item_to_unit_lower'] = item_to_unit_lower
else:
     st.session_state['master_item_list'] = [""]
     st.session_state['item_to_unit_lower'] = {}

master_item_names = st.session_state.get('master_item_list', [""])
item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})

if len(master_item_names) <= 1: # Only contains the blank option
    st.error("Item list from 'reference' sheet is empty or could not be loaded. Cannot create indents.")
    # st.stop() # Decide if app should stop completely

# --- MRN Generation ---
def generate_mrn() -> str:
    """Generates the next MRN based on the log sheet."""
    if not log_sheet: return f"MRN-ERR-NOSHEET"
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
            # Fallback if no valid MRN-xxx found
            if last_valid_num == 0:
                 non_empty_count = sum(1 for v in all_mrns if v)
                 last_valid_num = max(0, non_empty_count - 1)
            next_number = last_valid_num + 1
        return f"MRN-{str(next_number).zfill(3)}"
    except gspread.exceptions.APIError as e:
        st.error(f"API Error generating MRN: {e}")
        return f"MRN-ERR-API-{datetime.now().strftime('%H%M%S')}"
    except Exception as e:
        st.error(f"Error generating MRN: {e}")
        return f"MRN-ERR-EXC-{datetime.now().strftime('%H%M%S')}"

# --- PDF Generation Function ---
# (Keep the PDF function as it was in the previous working version, assuming it was okay)
def create_indent_pdf(data: Dict[str, Any]) -> bytes:
    """Creates a PDF document for the indent request."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", "B", 16); pdf.cell(0, 10, "Material Indent Request", ln=True, align='C'); pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(95, 7, f"MRN: {data['mrn']}", ln=0); pdf.cell(95, 7, f"Date Required: {data['date']}", ln=1, align='R')
    pdf.cell(0, 7, f"Department: {data['dept']}", ln=1); pdf.ln(7)
    pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(230, 230, 230)
    col_widths = {'item': 90, 'qty': 15, 'unit': 25, 'note': 60}
    pdf.cell(col_widths['item'], 7, "Item", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['qty'], 7, "Qty", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['unit'], 7, "Unit", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['note'], 7, "Note", border=1, ln=1, align='C', fill=True)
    pdf.set_font("Helvetica", "", 9); line_height = 6
    for item_tuple in data['items']: # Iterate through the list of tuples
        item, qty, unit, note = item_tuple # Unpack tuple
        start_y = pdf.get_y(); current_x = pdf.l_margin
        # MultiCell Item
        pdf.multi_cell(col_widths['item'], line_height, str(item), border='LR', align='L', ln=3); item_y = pdf.get_y()
        current_x += col_widths['item']; pdf.set_xy(current_x, start_y)
        # Cell Qty
        pdf.cell(col_widths['qty'], line_height, str(qty), border='R', ln=3, align='C'); qty_y = pdf.get_y() # Use ln=3 and get_y after cell
        current_x += col_widths['qty']; pdf.set_xy(current_x, start_y)
        # Cell Unit
        pdf.cell(col_widths['unit'], line_height, str(unit), border='R', ln=3, align='C'); unit_y = pdf.get_y()
        current_x += col_widths['unit']; pdf.set_xy(current_x, start_y)
        # MultiCell Note
        pdf.multi_cell(col_widths['note'], line_height, str(note if note else "-"), border='R', align='L', ln=3); note_y = pdf.get_y()
        # Determine max height and draw bottom line
        max_y = max(item_y, start_y + line_height) # Use start_y + line_height as min height for cells
        # We need to recalculate max_y considering all cells' potential wrapping
        # A simpler approach (might leave gaps if only one item wraps significantly):
        pdf.set_xy(pdf.l_margin, start_y) # Reset X position
        height1 = pdf.get_string_width(str(item)) / col_widths['item'] * line_height # Rough height estimate
        height4 = pdf.get_string_width(str(note if note else "-")) / col_widths['note'] * line_height
        actual_row_height = max(line_height, height1, height4) # Use max estimated height
        pdf.multi_cell(col_widths['item'], line_height, str(item), border='LR', align='L')
        pdf.set_xy(pdf.l_margin + col_widths['item'], start_y)
        pdf.multi_cell(col_widths['qty'], line_height, str(qty), border='R', align='C')
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['qty'], start_y)
        pdf.multi_cell(col_widths['unit'], line_height, str(unit), border='R', align='C')
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['qty'] + col_widths['unit'], start_y)
        pdf.multi_cell(col_widths['note'], line_height, str(note if note else "-"), border='R', align='L')
        # Use the multi_cell's final Y position for the line
        final_y = pdf.get_y()
        pdf.line(pdf.l_margin, final_y, pdf.l_margin + sum(col_widths.values()), final_y)
        pdf.set_y(final_y); pdf.ln(0.1)
    return pdf.output(dest='S').encode('latin-1')

# --- Function to Load and Clean Log Data (Cached) ---
@st.cache_data(ttl=60, show_spinner="Loading indent history...") # Cache log data for 1 minute
def load_indent_log_data() -> pd.DataFrame:
    """Loads and cleans data from the main indent log sheet."""
    if not log_sheet: return pd.DataFrame() # Return empty if no sheet connection
    try:
        records = log_sheet.get_all_records()
        if not records:
            expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
            return pd.DataFrame(columns=expected_cols)
        df = pd.DataFrame(records)
        expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
        for col in expected_cols:
            if col not in df.columns:
                df[col] = pd.NA
                # st.warning(f"Log sheet missing expected column: '{col}'. Added as empty.") # Less verbose
        if 'Timestamp' in df.columns: df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        if 'Date Required' in df.columns: df['Date Required'] = pd.to_datetime(df['Date Required'], format='%d-%m-%Y', errors='coerce')
        if 'Qty' in df.columns: df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0).astype(int)
        # Fill NA in object columns (like Item, Unit, Note) with empty string for display
        for col in ['Item', 'Unit', 'Note', 'MRN', 'Department']:
             if col in df.columns:
                 df[col] = df[col].fillna('')

        return df.sort_values(by='Timestamp', ascending=False, na_position='last') # Sort newest first, handle NA
    except gspread.exceptions.APIError as e: st.error(f"API Error loading indent log: {e}"); return pd.DataFrame()
    except Exception as e: st.error(f"Error loading/cleaning indent log: {e}"); return pd.DataFrame()

# --- --- --- --- --- --- --- ---

# --- UI divided into Tabs ---
tab1, tab2 = st.tabs(["📝 New Indent", "📊 View Indents"])

# --- TAB 1: New Indent Form ---
with tab1:
    # --- Session State Initialization ---
    if "form_items" not in st.session_state:
        st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-'}]
    # Removed item_id_counter as time_ns should be sufficient for keys
    if 'last_dept' not in st.session_state: st.session_state.last_dept = None
    if 'submitted_data_for_summary' not in st.session_state: st.session_state.submitted_data_for_summary = None

    # --- Helper Functions for Item Row Management ---
    def add_item():
        new_id = f"item_{time.time_ns()}"
        st.session_state.form_items.append({'id': new_id, 'item': None, 'qty': 1, 'note': '', 'unit': '-'})

    def remove_item(item_id_to_remove):
        st.session_state.form_items = [item for item in st.session_state.form_items if item['id'] != item_id_to_remove]
        if not st.session_state.form_items: add_item() # Ensure at least one row remains

    def clear_all_items():
        st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-'}]
        # Resetting header inputs can be done here or left as is based on preference
        # st.session_state.selected_dept = ""
        # st.session_state.selected_date = date.today()

    # --- *** CORRECTED Callback Function *** ---
    def update_unit_display_and_item_value(item_id, selectbox_key):
        """Callback to update unit AND the item value in the state dict."""
        selected_item_name = st.session_state[selectbox_key] # *** Read value from the widget's state ***
        unit = "-" # Default unit
        if selected_item_name:
            unit = item_to_unit_lower.get(selected_item_name.lower(), "N/A") # Lookup unit
            unit = unit if unit else "-" # Ensure '-' if lookup returns None or empty

        # Find the correct dictionary in the list and update it
        for i, item_dict in enumerate(st.session_state.form_items):
            if item_dict['id'] == item_id:
                # *** Update both item and unit in the dictionary ***
                st.session_state.form_items[i]['item'] = selected_item_name if selected_item_name else None
                st.session_state.form_items[i]['unit'] = unit
                break # Found the item, exit loop

    # --- Header Inputs ---
    DEPARTMENTS = ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"]
    last_dept = st.session_state.get('last_dept')
    dept_index = 0
    try:
        # Use get() for selected_dept as it might not exist on first run after clearing
        current_selection = st.session_state.get("selected_dept", last_dept)
        if current_selection and current_selection in DEPARTMENTS:
             dept_index = DEPARTMENTS.index(current_selection)
    except ValueError: dept_index = 0

    dept = st.selectbox( "Select Department*", DEPARTMENTS, index=dept_index, key="selected_dept", help="Select the requesting department.")
    delivery_date = st.date_input( "Date Required*", value=st.session_state.get("selected_date", date.today()), min_value=date.today(), format="DD/MM/YYYY", key="selected_date", help="Select the date materials are needed.")

    st.divider()
    st.subheader("Enter Items:")

    # --- Item Input Rows ---
    # Create a copy to iterate over while allowing mutation via remove button
    items_to_render = list(st.session_state.form_items)
    for i, item_dict in enumerate(items_to_render):
        item_id = item_dict['id']
        # Get current values from the dictionary in state
        current_item_value = item_dict.get('item')
        current_qty = item_dict.get('qty', 1)
        current_note = item_dict.get('note', '')
        current_unit = item_dict.get('unit', '-') # Get unit from state dict

        item_label = current_item_value if current_item_value else f"Item #{i+1}"

        with st.expander(label=f"{item_label} (Qty: {current_qty}, Unit: {current_unit})", expanded=True):
            col1, col2, col3, col4 = st.columns([4, 3, 1, 1]) # Adjusted ratio note wider

            # Define the unique key for the selectbox for this item row
            selectbox_key = f"item_select_{item_id}"

            with col1:
                # Find current index for selectbox
                try:
                    current_item_index = master_item_names.index(current_item_value) if current_item_value else 0
                except ValueError:
                    current_item_index = 0 # Default to blank if item not in list (e.g., after list update)

                st.selectbox(
                    label="Item Select", options=master_item_names,
                    index=current_item_index, # Use the current value from state dict to set index
                    key=selectbox_key, # Unique key for this widget
                    placeholder="Type or select an item...", label_visibility="collapsed",
                    # *** Use the corrected callback ***
                    on_change=update_unit_display_and_item_value,
                    args=(item_id, selectbox_key) # Pass item_id and the selectbox's key
                 )

            with col2:
                # Use st.session_state to set value for text_input to allow programmatic clearing
                st.session_state[f"note_{item_id}"] = current_note # Ensure state matches dict
                st.text_input( f"Note", key=f"note_{item_id}", placeholder="Optional note...", label_visibility="collapsed" )
                # Update the dict from the widget state after potential user input
                st.session_state.form_items[i]['note'] = st.session_state[f"note_{item_id}"]

            with col3:
                 # Use st.session_state to set value for number_input
                 st.session_state[f"qty_{item_id}"] = current_qty
                 st.number_input( f"Quantity", min_value=1, step=1, key=f"qty_{item_id}", label_visibility="collapsed" )
                 # Update the dict from the widget state
                 st.session_state.form_items[i]['qty'] = st.session_state[f"qty_{item_id}"]


            with col4:
                 # Remove Button - only show if more than 1 item exists
                 if len(st.session_state.form_items) > 1:
                     st.button("❌", key=f"remove_{item_id}", on_click=remove_item, args=(item_id,), help="Remove this item")
                 else:
                      st.write("") # Placeholder to maintain layout


    st.divider()

    # --- Add/Clear Buttons ---
    col1_btn, col2_btn = st.columns(2)
    with col1_btn: st.button("➕ Add Another Item", on_click=add_item, use_container_width=True)
    with col2_btn: st.button("🔄 Clear All Items & Form", on_click=clear_all_items, use_container_width=True) # Renamed for clarity

    # --- Validation Checks ---
    items_for_validation = [item['item'] for item in st.session_state.form_items if item.get('item')]
    item_counts = Counter(items_for_validation)
    duplicates_found = {item: count for item, count in item_counts.items() if count > 1}
    has_duplicates = bool(duplicates_found)
    # Check items directly from the potentially updated state dicts
    has_valid_items = any(item.get('item') and item.get('qty', 0) > 0 for item in st.session_state.form_items)
    current_dept_tab1 = st.session_state.get("selected_dept", "") # Read from state

    submit_disabled = not has_valid_items or has_duplicates or not current_dept_tab1
    error_messages = []
    tooltip_message = "Submit the current indent request."

    if not has_valid_items: error_messages.append("Add at least one valid item with quantity > 0.")
    if has_duplicates: error_messages.append(f"Remove duplicate items: {', '.join(duplicates_found.keys())}.")
    if not current_dept_tab1: error_messages.append("Select a department.")

    st.divider()
    if error_messages:
        for msg in error_messages: st.warning(f"⚠️ {msg}")
        tooltip_message = "Please fix the issues listed above."

    # --- Final Submission Button ---
    if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message):

        # Final Validation before Submission
        final_items_to_submit: List[Tuple[str, int, str, str]] = []
        final_item_names = set()
        final_has_duplicates = False

        for item_dict in st.session_state.form_items:
            selected_item = item_dict.get('item')
            qty = item_dict.get('qty', 0)
            unit = item_dict.get('unit', 'N/A') # Get unit from dict
            note = item_dict.get('note', '')

            if selected_item and qty > 0:
                if selected_item in final_item_names:
                    final_has_duplicates = True
                    st.error(f"Duplicate item '{selected_item}' found during final check.")
                    break
                final_item_names.add(selected_item)
                final_items_to_submit.append((selected_item, qty, unit, note))

        if final_has_duplicates: st.stop()
        if not final_items_to_submit: st.error("No valid items to submit."); st.stop()

        # Proceed with submission
        try:
            mrn = generate_mrn()
            if "ERR" in mrn: st.error(f"Failed to generate MRN ({mrn}). Cannot submit."); st.stop()

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            current_date_obj = st.session_state.get("selected_date", date.today())
            formatted_date = current_date_obj.strftime("%d-%m-%Y")

            rows_to_add = [[mrn, timestamp, current_dept_tab1, formatted_date, item, str(qty), unit, note if note else "N/A"] for item, qty, unit, note in final_items_to_submit]

            if rows_to_add and log_sheet:
                with st.spinner(f"Submitting indent {mrn}..."):
                    try:
                        log_sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
                        load_indent_log_data.clear() # Clear cache for Tab 2
                    except gspread.exceptions.APIError as api_error: st.error(f"API Error submitting: {api_error}."); st.stop()
                    except Exception as submit_e: st.error(f"Submission error: {submit_e}"); st.exception(submit_e); st.stop()

                st.session_state['submitted_data_for_summary'] = {'mrn': mrn, 'dept': current_dept_tab1, 'date': formatted_date, 'items': final_items_to_submit}
                st.session_state['last_dept'] = current_dept_tab1
                clear_all_items() # Reset form items
                # Don't clear selected_dept or selected_date here, keep them for next indent maybe?
                st.rerun() # Rerun to show summary

        except Exception as e: st.error(f"Error during submission: {e}"); st.exception(e)

    # --- Display Post-Submission Summary ---
    if st.session_state.get('submitted_data_for_summary'):
        submitted_data = st.session_state['submitted_data_for_summary']
        st.success(f"Indent submitted! MRN: {submitted_data['mrn']}")
        st.balloons(); st.divider(); st.subheader("Submitted Indent Summary")
        st.info(f"**MRN:** {submitted_data['mrn']} | **Dept:** {submitted_data['dept']} | **Reqd Date:** {submitted_data['date']}")
        submitted_df = pd.DataFrame(submitted_data['items'], columns=["Item", "Qty", "Unit", "Note"])
        st.dataframe(submitted_df, hide_index=True, use_container_width=True)
        total_submitted_qty = sum(item[1] for item in submitted_data['items'])
        st.markdown(f"**Total Submitted Qty:** {total_submitted_qty}"); st.divider()
        try:
            pdf_output: bytes = create_indent_pdf(submitted_data)
            st.download_button(label="📄 Download PDF", data=pdf_output, file_name=f"Indent_{submitted_data['mrn']}.pdf", mime="application/pdf")
        except Exception as pdf_error: st.error(f"Could not generate PDF: {pdf_error}")
        if st.button("Start New Indent"):
            st.session_state['submitted_data_for_summary'] = None # Clear summary flag
            st.rerun()

# --- TAB 2: View Indents ---
with tab2:
    st.subheader("View Past Indent Requests")

    # Load data (spinner handled by @st.cache_data)
    log_df = load_indent_log_data()

    if not log_df.empty:
        st.divider()
        with st.expander("Filter Options", expanded=True):
            # Sensible filter defaults
            dept_options = sorted([d for d in log_df['Department'].unique() if d])
            min_date_log = (log_df['Date Required'].dropna().min() if pd.notna(log_df['Date Required'].dropna().min()) else date.today() - pd.Timedelta(days=30)).date()
            max_date_log = (log_df['Date Required'].dropna().max() if pd.notna(log_df['Date Required'].dropna().max()) else date.today()).date()
            if min_date_log > max_date_log: min_date_log = max_date_log # Ensure min <= max

            filt_col1, filt_col2, filt_col3 = st.columns([1, 1, 2])
            with filt_col1:
                filt_start_date = st.date_input("Reqd. From", value=min_date_log, min_value=min_date_log, max_value=max_date_log, key="filt_start")
                valid_end_min = filt_start_date
                filt_end_date = st.date_input("Reqd. To", value=max_date_log, min_value=valid_end_min, max_value=max_date_log, key="filt_end")
            with filt_col2:
                selected_depts = st.multiselect("Filter by Department", options=dept_options, default=[], key="filt_dept")
                mrn_search = st.text_input("Search by MRN", key="filt_mrn", placeholder="e.g., MRN-005")
            with filt_col3:
                item_search = st.text_input("Search by Item Name", key="filt_item", placeholder="e.g., Salt")

        # Apply Filters
        filtered_df = log_df.copy()
        try:
            if 'Date Required' in filtered_df.columns:
                 start_ts = pd.Timestamp(filt_start_date); end_ts = pd.Timestamp(filt_end_date)
                 date_filt_cond = (filtered_df['Date Required'].notna() & (filtered_df['Date Required'].dt.normalize() >= start_ts) & (filtered_df['Date Required'].dt.normalize() <= end_ts))
                 filtered_df = filtered_df[date_filt_cond]
            if selected_depts and 'Department' in filtered_df.columns: filtered_df = filtered_df[filtered_df['Department'].isin(selected_depts)]
            if mrn_search and 'MRN' in filtered_df.columns: filtered_df = filtered_df[filtered_df['MRN'].astype(str).str.contains(mrn_search, case=False, na=False)]
            if item_search and 'Item' in filtered_df.columns: filtered_df = filtered_df[filtered_df['Item'].astype(str).str.contains(item_search, case=False, na=False)]
        except Exception as filter_e: st.error(f"Error applying filters: {filter_e}"); filtered_df = log_df.copy()

        # Display
        st.divider()
        st.write(f"Displaying {len(filtered_df)} matching records:")
        st.dataframe( filtered_df, use_container_width=True, hide_index=True,
            column_config={
                "Date Required": st.column_config.DateColumn("Date Reqd.", format="DD-MM-YYYY"),
                "Timestamp": st.column_config.DatetimeColumn("Submitted", format="YYYY-MM-DD HH:mm"), # Shorter Label
                "Qty": st.column_config.NumberColumn("Qty", format="%d"),
                "MRN": st.column_config.TextColumn("MRN"), "Department": st.column_config.TextColumn("Dept."),
                "Item": st.column_config.TextColumn("Item Name", width="medium"),
                "Unit": st.column_config.TextColumn("Unit"), "Note": st.column_config.TextColumn("Notes", width="large"),
            } )
    else: st.info("No indent records found or log is currently unavailable.")

# --- Optional Debug ---
# with st.sidebar.expander("Session State Debug"): st.json(st.session_state.to_dict())
