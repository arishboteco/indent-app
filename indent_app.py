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

# --- Main Application Title ---
st.title("Material Indent Form")

# Google Sheets setup & Credentials Handling
scope: List[str] = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
DEPARTMENTS = ["", "Kitchen", "Bar", "Housekeeping", "Admin", "Maintenance"] # Define globally
TOP_N_SUGGESTIONS = 7 # How many suggestions to show

@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def connect_gsheets():
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("Missing GCP credentials in st.secrets!")
            return None, None, None
        json_creds_data: Any = st.secrets["gcp_service_account"]
        if isinstance(json_creds_data, str):
            try:
                creds_dict: Dict[str, Any] = json.loads(json_creds_data)
            except json.JSONDecodeError:
                st.error("Error parsing GCP credentials string from st.secrets.")
                return None, None, None
        elif isinstance(json_creds_data, dict):
            creds_dict = json_creds_data
        else:
            st.error("GCP credentials in st.secrets are not in a valid format (string or dict).")
            return None, None, None
        
        creds: ServiceAccountCredentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client: Client = gspread.authorize(creds)
        
        try:
            indent_log_spreadsheet: Spreadsheet = client.open("Indent Log")
            log_sheet: Worksheet = indent_log_spreadsheet.sheet1 # Main data logging sheet
            reference_sheet: Worksheet = indent_log_spreadsheet.worksheet("reference") # Item reference data
            return client, log_sheet, reference_sheet
        except gspread.exceptions.SpreadsheetNotFound:
            st.error("Spreadsheet 'Indent Log' not found. Please ensure it exists and the service account has access.")
            return None, None, None
        except gspread.exceptions.WorksheetNotFound:
            st.error("Worksheet 'Sheet1' (for log) or 'reference' not found in 'Indent Log' spreadsheet.")
            return None, None, None
        except gspread.exceptions.APIError as e:
            st.error(f"Google API Error connecting to sheets: {e}")
            return None, None, None
    except json.JSONDecodeError: # Should be caught earlier, but good as a fallback
        st.error("Error parsing GCP credentials JSON during setup.")
        return None, None, None
    except gspread.exceptions.RequestError as e: # Network or auth issues during gspread.authorize
        st.error(f"Network or authorization error connecting to Google Sheets: {e}")
        return None, None, None
    except Exception as e:
        st.error(f"An unexpected error occurred during Google Sheets setup: {e}")
        st.exception(e)
        return None, None, None

client, log_sheet, reference_sheet = connect_gsheets()

if not client or not log_sheet or not reference_sheet:
    st.error("Failed to connect to Google Sheets. Application cannot proceed.")
    st.stop()

# --- Reference Data Loading Function (Reads Item, Purchase Unit, Base Unit, Conversion Factor, Category & Sub-Category) ---
@st.cache_data(ttl=3600, show_spinner="Fetching item reference data...")
def get_reference_data(_reference_sheet: Worksheet) -> Tuple[
    DefaultDict[str, List[str]],  # dept_to_items_map
    Dict[str, str],              # item_to_default_purchase_unit_lower
    Dict[str, str],              # item_to_base_unit_lower
    Dict[str, float],            # item_to_conversion_factor_lower
    Dict[str, str],              # item_to_category_lower
    Dict[str, str]               # item_to_subcategory_lower
]:
    item_to_default_purchase_unit_lower: Dict[str, str] = {}
    item_to_base_unit_lower: Dict[str, str] = {}
    item_to_conversion_factor_lower: Dict[str, float] = {}
    item_to_category_lower: Dict[str, str] = {}
    item_to_subcategory_lower: Dict[str, str] = {}
    dept_to_items_map: DefaultDict[str, List[str]] = defaultdict(list)

    try:
        # IMPORTANT: Assumes first row of 'reference' sheet are these exact headers:
        # Item, Unit, BaseUnit, ConversionFactor, Permitted Depts, Category, Sub-Category
        all_records = _reference_sheet.get_all_records() # Reads data assuming first row is header
        valid_departments = set(dept for dept in DEPARTMENTS if dept)

        for i, row_dict in enumerate(all_records):
            item = str(row_dict.get("Item", "")).strip()
            # "Unit" is your existing column for the default purchase unit
            default_purchase_unit = str(row_dict.get("Unit", "")).strip()
            base_unit = str(row_dict.get("BaseUnit", "")).strip() # New column
            conversion_factor_str = str(row_dict.get("ConversionFactor", "")).strip() # New column
            
            permitted_depts_str = str(row_dict.get("Permitted Depts", "")).strip()
            category = str(row_dict.get("Category", "")).strip()
            subcategory = str(row_dict.get("Sub-Category", "")).strip()
            item_lower = item.lower()

            if not all([item, default_purchase_unit, base_unit, conversion_factor_str]):
                if item or default_purchase_unit or base_unit or conversion_factor_str:
                    st.warning(f"Skipping row {i+2} in 'reference' sheet due to missing core item/unit data: Item='{item}'")
                continue
            
            try:
                conversion_factor = float(conversion_factor_str)
                if conversion_factor <= 0:
                    st.warning(f"Skipping item '{item}' (row {i+2}) due to invalid (non-positive) conversion factor: {conversion_factor_str}")
                    continue
            except ValueError:
                st.warning(f"Skipping item '{item}' (row {i+2}) due to non-numeric conversion factor: {conversion_factor_str}")
                continue

            if item:
                item_to_default_purchase_unit_lower[item_lower] = default_purchase_unit
                item_to_base_unit_lower[item_lower] = base_unit
                item_to_conversion_factor_lower[item_lower] = conversion_factor
                item_to_category_lower[item_lower] = category if category else "Uncategorized"
                item_to_subcategory_lower[item_lower] = subcategory if subcategory else "General"

                if not permitted_depts_str or permitted_depts_str.lower() == 'all':
                    for dept_name in valid_departments:
                        dept_to_items_map[dept_name].append(item)
                else:
                    departments_for_item = [d.strip() for d in permitted_depts_str.split(',') if d.strip() in valid_departments]
                    for dept_name in departments_for_item:
                        dept_to_items_map[dept_name].append(item)

        for dept_name in dept_to_items_map:
            dept_to_items_map[dept_name] = sorted(list(set(dept_to_items_map[dept_name])))
            
        return (dept_to_items_map, item_to_default_purchase_unit_lower, item_to_base_unit_lower,
                item_to_conversion_factor_lower, item_to_category_lower, item_to_subcategory_lower)

    except gspread.exceptions.APIError as e:
        st.error(f"API Error loading reference data: {e}")
    except Exception as e:
        st.error(f"An unexpected error occurred while loading reference data: {e}")
        st.exception(e)
    
    return defaultdict(list), {}, {}, {}, {}, {}


