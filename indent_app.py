import streamlit as st
import pandas as pd
import gspread
from gspread import Client, Spreadsheet, Worksheet
from fpdf import FPDF
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
from PIL import Image
from collections import Counter, defaultdict # Added defaultdict
from typing import Any, Dict, List, Tuple, Optional, DefaultDict, Union # Added Union
import time
from operator import itemgetter # For sorting
import urllib.parse # For WhatsApp link encoding

# --- Configuration & Setup ---

try:
    logo = Image.open("logo.png")
    st.image(logo, width=75)
except FileNotFoundError:
    st.warning("Logo image 'logo.png' not found.")
except Exception as e:
    st.warning(f"Could not load logo: {e}")

st.title("Material Indent Form")

# Google Sheets setup & Credentials Handling
scope: List[str] = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
DEPARTMENTS = ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"] # Define globally
TOP_N_SUGGESTIONS = 7 # How many suggestions to show

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

# --- Reference Data Loading Function ---
@st.cache_data(ttl=3600, show_spinner="Fetching item reference data...")
def get_reference_data(_reference_sheet: Worksheet) -> Tuple[DefaultDict[str, List[str]], Dict[str, str], Dict[str, str], Dict[str, str]]:
    # ... (function remains the same) ...
    item_to_unit_lower: Dict[str, str] = {}; item_to_category_lower: Dict[str, str] = {}; item_to_subcategory_lower: Dict[str, str] = {}; dept_to_items_map: DefaultDict[str, List[str]] = defaultdict(list)
    try:
        all_data: List[List[str]] = _reference_sheet.get_all_values(); header_skipped: bool = False; valid_departments = set(dept for dept in DEPARTMENTS if dept)
        for i, row in enumerate(all_data):
            if len(row) < 5:
                if i > 0 or not header_skipped: st.warning(f"Skipping row {i+1} in 'reference' sheet: expected 5 columns, found {len(row)}.")
                if i == 0 and ("item" in str(row[0]).lower()): header_skipped = True
                continue
            if not any(str(cell).strip() for cell in row[:5]): continue
            if not header_skipped and i == 0 and ("item" in str(row[0]).lower()): header_skipped = True; continue
            item: str = str(row[0]).strip(); unit: str = str(row[1]).strip(); permitted_depts_str: str = str(row[2]).strip(); category: str = str(row[3]).strip(); subcategory: str = str(row[4]).strip(); item_lower: str = item.lower()
            if item:
                item_to_unit_lower[item_lower] = unit if unit else "N/A"; item_to_category_lower[item_lower] = category if category else "Uncategorized"; item_to_subcategory_lower[item_lower] = subcategory if subcategory else "General"
                if not permitted_depts_str or permitted_depts_str.lower() == 'all':
                    for dept_name in valid_departments: dept_to_items_map[dept_name].append(item)
                else:
                    departments = [dept.strip() for dept in permitted_depts_str.split(',') if dept.strip() in valid_departments]
                    for dept_name in departments: dept_to_items_map[dept_name].append(item)
        for dept_name in dept_to_items_map: dept_to_items_map[dept_name] = sorted(list(set(dept_to_items_map[dept_name])))
        return dept_to_items_map, item_to_unit_lower, item_to_category_lower, item_to_subcategory_lower
    except gspread.exceptions.APIError as e: st.error(f"API Error loading reference: {e}"); return defaultdict(list), {}, {}, {}
    except IndexError: st.error("Error reading reference sheet. Ensure 5 columns: Item, Unit, Permitted Depts, Category, Sub-Category."); return defaultdict(list), {}, {}, {}
    except Exception as e: st.error(f"Error loading reference: {e}"); return defaultdict(list), {}, {}, {}

