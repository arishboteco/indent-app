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

# --- Configuration & Setup ---
# Display logo
# ... (same as before) ...
# Google Sheets setup & Credentials Handling
# ... (same as before) ...
scope: List[str] = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    if "gcp_service_account" not in st.secrets: st.error("Missing GCP credentials!"); st.stop()
    json_creds_data: Any = st.secrets["gcp_service_account"]
    creds_dict: Dict[str, Any] = json.loads(json_creds_data) if isinstance(json_creds_data, str) else json_creds_data
    creds: ServiceAccountCredentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client: Client = gspread.authorize(creds)
    try:
        indent_log_spreadsheet: Spreadsheet = client.open("Indent Log")
        sheet: Worksheet = indent_log_spreadsheet.sheet1 # Log Sheet
        reference_sheet: Worksheet = indent_log_spreadsheet.worksheet("reference") # Item Reference Sheet
    except gspread.exceptions.SpreadsheetNotFound: st.error("Spreadsheet 'Indent Log' not found."); st.stop()
    except gspread.exceptions.WorksheetNotFound: st.error("Worksheet 'Sheet1' or 'reference' not found."); st.stop()
    except gspread.exceptions.APIError as e: st.error(f"Google API Error accessing sheets: {e}"); st.stop()
except json.JSONDecodeError: st.error("Error parsing GCP credentials."); st.stop()
except gspread.exceptions.RequestError as e: st.error(f"Network error connecting to Google: {e}"); st.stop()
except Exception as e: st.error(f"Google Sheets setup error: {e}"); st.exception(e); st.stop()


# --- Reference Data Loading Function ---
def get_reference_data(_client: Client) -> Tuple[List[str], Dict[str, str]]:
    # ... (same as before) ...
    try:
        _reference_sheet = _client.open("Indent Log").worksheet("reference")
        all_data: List[List[str]] = _reference_sheet.get_all_values()
        item_names: List[str] = []; item_to_unit_lower: Dict[str, str] = {}
        processed_items_lower: set[str] = set(); header_skipped: bool = False
        for i, row in enumerate(all_data):
            if not any(str(cell).strip() for cell in row): continue
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower() or "unit" in str(row[1]).lower()): header_skipped = True; continue
            if len(row) >= 2:
                item: str = str(row[0]).strip(); unit: str = str(row[1]).strip(); item_lower: str = item.lower()
                if item and item_lower not in processed_items_lower:
                    item_names.append(item); item_to_unit_lower[item_lower] = unit if unit else "N/A"; processed_items_lower.add(item_lower)
        item_names.sort()
        return item_names, item_to_unit_lower
    except gspread.exceptions.APIError as e: st.error(f"API Error loading reference data: {e}"); return [], {}
    except Exception as e: st.error(f"Error loading reference data: {e}"); return [], {}

# --- Populate State from Loaded Data ---
# ... (same as before) ...
if 'master_item_list' not in st.session_state or 'item_to_unit_lower' not in st.session_state:
     loaded_item_names, loaded_item_to_unit_lower = get_reference_data(client)
     st.session_state['master_item_list'] = loaded_item_names
     st.session_state['item_to_unit_lower'] = loaded_item_to_unit_lower
master_item_names = st.session_state.get('master_item_list', [])
item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})
if not master_item_names: st.error("Item list empty/not loaded. Cannot proceed."); st.stop()


# --- MRN Generation ---
def generate_mrn() -> str:
    # ... (same as before) ...
    try:
        all_mrns = sheet.col_values(1); next_number = 1
        if len(all_mrns) > 1:
            last_valid_num = 0
            for mrn_str in reversed(all_mrns):
                if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit(): last_valid_num = int(mrn_str[4:]); break
            if last_valid_num == 0: last_valid_num = max(0, len([v for v in all_mrns if v]) -1)
            next_number = last_valid_num + 1
        return f"MRN-{str(next_number).zfill(3)}"
    except gspread.exceptions.APIError as e: st.error(f"API Error generating MRN: {e}"); return f"MRN-ERR-{datetime.now().strftime('%H%M')}"
    except Exception as e: st.error(f"MRN Error: {e}"); return f"MRN-ERR-{datetime.now().strftime('%H%M')}"