# --- Load Reference Data and Initialize State ---
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False

if not st.session_state.data_loaded and reference_sheet:
    (dept_map, item_pu_map, item_base_unit_map, item_conv_factor_map,
     cat_map, subcat_map) = get_reference_data(reference_sheet)
    
    st.session_state['dept_items_map'] = dept_map
    st.session_state['item_to_default_purchase_unit_lower'] = item_pu_map
    st.session_state['item_to_base_unit_lower'] = item_base_unit_map
    st.session_state['item_to_conversion_factor_lower'] = item_conv_factor_map
    st.session_state['item_to_category_lower'] = cat_map
    st.session_state['item_to_subcategory_lower'] = subcat_map
    st.session_state['available_items_for_dept'] = [""]
    st.session_state.data_loaded = True

elif not reference_sheet and not st.session_state.data_loaded:
     st.error("Reference data Google Sheet not available. Cannot initialize item data.")
     st.session_state['dept_items_map'] = defaultdict(list)
     st.session_state['item_to_default_purchase_unit_lower'] = {}
     st.session_state['item_to_base_unit_lower'] = {}
     st.session_state['item_to_conversion_factor_lower'] = {}
     st.session_state['item_to_category_lower'] = {}
     st.session_state['item_to_subcategory_lower'] = {}
     st.session_state['available_items_for_dept'] = [""]

if "form_items" not in st.session_state or not isinstance(st.session_state.form_items, list) or not st.session_state.form_items:
     st.session_state.form_items = [{
         'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '',
         'unit': '-',                      # Name of the purchase unit for request
         'base_unit_name': '-',            # Name of the item's base unit
         'selected_conversion_factor': 1.0, # Factor of 'unit' to 'base_unit_name'
         'category': None, 'subcategory': None
     }]
else:
    for item_d in st.session_state.form_items:
        item_d.setdefault('unit', item_d.get('unit', '-')) 
        item_d.setdefault('base_unit_name', '-')
        item_d.setdefault('selected_conversion_factor', 1.0)
        item_d.setdefault('category', None)
        item_d.setdefault('subcategory', None)

if 'last_dept' not in st.session_state: st.session_state.last_dept = None
if 'submitted_data_for_summary' not in st.session_state: st.session_state.submitted_data_for_summary = None
if 'num_items_to_add' not in st.session_state: st.session_state.num_items_to_add = 1
if 'requested_by' not in st.session_state: st.session_state.requested_by = ""


# --- Function to Load Log Data (Cached) ---
@st.cache_data(ttl=300, show_spinner="Loading indent history...")
def load_indent_log_data() -> pd.DataFrame:
    if not log_sheet: return pd.DataFrame()
    try:
        records = log_sheet.get_all_records(head=1) # Assumes first row is header
        if not records:
            # IMPORTANT: Define expected columns for an empty log or if headers are missing
            expected_cols = ['MRN', 'Timestamp', 'Requested By', 'Department', 'Date Required', 'Item',
                             'RequestedQty', 'RequestedUnit', 'BaseQty', 'BaseUnit', 'Note']
            return pd.DataFrame(columns=expected_cols)

        df = pd.DataFrame(records)
        
        # Define the NEW expected columns for your log sheet
        expected_cols = ['MRN', 'Timestamp', 'Requested By', 'Department', 'Date Required', 'Item',
                         'RequestedQty', 'RequestedUnit', 'BaseQty', 'BaseUnit', 'Note']

        for col in expected_cols:
            if col not in df.columns:
                df[col] = pd.NA # Add missing columns with NA

        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        if 'Date Required' in df.columns:
            df['Date Required'] = pd.to_datetime(df['Date Required'], format='%d-%m-%Y', errors='coerce')
        
        # Convert quantity columns to numeric, handling errors
        if 'RequestedQty' in df.columns:
            df['RequestedQty'] = pd.to_numeric(df['RequestedQty'], errors='coerce').fillna(0)
        if 'BaseQty' in df.columns:
            df['BaseQty'] = pd.to_numeric(df['BaseQty'], errors='coerce').fillna(0)

        # Fill NA for text-based columns
        for col in ['Item', 'RequestedUnit', 'BaseUnit', 'Note', 'MRN', 'Department', 'Requested By']:
             if col in df.columns:
                 df[col] = df[col].astype(str).fillna('') # Convert to string before fillna for consistency

        # Ensure display columns match expected columns, handling missing ones
        display_cols = [col for col in expected_cols if col in df.columns]
        df = df[display_cols]
        
        # Drop rows where essential data like Timestamp might be missing after coercion
        df = df.dropna(subset=['Timestamp']) 
        return df.sort_values(by='Timestamp', ascending=False, na_position='last')

    except gspread.exceptions.APIError as e:
        st.error(f"API Error loading indent log: {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading or cleaning indent log: {e}")
        st.exception(e)
        return pd.DataFrame()

