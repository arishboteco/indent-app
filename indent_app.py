import streamlit as st
import pandas as pd
import gspread
from gspread import Client, Spreadsheet, Worksheet
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
    logo = Image.open("logo.png")
    st.image(logo, width=200)
except FileNotFoundError: st.warning("Logo not found.")
except Exception as e: st.warning(f"Logo error: {e}")

# --- Main Application Title ---
st.title("Material Indent Form")

# Google Sheets setup & Credentials Handling
# ... (Keep the robust setup block as before) ...
scope: List[str] = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    if "gcp_service_account" not in st.secrets: st.error("Missing GCP credentials!"); st.stop()
    json_creds_data: Any = st.secrets["gcp_service_account"]
    creds_dict: Dict[str, Any] = json.loads(json_creds_data) if isinstance(json_creds_data, str) else json_creds_data
    creds: ServiceAccountCredentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client: Client = gspread.authorize(creds)
    try:
        indent_log_spreadsheet: Spreadsheet = client.open("Indent Log")
        sheet: Worksheet = indent_log_spreadsheet.sheet1
        reference_sheet: Worksheet = indent_log_spreadsheet.worksheet("reference")
    except gspread.exceptions.SpreadsheetNotFound: st.error("'Indent Log' not found."); st.stop()
    except gspread.exceptions.WorksheetNotFound: st.error("'Sheet1' or 'reference' not found."); st.stop()
    except gspread.exceptions.APIError as e: st.error(f"API Error: {e}"); st.stop()
except json.JSONDecodeError: st.error("Error parsing GCP credentials."); st.stop()
except gspread.exceptions.RequestError as e: st.error(f"Network error: {e}"); st.stop()
except Exception as e: st.error(f"Setup error: {e}"); st.exception(e); st.stop()


# --- Reference Data Loading Function ---
@st.cache_data(ttl=300)
def get_reference_data(_client: Client) -> Tuple[List[str], Dict[str, str]]:
    # ... (Keep the same function as before) ...
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
        st.session_state['master_item_list'] = item_names
        st.session_state['item_to_unit_lower'] = item_to_unit_lower
        return item_names, item_to_unit_lower
    except gspread.exceptions.APIError as e: st.error(f"API Error loading ref data: {e}"); return [], {}
    except Exception as e: st.error(f"Error loading ref data: {e}"); st.exception(e); return [], {}


# --- Populate State from Loaded Data ---
if 'master_item_list' not in st.session_state or 'item_to_unit_lower' not in st.session_state:
     master_item_names, item_to_unit_lower_map = get_reference_data(client)
else:
    master_item_names = st.session_state['master_item_list']
    item_to_unit_lower = st.session_state['item_to_unit_lower']
if not st.session_state.get('master_item_list'): st.error("Item list empty. Cannot proceed."); st.stop()


# --- MRN Generation ---
def generate_mrn() -> str:
    # ... (Keep the same function as before) ...
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
    # ... (Keep the same function as before, ensure fpdf2 installed) ...
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
    for item_data in data.get('items', []):
        if len(item_data) == 4:
           item, qty, unit, note = item_data
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
        else: st.warning(f"Invalid PDF item data: {item_data}")
    return pdf.output()


# --- Function to Load and Clean Log Data (Cached) ---
@st.cache_data(ttl=60)
def load_indent_log_data() -> pd.DataFrame:
    # ... (Keep the same function as before) ...
    try:
        records = sheet.get_all_records(numericise_ignore=['all'])
        if not records: expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']; return pd.DataFrame(columns=expected_cols)
        df = pd.DataFrame(records)
        expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
        for col in expected_cols:
             if col not in df.columns: df[col] = pd.NA
        if 'Timestamp' in df.columns: df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        if 'Date Required' in df.columns:
            df['Date Required'] = pd.to_datetime(df['Date Required'], format='%d-%m-%Y', errors='coerce')
            mask = df['Date Required'].isna()
            if mask.any(): df.loc[mask, 'Date Required'] = pd.to_datetime(df.loc[mask, 'Date Required'], format='%Y-%m-%d', errors='coerce')
        if 'Qty' in df.columns: df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0).astype(int)
        df = df[expected_cols]
        return df
    except Exception as e: st.error(f"Error loading log: {e}"); return pd.DataFrame()