# --- PDF Generation Function ---
def create_indent_pdf(data: Dict[str, Any]) -> bytes:
    # ... (Same as before) ...
    pdf = FPDF(); pdf.add_page(); pdf.set_margins(10, 10, 10); pdf.set_auto_page_break(auto=True, margin=15)
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
    for item, qty, unit, note in data['items']:
        start_y = pdf.get_y(); current_x = pdf.l_margin
        pdf.multi_cell(col_widths['item'], line_height, str(item), border='LR', align='L', ln=3); item_y = pdf.get_y()
        current_x += col_widths['item']; pdf.set_xy(current_x, start_y)
        pdf.cell(col_widths['qty'], line_height, str(qty), border='R', ln=0, align='C'); qty_y = start_y + line_height
        current_x += col_widths['qty']; pdf.set_xy(current_x, start_y)
        pdf.cell(col_widths['unit'], line_height, str(unit), border='R', ln=0, align='C'); unit_y = start_y + line_height
        current_x += col_widths['unit']; pdf.set_xy(current_x, start_y)
        pdf.multi_cell(col_widths['note'], line_height, str(note if note else "-"), border='R', align='L', ln=3); note_y = pdf.get_y()
        max_y = max(item_y, qty_y, unit_y, note_y, start_y + line_height)
        pdf.line(pdf.l_margin, max_y, pdf.l_margin + sum(col_widths.values()), max_y)
        pdf.set_y(max_y); pdf.ln(0.1)
    return pdf.output()


# --- Function to Load and Clean Log Data (Cached) ---
@st.cache_data(ttl=300) # Cache data for 5 minutes
def load_indent_log_data() -> pd.DataFrame:
    """Fetches all records from the main log sheet ('sheet1'), cleans data types,
       and returns data as a Pandas DataFrame. Assumes header row exists."""
    try:
        # st.write("DEBUG: Fetching indent log data from Google Sheet...") # Uncomment for debug
        records = sheet.get_all_records() # Uses header row to create dict keys
        if not records:
            expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
            st.info("Indent log sheet appears to be empty.")
            return pd.DataFrame(columns=expected_cols)

        df = pd.DataFrame(records)
        # --- Data Cleaning ---
        expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note'] # Adjust EXACTLY to your Sheet1 header
        missing_cols = [col for col in expected_cols if col not in df.columns]
        if missing_cols:
             st.warning(f"Log sheet might be missing expected columns: {', '.join(missing_cols)}. Found: {list(df.columns)}")

        # Convert 'Timestamp' (assuming format like YYYY-MM-DD HH:MM:SS)
        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')

        # Convert 'Date Required' (assuming format DD-MM-YYYY from submission)
        # *** IMPORTANT: Adjust 'format' if your sheet stores it differently ***
        if 'Date Required' in df.columns:
            df['Date Required'] = pd.to_datetime(df['Date Required'], format='%d-%m-%Y', errors='coerce')

        # Convert 'Qty' to numeric
        if 'Qty' in df.columns:
            # Convert empty strings or non-numeric to NaN, then fill NaN with 0, then convert to int
            df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0).astype(int)

        # Optional: Clean up other columns like stripping whitespace or filling blanks
        # if 'Department' in df.columns: df['Department'] = df['Department'].str.strip().fillna('Unknown')
        # if 'Note' in df.columns: df['Note'] = df['Note'].fillna('')

        # --- End Cleaning ---
        # st.write(f"DEBUG: Loaded and cleaned {len(df)} records.") # Uncomment for debug
        return df

    except gspread.exceptions.APIError as e:
        st.error(f"API Error loading indent log: {e}")
        return pd.DataFrame() # Return empty DataFrame on error
    except Exception as e:
        st.error(f"Error loading/cleaning indent log data: {e}")
        # st.exception(e) # Uncomment for detailed traceback
        return pd.DataFrame() # Return empty DataFrame on error

# --- --- --- --- --- --- --- ---


# --- UI divided into Tabs ---
tab1, tab2 = st.tabs(["📝 New Indent", "📊 View Indents"])

