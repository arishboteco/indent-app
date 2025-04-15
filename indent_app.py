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

try:
    logo = Image.open("logo.png")
    st.image(logo, width=75) # Smaller logo
except FileNotFoundError:
    st.warning("Logo image 'logo.png' not found.")
except Exception as e:
    st.warning(f"Could not load logo: {e}")

# --- Main Application Title ---
st.title("Material Indent Form")

# Google Sheets setup & Credentials Handling
scope: List[str] = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def connect_gsheets():
    # ... (connection logic remains the same) ...
    try:
        if "gcp_service_account" not in st.secrets: st.error("Missing GCP credentials!"); return None, None, None
        json_creds_data: Any = st.secrets["gcp_service_account"]
        if isinstance(json_creds_data, str):
            try: creds_dict: Dict[str, Any] = json.loads(json_creds_data)
            except json.JSONDecodeError: st.error("Error parsing GCP credentials string."); return None, None, None
        elif isinstance(json_creds_data, dict): creds_dict = json_creds_data
        else: st.error("GCP credentials format error."); return None, None, None
        creds: ServiceAccountCredentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client: Client = gspread.authorize(creds)
        try:
            indent_log_spreadsheet: Spreadsheet = client.open("Indent Log")
            log_sheet: Worksheet = indent_log_spreadsheet.sheet1
            reference_sheet: Worksheet = indent_log_spreadsheet.worksheet("reference")
            return client, log_sheet, reference_sheet
        except gspread.exceptions.SpreadsheetNotFound: st.error("Spreadsheet 'Indent Log' not found."); return None, None, None
        except gspread.exceptions.WorksheetNotFound: st.error("Worksheet 'Sheet1' or 'reference' not found."); return None, None, None
        except gspread.exceptions.APIError as e: st.error(f"Google API Error: {e}"); return None, None, None
    except json.JSONDecodeError: st.error("Error parsing GCP credentials JSON."); return None, None, None
    except gspread.exceptions.RequestError as e: st.error(f"Network error connecting to Google: {e}"); return None, None, None
    except Exception as e: st.error(f"Google Sheets setup error: {e}"); st.exception(e); return None, None, None

client, log_sheet, reference_sheet = connect_gsheets()
if not client or not log_sheet or not reference_sheet: st.error("Failed Sheets connection."); st.stop()

# --- Reference Data Loading Function (CACHED) ---
@st.cache_data(ttl=3600, show_spinner="Fetching item reference data...")
def get_reference_data(_reference_sheet: Worksheet) -> Tuple[List[str], Dict[str, str]]:
    # ... (function remains the same) ...
    try:
        all_data: List[List[str]] = _reference_sheet.get_all_values()
        item_names: List[str] = [""]
        item_to_unit_lower: Dict[str, str] = {}
        processed_items_lower: set[str] = set()
        header_skipped: bool = False
        for i, row in enumerate(all_data):
            if not any(str(cell).strip() for cell in row): continue
            if not header_skipped and i == 0 and (("item" in str(row[0]).lower() or "name" in str(row[0]).lower()) and "unit" in str(row[1]).lower()): header_skipped = True; continue
            if len(row) >= 2:
                item: str = str(row[0]).strip(); unit: str = str(row[1]).strip(); item_lower: str = item.lower()
                if item and item_lower not in processed_items_lower: item_names.append(item); item_to_unit_lower[item_lower] = unit if unit else "N/A"; processed_items_lower.add(item_lower)
        other_items = sorted([name for name in item_names if name]); item_names = [""] + other_items
        return item_names, item_to_unit_lower
    except gspread.exceptions.APIError as e: st.error(f"API Error loading reference: {e}"); return [""], {}
    except Exception as e: st.error(f"Error loading reference: {e}"); return [""], {}


# --- Load Reference Data into State ---
if reference_sheet: master_item_names, item_to_unit_lower = get_reference_data(reference_sheet); st.session_state['master_item_list'] = master_item_names; st.session_state['item_to_unit_lower'] = item_to_unit_lower
else: st.session_state['master_item_list'] = [""]; st.session_state['item_to_unit_lower'] = {}
master_item_names = st.session_state.get('master_item_list', [""])
item_to_unit_lower = st.session_state.get('item_to_unit_lower', {})
if len(master_item_names) <= 1: st.error("Item list empty/not loaded.")