# --- NEW Function: Calculate Top Items per Department (Cached) ---
@st.cache_data(ttl=3600, show_spinner="Analyzing history for suggestions...")
def calculate_top_items_per_dept(log_df: pd.DataFrame, top_n: int = 7) -> Dict[str, List[str]]:
    if log_df.empty or 'Department' not in log_df.columns or 'Item' not in log_df.columns:
        return {}
    log_df_clean = log_df.dropna(subset=['Department', 'Item'])
    log_df_clean = log_df_clean[log_df_clean['Item'] != '']
    log_df_clean['Item'] = log_df_clean['Item'].astype(str)
    if log_df_clean.empty:
        return {}
    try:
        top_items = log_df_clean.groupby('Department')['Item'].apply(
            lambda x: x.value_counts().head(top_n).index.tolist()
        )
        return top_items.to_dict()
    except Exception as e:
        st.warning(f"Could not calculate top items: {e}")
        return {}

# --- Load historical data & Calculate suggestions ---
log_data_for_suggestions = load_indent_log_data()
top_items_map = calculate_top_items_per_dept(log_data_for_suggestions, top_n=TOP_N_SUGGESTIONS)
st.session_state['top_items_map'] = top_items_map


# --- MRN Generation ---
def generate_mrn() -> str:
    if not log_sheet:
        return f"MRN-ERR-NOSHEET"
    try:
        all_mrns = log_sheet.col_values(1) # Assuming MRN is in the first column
        next_number = 1
    except gspread.exceptions.APIError as e:
        st.error(f"API Error fetching MRNs: {e}")
        return f"MRN-ERR-API-{datetime.now().strftime('%H%M%S')}"
    except Exception as e: # Catch other potential errors like network issues
        st.error(f"Error fetching MRNs: {e}")
        return f"MRN-ERR-EXC-{datetime.now().strftime('%H%M%S')}"

    if len(all_mrns) > 1: # If more than just header
        last_valid_num = 0
        # Iterate backwards from the last entry to find the last valid MRN number
        for mrn_str in reversed(all_mrns):
            if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit():
                last_valid_num = int(mrn_str[4:])
                break
        # Fallback if no valid MRN-### found but there are entries (e.g. header only or malformed MRNs)
        if last_valid_num == 0 :
             # Count non-empty rows, subtract 1 for header if applicable, or just count actual data rows
             # This fallback might need adjustment based on how "empty" rows are handled or if header isn't "MRN-..."
             non_empty_count = sum(1 for v in all_mrns if v.strip()) # Count non-empty MRN values
             last_valid_num = max(0, non_empty_count -1) # Assuming header is one of them if first row is not MRN-

        next_number = last_valid_num + 1
        
    return f"MRN-{str(next_number).zfill(3)}"


# --- PDF Generation Function ---
def create_indent_pdf(data: Dict[str, Any]) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Material Indent Request", ln=True, align='C')
    pdf.ln(8)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(95, 6, f"MRN: {data.get('mrn', 'N/A')}", ln=0)
    pdf.cell(95, 6, f"Requested By: {data.get('requester', 'N/A')}", ln=1, align='R')
    pdf.cell(95, 6, f"Department: {data.get('dept', 'N/A')}", ln=0)
    pdf.cell(95, 6, f"Date Required: {data.get('date', 'N/A')}", ln=1, align='R')
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 230, 230)
    # Adjusted column widths for new structure (Requested Qty/Unit)
    col_widths = {'item': 80, 'req_qty': 20, 'req_unit': 30, 'note': 60} # BaseQty/Unit optional for PDF

    pdf.cell(col_widths['item'], 7, "Item", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['req_qty'], 7, "Req. Qty", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['req_unit'], 7, "Req. Unit", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['note'], 7, "Note", border=1, ln=1, align='C', fill=True)

    current_category = None
    current_subcategory = None
    items_data = data.get('items', []) # This now holds the detailed tuple
    if not isinstance(items_data, list): items_data = []

    # items_data tuple: (ItemName, RequestedQty, RequestedUnitName, BaseQty, BaseUnitName, Note, Category, SubCategory)
    for item_tuple in items_data:
        if len(item_tuple) < 8: continue # Expecting 8 elements now

        item_name, req_qty, req_unit, base_qty, base_unit_name, note_text, category, subcategory = item_tuple
        
        category = category or "Uncategorized"
        subcategory = subcategory or "General"

        if category != current_category:
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_fill_color(210, 210, 210)
            pdf.cell(0, 6, f"Category: {category}", ln=1, align='L', fill=True, border='LTRB')
            current_category = category
            current_subcategory = None # Reset subcategory when category changes
            pdf.set_fill_color(230, 230, 230) # Reset for item rows header, if any

        if subcategory != current_subcategory:
            pdf.ln(1) # Small space before subcategory
            pdf.set_font("Helvetica", "BI", 9)
            pdf.cell(0, 5, f"  Sub-Category: {subcategory}", ln=1, align='L')
            current_subcategory = subcategory

        pdf.set_font("Helvetica", "", 9)
        line_height = 5.5 
        start_y = pdf.get_y()

        # Item Name
        pdf.multi_cell(col_widths['item'], line_height, str(item_name), border='LR', align='L')
        y1 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'], start_y)

        # Requested Qty
        pdf.multi_cell(col_widths['req_qty'], line_height, f"{req_qty:.2f}", border='R', align='C')
        y2 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['req_qty'], start_y)

        # Requested Unit
        pdf.multi_cell(col_widths['req_unit'], line_height, str(req_unit), border='R', align='C')
        y3 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['req_qty'] + col_widths['req_unit'], start_y)
        
        # Note
        pdf.multi_cell(col_widths['note'], line_height, str(note_text if note_text else "-"), border='R', align='L')
        y4 = pdf.get_y()

        # Determine max height of the cells in this row and draw bottom border
        final_y = max(start_y + line_height, y1, y2, y3, y4)
        pdf.line(pdf.l_margin, final_y, pdf.l_margin + sum(col_widths.values()), final_y)
        pdf.set_y(final_y)
        pdf.ln(0.1) # Minimal line break to ensure next item doesn't overlap border

    return pdf.output(dest='S').encode('latin-1') # Use 'S' for string output, then encode