# --- Load Reference Data ---
if 'data_loaded' not in st.session_state: st.session_state.data_loaded = False
if not st.session_state.data_loaded and reference_sheet:
    dept_map, unit_map, cat_map, subcat_map = get_reference_data(reference_sheet)
    st.session_state['dept_items_map'] = dept_map; st.session_state['item_to_unit_lower'] = unit_map
    st.session_state['item_to_category_lower'] = cat_map; st.session_state['item_to_subcategory_lower'] = subcat_map
    st.session_state['available_items_for_dept'] = [""]; st.session_state.data_loaded = True
elif not reference_sheet:
     st.error("Cannot load reference data.")
     st.session_state['dept_items_map'] = defaultdict(list); st.session_state['item_to_unit_lower'] = {}; st.session_state['item_to_category_lower'] = {}; st.session_state['item_to_subcategory_lower'] = {}; st.session_state['available_items_for_dept'] = [""]

# --- Function to Load Log Data (Cached) ---
@st.cache_data(ttl=300, show_spinner="Loading indent history...") # Cache log slightly longer
def load_indent_log_data() -> pd.DataFrame:
    # ... (function now handles 'Requested By' column) ...
    if not log_sheet: return pd.DataFrame()
    try:
        records = log_sheet.get_all_records(head=1)
        if not records: expected_cols = ['MRN', 'Timestamp', 'Requested By', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']; return pd.DataFrame(columns=expected_cols)
        df = pd.DataFrame(records); expected_cols = ['MRN', 'Timestamp', 'Requested By', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
        for col in expected_cols:
            if col not in df.columns: df[col] = pd.NA
        if 'Timestamp' in df.columns: df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        if 'Date Required' in df.columns: df['Date Required'] = pd.to_datetime(df['Date Required'], format='%d-%m-%Y', errors='coerce')
        if 'Qty' in df.columns: df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0).astype(int)
        for col in ['Item', 'Unit', 'Note', 'MRN', 'Department', 'Requested By']:
             if col in df.columns: df[col] = df[col].fillna('')
        display_cols = [col for col in expected_cols if col in df.columns]; df = df[display_cols]
        # Ensure Timestamp is datetime for sorting, drop rows where it failed parsing
        df = df.dropna(subset=['Timestamp'])
        return df.sort_values(by='Timestamp', ascending=False, na_position='last')
    except gspread.exceptions.APIError as e: st.error(f"API Error loading log: {e}"); return pd.DataFrame()
    except Exception as e: st.error(f"Error loading/cleaning log: {e}"); return pd.DataFrame()

# --- NEW Function: Calculate Top Items per Department (Cached) ---
@st.cache_data(ttl=3600, show_spinner="Analyzing history for suggestions...") # Cache for an hour
def calculate_top_items_per_dept(log_df: pd.DataFrame, top_n: int = 7) -> Dict[str, List[str]]:
    """Calculates the top N most frequent items requested per department."""
    if log_df.empty or 'Department' not in log_df.columns or 'Item' not in log_df.columns:
        return {}

    # Ensure 'Item' column is string and handle potential NaN/empty strings
    log_df_clean = log_df.dropna(subset=['Department', 'Item'])
    log_df_clean = log_df_clean[log_df_clean['Item'] != '']
    log_df_clean['Item'] = log_df_clean['Item'].astype(str)

    if log_df_clean.empty:
        return {}

    # Group by Department, count item frequency, get top N
    try:
        top_items = log_df_clean.groupby('Department')['Item'] \
                              .apply(lambda x: x.value_counts().head(top_n).index.tolist())
        return top_items.to_dict()
    except Exception as e:
        st.warning(f"Could not calculate top items: {e}")
        return {}

# --- Load historical data for suggestions ---
# We need the log_df available early to calculate suggestions
log_data_for_suggestions = load_indent_log_data()
top_items_map = calculate_top_items_per_dept(log_data_for_suggestions, top_n=TOP_N_SUGGESTIONS)
st.session_state['top_items_map'] = top_items_map # Store in state for access


# --- Initialize Session State Variables ---
if "form_items" not in st.session_state or not isinstance(st.session_state.form_items, list) or not st.session_state.form_items:
     st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-', 'category': None, 'subcategory': None}]
else:
    for item_d in st.session_state.form_items: item_d.setdefault('category', None); item_d.setdefault('subcategory', None)
if 'last_dept' not in st.session_state: st.session_state.last_dept = None
if 'submitted_data_for_summary' not in st.session_state: st.session_state.submitted_data_for_summary = None
if 'num_items_to_add' not in st.session_state: st.session_state.num_items_to_add = 1
if 'requested_by' not in st.session_state: st.session_state.requested_by = ""


# --- MRN Generation ---
def generate_mrn() -> str:
    # ... (function remains the same) ...
    if not log_sheet: return f"MRN-ERR-NOSHEET"
    try: all_mrns = log_sheet.col_values(1); next_number = 1
    except gspread.exceptions.APIError as e: st.error(f"API Error fetching MRNs: {e}"); return f"MRN-ERR-API-{datetime.now().strftime('%H%M%S')}" # Handle potential read error
    except Exception as e: st.error(f"Error fetching MRNs: {e}"); return f"MRN-ERR-EXC-{datetime.now().strftime('%H%M%S')}"
    if len(all_mrns) > 1:
        last_valid_num = 0
        for mrn_str in reversed(all_mrns):
            if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit(): last_valid_num = int(mrn_str[4:]); break
        if last_valid_num == 0: non_empty_count = sum(1 for v in all_mrns if v); last_valid_num = max(0, non_empty_count - 1)
        next_number = last_valid_num + 1
    return f"MRN-{str(next_number).zfill(3)}"


# --- PDF Generation Function ---
def create_indent_pdf(data: Dict[str, Any]) -> bytes:
    # ... (function remains the same) ...
    pdf = FPDF(); pdf.add_page(); pdf.set_margins(10, 10, 10); pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", "B", 16); pdf.cell(0, 10, "Material Indent Request", ln=True, align='C'); pdf.ln(8)
    pdf.set_font("Helvetica", "", 11); pdf.cell(95, 6, f"MRN: {data.get('mrn', 'N/A')}", ln=0); pdf.cell(95, 6, f"Requested By: {data.get('requester', 'N/A')}", ln=1, align='R')
    pdf.cell(95, 6, f"Department: {data.get('dept', 'N/A')}", ln=0); pdf.cell(95, 6, f"Date Required: {data.get('date', 'N/A')}", ln=1, align='R'); pdf.ln(6)
    pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(230, 230, 230); col_widths = {'item': 90, 'qty': 15, 'unit': 25, 'note': 60}
    pdf.cell(col_widths['item'], 7, "Item", border=1, ln=0, align='C', fill=True); pdf.cell(col_widths['qty'], 7, "Qty", border=1, ln=0, align='C', fill=True); pdf.cell(col_widths['unit'], 7, "Unit", border=1, ln=0, align='C', fill=True); pdf.cell(col_widths['note'], 7, "Note", border=1, ln=1, align='C', fill=True)
    current_category = None; current_subcategory = None; items_data = data.get('items', [])
    if not isinstance(items_data, list): items_data = []
    for item_tuple in items_data:
        if len(item_tuple) < 6: continue
        item, qty, unit, note, category, subcategory = item_tuple
        category = category or "Uncategorized"; subcategory = subcategory or "General"
        if category != current_category:
            pdf.ln(3); pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(210, 210, 210)
            pdf.cell(0, 6, f"Category: {category}", ln=1, align='L', fill=True, border='LTRB')
            current_category = category; current_subcategory = None; pdf.set_fill_color(230, 230, 230)
        if subcategory != current_subcategory:
            pdf.ln(1); pdf.set_font("Helvetica", "BI", 9)
            pdf.cell(0, 5, f"  Sub-Category: {subcategory}", ln=1, align='L')
            current_subcategory = subcategory
        pdf.set_font("Helvetica", "", 9); line_height = 5.5; start_y = pdf.get_y()
        pdf.multi_cell(col_widths['item'], line_height, str(item), border='LR', align='L'); y1 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'], start_y); pdf.multi_cell(col_widths['qty'], line_height, str(qty), border='R', align='C'); y2 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['qty'], start_y); pdf.multi_cell(col_widths['unit'], line_height, str(unit), border='R', align='C'); y3 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['qty'] + col_widths['unit'], start_y); pdf.multi_cell(col_widths['note'], line_height, str(note if note else "-"), border='R', align='L'); y4 = pdf.get_y()
        final_y = max(start_y + line_height, y1, y2, y3, y4); pdf.line(pdf.l_margin, final_y, pdf.l_margin + sum(col_widths.values()), final_y)
        pdf.set_y(final_y); pdf.ln(0.1)
    return pdf.output()


# --- UI Tabs ---
tab1, tab2 = st.tabs(["📝 New Indent", "📊 View Indents"])

# --- TAB 1: New Indent Form ---
with tab1:
    # --- Helper Functions ---
    def add_item(count=1):
        if not isinstance(count, int) or count < 1: count = 1
        for _ in range(count): new_id = f"item_{time.time_ns()}"; st.session_state.form_items.append({'id': new_id, 'item': None, 'qty': 1, 'note': '', 'unit': '-', 'category': None, 'subcategory': None})
    def remove_item(item_id): st.session_state.form_items = [item for item in st.session_state.form_items if item['id'] != item_id]; ("" if st.session_state.form_items else add_item(count=1))
    def clear_all_items(): st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '', 'unit': '-', 'category': None, 'subcategory': None}]
    def handle_add_items_click(): num_to_add = st.session_state.get('num_items_to_add', 1); add_item(count=num_to_add)

    # *** NEW: Helper function to add a suggested item ***
    def add_suggested_item(item_name_to_add):
        if item_name_to_add:
            # Check if already in list
            current_items = [item_dict.get('item') for item_dict in st.session_state.form_items]
            if item_name_to_add in current_items:
                st.toast(f"'{item_name_to_add}' is already in the list.", icon="ℹ️")
                return

            # Find details
            unit_map = st.session_state.get("item_to_unit_lower", {})
            cat_map = st.session_state.get("item_to_category_lower", {})
            subcat_map = st.session_state.get("item_to_subcategory_lower", {})
            item_lower = item_name_to_add.lower()
            unit = unit_map.get(item_lower, "-"); unit = unit if unit else "-"
            category = cat_map.get(item_lower)
            subcategory = subcat_map.get(item_lower)

            # Add new row with details
            new_id = f"item_{time.time_ns()}"
            st.session_state.form_items.append({
                'id': new_id,
                'item': item_name_to_add,
                'qty': 1, # Default qty
                'note': '', # Default note
                'unit': unit,
                'category': category,
                'subcategory': subcategory
            })


    # --- Department Change Callback ---
    def department_changed_callback():
        selected_dept = st.session_state.get("selected_dept"); dept_map = st.session_state.get("dept_items_map", defaultdict(list)); available_items = [""]
        if selected_dept: specific_items = dept_map.get(selected_dept, []); combined_items = sorted(list(set(specific_items))); available_items.extend(combined_items)
        st.session_state.available_items_for_dept = available_items
        for i in range(len(st.session_state.form_items)): # Reset items
            st.session_state.form_items[i]['item'] = None; st.session_state.form_items[i]['unit'] = '-'; st.session_state.form_items[i]['note'] = ''; st.session_state.form_items[i]['category'] = None; st.session_state.form_items[i]['subcategory'] = None

    # --- Item Selection Callback ---
    def item_selected_callback(item_id, selectbox_key):
        unit_map = st.session_state.get("item_to_unit_lower", {}); cat_map = st.session_state.get("item_to_category_lower", {}); subcat_map = st.session_state.get("item_to_subcategory_lower", {})
        selected_item_name = st.session_state.get(selectbox_key); unit = "-"; category = None; subcategory = None
        if selected_item_name:
            item_lower = selected_item_name.lower(); unit = unit_map.get(item_lower, "-"); unit = unit if unit else "-"
            category = cat_map.get(item_lower); subcategory = subcat_map.get(item_lower)
        for i, item_dict in enumerate(st.session_state.form_items):
            if item_dict['id'] == item_id:
                st.session_state.form_items[i]['item'] = selected_item_name if selected_item_name else None; st.session_state.form_items[i]['unit'] = unit
                st.session_state.form_items[i]['category'] = category; st.session_state.form_items[i]['subcategory'] = subcategory; break

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
    requester_name = st.text_input("Your Name / Requested By*", key="requested_by", value=st.session_state.requested_by, help="Enter the name of the person requesting the items.")

    # --- Initialize available items ---
    if 'dept_items_map' in st.session_state and 'available_items_for_dept' not in st.session_state: department_changed_callback()
    elif st.session_state.get("selected_dept") and not st.session_state.get('available_items_for_dept'): department_changed_callback()

    st.divider()

    # --- NEW: Suggested Items Section ---
    selected_dept_for_suggestions = st.session_state.get("selected_dept")
    if selected_dept_for_suggestions and 'top_items_map' in st.session_state:
        suggestions = st.session_state.top_items_map.get(selected_dept_for_suggestions, [])
        items_already_in_form = [item_d.get('item') for item_d in st.session_state.form_items if item_d.get('item')]
        # Filter suggestions to exclude items already in the form
        valid_suggestions = [item for item in suggestions if item not in items_already_in_form]

        if valid_suggestions:
            st.subheader("✨ Quick Add Common Items")
            # Display buttons in columns - adjust number of columns as needed
            num_suggestion_cols = min(len(valid_suggestions), 5) # Max 5 suggestions per row
            suggestion_cols = st.columns(num_suggestion_cols)
            for idx, item_name in enumerate(valid_suggestions):
                col_index = idx % num_suggestion_cols
                with suggestion_cols[col_index]:
                    # Use item name in key for uniqueness
                    st.button(
                        f"+ {item_name}",
                        key=f"suggest_{selected_dept_for_suggestions}_{item_name}", # More specific key
                        on_click=add_suggested_item,
                        args=(item_name,),
                        use_container_width=True
                    )
            st.divider() # Divider after suggestions

    st.subheader("Enter Items:")

    # --- Item Input Rows ---
    # ... (Item input loop remains the same) ...
    current_selected_items_in_form = [ item['item'] for item in st.session_state.form_items if item.get('item') ]
    duplicate_item_counts = Counter(current_selected_items_in_form); duplicates_found_dict = { item: count for item, count in duplicate_item_counts.items() if count > 1 }
    items_to_render = list(st.session_state.form_items)
    for i, item_dict in enumerate(items_to_render):
        item_id = item_dict['id']; qty_key = f"qty_{item_id}"; note_key = f"note_{item_id}"; selectbox_key = f"item_select_{item_id}"
        if qty_key in st.session_state: st.session_state.form_items[i]['qty'] = int(st.session_state[qty_key]) if isinstance(st.session_state[qty_key], (int, float, str)) and str(st.session_state[qty_key]).isdigit() else 1
        if note_key in st.session_state: st.session_state.form_items[i]['note'] = st.session_state[note_key]
        current_item_value = st.session_state.form_items[i].get('item'); current_qty = st.session_state.form_items[i].get('qty', 1)
        current_note = st.session_state.form_items[i].get('note', ''); current_unit = st.session_state.form_items[i].get('unit', '-')
        current_category = st.session_state.form_items[i].get('category'); current_subcategory = st.session_state.form_items[i].get('subcategory')
        item_label = current_item_value if current_item_value else f"Item #{i+1}"; is_duplicate = current_item_value and current_item_value in duplicates_found_dict
        duplicate_indicator = "⚠️ " if is_duplicate else ""; expander_label = f"{duplicate_indicator}**{item_label}**"
        with st.expander(label=expander_label, expanded=True):
            if is_duplicate: st.warning(f"DUPLICATE ITEM: '{current_item_value}' is selected multiple times.", icon="⚠️")
            st.caption(f"Category: {current_category or '-'} | Sub-Cat: {current_subcategory or '-'}")
            col1, col2, col3, col4 = st.columns([4, 3, 1, 1])
            with col1:
                available_options = st.session_state.get('available_items_for_dept', [""])
                try: current_item_index = available_options.index(current_item_value) if current_item_value in available_options else 0
                except ValueError: current_item_index = 0
                st.selectbox( "Item Select", options=available_options, index=current_item_index, key=selectbox_key, placeholder="Select item for department...", label_visibility="collapsed", on_change=item_selected_callback, args=(item_id, selectbox_key) )
            with col2: st.text_input( "Note", value=current_note, key=note_key, placeholder="Optional note...", label_visibility="collapsed" )
            with col3: st.number_input( "Quantity", min_value=1, step=1, value=current_qty, key=qty_key, label_visibility="collapsed" ); st.caption(f"Unit: {current_unit or '-'}")
            with col4:
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
    has_duplicates = bool(duplicates_found_dict); has_valid_items = any(item.get('item') and item.get('qty', 0) > 0 for item in st.session_state.form_items)
    current_dept_tab1 = st.session_state.get("selected_dept", ""); requester_name_filled = bool(st.session_state.get("requested_by", ""))
    submit_disabled = not has_valid_items or has_duplicates or not current_dept_tab1 or not requester_name_filled
    error_messages = []; tooltip_message = "Submit the current indent request."
    if not has_valid_items: error_messages.append("Add at least one valid item with quantity > 0.")
    if has_duplicates: error_messages.append(f"Remove duplicate items (marked with ⚠️): {', '.join(duplicates_found_dict.keys())}.")
    if not current_dept_tab1: error_messages.append("Select a department.")
    if not requester_name_filled: error_messages.append("Enter the requester's name.")
    st.divider()
    if error_messages:
        for msg in error_messages: st.warning(f"⚠️ {msg}")
        tooltip_message = "Please fix the issues listed above."

    # --- Submission ---
    if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message):
        # ... (Submission logic remains the same) ...
        final_items_to_submit_unsorted: List[Tuple[str, int, str, str, Optional[str], Optional[str]]] = []
        final_check_items = [item['item'] for item in st.session_state.form_items if item.get('item')]; final_check_counts = Counter(final_check_items)
        final_duplicates_dict = {item: count for item, count in final_check_counts.items() if count > 1}
        if bool(final_duplicates_dict): st.error(f"Duplicate items detected ({', '.join(final_duplicates_dict.keys())})."); st.stop()
        for item_dict in st.session_state.form_items:
            selected_item = item_dict.get('item'); qty = item_dict.get('qty', 0); unit = item_dict.get('unit', '-'); note = item_dict.get('note', '')
            category = item_dict.get('category'); subcategory = item_dict.get('subcategory')
            if selected_item and qty > 0: final_items_to_submit_unsorted.append(( selected_item, qty, unit, note, category or "Uncategorized", subcategory or "General" ))
        if not final_items_to_submit_unsorted: st.error("No valid items to submit."); st.stop()
        final_items_to_submit = sorted( final_items_to_submit_unsorted, key=lambda x: (str(x[4] or ''), str(x[5] or ''), str(x[0])) )
        requester = st.session_state.get("requested_by", "").strip();
        if not requester: st.error("Requester name cannot be empty."); st.stop()
        try:
            mrn = generate_mrn();
            if "ERR" in mrn: st.error(f"Failed MRN ({mrn})."); st.stop()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S"); date_to_format = st.session_state.get("selected_date", date.today()); formatted_date = date_to_format.strftime("%d-%m-%Y")
            rows_to_add = [[mrn, timestamp, requester, current_dept_tab1, formatted_date, item, str(qty), unit, note if note else "N/A"] for item, qty, unit, note, cat, subcat in final_items_to_submit]
            if rows_to_add and log_sheet:
                with st.spinner(f"Submitting indent {mrn}..."):
                    try: log_sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED'); load_indent_log_data.clear(); calculate_top_items_per_dept.clear() # Clear suggestion cache too
                    except gspread.exceptions.APIError as e: st.error(f"API Error: {e}."); st.stop()
                    except Exception as e: st.error(f"Submission error: {e}"); st.exception(e); st.stop()
                st.session_state['submitted_data_for_summary'] = {'mrn': mrn, 'dept': current_dept_tab1, 'date': formatted_date, 'requester': requester, 'items': final_items_to_submit}
                st.session_state['last_dept'] = current_dept_tab1; clear_all_items(); st.rerun()
        except Exception as e: st.error(f"Submission error: {e}"); st.exception(e)


    # --- Post-Submission Summary ---
    if st.session_state.get('submitted_data_for_summary'):
        submitted_data = st.session_state['submitted_data_for_summary']
        st.success(f"Indent submitted! MRN: {submitted_data['mrn']}")
        st.balloons(); st.divider(); st.subheader("Submitted Indent Summary")
        st.info(f"**MRN:** {submitted_data['mrn']} | **Dept:** {submitted_data['dept']} | **Reqd Date:** {submitted_data['date']} | **By:** {submitted_data.get('requester', 'N/A')}")
        submitted_df = pd.DataFrame( submitted_data['items'], columns=["Item", "Qty", "Unit", "Note", "Category", "Sub-Category"] )
        st.dataframe(submitted_df, hide_index=True, use_container_width=True, column_config={ "Category": st.column_config.TextColumn("Category"), "Sub-Category": st.column_config.TextColumn("Sub-Cat") })
        total_submitted_qty = sum(item[1] for item in submitted_data['items'])
        st.markdown(f"**Total Submitted Qty:** {total_submitted_qty}"); st.divider()
        # Buttons side-by-side
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            try: pdf_data = create_indent_pdf(submitted_data); pdf_bytes: bytes = bytes(pdf_data); st.download_button(label="📄 Download PDF", data=pdf_bytes, file_name=f"Indent_{submitted_data['mrn']}.pdf", mime="application/pdf", use_container_width=True)
            except Exception as pdf_error: st.error(f"Could not generate PDF: {pdf_error} (Type: {type(pdf_data)})"); st.exception(pdf_error)
        with col_btn2:
            try:
                wa_text = f"Indent Submitted:\nMRN: {submitted_data.get('mrn', 'N/A')}\nDepartment: {submitted_data.get('dept', 'N/A')}\nRequested By: {submitted_data.get('requester', 'N/A')}\nDate Required: {submitted_data.get('date', 'N/A')}\n\nPlease see attached PDF for item details."
                encoded_text = urllib.parse.quote_plus(wa_text); wa_url = f"https://wa.me/?text={encoded_text}"
                st.link_button("✅ Prepare WhatsApp Message", wa_url, use_container_width=True)
            except Exception as wa_e: st.error(f"Could not create WhatsApp link: {wa_e}")
        st.caption("NOTE: To share on WhatsApp, first Download PDF, then click Prepare WhatsApp Message, choose contact/group, and MANUALLY attach the downloaded PDF before sending.")
        st.divider()
        if st.button("Start New Indent"): st.session_state['submitted_data_for_summary'] = None; st.rerun()