# --- MRN Generation ---
def generate_mrn() -> str:
    # ... (function remains the same) ...
    if not log_sheet: return f"MRN-ERR-NOSHEET"
    try:
        all_mrns = log_sheet.col_values(1); next_number = 1
        if len(all_mrns) > 1:
            last_valid_num = 0
            for mrn_str in reversed(all_mrns):
                if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit(): last_valid_num = int(mrn_str[4:]); break
            if last_valid_num == 0: non_empty_count = sum(1 for v in all_mrns if v); last_valid_num = max(0, non_empty_count - 1)
            next_number = last_valid_num + 1
        return f"MRN-{str(next_number).zfill(3)}"
    except gspread.exceptions.APIError as e: st.error(f"API Error generating MRN: {e}"); return f"MRN-ERR-API-{datetime.now().strftime('%H%M%S')}"
    except Exception as e: st.error(f"Error generating MRN: {e}"); return f"MRN-ERR-EXC-{datetime.now().strftime('%H%M%S')}"


# --- PDF Generation Function ---
def create_indent_pdf(data: Dict[str, Any]) -> bytes:
    # ... (function remains the same) ...
    pdf = FPDF(); pdf.add_page(); pdf.set_margins(10, 10, 10); pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", "B", 16); pdf.cell(0, 10, "Material Indent Request", ln=True, align='C'); pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(95, 7, f"MRN: {data['mrn']}", ln=0); pdf.cell(95, 7, f"Date Required: {data['date']}", ln=1, align='R')
    pdf.cell(0, 7, f"Department: {data['dept']}", ln=1); pdf.ln(7)
    pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(230, 230, 230)
    col_widths = {'item': 90, 'qty': 15, 'unit': 25, 'note': 60}
    pdf.cell(col_widths['item'], 7, "Item", border=1, ln=0, align='C', fill=True); pdf.cell(col_widths['qty'], 7, "Qty", border=1, ln=0, align='C', fill=True); pdf.cell(col_widths['unit'], 7, "Unit", border=1, ln=0, align='C', fill=True); pdf.cell(col_widths['note'], 7, "Note", border=1, ln=1, align='C', fill=True)
    pdf.set_font("Helvetica", "", 9); line_height = 6
    for item_tuple in data['items']:
        item, qty, unit, note = item_tuple
        start_y = pdf.get_y()
        pdf.multi_cell(col_widths['item'], line_height, str(item), border='LR', align='L'); y1 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'], start_y); pdf.multi_cell(col_widths['qty'], line_height, str(qty), border='R', align='C'); y2 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['qty'], start_y); pdf.multi_cell(col_widths['unit'], line_height, str(unit), border='R', align='C'); y3 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['qty'] + col_widths['unit'], start_y); pdf.multi_cell(col_widths['note'], line_height, str(note if note else "-"), border='R', align='L'); y4 = pdf.get_y()
        final_y = max(y1, y2, y3, y4); pdf.line(pdf.l_margin, final_y, pdf.l_margin + sum(col_widths.values()), final_y)
        pdf.set_y(final_y); pdf.ln(0.1)
    return pdf.output()


# --- Function to Load Log Data (Cached) ---
@st.cache_data(ttl=60, show_spinner="Loading indent history...")
def load_indent_log_data() -> pd.DataFrame:
    # ... (function remains the same, uses DD-MM-YYYY) ...
    if not log_sheet: return pd.DataFrame()
    try:
        records = log_sheet.get_all_records()
        if not records: expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']; return pd.DataFrame(columns=expected_cols)
        df = pd.DataFrame(records); expected_cols = ['MRN', 'Timestamp', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
        for col in expected_cols:
            if col not in df.columns: df[col] = pd.NA
        if 'Timestamp' in df.columns: df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        if 'Date Required' in df.columns: df['Date Required'] = pd.to_datetime(df['Date Required'], format='%d-%m-%Y', errors='coerce')
        if 'Qty' in df.columns: df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0).astype(int)
        for col in ['Item', 'Unit', 'Note', 'MRN', 'Department']:
             if col in df.columns: df[col] = df[col].fillna('')
        return df.sort_values(by='Timestamp', ascending=False, na_position='last')
    except gspread.exceptions.APIError as e: st.error(f"API Error loading log: {e}"); return pd.DataFrame()
    except Exception as e: st.error(f"Error loading/cleaning log: {e}"); return pd.DataFrame()


# --- UI Tabs ---
tab1, tab2 = st.tabs(["📝 New Indent", "📊 View Indents"])