# --- UI Tabs ---
tab1, tab2 = st.tabs(["📝 New Indent", "📊 View Indents"])

# --- TAB 1: New Indent Form ---
with tab1:
    # --- Helper Functions ---
    def add_item(count=1):
        if not isinstance(count, int) or count < 1: count = 1
        for _ in range(count):
            new_id = f"item_{time.time_ns()}"
            st.session_state.form_items.append({
                'id': new_id, 'item': None, 'qty': 1, 'note': '',
                'unit': '-', 'base_unit_name': '-', 'selected_conversion_factor': 1.0,
                'category': None, 'subcategory': None
            })

    def remove_item(item_id):
        st.session_state.form_items = [item for item in st.session_state.form_items if item['id'] != item_id]
        if not st.session_state.form_items : add_item(count=1) # Ensure at least one item row

    def clear_all_items():
        st.session_state.form_items = [{
            'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1, 'note': '',
            'unit': '-', 'base_unit_name': '-', 'selected_conversion_factor': 1.0,
            'category': None, 'subcategory': None
        }]
        # Note: Does not clear requester name or other header fields by default

    def handle_add_items_click():
        num_to_add = st.session_state.get('num_items_to_add', 1)
        add_item(count=num_to_add)

    def add_suggested_item(item_name_to_add: str):
        if item_name_to_add:
            # Check if item already exists in the form
            current_items_in_form = [item_d.get('item') for item_d in st.session_state.form_items if item_d.get('item')]
            if item_name_to_add in current_items_in_form:
                st.toast(f"'{item_name_to_add}' is already in the indent list.", icon="ℹ️")
                return

            # Retrieve unit and category info from session state (populated by get_reference_data)
            default_pu_map = st.session_state.get("item_to_default_purchase_unit_lower", {})
            base_unit_map = st.session_state.get("item_to_base_unit_lower", {})
            conversion_factor_map = st.session_state.get("item_to_conversion_factor_lower", {})
            cat_map = st.session_state.get("item_to_category_lower", {})
            subcat_map = st.session_state.get("item_to_subcategory_lower", {})

            item_lower = item_name_to_add.lower()
            default_pu_name = default_pu_map.get(item_lower, "-")
            base_unit_name_for_item = base_unit_map.get(item_lower, "-")
            conv_factor_for_default_pu = conversion_factor_map.get(item_lower, 1.0)
            category = cat_map.get(item_lower)
            subcategory = subcat_map.get(item_lower)
            
            new_id = f"item_{time.time_ns()}"
            st.session_state.form_items.append({
                'id': new_id, 'item': item_name_to_add, 'qty': 1, 'note': '',
                'unit': default_pu_name, 
                'base_unit_name': base_unit_name_for_item,
                'selected_conversion_factor': conv_factor_for_default_pu,
                'category': category, 'subcategory': subcategory
            })


    # --- Department Change Callback ---
    def department_changed_callback():
        selected_dept = st.session_state.get("selected_dept")
        dept_map = st.session_state.get("dept_items_map", defaultdict(list))
        available_items = [""] # Start with a blank option
        if selected_dept and selected_dept in dept_map:
            specific_items = dept_map[selected_dept]
            # Items should already be sorted and unique from get_reference_data
            available_items.extend(specific_items) 
        
        st.session_state.available_items_for_dept = available_items
        
        # Reset items in the form when department changes, as available items list changes
        # This prevents invalid item selections from persisting.
        # Keep the number of rows, but clear item-specific data.
        for i in range(len(st.session_state.form_items)):
            st.session_state.form_items[i]['item'] = None
            st.session_state.form_items[i]['unit'] = '-'
            st.session_state.form_items[i]['base_unit_name'] = '-'
            st.session_state.form_items[i]['selected_conversion_factor'] = 1.0
            st.session_state.form_items[i]['note'] = '' # Optionally clear notes too
            st.session_state.form_items[i]['category'] = None
            st.session_state.form_items[i]['subcategory'] = None


    # --- Item Selection Callback ---
    def item_selected_callback(item_id: str, selectbox_key: str):
        default_pu_map = st.session_state.get("item_to_default_purchase_unit_lower", {})
        base_unit_map = st.session_state.get("item_to_base_unit_lower", {})
        conversion_factor_map = st.session_state.get("item_to_conversion_factor_lower", {})
        cat_map = st.session_state.get("item_to_category_lower", {})
        subcat_map = st.session_state.get("item_to_subcategory_lower", {})
        
        selected_item_name = st.session_state.get(selectbox_key)
        
        current_default_pu = "-"
        current_base_unit = "-"
        current_conv_factor = 1.0
        category_for_item = None
        subcategory_for_item = None

        if selected_item_name: # If an item is actually selected (not blank)
            item_lower = selected_item_name.lower()
            current_default_pu = default_pu_map.get(item_lower, "-")
            current_base_unit = base_unit_map.get(item_lower, "-")
            current_conv_factor = conversion_factor_map.get(item_lower, 1.0)
            category_for_item = cat_map.get(item_lower)
            subcategory_for_item = subcat_map.get(item_lower)

        for i, item_dict in enumerate(st.session_state.form_items):
            if item_dict['id'] == item_id:
                st.session_state.form_items[i]['item'] = selected_item_name if selected_item_name else None
                st.session_state.form_items[i]['unit'] = current_default_pu
                st.session_state.form_items[i]['base_unit_name'] = current_base_unit
                st.session_state.form_items[i]['selected_conversion_factor'] = current_conv_factor
                st.session_state.form_items[i]['category'] = category_for_item
                st.session_state.form_items[i]['subcategory'] = subcategory_for_item
                break

    # --- Header Inputs ---
    st.subheader("Indent Details")
    col_head1, col_head2 = st.columns(2)
    with col_head1:
        last_dept_val = st.session_state.get('last_dept')
        dept_index = 0
        try:
            # Try to use current selection in session state, fallback to last_dept, then to default 0
            current_selection_dept = st.session_state.get("selected_dept", last_dept_val)
            if current_selection_dept and current_selection_dept in DEPARTMENTS:
                dept_index = DEPARTMENTS.index(current_selection_dept)
        except (ValueError, TypeError): # Handle cases where current_selection_dept might not be in DEPARTMENTS or is None
            dept_index = 0 # Default to the first option (blank)

        dept = st.selectbox(
            "Select Department*", DEPARTMENTS, index=dept_index, key="selected_dept",
            help="Select department first to filter items.", on_change=department_changed_callback
        )
    with col_head2:
        # Ensure selected_date is initialized properly or defaults to today
        default_date = st.session_state.get("selected_date", date.today())
        if not isinstance(default_date, date): # Fallback if somehow it's not a date object
            default_date = date.today()

        delivery_date = st.date_input(
            "Date Required*", value=default_date, min_value=date.today(),
            format="DD/MM/YYYY", key="selected_date", help="Select the date materials are needed."
        )
        
    requester_name_val = st.text_input(
        "Your Name / Requested By*", key="requested_by", value=st.session_state.requested_by,
        help="Enter the name of the person requesting the items."
    )

    # --- Initialize available items if not already done (e.g., on first run or if dept changes) ---
    if 'dept_items_map' in st.session_state and 'available_items_for_dept' not in st.session_state:
        department_changed_callback() # Call if dept_items_map is loaded but available_items_for_dept isn't set
    elif st.session_state.get("selected_dept") and not st.session_state.get('available_items_for_dept', [""]):
        # This condition handles if a department is selected but its items haven't been populated yet
        # (e.g., if a page reload occurred with a department selected)
        department_changed_callback()


    st.divider()

    # --- Suggested Items Section ---
    selected_dept_for_suggestions = st.session_state.get("selected_dept")
    if selected_dept_for_suggestions and 'top_items_map' in st.session_state:
        suggestions = st.session_state.top_items_map.get(selected_dept_for_suggestions, [])
        items_already_in_form = [item_d.get('item') for item_d in st.session_state.form_items if item_d.get('item')]
        valid_suggestions = [item for item in suggestions if item not in items_already_in_form]
        
        if valid_suggestions:
            st.subheader("✨ Quick Add Common Items")
            num_suggestion_cols = min(len(valid_suggestions), 5) # Max 5 columns for suggestions
            suggestion_cols = st.columns(num_suggestion_cols)
            for idx, item_name_sugg in enumerate(valid_suggestions):
                col_index = idx % num_suggestion_cols
                with suggestion_cols[col_index]:
                    st.button(
                        f"+ {item_name_sugg}",
                        key=f"suggest_{selected_dept_for_suggestions}_{item_name_sugg.replace(' ', '_')}", # Ensure key is valid
                        on_click=add_suggested_item,
                        args=(item_name_sugg,),
                        use_container_width=True
                    )
            st.divider()

    st.subheader("Enter Items:")

    # --- Item Input Rows ---
    current_selected_items_in_form = [item_val['item'] for item_val in st.session_state.form_items if item_val.get('item')]
    duplicate_item_counts = Counter(current_selected_items_in_form)
    duplicates_found_dict = {item_val: count for item_val, count in duplicate_item_counts.items() if count > 1}
    
    items_to_render = list(st.session_state.form_items) # Iterate over a copy for stable modification

    for i, item_dict_render in enumerate(items_to_render):
        item_id_render = item_dict_render['id']
        qty_key = f"qty_{item_id_render}"
        note_key = f"note_{item_id_render}"
        selectbox_key_render = f"item_select_{item_id_render}"

        # Persist qty and note from widget state back to session_state.form_items
        if qty_key in st.session_state:
            try:
                st.session_state.form_items[i]['qty'] = int(st.session_state[qty_key])
            except (ValueError, TypeError):
                st.session_state.form_items[i]['qty'] = 1 # Default to 1 if invalid input
        if note_key in st.session_state:
            st.session_state.form_items[i]['note'] = st.session_state[note_key]
        
        # Get current values from the canonical source (session_state.form_items)
        current_item_value = st.session_state.form_items[i].get('item')
        current_qty = st.session_state.form_items[i].get('qty', 1)
        current_note = st.session_state.form_items[i].get('note', '')
        current_display_unit = st.session_state.form_items[i].get('unit', '-') # This is the Purchase Unit name
        current_item_category = st.session_state.form_items[i].get('category')
        current_item_subcategory = st.session_state.form_items[i].get('subcategory')
        current_item_base_unit = st.session_state.form_items[i].get('base_unit_name', '-')


        item_label = current_item_value if current_item_value else f"Item #{i+1}"
        is_duplicate = current_item_value and current_item_value in duplicates_found_dict
        duplicate_indicator = "⚠️ " if is_duplicate else ""
        expander_label = f"{duplicate_indicator}**{item_label}**"

        with st.expander(label=expander_label, expanded=True):
            if is_duplicate:
                st.warning(f"DUPLICATE ITEM: '{current_item_value}' is selected multiple times. Please consolidate.", icon="⚠️")

            col1, col2, col3, col4 = st.columns([4, 3, 1, 1]) 

            with col1: # Item Select & Cat/SubCat/BaseUnit Info
                available_options_for_dept = st.session_state.get('available_items_for_dept', [""])
                try:
                    current_item_index_val = available_options_for_dept.index(current_item_value) if current_item_value in available_options_for_dept else 0
                except ValueError:
                    current_item_index_val = 0 # Should not happen if available_items_for_dept includes ""
                
                st.selectbox(
                    "Item Select", options=available_options_for_dept, index=current_item_index_val,
                    key=selectbox_key_render, placeholder="Select item...", label_visibility="collapsed",
                    on_change=item_selected_callback, args=(item_id_render, selectbox_key_render)
                )
                st.caption(f"Cat: {current_item_category or '-'} | Sub-Cat: {current_item_subcategory or '-'} | Base Unit: {current_item_base_unit or '-'}")
            
            with col2: # Note
                st.text_input(
                    "Note", value=current_note, key=note_key,
                    placeholder="Optional note...", label_visibility="collapsed"
                )
            
            with col3: # Quantity & Unit
                st.number_input(
                    "Quantity", min_value=1, step=1, value=int(current_qty), key=qty_key, # Ensure value is int
                    label_visibility="collapsed"
                )
                st.caption(f"Unit: {current_display_unit or '-'}") # Displaying the Purchase Unit
            
            with col4: # Remove Button
                 if len(st.session_state.form_items) > 1:
                     st.button("❌", key=f"remove_{item_id_render}", on_click=remove_item, args=(item_id_render,), help="Remove this item")
                 else:
                     st.write("") # Keep layout consistent

    st.divider()

    # --- Add Item Controls ---
    col_add1, col_add2, col_add3 = st.columns([1, 2, 2])
    with col_add1:
        st.number_input("Add:", min_value=1, step=1, value=st.session_state.get('num_items_to_add', 1), key='num_items_to_add', label_visibility="collapsed")
    with col_add2:
        st.button("➕ Add Rows", on_click=handle_add_items_click, use_container_width=True)
    with col_add3:
        st.button("🔄 Clear Item List", on_click=clear_all_items, use_container_width=True)

    # --- Validation ---
    has_duplicates_val = bool(duplicates_found_dict)
    has_valid_items = any(
        item_val.get('item') and item_val.get('qty', 0) > 0 and item_val.get('unit', '-') != '-'
        for item_val in st.session_state.form_items
    )
    current_dept_tab1_val = st.session_state.get("selected_dept", "")
    requester_name_filled_val = bool(st.session_state.get("requested_by", "").strip())
    
    submit_disabled = not has_valid_items or has_duplicates_val or not current_dept_tab1_val or not requester_name_filled_val
    
    error_messages = []
    tooltip_message = "Submit the current indent request."

    if not has_valid_items:
        error_messages.append("Add at least one valid item with quantity > 0 and unit defined.")
    if has_duplicates_val:
        error_messages.append(f"Remove or consolidate duplicate items (marked with ⚠️): {', '.join(duplicates_found_dict.keys())}.")
    if not current_dept_tab1_val:
        error_messages.append("Select a department.")
    if not requester_name_filled_val:
        error_messages.append("Enter the requester's name.")
    
    st.divider()
    if error_messages:
        for msg in error_messages:
            st.warning(f"⚠️ {msg}")
        tooltip_message = "Please fix the issues listed above before submitting."


    # --- Submission ---
    if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled, help=tooltip_message):
        # Structure: [ItemName, RequestedQty (in PU), RequestedUnitName (PU name), BaseQty, BaseUnitName, Note, Category, SubCategory]
        final_items_to_submit_unsorted: List[Tuple[str, float, str, float, str, str, Optional[str], Optional[str]]] = []

        # Final duplicate check on the items being submitted
        items_for_final_check = [item_d['item'] for item_d in st.session_state.form_items if item_d.get('item') and item_d.get('qty',0)>0]
        final_dup_counts = Counter(items_for_final_check)
        final_duplicates = {item_name: count for item_name, count in final_dup_counts.items() if count > 1}

        if final_duplicates:
            st.error(f"Duplicate items detected during final check: {', '.join(final_duplicates.keys())}. Please consolidate.")
            st.stop()

        for item_dict_submit in st.session_state.form_items:
            selected_item = item_dict_submit.get('item')
            requested_qty_val = item_dict_submit.get('qty', 0)
            requested_purchase_unit_name = item_dict_submit.get('unit', '-')
            item_base_unit_name = item_dict_submit.get('base_unit_name', '-')
            conversion_factor_for_item = item_dict_submit.get('selected_conversion_factor', 0.0) # Use 0.0 to spot issues

            note_text = item_dict_submit.get('note', '')
            category_name = item_dict_submit.get('category')
            subcategory_name = item_dict_submit.get('subcategory')

            if selected_item and requested_qty_val > 0:
                if requested_purchase_unit_name == '-' or item_base_unit_name == '-' or conversion_factor_for_item <= 0:
                    st.warning(f"Item '{selected_item}' has incomplete unit/conversion data and will be skipped. Check reference sheet.")
                    continue # Skip this item

                calculated_base_quantity = float(requested_qty_val) * conversion_factor_for_item
                
                final_items_to_submit_unsorted.append((
                    selected_item, float(requested_qty_val), requested_purchase_unit_name,
                    calculated_base_quantity, item_base_unit_name,
                    note_text, category_name or "Uncategorized", subcategory_name or "General"
                ))
        
        if not final_items_to_submit_unsorted:
            st.error("No valid items with complete unit information to submit after final processing."); st.stop()

        final_items_to_submit = sorted(
            final_items_to_submit_unsorted,
            key=lambda x: (str(x[6] or ''), str(x[7] or ''), str(x[0]))
        )

        requester_submit_val = st.session_state.get("requested_by", "").strip() # Already validated not empty
        current_dept_submit_val = st.session_state.get("selected_dept", "")   # Already validated not empty

        try:
            mrn_val = generate_mrn()
            if "ERR" in mrn_val:
                st.error(f"Failed to generate MRN ({mrn_val}). Indent not submitted."); st.stop()
            
            current_timestamp_val = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            selected_date_submit_val = st.session_state.get("selected_date", date.today())
            formatted_date_required_val = selected_date_submit_val.strftime("%d-%m-%Y")

            # --- Data for Google Sheet ---
            # Ensure 'Indent Log' sheet (log_sheet) has columns:
            # MRN, Timestamp, Requested By, Department, Date Required, Item,
            # RequestedQty, RequestedUnit, BaseQty, BaseUnit, Note
            rows_to_add_to_gsheet = []
            for item_n, req_q, req_u, base_q, base_u, item_note_txt, _, _ in final_items_to_submit:
                rows_to_add_to_gsheet.append([
                    mrn_val, current_timestamp_val, requester_submit_val, current_dept_submit_val, formatted_date_required_val,
                    item_n, f"{req_q:.2f}", req_u, f"{base_q:.3f}", base_u, item_note_txt if item_note_txt else "N/A"
                ])
            
            if rows_to_add_to_gsheet and log_sheet:
                with st.spinner(f"Submitting indent {mrn_val}..."):
                    try:
                        log_sheet.append_rows(rows_to_add_to_gsheet, value_input_option='USER_ENTERED')
                        load_indent_log_data.clear()
                        calculate_top_items_per_dept.clear()
                    except gspread.exceptions.APIError as e_gs:
                        st.error(f"Google Sheets API Error: {e_gs}. "
                                 "Ensure 'Indent Log' sheet columns match: "
                                 "MRN, Timestamp, Requested By, Department, Date Required, Item, "
                                 "RequestedQty, RequestedUnit, BaseQty, BaseUnit, Note.")
                        st.stop()
                    except Exception as e_submit:
                        st.error(f"Submission error to Google Sheets: {e_submit}"); st.exception(e_submit); st.stop()
                
                st.session_state['submitted_data_for_summary'] = {
                    'mrn': mrn_val, 'dept': current_dept_submit_val, 'date': formatted_date_required_val,
                    'requester': requester_submit_val, 'items': final_items_to_submit
                }
                st.session_state['last_dept'] = current_dept_submit_val
                clear_all_items()
                st.rerun()
        except Exception as e_main_submit:
            st.error(f"Overall submission processing error: {e_main_submit}"); st.exception(e_main_submit)


    # --- Post-Submission Summary ---
    if st.session_state.get('submitted_data_for_summary'):
        submitted_data = st.session_state['submitted_data_for_summary']
        st.success(f"Indent submitted successfully! MRN: {submitted_data['mrn']}")
        st.balloons()
        st.divider()
        st.subheader("Submitted Indent Summary")
        st.info(f"**MRN:** {submitted_data['mrn']} | **Dept:** {submitted_data['dept']} | "
                f"**Reqd Date:** {submitted_data['date']} | **By:** {submitted_data.get('requester', 'N/A')}")

        # items tuple: (ItemName, RequestedQty, RequestedUnitName, BaseQty, BaseUnitName, Note, Category, SubCategory)
        submitted_df_cols = ["Item", "Req. Qty", "Req. Unit", "Base Qty", "Base Unit", "Note", "Category", "Sub-Category"]
        submitted_items_for_df = [list(item_s) for item_s in submitted_data['items']] # Convert tuples to lists for DF
        
        submitted_df = pd.DataFrame(submitted_items_for_df, columns=submitted_df_cols)
        
        # Select columns to display in the summary dataframe
        display_summary_cols = ["Item", "Req. Qty", "Req. Unit", "Note", "Category", "Sub-Category"]
        # Optionally include base quantity/unit if desired:
        # display_summary_cols = ["Item", "Req. Qty", "Req. Unit", "Base Qty", "Base Unit", "Note", "Category", "Sub-Category"]

        st.dataframe(
            submitted_df[display_summary_cols],
            hide_index=True, use_container_width=True,
            column_config={
                "Req. Qty": st.column_config.NumberColumn("Req. Qty", format="%.2f"),
                "Category": st.column_config.TextColumn("Category"),
                "Sub-Category": st.column_config.TextColumn("Sub-Cat")
            }
        )
        
        total_submitted_items = len(submitted_data['items'])
        st.markdown(f"**Total Unique Items Submitted:** {total_submitted_items}")
        st.divider()

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            try:
                pdf_bytes = create_indent_pdf(submitted_data) # create_indent_pdf expects dict
                st.download_button(
                    label="📄 Download PDF", data=pdf_bytes,
                    file_name=f"Indent_{submitted_data['mrn']}.pdf", mime="application/pdf",
                    use_container_width=True
                )
            except Exception as pdf_error:
                st.error(f"Could not generate PDF: {pdf_error}")
                st.exception(pdf_error)
        
        with col_btn2:
            try:
                wa_text_parts = [
                    f"Indent Submitted:",
                    f"MRN: {submitted_data.get('mrn', 'N/A')}",
                    f"Department: {submitted_data.get('dept', 'N/A')}",
                    f"Requested By: {submitted_data.get('requester', 'N/A')}",
                    f"Date Required: {submitted_data.get('date', 'N/A')}",
                    f"\nPlease see attached PDF for item details."
                ]
                wa_text = "\n".join(wa_text_parts)
                encoded_text = urllib.parse.quote_plus(wa_text)
                wa_url = f"https://wa.me/?text={encoded_text}"
                st.link_button("✅ Prepare WhatsApp Message", wa_url, use_container_width=True, target="_blank")
            except Exception as wa_e:
                st.error(f"Could not create WhatsApp link: {wa_e}")
        
        st.caption("NOTE: To share on WhatsApp, first Download PDF, then click Prepare WhatsApp Message, "
                   "choose contact/group, and MANUALLY attach the downloaded PDF before sending.")
        st.divider()
        
        if st.button("Start New Indent"):
            st.session_state['submitted_data_for_summary'] = None
            # Optionally preserve requester name:
            # current_requester = st.session_state.get('requested_by', "")
            clear_all_items() # This will reset form_items
            # st.session_state.requested_by = current_requester # Re-assign if preserving
            st.rerun()