# --- --- --- --- --- --- --- ---

# --- Initialize Flags ---
st.session_state.setdefault('show_clear_confirmation', False)
st.session_state.setdefault('reset_filters_flag', False)

# --- UI divided into Tabs ---
tab1, tab2 = st.tabs(["📝 New Indent", "📊 View Indents"])

# --- TAB 1: New Indent Form ---
with tab1:
    # --- Session State Initialization ---
    if "item_count" not in st.session_state: st.session_state.item_count = 5
    else: st.session_state.item_count = max(1, st.session_state.item_count)
    for i in range(st.session_state.item_count):
        st.session_state.setdefault(f"item_{i}", None); st.session_state.setdefault(f"qty_{i}", 1)
        st.session_state.setdefault(f"note_{i}", ""); st.session_state.setdefault(f"unit_display_{i}", "-")
    st.session_state.setdefault('last_dept', None)

    # --- Callback Function ---
    def update_unit_display(index: int) -> None:
        # ... (Callback remains the same) ...
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
    delivery_date = st.date_input("Date Required", value=st.session_state.get("selected_date", date.today()), min_value=date.today(), format="DD/MM/YYYY", key="selected_date")

    # --- Item Input Section ---
    st.divider()
    st.subheader("Enter Items:")
    for i in range(st.session_state.item_count):
        item_label = st.session_state.get(f"item_{i}", f"Item {i}")
        with st.expander(label=f"Item {i}: {item_label}", expanded=False): # Start collapsed
            col1, col2 = st.columns([3, 1])
            with col1:
                st.selectbox(f"Item Select {i}", options=[""] + master_item_names, key=f"item_{i}",
                             placeholder="Select item...", label_visibility="collapsed",
                             on_change=update_unit_display, args=(i,))
                st.text_input(f"Note {i}", key=f"note_{i}", placeholder="Note...", label_visibility="collapsed")
            with col2:
                st.markdown("**Unit:**"); unit_to_display = st.session_state.get(f"unit_display_{i}", "-"); st.markdown(f"### {unit_to_display}")
                st.number_input(f"Quantity {i}", min_value=1, step=1, key=f"qty_{i}", label_visibility="collapsed")

    # --- Add/Remove/Clear Buttons ---
    st.divider()
    col1_btn, col2_btn, col3_btn = st.columns([1, 1, 1])
    with col1_btn:
        if st.button("➕ Add Row", key="add_item_tab1", help="Add another item row"):
            idx = st.session_state.item_count; st.session_state[f"item_{idx}"]=None; st.session_state[f"qty_{idx}"]=1
            st.session_state[f"note_{idx}"]=""; st.session_state[f"unit_display_{idx}"]="-"
            st.session_state.item_count += 1; st.rerun()
    with col2_btn:
        can_remove = st.session_state.item_count > 1
        if st.button("➖ Remove Last", disabled=not can_remove, key="remove_item_tab1", help="Remove the last item row"):
            if can_remove:
                idx = st.session_state.item_count - 1
                for prefix in ["item_", "qty_", "note_", "unit_display_"]: st.session_state.pop(f"{prefix}{idx}", None)
                st.session_state.item_count -= 1; st.rerun()
    with col3_btn:
        # FIX: Replace st.confirm with two-stage button logic
        if st.button("🔄 Clear Form", key="clear_items_tab1", help="Remove all items and reset the form"):
             st.session_state['show_clear_confirmation'] = True # Set flag
             st.rerun() # Rerun to show confirmation options

    # FIX: Display confirmation buttons if flag is set
    if st.session_state.get('show_clear_confirmation', False):
        st.warning("Are you sure you want to clear all entered items?")
        confirm_col_yes, confirm_col_no = st.columns(2)
        with confirm_col_yes:
            if st.button("Yes, Clear All", type="primary", key="confirm_clear_yes"):
                # --- Actual Clearing Logic ---
                keys_to_delete = [f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)]
                for key in keys_to_delete:
                    if key in st.session_state: del st.session_state[key]
                st.session_state.item_count = 5 # Reset to 5 rows
                for i in range(st.session_state.item_count): # Re-initialize state for rows 0-4
                     st.session_state.setdefault(f"item_{i}", None); st.session_state.setdefault(f"qty_{i}", 1)
                     st.session_state.setdefault(f"note_{i}", ""); st.session_state.setdefault(f"unit_display_{i}", "-")
                # --- End Clearing Logic ---
                del st.session_state['show_clear_confirmation'] # Clear flag
                st.success("Form Cleared.")
                st.rerun() # Rerun to reflect cleared state
        with confirm_col_no:
            if st.button("Cancel", key="confirm_clear_no"):
                del st.session_state['show_clear_confirmation'] # Clear flag
                st.rerun() # Rerun to hide confirmation

    # --- Immediate Duplicate Check & Feedback ---
    # ... (Duplicate check logic remains the same) ...
    current_selected_items = [st.session_state.get(f"item_{k}") for k in range(st.session_state.item_count) if st.session_state.get(f"item_{k}")]
    item_counts = Counter(current_selected_items); duplicates_found = {item: count for item, count in item_counts.items() if count > 1}
    has_duplicates_in_state = bool(duplicates_found)

    # --- Pre-Submission Check & Button Disabling Info ---
    # ... (Pre-submission checks remain the same) ...
    has_valid_items = any(st.session_state.get(f"item_{k}") and st.session_state.get(f"qty_{k}", 0) > 0 for k in range(st.session_state.item_count))
    current_dept_tab1 = st.session_state.get("selected_dept", "")
    submit_disabled = not has_valid_items or has_duplicates_in_state or not current_dept_tab1
    tooltip_message = ""; error_messages = []
    if not has_valid_items: error_messages.append("Add item(s). ")
    if has_duplicates_in_state: error_messages.append("Remove duplicates. ")
    if not current_dept_tab1: error_messages.append("Select department.")
    tooltip_message = "".join(error_messages)

    st.divider()
    if submit_disabled and tooltip_message:
        if has_duplicates_in_state: dup_list = ", ".join(duplicates_found.keys()); st.error(f"⚠️ Cannot submit: Duplicates ({dup_list}).")
        else: st.warning(f"⚠️ Cannot submit: {tooltip_message}")

    # --- Final Submission Button ---
    if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message if submit_disabled else "Submit the current indent", key="submit_indent_tab1"):
        # ... (Submission logic remains the same) ...
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
        try:
            mrn = generate_mrn(); timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            current_date_obj = st.session_state.get("selected_date", date.today()); formatted_date = current_date_obj.strftime("%d-%m-%Y")
            rows_to_add = [[mrn, timestamp, current_dept_tab1, formatted_date, item, str(qty), unit, note if note else "N/A"] for item, qty, unit, note in items_to_submit_final]
            if rows_to_add:
                with st.spinner(f"Submitting indent {mrn}..."):
                    try: sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
                    except gspread.exceptions.APIError as api_error: st.error(f"API Error submitting: {api_error}."); st.stop()
                st.session_state['submitted_data_for_summary'] = { 'mrn': mrn, 'dept': current_dept_tab1, 'date': formatted_date, 'items': items_to_submit_final }
                st.session_state['last_dept'] = current_dept_tab1
                keys_to_delete = [f"{prefix}{i}" for prefix in ["item_", "qty_", "note_", "unit_display_"] for i in range(st.session_state.item_count)]
                keys_to_delete.extend(["selected_dept", "selected_date"])
                for key in keys_to_delete:
                    if key in st.session_state: del st.session_state[key]
                st.session_state.item_count = 5
                for i in range(st.session_state.item_count):
                     st.session_state.setdefault(f"item_{i}", None); st.session_state.setdefault(f"qty_{i}", 1)
                     st.session_state.setdefault(f"note_{i}", ""); st.session_state.setdefault(f"unit_display_{i}", "-")
                st.rerun()
        except Exception as e: st.error(f"Error during submission: {e}"); st.exception(e)

    # --- Display Post-Submission Summary (within Tab 1) ---
    if 'submitted_data_for_summary' in st.session_state:
        # ... (Post-submission summary display logic - unchanged) ...
        submitted_data = st.session_state['submitted_data_for_summary']
        st.success(f"Indent submitted successfully! MRN: {submitted_data['mrn']}")
        st.balloons(); st.divider(); st.subheader("Submitted Indent Summary")
        st.info(f"**MRN:** {submitted_data['mrn']} | **Department:** {submitted_data['dept']} | **Date Required:** {submitted_data['date']}")
        submitted_df = pd.DataFrame(submitted_data['items'], columns=["Item", "Qty", "Unit", "Note"])
        st.dataframe(submitted_df, hide_index=True, use_container_width=True)
        total_submitted_qty = sum(item[1] for item in submitted_data['items'])
        st.markdown(f"**Total Submitted Quantity:** {total_submitted_qty}"); st.divider()
        try:
            pdf_output: bytes = create_indent_pdf(submitted_data); pdf_bytes_data = bytes(pdf_output)
            st.download_button(label="📄 Download Indent PDF", data=pdf_bytes_data, file_name=f"Indent_{submitted_data['mrn']}.pdf", mime="application/pdf", key='pdf_download_button')
        except Exception as pdf_error: st.error(f"Could not generate PDF: {pdf_error}"); st.exception(pdf_error)
        if st.button("Start New Indent", key='new_indent_button'):
            del st.session_state['submitted_data_for_summary']; st.rerun()
        else: st.stop() # Keep showing summary until button is clicked