# --- TAB 1: New Indent Form ---
with tab1:
    # --- Session State Init ---
    if "form_items" not in st.session_state: st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-'}]
    if 'last_dept' not in st.session_state: st.session_state.last_dept = None
    if 'submitted_data_for_summary' not in st.session_state: st.session_state.submitted_data_for_summary = None
    # Initialize state for the number input to add items
    if 'num_items_to_add' not in st.session_state: st.session_state.num_items_to_add = 1


    # --- Helper Functions ---
    # *** MODIFIED: add_item now accepts a count ***
    def add_item(count=1):
        """Adds the specified number of blank item rows."""
        if not isinstance(count, int) or count < 1:
            count = 1 # Default to adding 1 if input is invalid
        for _ in range(count):
            new_id = f"item_{time.time_ns()}"
            st.session_state.form_items.append({'id': new_id, 'item': None, 'qty': 1, 'note': '', 'unit': '-'})

    def remove_item(item_id): st.session_state.form_items = [item for item in st.session_state.form_items if item['id'] != item_id]; ("" if st.session_state.form_items else add_item(count=1)) # Ensure one row if list becomes empty
    def clear_all_items(): st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-'}]

    # *** NEW: Callback for the Add Rows button ***
    def handle_add_items_click():
        num_to_add = st.session_state.get('num_items_to_add', 1)
        add_item(count=num_to_add)
        # Optional: Reset the number input back to 1 after adding
        st.session_state.num_items_to_add = 1


    # --- Item Select Callback ---
    def update_unit_display_and_item_value(item_id, selectbox_key):
        selected_item_name = st.session_state[selectbox_key]; unit = "-";
        if selected_item_name: unit = item_to_unit_lower.get(selected_item_name.lower(), "N/A"); unit = unit if unit else "-"
        for i, item_dict in enumerate(st.session_state.form_items):
            if item_dict['id'] == item_id: st.session_state.form_items[i]['item'] = selected_item_name if selected_item_name else None; st.session_state.form_items[i]['unit'] = unit; break

    # --- Header Inputs ---
    st.subheader("Indent Details")
    col_head1, col_head2 = st.columns(2)
    with col_head1:
        DEPARTMENTS = ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"]
        last_dept = st.session_state.get('last_dept'); dept_index = 0
        try: current_selection = st.session_state.get("selected_dept", last_dept);
        except Exception: current_selection=None
        if current_selection and current_selection in DEPARTMENTS:
            try: dept_index = DEPARTMENTS.index(current_selection)
            except ValueError: dept_index = 0
        dept = st.selectbox( "Select Department*", DEPARTMENTS, index=dept_index, key="selected_dept", help="Select the requesting department." )
    with col_head2:
        delivery_date = st.date_input( "Date Required*", value=st.session_state.get("selected_date", date.today()), min_value=date.today(), format="DD/MM/YYYY", key="selected_date", help="Select the date materials are needed." )

    st.divider(); st.subheader("Enter Items:")

    # --- Item Input Rows ---
    # ... (Item input loop remains the same) ...
    current_selected_items_in_form = [ item['item'] for item in st.session_state.form_items if item.get('item') ]
    duplicate_item_counts = Counter(current_selected_items_in_form)
    duplicates_found_dict = { item: count for item, count in duplicate_item_counts.items() if count > 1 }

    items_to_render = list(st.session_state.form_items)
    for i, item_dict in enumerate(items_to_render):
        item_id = item_dict['id']
        qty_key = f"qty_{item_id}"; note_key = f"note_{item_id}"; selectbox_key = f"item_select_{item_id}"
        if qty_key in st.session_state:
            widget_qty = st.session_state[qty_key]
            st.session_state.form_items[i]['qty'] = int(widget_qty) if isinstance(widget_qty, (int, float, str)) and str(widget_qty).isdigit() else 1
        if note_key in st.session_state: st.session_state.form_items[i]['note'] = st.session_state[note_key]
        current_item_value = st.session_state.form_items[i].get('item'); current_qty_from_dict = st.session_state.form_items[i].get('qty', 1)
        current_note = st.session_state.form_items[i].get('note', ''); current_unit = st.session_state.form_items[i].get('unit', '-')
        item_label = current_item_value if current_item_value else f"Item #{i+1}"
        is_duplicate = current_item_value and current_item_value in duplicates_found_dict
        duplicate_indicator = "⚠️ " if is_duplicate else ""
        expander_label = f"{duplicate_indicator}**{item_label}** (Qty: {current_qty_from_dict}, Unit: {current_unit})"

        with st.expander(label=expander_label, expanded=True):
            if is_duplicate:
                st.warning(f"DUPLICATE ITEM: '{current_item_value}' is selected multiple times.", icon="⚠️")
            col1, col2, col3, col4 = st.columns([4, 3, 1, 1])
            with col1: # Item Select
                try: current_item_index = master_item_names.index(current_item_value) if current_item_value else 0
                except ValueError: current_item_index = 0
                st.selectbox( "Item Select", options=master_item_names, index=current_item_index, key=selectbox_key, placeholder="Type or select an item...", label_visibility="collapsed", on_change=update_unit_display_and_item_value, args=(item_id, selectbox_key) )
            with col2: # Note
                st.text_input( "Note", value=current_note, key=note_key, placeholder="Optional note...", label_visibility="collapsed" )
            with col3: # Quantity
                st.number_input( "Quantity", min_value=1, step=1, value=current_qty_from_dict, key=qty_key, label_visibility="collapsed" )
            with col4: # Remove Button
                 if len(st.session_state.form_items) > 1: st.button("❌", key=f"remove_{item_id}", on_click=remove_item, args=(item_id,), help="Remove this item")
                 else: st.write("")

    st.divider()

    # --- MODIFIED: Add Item Controls ---
    col_add1, col_add2, col_add3 = st.columns([1, 2, 2]) # Adjust ratios as needed
    with col_add1:
        st.number_input(
            "Add:", # Compact label
            min_value=1,
            step=1,
            key='num_items_to_add', # Use this key in the callback
            label_visibility="collapsed", # Hide label, use placeholder/button text
            value=st.session_state.num_items_to_add # Set value from state
        )
    with col_add2:
        st.button(
            "➕ Add Rows",
            on_click=handle_add_items_click, # Use the new callback
            use_container_width=True
        )
    with col_add3:
         st.button("🔄 Clear Item List", on_click=clear_all_items, use_container_width=True)


    # --- Validation ---
    # ... (Validation logic remains the same) ...
    has_duplicates = bool(duplicates_found_dict)
    has_valid_items = any(item.get('item') and item.get('qty', 0) > 0 for item in st.session_state.form_items)
    current_dept_tab1 = st.session_state.get("selected_dept", "")
    submit_disabled = not has_valid_items or has_duplicates or not current_dept_tab1
    error_messages = []; tooltip_message = "Submit the current indent request."
    if not has_valid_items: error_messages.append("Add at least one valid item with quantity > 0.")
    if has_duplicates: error_messages.append(f"Remove duplicate items (marked with ⚠️): {', '.join(duplicates_found_dict.keys())}.")
    if not current_dept_tab1: error_messages.append("Select a department.")
    st.divider()
    if error_messages:
        for msg in error_messages: st.warning(f"⚠️ {msg}")
        tooltip_message = "Please fix the issues listed above."


    # --- Submission ---
    if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message):
        # ... (Submission logic remains the same) ...
        final_items_to_submit: List[Tuple[str, int, str, str]] = []; final_item_names = set();
        final_check_items = [item['item'] for item in st.session_state.form_items if item.get('item')]
        final_check_counts = Counter(final_check_items)
        final_duplicates_dict = {item: count for item, count in final_check_counts.items() if count > 1}
        if bool(final_duplicates_dict):
             st.error(f"Duplicate items still detected ({', '.join(final_duplicates_dict.keys())}). Please remove duplicates.")
             st.stop()
        for item_dict in st.session_state.form_items:
            selected_item = item_dict.get('item'); qty = item_dict.get('qty', 0); unit = item_dict.get('unit', 'N/A'); note = item_dict.get('note', '')
            if selected_item and qty > 0: final_items_to_submit.append((selected_item, qty, unit, note))
        if not final_items_to_submit: st.error("No valid items to submit."); st.stop()
        try:
            mrn = generate_mrn();
            if "ERR" in mrn: st.error(f"Failed MRN ({mrn})."); st.stop()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S");
            date_to_format = st.session_state.get("selected_date", date.today())
            formatted_date = date_to_format.strftime("%d-%m-%Y") # DD-MM-YYYY storage
            rows_to_add = [[mrn, timestamp, current_dept_tab1, formatted_date, item, str(qty), unit, note if note else "N/A"] for item, qty, unit, note in final_items_to_submit]
            if rows_to_add and log_sheet:
                with st.spinner(f"Submitting indent {mrn}..."):
                    try: log_sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED'); load_indent_log_data.clear()
                    except gspread.exceptions.APIError as e: st.error(f"API Error: {e}."); st.stop()
                    except Exception as e: st.error(f"Submission error: {e}"); st.exception(e); st.stop()
                st.session_state['submitted_data_for_summary'] = {'mrn': mrn, 'dept': current_dept_tab1, 'date': formatted_date, 'items': final_items_to_submit}
                st.session_state['last_dept'] = current_dept_tab1;
                clear_all_items();
                st.session_state.num_items_to_add = 1 # Reset number input state after submission
                st.rerun()
        except Exception as e: st.error(f"Submission error: {e}"); st.exception(e)


    # --- Post-Submission Summary ---
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
            pdf_data = create_indent_pdf(submitted_data)
            pdf_bytes: bytes = bytes(pdf_data) # Ensure bytes
            st.download_button(label="📄 Download PDF", data=pdf_bytes, file_name=f"Indent_{submitted_data['mrn']}.pdf", mime="application/pdf")
        except Exception as pdf_error: st.error(f"Could not generate PDF: {pdf_error} (Type: {type(pdf_data)})"); st.exception(pdf_error)
        if st.button("Start New Indent"): st.session_state['submitted_data_for_summary'] = None; st.session_state.num_items_to_add = 1; st.rerun()