# --- TAB 2: View Indents ---
with tab2:
    st.subheader("View Past Indent Requests")
    log_df_tab2 = load_indent_log_data() # This now loads the new structure

    if not log_df_tab2.empty:
        st.divider()
        with st.expander("Filter Options", expanded=True):
            dept_options_filt = sorted([d for d in log_df_tab2['Department'].unique() if d and d != ''])
            requester_options_filt = sorted([r for r in log_df_tab2['Requested By'].unique() if r and r != ''])
            
            min_ts_filt = log_df_tab2['Date Required'].dropna().min()
            max_ts_filt = log_df_tab2['Date Required'].dropna().max()
            
            default_start_filt = date.today() - pd.Timedelta(days=90)
            default_end_filt = date.today()

            min_date_log_filt = min_ts_filt.date() if pd.notna(min_ts_filt) else default_start_filt
            max_date_log_filt = max_ts_filt.date() if pd.notna(max_ts_filt) else default_end_filt
            
            # Ensure default_start is not after max_date_log
            calculated_default_start_filt = max(min_date_log_filt, default_start_filt) if default_start_filt < max_date_log_filt else min_date_log_filt
            if calculated_default_start_filt > max_date_log_filt: calculated_default_start_filt = min_date_log_filt


            filt_col1, filt_col2, filt_col3 = st.columns([1, 1, 2])
            with filt_col1:
                filt_start_date = st.date_input(
                    "Reqd. From", value=calculated_default_start_filt,
                    min_value=min_date_log_filt, max_value=max_date_log_filt,
                    key="filt_start", format="DD/MM/YYYY"
                )
                # Ensure end_date's min_value is start_date
                valid_end_min_filt = filt_start_date 
                filt_end_date = st.date_input(
                    "Reqd. To", value=max_date_log_filt,
                    min_value=valid_end_min_filt, max_value=max_date_log_filt,
                    key="filt_end", format="DD/MM/YYYY"
                )
            with filt_col2:
                selected_depts_filt = st.multiselect("Department", options=dept_options_filt, default=[], key="filt_dept")
                if requester_options_filt:
                    selected_requesters_filt = st.multiselect("Requested By", options=requester_options_filt, default=[], key="filt_req")
            with filt_col3:
                mrn_search_filt = st.text_input("MRN", key="filt_mrn", placeholder="e.g., MRN-005")
                item_search_filt = st.text_input("Item Name", key="filt_item", placeholder="e.g., Salt")
        
        st.caption("Default view shows indents required in the last 90 days. Use filters for specific records.")
        
        filtered_df_tab2 = log_df_tab2.copy()
        try:
            start_filter_ts = pd.Timestamp(st.session_state.filt_start)
            end_filter_ts = pd.Timestamp(st.session_state.filt_end)

            date_filt_cond = (
                filtered_df_tab2['Date Required'].notna() &
                (filtered_df_tab2['Date Required'].dt.normalize() >= start_filter_ts) &
                (filtered_df_tab2['Date Required'].dt.normalize() <= end_filter_ts)
            )
            filtered_df_tab2 = filtered_df_tab2[date_filt_cond]

            if st.session_state.filt_dept:
                filtered_df_tab2 = filtered_df_tab2[filtered_df_tab2['Department'].isin(st.session_state.filt_dept)]
            if requester_options_filt and st.session_state.get('filt_req'): # Check if filt_req exists
                filtered_df_tab2 = filtered_df_tab2[filtered_df_tab2['Requested By'].isin(st.session_state.filt_req)]
            if st.session_state.filt_mrn:
                filtered_df_tab2 = filtered_df_tab2[filtered_df_tab2['MRN'].astype(str).str.contains(st.session_state.filt_mrn, case=False, na=False)]
            if st.session_state.filt_item:
                filtered_df_tab2 = filtered_df_tab2[filtered_df_tab2['Item'].astype(str).str.contains(st.session_state.filt_item, case=False, na=False)]
        except Exception as filter_e:
            st.error(f"Filter error: {filter_e}")
            # filtered_df_tab2 remains a copy of log_df_tab2 on error, which is fine
        
        st.divider()
        st.write(f"Displaying {len(filtered_df_tab2)} records based on filters:")
        
        # Update column_config for the new log structure
        st.dataframe(
            filtered_df_tab2,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Date Required": st.column_config.DateColumn("Date Reqd.", format="DD/MM/YYYY"),
                "Timestamp": st.column_config.DatetimeColumn("Submitted On", format="YYYY-MM-DD HH:mm"),
                "Requested By": st.column_config.TextColumn("Req. By"),
                "MRN": st.column_config.TextColumn("MRN"),
                "Department": st.column_config.TextColumn("Dept."),
                "Item": st.column_config.TextColumn("Item Name", width="medium"),
                "RequestedQty": st.column_config.NumberColumn("Req. Qty", format="%.2f"),
                "RequestedUnit": st.column_config.TextColumn("Req. Unit"),
                "BaseQty": st.column_config.NumberColumn("Base Qty", format="%.3f"), # Optional to display
                "BaseUnit": st.column_config.TextColumn("Base Unit"),          # Optional to display
                "Note": st.column_config.TextColumn("Notes", width="large"),
            }
        )
    else:
        st.info("No indent records found or the log is currently unavailable.")

# --- Optional Debug ---
# with st.sidebar.expander("Session State Debug"):
#    st.json(st.session_state.to_dict())