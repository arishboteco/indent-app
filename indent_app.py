import streamlit as st
import pandas as pd
import gspread
from gspread import Client, Spreadsheet, Worksheet
from fpdf import FPDF
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
from PIL import Image
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple, Optional, DefaultDict
import time
from operator import itemgetter # For sorting

# --- Configuration & Setup ---

try:
    logo = Image.open("logo.png")
    st.image(logo, width=75)
except FileNotFoundError:
    st.warning("Logo image 'logo.png' not found.")
except Exception as e:
    st.warning(f"Could not load logo: {e}")

st.title("Material Indent Form")

scope: List[str] = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
DEPARTMENTS = ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"]

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

# --- MODIFIED Reference Data Loading (Reads Category & Sub-Category) ---
@st.cache_data(ttl=3600, show_spinner="Fetching item reference data...")
def get_reference_data(_reference_sheet: Worksheet) -> Tuple[DefaultDict[str, List[str]], Dict[str, str], Dict[str, str], Dict[str, str]]:
    """Fetches reference data including permitted departments, category, sub-category.
    Assumes columns: 0=Item, 1=Unit, 2=Permitted Depts, 3=Category, 4=Sub-Category.
    """
    item_to_unit_lower: Dict[str, str] = {}
    item_to_category_lower: Dict[str, str] = {}
    item_to_subcategory_lower: Dict[str, str] = {}
    dept_to_items_map: DefaultDict[str, List[str]] = defaultdict(list)

    try:
        all_data: List[List[str]] = _reference_sheet.get_all_values()
        header_skipped: bool = False
        valid_departments = set(dept for dept in DEPARTMENTS if dept)

        for i, row in enumerate(all_data):
            # Ensure row has enough columns before trying to access them
            if len(row) < 5:
                if i > 0 or not header_skipped: # Skip header row check if too short
                     st.warning(f"Skipping row {i+1} in 'reference' sheet: expected 5 columns, found {len(row)}.")
                if i == 0 and ("item" in str(row[0]).lower()): # Check if it looks like a header
                     header_skipped = True
                continue # Skip rows that are too short

            if not any(str(cell).strip() for cell in row[:5]): continue # Skip empty rows (check first 5 cols)

            # Basic header detection (adjust if needed)
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower()):
                header_skipped = True
                continue

            item: str = str(row[0]).strip()
            unit: str = str(row[1]).strip()
            permitted_depts_str: str = str(row[2]).strip()
            category: str = str(row[3]).strip()
            subcategory: str = str(row[4]).strip()
            item_lower: str = item.lower()

            if item: # Process only if item name is present
                # Store mappings
                item_to_unit_lower[item_lower] = unit if unit else "N/A"
                item_to_category_lower[item_lower] = category if category else "Uncategorized" # Default category
                item_to_subcategory_lower[item_lower] = subcategory if subcategory else "General" # Default sub-category

                # Determine department mapping
                if not permitted_depts_str or permitted_depts_str.lower() == 'all':
                    for dept_name in valid_departments:
                        dept_to_items_map[dept_name].append(item)
                else:
                    departments = [dept.strip() for dept in permitted_depts_str.split(',') if dept.strip() in valid_departments]
                    for dept_name in departments:
                        dept_to_items_map[dept_name].append(item)

        # Sort item lists within each department
        for dept_name in dept_to_items_map:
            dept_to_items_map[dept_name] = sorted(list(set(dept_to_items_map[dept_name]))) # Ensure unique and sorted

        return dept_to_items_map, item_to_unit_lower, item_to_category_lower, item_to_subcategory_lower

    except gspread.exceptions.APIError as e: st.error(f"API Error loading reference: {e}"); return defaultdict(list), {}, {}, {}
    except IndexError: st.error("Error reading reference sheet. Does it have at least 5 columns (Item, Unit, Permitted Depts, Category, Sub-Category)?"); return defaultdict(list), {}, {}, {}
    except Exception as e: st.error(f"Error loading reference: {e}"); return defaultdict(list), {}, {}, {}


# --- Load Reference Data and Initialize State ---
if 'data_loaded' not in st.session_state: st.session_state.data_loaded = False