# --- TAB 2: View Indents ---
with tab2:
    # ... (Tab 2 code remains the same) ...
    st.subheader("View Past Indent Requests")
    log_df = load_indent_log_data()
    if not log_df.empty:
        st.divider()
        with st.expander("Filter Options", expanded=True):
            dept_options = sorted([d for d in log_df['Department'].unique() if d])
            min_ts = log_df['Date Required'].dropna().min()
            max_ts = log_df['Date Required'].dropna().max()
            default_start = date.today() - pd.Timedelta(days=30)
            default_end = date.today()
            min_date_log = min_ts.date() if pd.notna(min_ts) else default_start
            max_date_log = max_ts.date() if pd.notna(max_ts) else default_end
            if min_date_log > max_date_log: min_date_log = max_date_log

            filt_col1, filt_col2, filt_col3 = st.columns([1, 1, 2])
            with filt_col1:
                filt_start_date = st.date_input("Reqd. From", value=min_date_log, min_value=min_date_log, max_value=max_date_log, key="filt_start", format="DD/MM/YYYY")
                valid_end_min = filt_start_date;
                filt_end_date = st.date_input("Reqd. To", value=max_date_log, min_value=valid_end_min, max_value=max_date_log, key="filt_end", format="DD/MM/YYYY")
            with filt_col2: selected_depts = st.multiselect("Department", options=dept_options, default=[], key="filt_dept"); mrn_search = st.text_input("MRN", key="filt_mrn", placeholder="e.g., MRN-005")
            with filt_col3: item_search = st.text_input("Item Name", key="filt_item", placeholder="e.g., Salt")
        filtered_df = log_df.copy()
        try: # Apply Filters
            if 'Date Required' in filtered_df.columns: start_ts = pd.Timestamp(filt_start_date); end_ts = pd.Timestamp(filt_end_date); date_filt_cond = (filtered_df['Date Required'].notna() & (filtered_df['Date Required'].dt.normalize() >= start_ts) & (filtered_df['Date Required'].dt.normalize() <= end_ts)); filtered_df = filtered_df[date_filt_cond]
            if selected_depts and 'Department' in filtered_df.columns: filtered_df = filtered_df[filtered_df['Department'].isin(selected_depts)]
            if mrn_search and 'MRN' in filtered_df.columns: filtered_df = filtered_df[filtered_df['MRN'].astype(str).str.contains(mrn_search, case=False, na=False)]
            if item_search and 'Item' in filtered_df.columns: filtered_df = filtered_df[filtered_df['Item'].astype(str).str.contains(item_search, case=False, na=False)]
        except Exception as filter_e: st.error(f"Filter error: {filter_e}"); filtered_df = log_df.copy()
        st.divider(); st.write(f"Displaying {len(filtered_df)} records:")
        st.dataframe( filtered_df, use_container_width=True, hide_index=True,
            column_config={
                "Date Required": st.column_config.DateColumn("Date Reqd.", format="DD/MM/YYYY"),
                "Timestamp": st.column_config.DatetimeColumn("Submitted", format="YYYY-MM-DD HH:mm"),
                "Qty": st.column_config.NumberColumn("Qty", format="%d"),
                "MRN": st.column_config.TextColumn("MRN"),
                "Department": st.column_config.TextColumn("Dept."),
                "Item": st.column_config.TextColumn("Item Name", width="medium"),
                "Unit": st.column_config.TextColumn("Unit"),
                "Note": st.column_config.TextColumn("Notes", width="large"),
             } )
    else: st.info("No indent records found or log is unavailable.")
# --- Optional Debug ---
# with st.sidebar.expander("Session State Debug"): st.json(st.session_state.to_dict())