# --- TAB 1: New Indent Form ---
with tab1:
    st.title("Material Indent Form")
    # ... (All code for Tab 1 remains exactly the same as the previous version) ...
    # Includes: Session State Init, Callback Def, Header Inputs, Add/Remove/Clear Buttons,
    # Item Input Rows (with expander, no dropdown filtering), Duplicate Check,
    # Submit Button logic, Post-Submission Summary display logic

    # --- Session State Initialization ---
    if "item_count" not in st.session_state: st.session_state.item_count = 1
    for i in range(st.session_state.item_count):
        st.session_state.setdefault(f"item_{i}", None); st.session_state.setdefault(f"qty_{i}", 1)
        st.session_state.setdefault(f"note_{i}", ""); st.session_state.setdefault(f"unit_display_{i}", "-")
    st.session_state.setdefault('last_dept', None)

    # --- Callback Function ---
    def update_unit_display(index: int) -> None:
        selected_item = st.session_state.get(f"item_{index}")
        local_map = st.session_state.get('item_to_unit_lower', {})
        unit = local_map.get(selected_item.lower(), "N/A") if selected_item else "-"
        st.session_state[f"unit_display_{index}"] = unit if unit else "-"

    # --- Header Inputs ---
    DEPARTMENTS = ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"]
    last_dept = st.session_state.get('last_dept')
    dept_index = 0
    if last_dept and last_dept in DEPARTMENTS:
        try: dept_index = DEPARTMENTS.index(last_dept)
        except ValueError: dept_index = 0
    dept = st.selectbox("Select Department", DEPARTMENTS, index=dept_index, key="selected_dept", placeholder="Select department...")
    delivery_date = st.date_input("Date Required", value=date.today(), min_value=date.today(), format="DD/MM/YYYY", key="selected_date")

    # --- Add/Remove/Clear Buttons ---
    col1_btn, col2_btn, col3_btn = st.columns([1, 1, 1])
    with col1_btn:
        if st.button("➕ Add Item", key="add_item_tab1"):
            idx = st.session_state.item_count; st.session_state[f"item_{idx}"]=None; st.session_state[f"qty_{idx}"]=1
            st.session_state[f"note_{idx}"]=""; st.session_state[f"unit_display_{idx}"]="-"
            st.session_state.item_count += 1; # IMPLICIT rerun
    with col2_btn:
        can_remove = st.session_state.item_count > 1
        if st.button("➖ Remove Last", disabled=not can_remove, key="remove_item_tab1"):
            if can_remove:
                idx = st.session_state.item_count - 1
                for prefix in ["item_", "qty_", "note_", "unit_display_"]: st.session_state.pop(f"{prefix}{idx}", None)
                st.session_state.item_count -= 1; # IMPLICIT rerun
    with col3_btn:
        if st.button("🔄 Clear All Items", key="clear_items_tab1"):
            keys_to_delete = [f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)]
            for key in keys_to_delete:
                if key in st.session_state: del st.session_state[key]
            st.session_state.item_count = 1
            st.session_state.setdefault("item_0", None); st.session_state.setdefault("qty_0", 1)
            st.session_state.setdefault("note_0", ""); st.session_state.setdefault("unit_display_0", "-")
            st.rerun()


    st.markdown("---")
    st.subheader("Enter Items:")

    # --- Item Input Rows (NO Filtering, WITH Expander) ---
    for i in range(st.session_state.item_count):
        item_label = st.session_state.get(f"item_{i}", "New")
        with st.expander(label=f"Item {i}: {item_label}", expanded=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.selectbox(
                    label=f"Item Select {i}", options=[""] + master_item_names, key=f"item_{i}",
                    placeholder="Type or select an item...", label_visibility="collapsed",
                    on_change=update_unit_display, args=(i,)
                )
                st.text_input(f"Note {i}", key=f"note_{i}", placeholder="Special instructions...", label_visibility="collapsed")
            with col2:
                st.markdown("**Unit:**"); unit_to_display = st.session_state.get(f"unit_display_{i}", "-"); st.markdown(f"### {unit_to_display}") # Dynamic Unit
                st.number_input(f"Quantity {i}", min_value=1, step=1, key=f"qty_{i}", label_visibility="collapsed")


    # --- Immediate Duplicate Check & Feedback ---
    current_selected_items = [st.session_state.get(f"item_{k}") for k in range(st.session_state.item_count) if st.session_state.get(f"item_{k}")]
    item_counts = Counter(current_selected_items); duplicates_found = {item: count for item, count in item_counts.items() if count > 1}
    has_duplicates_in_state = bool(duplicates_found)

    # --- Pre-Submission Check & Button Disabling Info ---
    has_valid_items = any(st.session_state.get(f"item_{k}") and st.session_state.get(f"qty_{k}", 0) > 0 for k in range(st.session_state.item_count))
    current_dept_tab1 = st.session_state.get("selected_dept", "") # Use specific var name for clarity
    submit_disabled = not has_valid_items or has_duplicates_in_state or not current_dept_tab1
    tooltip_message = ""; error_messages = []
    if not has_valid_items: error_messages.append("Add item(s). ")
    if has_duplicates_in_state: error_messages.append("Remove duplicates. ")
    if not current_dept_tab1: error_messages.append("Select department.")
    tooltip_message = "".join(error_messages)

    st.markdown("---")
    if submit_disabled and tooltip_message:
        if has_duplicates_in_state:
            dup_list = ", ".join(duplicates_found.keys())
            st.error(f"⚠️ Cannot submit: Duplicate items detected ({dup_list}). Please fix.")
        else:
            st.warning(f"⚠️ Cannot submit: {tooltip_message}")


    # --- Final Submission Button ---
    if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message if submit_disabled else "Submit the current indent", key="submit_indent_tab1"):

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
            # Use current_dept_tab1 variable
            rows_to_add = [[mrn, timestamp, current_dept_tab1, formatted_date, item, str(qty), unit, note if note else "N/A"]
                           for item, qty, unit, note in items_to_submit_final]
            if rows_to_add:
                with st.spinner(f"Submitting indent {mrn}..."):
                    try: sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
                    except gspread.exceptions.APIError as api_error: st.error(f"API Error submitting: {api_error}."); st.stop()

                st.session_state['submitted_data_for_summary'] = { 'mrn': mrn, 'dept': current_dept_tab1, 'date': formatted_date, 'items': items_to_submit_final }
                st.session_state['last_dept'] = current_dept_tab1 # Remember dept

                # --- Clean up FORM state ONLY ---
                keys_to_delete = []
                keys_to_delete.extend([f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)])
                keys_to_delete.extend(["selected_dept", "selected_date"]) # Clear current selections
                for key in keys_to_delete:
                    if key in st.session_state: del st.session_state[key]
                st.session_state.item_count = 1
                st.session_state.setdefault("item_0", None); st.session_state.setdefault("qty_0", 1)
                st.session_state.setdefault("note_0", ""); st.session_state.setdefault("unit_display_0", "-")

                st.rerun()

        except Exception as e: st.error(f"Error during submission: {e}"); st.exception(e)

    # --- Display Post-Submission Summary (within Tab 1) ---
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

        # --- Generate PDF Data & Download Button (with bytes conversion fix) ---
        try:
            pdf_output: bytes = create_indent_pdf(submitted_data)
            pdf_bytes_data = bytes(pdf_output)
            st.download_button(
                 label="📄 Download Indent PDF", data=pdf_bytes_data,
                 file_name=f"Indent_{submitted_data['mrn']}.pdf", mime="application/pdf",
                 key='pdf_download_button'
             )
        except Exception as pdf_error:
            st.error(f"Could not generate PDF: {pdf_error}"); st.exception(pdf_error)

        if st.button("Start New Indent", key='new_indent_button'):
            del st.session_state['submitted_data_for_summary']
            st.rerun()


# --- TAB 2: View Indents ---
with tab2:
    st.subheader("View Past Indent Requests")

    # Call the function to load data (uses cache)
    log_df_raw = load_indent_log_data() # Renamed variable for clarity

    if log_df_raw.empty:
        # Check if it's empty because the sheet is empty or because of an error
        # (Error message would have been shown by load_indent_log_data)
        st.info("No indent records found or unable to load data.")
    else:
        # Display basic info for now
        st.info(f"Loaded {len(log_df_raw)} records from the indent log.")
        st.markdown("Raw data view (cleaning and filtering next):")
        # Display the DataFrame (which should have cleaned types now)
        st.dataframe(log_df_raw, use_container_width=True, hide_index=True)

# --- Optional Full State Debug ---
# st.sidebar.write("### Session State")
# st.sidebar.json(st.session_state.to_dict())