if not st.session_state.data_loaded and reference_sheet:
    dept_map, unit_map, cat_map, subcat_map = get_reference_data(reference_sheet)
    st.session_state['dept_items_map'] = dept_map
    st.session_state['item_to_unit_lower'] = unit_map
    st.session_state['item_to_category_lower'] = cat_map # Store new map
    st.session_state['item_to_subcategory_lower'] = subcat_map # Store new map
    st.session_state['available_items_for_dept'] = [""] # Initialize empty
    st.session_state.data_loaded = True
elif not reference_sheet:
     st.error("Cannot load reference data.")
     st.session_state['dept_items_map'] = defaultdict(list)
     st.session_state['item_to_unit_lower'] = {}
     st.session_state['item_to_category_lower'] = {}
     st.session_state['item_to_subcategory_lower'] = {}
     st.session_state['available_items_for_dept'] = [""]

# Initialize default form_items structure if needed
if "form_items" not in st.session_state or not st.session_state.form_items:
     st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-', 'category': None, 'subcategory': None}]


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


# --- MODIFIED PDF Generation Function (Handles Grouping) ---
def create_indent_pdf(data: Dict[str, Any]) -> bytes:
    """Creates a PDF document grouped by Category and Sub-Category."""
    pdf = FPDF(); pdf.add_page(); pdf.set_margins(10, 10, 10); pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", "B", 16); pdf.cell(0, 10, "Material Indent Request", ln=True, align='C'); pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(95, 7, f"MRN: {data['mrn']}", ln=0); pdf.cell(95, 7, f"Date Required: {data['date']}", ln=1, align='R')
    pdf.cell(0, 7, f"Department: {data['dept']}", ln=1); pdf.ln(7)

    # Table Header
    pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(230, 230, 230)
    col_widths = {'item': 90, 'qty': 15, 'unit': 25, 'note': 60} # Keep same widths
    pdf.cell(col_widths['item'], 7, "Item", border=1, ln=0, align='C', fill=True); pdf.cell(col_widths['qty'], 7, "Qty", border=1, ln=0, align='C', fill=True); pdf.cell(col_widths['unit'], 7, "Unit", border=1, ln=0, align='C', fill=True); pdf.cell(col_widths['note'], 7, "Note", border=1, ln=1, align='C', fill=True)

    current_category = None
    current_subcategory = None

    # Data['items'] is now sorted list of (item, qty, unit, note, category, subcategory) tuples
    for item_tuple in data['items']:
        item, qty, unit, note, category, subcategory = item_tuple
        category = category or "Uncategorized" # Handle None category
        subcategory = subcategory or "General" # Handle None subcategory

        # Check for Category change
        if category != current_category:
            pdf.ln(4) # Add space before new category
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_fill_color(200, 200, 200) # Slightly darker fill for category
            pdf.cell(0, 7, f"Category: {category}", ln=1, align='L', fill=True, border=1)
            current_category = category
            current_subcategory = None # Reset subcategory when category changes

        # Check for Sub-Category change
        if subcategory != current_subcategory:
            pdf.ln(1) # Smaller space before subcategory
            pdf.set_font("Helvetica", "BI", 10) # Bold Italic for subcategory
            pdf.cell(0, 6, f"  Sub-Category: {subcategory}", ln=1, align='L') # Indent slightly
            current_subcategory = subcategory

        # Print item row (same logic as before)
        pdf.set_font("Helvetica", "", 9); line_height = 6
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
    # Note: This does not load Category/SubCategory into the log view yet
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
    # Ensure form_items includes category/subcategory keys
    if "form_items" not in st.session_state or not isinstance(st.session_state.form_items, list) or not st.session_state.form_items:
        st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-', 'category': None, 'subcategory': None}]
    else:
        # Ensure existing items have the keys (e.g., after code update)
        for item_d in st.session_state.form_items:
            item_d.setdefault('category', None)
            item_d.setdefault('subcategory', None)

    if 'last_dept' not in st.session_state: st.session_state.last_dept = None
    if 'submitted_data_for_summary' not in st.session_state: st.session_state.submitted_data_for_summary = None
    if 'num_items_to_add' not in st.session_state: st.session_state.num_items_to_add = 1


    # --- Helper Functions ---
    # Add item needs to include category/subcategory Nones
    def add_item(count=1):
        if not isinstance(count, int) or count < 1: count = 1
        for _ in range(count):
            new_id = f"item_{time.time_ns()}"
            st.session_state.form_items.append({'id': new_id, 'item': None, 'qty': 1, 'note': '', 'unit': '-', 'category': None, 'subcategory': None})

    def remove_item(item_id): st.session_state.form_items = [item for item in st.session_state.form_items if item['id'] != item_id]; ("" if st.session_state.form_items else add_item(count=1))
    def clear_all_items(): st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-', 'category': None, 'subcategory': None}]

    def handle_add_items_click():
        num_to_add = st.session_state.get('num_items_to_add', 1)
        add_item(count=num_to_add)


    # --- MODIFIED Department Change Callback (resets category/subcategory) ---
    def department_changed_callback():
        selected_dept = st.session_state.get("selected_dept")
        dept_map = st.session_state.get("dept_items_map", defaultdict(list))
        available_items = [""]

        if selected_dept:
            specific_items = dept_map.get(selected_dept, [])
            # Handle potential "All" items if implemented in get_reference_data
            # all_items = dept_map.get("All Departments", [])
            # combined_items = sorted(list(set(specific_items + all_items)))
            combined_items = sorted(list(set(specific_items))) # Using only specific for now
            available_items.extend(combined_items)

        st.session_state.available_items_for_dept = available_items

        # Reset existing item selections including category/subcategory
        for i in range(len(st.session_state.form_items)):
            st.session_state.form_items[i]['item'] = None
            st.session_state.form_items[i]['unit'] = '-'
            st.session_state.form_items[i]['note'] = ''
            st.session_state.form_items[i]['category'] = None
            st.session_state.form_items[i]['subcategory'] = None


    # --- MODIFIED Item Select Callback (Updates Unit, Category, SubCategory) ---
    def item_selected_callback(item_id, selectbox_key):
        unit_map = st.session_state.get("item_to_unit_lower", {})
        cat_map = st.session_state.get("item_to_category_lower", {})
        subcat_map = st.session_state.get("item_to_subcategory_lower", {})
        selected_item_name = st.session_state.get(selectbox_key)

        unit = "-"
        category = None
        subcategory = None

        if selected_item_name:
            item_lower = selected_item_name.lower()
            unit = unit_map.get(item_lower, "N/A"); unit = unit if unit else "-"
            category = cat_map.get(item_lower) # Can be None if not found
            subcategory = subcat_map.get(item_lower) # Can be None if not found

        # Update the specific item dict in the list
        for i, item_dict in enumerate(st.session_state.form_items):
            if item_dict['id'] == item_id:
                st.session_state.form_items[i]['item'] = selected_item_name if selected_item_name else None
                st.session_state.form_items[i]['unit'] = unit
                st.session_state.form_items[i]['category'] = category
                st.session_state.form_items[i]['subcategory'] = subcategory
                break


    # --- Header Inputs ---
    st.subheader("Indent Details")
    col_head1, col_head2 = st.columns(2)
    with col_head1:
        last_dept = st.session_state.get('last_dept'); dept_index = 0
        try: current_selection = st.session_state.get("selected_dept", last_dept);
        except Exception: current_selection=None
        if current_selection and current_selection in DEPARTMENTS:
            try: dept_index = DEPARTMENTS.index(current_selection)
            except ValueError: dept_index = 0
        dept = st.selectbox( "Select Department*", DEPARTMENTS, index=dept_index, key="selected_dept", help="Select department first to filter items.", on_change=department_changed_callback )
    with col_head2:
        delivery_date = st.date_input( "Date Required*", value=st.session_state.get("selected_date", date.today()), min_value=date.today(), format="DD/MM/YYYY", key="selected_date", help="Select the date materials are needed." )

    # --- Initialize available items based on initial/current department ---
    if 'dept_items_map' in st.session_state and 'available_items_for_dept' not in st.session_state:
         department_changed_callback() # Call it once to populate based on default dept
    # Or call if department is selected but available items is somehow empty/reset
    elif st.session_state.get("selected_dept") and not st.session_state.get('available_items_for_dept'):
         department_changed_callback()


    st.divider(); st.subheader("Enter Items:")

    # --- Item Input Rows ---
    current_selected_items_in_form = [ item['item'] for item in st.session_state.form_items if item.get('item') ]
    duplicate_item_counts = Counter(current_selected_items_in_form)
    duplicates_found_dict = { item: count for item, count in duplicate_item_counts.items() if count > 1 }

    items_to_render = list(st.session_state.form_items)
    for i, item_dict in enumerate(items_to_render):
        item_id = item_dict['id']
        qty_key = f"qty_{item_id}"; note_key = f"note_{item_id}"; selectbox_key = f"item_select_{item_id}"
        # Sync state
        if qty_key in st.session_state: st.session_state.form_items[i]['qty'] = int(st.session_state[qty_key]) if isinstance(st.session_state[qty_key], (int, float, str)) and str(st.session_state[qty_key]).isdigit() else 1
        if note_key in st.session_state: st.session_state.form_items[i]['note'] = st.session_state[note_key]

        # Read current values
        current_item_value = st.session_state.form_items[i].get('item'); current_qty = st.session_state.form_items[i].get('qty', 1)
        current_note = st.session_state.form_items[i].get('note', ''); current_unit = st.session_state.form_items[i].get('unit', '-')
        current_category = st.session_state.form_items[i].get('category') # Get category
        current_subcategory = st.session_state.form_items[i].get('subcategory') # Get subcategory

        item_label = current_item_value if current_item_value else f"Item #{i+1}"
        is_duplicate = current_item_value and current_item_value in duplicates_found_dict
        duplicate_indicator = "⚠️ " if is_duplicate else ""

        # MODIFIED: Expander label might get too long, consider showing Cat/SubCat inside
        # expander_label = f"{duplicate_indicator}**{item_label}** (Qty: {current_qty}, Unit: {current_unit})"
        expander_label = f"{duplicate_indicator}**{item_label}**" # Simpler label

        with st.expander(label=expander_label, expanded=True):
            if is_duplicate: st.warning(f"DUPLICATE ITEM: '{current_item_value}' is selected multiple times.", icon="⚠️")

            # Display Cat/SubCat inside expander
            col_info1, col_info2, col_info3 = st.columns(3)
            with col_info1:
                 st.markdown(f"**Unit:** {current_unit or '-'}")
            with col_info2:
                 st.markdown(f"**Category:** {current_category or '-'}")
            with col_info3:
                 st.markdown(f"**Sub-Cat:** {current_subcategory or '-'}")

            st.divider() # Separate info from inputs

            # Input columns
            col1, col2, col3, col4 = st.columns([4, 3, 1, 1])
            with col1: # Item Select
                available_options = st.session_state.get('available_items_for_dept', [""])
                try: current_item_index = available_options.index(current_item_value) if current_item_value in available_options else 0
                except ValueError: current_item_index = 0
                st.selectbox( "Item Select", options=available_options, index=current_item_index, key=selectbox_key, placeholder="Select item for department...", label_visibility="collapsed", on_change=item_selected_callback, args=(item_id, selectbox_key) ) # Use new callback
            with col2: # Note
                st.text_input( "Note", value=current_note, key=note_key, placeholder="Optional note...", label_visibility="collapsed" )
            with col3: # Quantity
                st.number_input( "Quantity", min_value=1, step=1, value=current_qty, key=qty_key, label_visibility="collapsed" )
            with col4: # Remove Button
                 if len(st.session_state.form_items) > 1: st.button("❌", key=f"remove_{item_id}", on_click=remove_item, args=(item_id,), help="Remove this item")
                 else: st.write("")

    st.divider()

    # --- Add Item Controls ---
    col_add1, col_add2, col_add3 = st.columns([1, 2, 2])
    with col_add1: st.number_input( "Add:", min_value=1, step=1, key='num_items_to_add', label_visibility="collapsed" )
    with col_add2: st.button( "➕ Add Rows", on_click=handle_add_items_click, use_container_width=True )
    with col_add3: st.button("🔄 Clear Item List", on_click=clear_all_items, use_container_width=True)

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
        final_items_to_submit_unsorted: List[Tuple[str, int, str, str, str, str]] = [] # Now 6 elements
        final_check_items = [item['item'] for item in st.session_state.form_items if item.get('item')]
        final_check_counts = Counter(final_check_items)
        final_duplicates_dict = {item: count for item, count in final_check_counts.items() if count > 1}
        if bool(final_duplicates_dict):
             st.error(f"Duplicate items still detected ({', '.join(final_duplicates_dict.keys())}). Please remove duplicates.")
             st.stop()

        for item_dict in st.session_state.form_items:
            selected_item = item_dict.get('item')
            qty = item_dict.get('qty', 0)
            unit = item_dict.get('unit', '-') # Default unit
            note = item_dict.get('note', '')
            category = item_dict.get('category') # Get category
            subcategory = item_dict.get('subcategory') # Get subcategory

            if selected_item and qty > 0:
                final_items_to_submit_unsorted.append((
                    selected_item, qty, unit, note,
                    category or "Uncategorized", # Use default if None
                    subcategory or "General" # Use default if None
                ))

        if not final_items_to_submit_unsorted: st.error("No valid items to submit."); st.stop()

        # *** Sort items by Category, then Sub-Category, then Item Name ***
        # Handles None values by treating them as empty strings for sorting
        final_items_to_submit = sorted(
            final_items_to_submit_unsorted,
            key=lambda x: (str(x[4] or ''), str(x[5] or ''), str(x[0]))
        )

        try:
            mrn = generate_mrn();
            if "ERR" in mrn: st.error(f"Failed MRN ({mrn})."); st.stop()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S");
            date_to_format = st.session_state.get("selected_date", date.today())
            formatted_date = date_to_format.strftime("%d-%m-%Y") # DD-MM-YYYY storage

            # Prepare rows for Google Sheet (still only submitting original 4 item details)
            # Modify this if you add Category/SubCategory columns to your log sheet
            rows_to_add = [[mrn, timestamp, current_dept_tab1, formatted_date, item, str(qty), unit, note if note else "N/A"]
                           for item, qty, unit, note, category, subcategory in final_items_to_submit] # Unpack 6, use 4

            if rows_to_add and log_sheet:
                with st.spinner(f"Submitting indent {mrn}..."):
                    try: log_sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED'); load_indent_log_data.clear()
                    except gspread.exceptions.APIError as e: st.error(f"API Error: {e}."); st.stop()
                    except Exception as e: st.error(f"Submission error: {e}"); st.exception(e); st.stop()

                # Store the FULL data including category/subcategory for summary/PDF
                st.session_state['submitted_data_for_summary'] = {'mrn': mrn, 'dept': current_dept_tab1, 'date': formatted_date, 'items': final_items_to_submit} # items now has 6 elements
                st.session_state['last_dept'] = current_dept_tab1;
                clear_all_items();
                st.rerun()
        except Exception as e: st.error(f"Submission error: {e}"); st.exception(e)


    # --- Post-Submission Summary ---
    if st.session_state.get('submitted_data_for_summary'):
        submitted_data = st.session_state['submitted_data_for_summary']
        st.success(f"Indent submitted! MRN: {submitted_data['mrn']}")
        st.balloons(); st.divider(); st.subheader("Submitted Indent Summary")
        st.info(f"**MRN:** {submitted_data['mrn']} | **Dept:** {submitted_data['dept']} | **Reqd Date:** {submitted_data['date']}")

        # *** Create DataFrame with Category/SubCategory and sorted ***
        # Use the sorted final_items_to_submit stored in submitted_data
        submitted_df = pd.DataFrame(
            submitted_data['items'],
            columns=["Item", "Qty", "Unit", "Note", "Category", "Sub-Category"] # Add new columns
        )
        st.dataframe(submitted_df, hide_index=True, use_container_width=True)

        total_submitted_qty = sum(item[1] for item in submitted_data['items']) # Index 1 is still Qty
        st.markdown(f"**Total Submitted Qty:** {total_submitted_qty}"); st.divider()
        try:
            pdf_data = create_indent_pdf(submitted_data) # PDF function now handles grouping
            pdf_bytes: bytes = bytes(pdf_data)
            st.download_button(label="📄 Download PDF", data=pdf_bytes, file_name=f"Indent_{submitted_data['mrn']}.pdf", mime="application/pdf")
        except Exception as pdf_error: st.error(f"Could not generate PDF: {pdf_error} (Type: {type(pdf_data)})"); st.exception(pdf_error)
        if st.button("Start New Indent"): st.session_state['submitted_data_for_summary'] = None; st.rerun()

# --- TAB 2: View Indents ---
with tab2:
    # ... (Tab 2 code remains the same - doesn't show Category/SubCategory yet) ...
    st.subheader("View Past Indent Requests")
    log_df = load_indent_log_data() # This function still only loads original columns
    if not log_df.empty:
        st.divider()
        with st.expander("Filter Options", expanded=True):
            # ... (Filtering logic remains the same) ...
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
        # Dataframe display does not yet show Category/SubCategory from log
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