# --- TAB 2: View Indents ---
with tab2:
    st.subheader("View Past Indent Requests")

    # --- Handle Filter Reset Flag ---
    # Calculate default date range BEFORE potentially resetting state
    log_df_for_dates = load_indent_log_data() # Load data once for date range calculation
    min_date_log = date.today() - pd.Timedelta(days=30)
    max_date_log = date.today()
    if not log_df_for_dates.empty and 'Date Required' in log_df_for_dates.columns and not log_df_for_dates['Date Required'].isnull().all():
         min_dt_val = log_df_for_dates['Date Required'].dropna().min()
         max_dt_val = log_df_for_dates['Date Required'].dropna().max()
         if pd.notna(min_dt_val): min_date_log = min_dt_val.date()
         if pd.notna(max_dt_val): max_date_log = max_dt_val.date()

    # FIX: Check and apply reset BEFORE rendering widgets
    if st.session_state.get('reset_filters_flag', False):
        st.session_state["filt_start"] = min_date_log
        st.session_state["filt_end"] = max_date_log
        st.session_state["filt_dept"] = []
        st.session_state["filt_mrn"] = ""
        st.session_state["filt_item"] = ""
        del st.session_state['reset_filters_flag'] # Unset flag immediately

    # Load data (might be cached from date calculation above)
    with st.spinner("Loading indent history..."):
        log_df = load_indent_log_data()

    # --- Filtering Widgets ---
    if not log_df.empty:
        with st.expander("Filter Options", expanded=True):
            filt_col_main, filt_col_reset = st.columns([8,1])
            with filt_col_main:
                 filt_col1, filt_col2, filt_col3 = st.columns([1, 1, 2])
                 with filt_col1:
                     # Use state values, which might have been reset just above
                     filt_start_date = st.date_input("Reqd. From", value=st.session_state.get("filt_start", min_date_log), min_value=min_date_log, max_value=max_date_log, key="filt_start")
                     filt_end_date = st.date_input("Reqd. To", value=st.session_state.get("filt_end", max_date_log), min_value=filt_start_date, max_value=max_date_log, key="filt_end")
                 with filt_col2:
                     dept_options = sorted([d for d in DEPARTMENTS if d])
                     # Use state value for default
                     selected_depts = st.multiselect("Filter by Department", options=dept_options, default=st.session_state.get("filt_dept", []), key="filt_dept")
                     # Use state value for default
                     mrn_search = st.text_input("Search by MRN", value=st.session_state.get("filt_mrn", ""), key="filt_mrn")
                 with filt_col3:
                      # Use state value for default
                     item_search = st.text_input("Search by Item Name", value=st.session_state.get("filt_item", ""), key="filt_item")

            # Reset Button - Sets flag and reruns
            with filt_col_reset:
                 st.write(""); st.write("") # Vertical alignment hack
                 if st.button("Reset", key="reset_filters_tab2_button", help="Clear all filters"):
                     st.session_state['reset_filters_flag'] = True # Set flag
                     st.rerun() # Trigger rerun

            # --- Apply Filters ---
            # (Filter logic remains the same - reads from state)
            filtered_df = log_df.copy()
            try:
                start_ts = pd.Timestamp(st.session_state.get("filt_start", min_date_log))
                end_ts = pd.Timestamp(st.session_state.get("filt_end", max_date_log))
                if 'Date Required' in filtered_df.columns and not filtered_df['Date Required'].isnull().all():
                    date_filt_condition = (filtered_df['Date Required'].notna() & (filtered_df['Date Required'].dt.normalize() >= start_ts) & (filtered_df['Date Required'].dt.normalize() <= end_ts))
                    filtered_df = filtered_df[date_filt_condition]
                sel_depts = st.session_state.get("filt_dept", [])
                if sel_depts and 'Department' in filtered_df.columns: filtered_df = filtered_df[filtered_df['Department'].isin(sel_depts)]
                mrn_s = st.session_state.get("filt_mrn", "")
                if mrn_s and 'MRN' in filtered_df.columns: filtered_df = filtered_df[filtered_df['MRN'].astype(str).str.contains(mrn_s, case=False, na=False)]
                item_s = st.session_state.get("filt_item", "")
                if item_s and 'Item' in filtered_df.columns: filtered_df = filtered_df[filtered_df['Item'].astype(str).str.contains(item_s, case=False, na=False)]
            except Exception as filter_e: st.error(f"Error applying filters: {filter_e}"); filtered_df = log_df.copy()

        # --- Display Section ---
        st.divider()
        st.write(f"Displaying {len(filtered_df)} matching records:")
        # ... (DataFrame display remains the same) ...
        st.dataframe(
            filtered_df, use_container_width=True, hide_index=True,
            column_config={
                "Date Required": st.column_config.DatetimeColumn("Date Reqd.", format="DD-MM-YYYY"),
                "Timestamp": st.column_config.DatetimeColumn("Submitted On", format="YYYY-MM-DD HH:mm"),
                "Qty": st.column_config.NumberColumn("Quantity", format="%d"),
                "MRN": st.column_config.TextColumn("MRN"), "Department": st.column_config.TextColumn("Dept."),
                "Item": st.column_config.TextColumn("Item Name", width="medium"), "Unit": st.column_config.TextColumn("Unit"),
                "Note": st.column_config.TextColumn("Notes", width="medium"),
            }
        )
    else: st.info("No indent records found or unable to load data.")

# --- Optional Full State Debug ---
# (Keep commented out unless needed)