# --- TAB 2: View Indents ---
with tab2:
    # ... (Tab 2 code remains the same) ...
    st.subheader("View Past Indent Requests")
    log_df_tab2 = load_indent_log_data() # Use a different variable name to avoid conflict if log_df is used elsewhere
    if not log_df_tab2.empty:
        st.divider()
        with st.expander("Filter Options", expanded=True):
            dept_options = sorted([d for d in log_df_tab2['Department'].unique() if d and d != ''])
            requester_options = sorted([r for r in log_df_tab2['Requested By'].unique() if r and r != '']) if 'Requested By' in log_df_tab2.columns else []
            min_ts = log_df_tab2['Date Required'].dropna().min(); max_ts = log_df_tab2['Date Required'].dropna().max()
            default_start = date.today() - pd.Timedelta(days=90); default_end = date.today()
            min_date_log = min_ts.date() if pd.notna(min_ts) else default_start; max_date_log = max_ts.date() if pd.notna(max_ts) else default_end
            calculated_default_start = max(min_date_log, default_start) if min_date_log > default_start else default_start
            if calculated_default_start > max_date_log : calculated_default_start = min_date_log
            if min_date_log > max_date_log: min_date_log = max_date_log
            filt_col1, filt_col2, filt_col3 = st.columns([1, 1, 2])
            with filt_col1:
                filt_start_date = st.date_input("Reqd. From", value=calculated_default_start, min_value=min_date_log, max_value=max_date_log, key="filt_start", format="DD/MM/YYYY")
                valid_end_min = filt_start_date; filt_end_date = st.date_input("Reqd. To", value=max_date_log, min_value=valid_end_min, max_value=max_date_log, key="filt_end", format="DD/MM/YYYY")
            with filt_col2:
                selected_depts = st.multiselect("Department", options=dept_options, default=[], key="filt_dept")
                if requester_options: selected_requesters = st.multiselect("Requested By", options=requester_options, default=[], key="filt_req")
            with filt_col3: mrn_search = st.text_input("MRN", key="filt_mrn", placeholder="e.g., MRN-005"); item_search = st.text_input("Item Name", key="filt_item", placeholder="e.g., Salt")
        st.caption("Showing indents required in the last 90 days by default. Use filters above to view older records.")
        filtered_df = log_df_tab2.copy()
        try: # Apply Filters
            start_filter_ts = pd.Timestamp(st.session_state.filt_start); end_filter_ts = pd.Timestamp(st.session_state.filt_end)
            date_filt_cond = (filtered_df['Date Required'].notna() & (filtered_df['Date Required'].dt.normalize() >= start_filter_ts) & (filtered_df['Date Required'].dt.normalize() <= end_filter_ts)); filtered_df = filtered_df[date_filt_cond]
            if st.session_state.filt_dept: filtered_df = filtered_df[filtered_df['Department'].isin(st.session_state.filt_dept)]
            if requester_options and 'filt_req' in st.session_state and st.session_state.filt_req and 'Requested By' in filtered_df.columns: filtered_df = filtered_df[filtered_df['Requested By'].isin(st.session_state.filt_req)]
            if st.session_state.filt_mrn: filtered_df = filtered_df[filtered_df['MRN'].astype(str).str.contains(st.session_state.filt_mrn, case=False, na=False)]
            if st.session_state.filt_item: filtered_df = filtered_df[filtered_df['Item'].astype(str).str.contains(st.session_state.filt_item, case=False, na=False)]
        except Exception as filter_e: st.error(f"Filter error: {filter_e}"); filtered_df = log_df_tab2.copy()
        st.divider(); st.write(f"Displaying {len(filtered_df)} records based on filters:")
        st.dataframe( filtered_df, use_container_width=True, hide_index=True,
            column_config={ "Date Required": st.column_config.DateColumn("Date Reqd.", format="DD/MM/YYYY"), "Timestamp": st.column_config.DatetimeColumn("Submitted", format="YYYY-MM-DD HH:mm"), "Requested By": st.column_config.TextColumn("Req. By"), "Qty": st.column_config.NumberColumn("Qty", format="%d"), "MRN": st.column_config.TextColumn("MRN"), "Department": st.column_config.TextColumn("Dept."), "Item": st.column_config.TextColumn("Item Name", width="medium"), "Unit": st.column_config.TextColumn("Unit"), "Note": st.column_config.TextColumn("Notes", width="large"), } )
    else: st.info("No indent records found or log is unavailable.")
# --- Optional Debug ---
# with st.sidebar.expander("Session State Debug"): st.json(st.session_state.to_dict())
