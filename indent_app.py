import streamlit as st
import pandas as pd
import gspread
from gspread import Client, Spreadsheet, Worksheet
from fpdf import FPDF
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
# from PIL import Image # PIL is not used if logo is removed
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple, Optional, DefaultDict # Union not used here
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
    # Function to connect to Google Sheets and return client, log_sheet, and reference_sheet objects
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
        st.exception(e) # Log the full traceback for debugging
        return None, None, None

client, log_sheet, reference_sheet = connect_gsheets()

if not client or not log_sheet or not reference_sheet:
    st.error("Failed to connect to Google Sheets. Application cannot proceed.")
    st.stop() # Stop execution if connection fails

# --- Reference Data Loading Function (Reads Item, Unit, Category & Sub-Category) ---
@st.cache_data(ttl=3600, show_spinner="Fetching item reference data...")
def get_reference_data(_reference_sheet: Worksheet) -> Tuple[DefaultDict[str, List[str]], Dict[str, str], Dict[str, str], Dict[str, str]]:
    # Initializes dictionaries to store reference data
    item_to_unit_lower: Dict[str, str] = {}
    item_to_category_lower: Dict[str, str] = {}
    item_to_subcategory_lower: Dict[str, str] = {}
    dept_to_items_map: DefaultDict[str, List[str]] = defaultdict(list)
    try:
        all_data: List[List[str]] = _reference_sheet.get_all_values() # Get all data from the sheet
        header_skipped: bool = False
        valid_departments = set(dept for dept in DEPARTMENTS if dept) # Use globally defined DEPARTMENTS

        # Simple header detection: check if common keywords are in the first row
        if all_data and ("item" in str(all_data[0][0]).lower() or "unit" in str(all_data[0][1]).lower()):
            header_skipped = True
            data_rows = all_data[1:] # If header detected, skip the first row
        else:
            data_rows = all_data # Otherwise, process all rows

        for i, row in enumerate(data_rows):
            row_num_for_warning = i + (2 if header_skipped else 1) # Adjust row number for user-friendly warnings
            # Expecting Item, Unit, Permitted Depts, Category, Sub-Category (at least 5 columns)
            if len(row) < 5: 
                if any(str(cell).strip() for cell in row): # Warn only if the row has some data
                     st.warning(f"Skipping row {row_num_for_warning} in 'reference' sheet: expected at least 5 columns, found {len(row)}.")
                continue
            if not any(str(cell).strip() for cell in row[:5]): # Skip if first 5 essential cells are blank
                continue
            
            # Extract data from row, stripping whitespace
            item: str = str(row[0]).strip()
            unit: str = str(row[1]).strip() # This is the Purchase Unit from your sheet
            permitted_depts_str: str = str(row[2]).strip()
            category: str = str(row[3]).strip()
            subcategory: str = str(row[4]).strip()
            item_lower: str = item.lower() # Use lower case for dictionary keys for consistency

            if item: # Process only if item name is present
                item_to_unit_lower[item_lower] = unit if unit else "N/A"
                item_to_category_lower[item_lower] = category if category else "Uncategorized"
                item_to_subcategory_lower[item_lower] = subcategory if subcategory else "General"
                
                # Map items to departments
                if not permitted_depts_str or permitted_depts_str.lower() == 'all':
                    for dept_name in valid_departments:
                        dept_to_items_map[dept_name].append(item)
                else:
                    departments_for_item = [dept.strip() for dept in permitted_depts_str.split(',') if dept.strip() in valid_departments]
                    for dept_name in departments_for_item:
                        dept_to_items_map[dept_name].append(item)
            else: # If item name is blank but other cells might have data
                if any(str(cell).strip() for cell in row[1:5]): 
                    st.warning(f"Skipping row {row_num_for_warning} in 'reference' sheet: Item name is missing.")

        # Ensure unique, sorted list of items per department
        for dept_name in dept_to_items_map:
            dept_to_items_map[dept_name] = sorted(list(set(dept_to_items_map[dept_name])))
            
        return dept_to_items_map, item_to_unit_lower, item_to_category_lower, item_to_subcategory_lower
    except gspread.exceptions.APIError as e:
        st.error(f"API Error loading reference: {e}")
    except IndexError: # Should be less frequent due to len(row) check
        st.error("Error reading reference sheet. Ensure it has at least 5 columns: Item, Unit, Permitted Depts, Category, Sub-Category.")
    except Exception as e:
        st.error(f"An unexpected error occurred loading reference data: {e}")
        st.exception(e) # Log the full exception for debugging
    return defaultdict(list), {}, {}, {} # Return empty structures on error


# --- Load Reference Data and Initialize State ---
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False

if not st.session_state.data_loaded and reference_sheet: # Check if reference_sheet is valid
    dept_map, unit_map, cat_map, subcat_map = get_reference_data(reference_sheet)
    st.session_state['dept_items_map'] = dept_map
    st.session_state['item_to_unit_lower'] = unit_map # Stores {item_lower: unit_name}
    st.session_state['item_to_category_lower'] = cat_map
    st.session_state['item_to_subcategory_lower'] = subcat_map
    st.session_state['available_items_for_dept'] = [""] # Initialized, will be populated by department_changed_callback
    st.session_state.data_loaded = True
elif not reference_sheet and not st.session_state.data_loaded : # If sheet connection failed and data not loaded
     st.error("Cannot load reference data from Google Sheet. Application functionality will be limited.")
     # Initialize to prevent KeyErrors later
     st.session_state['dept_items_map'] = defaultdict(list)
     st.session_state['item_to_unit_lower'] = {}
     st.session_state['item_to_category_lower'] = {}
     st.session_state['item_to_subcategory_lower'] = {}
     st.session_state['available_items_for_dept'] = [""]

# Ensure form_items are initialized correctly, especially 'qty' as float
if "form_items" not in st.session_state or not isinstance(st.session_state.form_items, list) or not st.session_state.form_items:
     st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 
                                     'qty': 1.0, # Qty initialized as float
                                     'note': '', 'unit': '-', 'category': None, 'subcategory': None}]
else:
    # If form_items already exist (e.g., from a previous run in the session), ensure 'qty' is float
    for item_d in st.session_state.form_items:
        item_d.setdefault('category', None)
        item_d.setdefault('subcategory', None)
        item_d.setdefault('qty', float(item_d.get('qty', 1.0))) # Ensure qty is float

# Initialize other session state variables if they don't exist
if 'last_dept' not in st.session_state: st.session_state.last_dept = None
if 'submitted_data_for_summary' not in st.session_state: st.session_state.submitted_data_for_summary = None
if 'num_items_to_add' not in st.session_state: st.session_state.num_items_to_add = 1
if 'requested_by' not in st.session_state: st.session_state.requested_by = ""

# --- Function to Load Log Data (Cached) ---
@st.cache_data(ttl=300, show_spinner="Loading indent history...")
def load_indent_log_data() -> pd.DataFrame:
    # Loads and cleans data from the indent log Google Sheet
    if not log_sheet: return pd.DataFrame() # Return empty DataFrame if no log sheet
    try:
        records = log_sheet.get_all_records(head=1) # Assumes first row is header
        if not records: # If sheet is empty or has only header
            expected_cols = ['MRN', 'Timestamp', 'Requested By', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
            return pd.DataFrame(columns=expected_cols)
        
        df = pd.DataFrame(records)
        expected_cols = ['MRN', 'Timestamp', 'Requested By', 'Department', 'Date Required', 'Item', 'Qty', 'Unit', 'Note']
        
        # Ensure all expected columns exist, fill with NA if missing
        for col in expected_cols:
            if col not in df.columns:
                df[col] = pd.NA
        
        # Convert timestamp and date columns to datetime objects
        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        if 'Date Required' in df.columns:
            df['Date Required'] = pd.to_datetime(df['Date Required'], format='%d-%m-%Y', errors='coerce')
        
        # Convert Qty to numeric (float), fill errors/NA with 0.0
        if 'Qty' in df.columns:
            df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0.0) # CHANGED to 0.0 for float
        
        # Fill NA for text-based columns with empty string
        for col in ['Item', 'Unit', 'Note', 'MRN', 'Department', 'Requested By']:
             if col in df.columns:
                 df[col] = df[col].astype(str).fillna('') # Ensure string type for these columns
        
        # Select and order columns as expected
        display_cols = [col for col in expected_cols if col in df.columns]
        df = df[display_cols]
        df = df.dropna(subset=['Timestamp']) # Remove rows where Timestamp couldn't be parsed
        return df.sort_values(by='Timestamp', ascending=False, na_position='last') # Sort by Timestamp
    except gspread.exceptions.APIError as e:
        st.error(f"API Error loading log: {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading/cleaning log data: {e}")
        st.exception(e) # Log the full exception
        return pd.DataFrame()

# --- Function to Calculate Top Items per Department (Must be defined before use) ---
@st.cache_data(ttl=3600, show_spinner="Analyzing history for suggestions...")
def calculate_top_items_per_dept(log_df: pd.DataFrame, top_n: int = 7) -> Dict[str, List[str]]:
    """Calculates the top N most frequent items requested per department."""
    if log_df.empty or 'Department' not in log_df.columns or 'Item' not in log_df.columns: 
        return {}
    log_df_clean = log_df.dropna(subset=['Department', 'Item'])
    # Ensure 'Item' column is string and not empty before value_counts
    log_df_clean = log_df_clean[log_df_clean['Item'].astype(str).str.strip() != ''] 
    log_df_clean['Item'] = log_df_clean['Item'].astype(str) # Ensure Item column is string type
    if log_df_clean.empty: 
        return {}
    try:
        # Group by Department, then find top N items by frequency for each department
        top_items = log_df_clean.groupby('Department')['Item'].apply(lambda x: x.value_counts().head(top_n).index.tolist())
        return top_items.to_dict()
    except Exception as e:
        st.warning(f"Could not calculate top items: {e}")
        return {}

# --- Load historical data & Calculate suggestions ---
log_data_for_suggestions = load_indent_log_data()
# Ensure calculate_top_items_per_dept is defined before this call
top_items_map = calculate_top_items_per_dept(log_data_for_suggestions, top_n=TOP_N_SUGGESTIONS)
st.session_state['top_items_map'] = top_items_map


# --- MRN Generation ---
def generate_mrn() -> str:
    # Generates a new Material Request Number (MRN)
    if not log_sheet: return f"MRN-ERR-NOSHEET" # Should not happen if connection check passed
    try:
        all_mrns = log_sheet.col_values(1) # Assumes MRN is in the first column
        next_number = 1
    except gspread.exceptions.APIError as e:
        st.error(f"API Error fetching MRNs: {e}")
        return f"MRN-ERR-API-{datetime.now().strftime('%H%M%S')}"
    except Exception as e: # Catch other potential errors like network issues
        st.error(f"Error fetching MRNs: {e}")
        return f"MRN-ERR-EXC-{datetime.now().strftime('%H%M%S')}"

    if len(all_mrns) > 1: # If more than just header (assuming header exists)
        last_valid_num = 0
        # Iterate backwards from the last entry to find the last valid MRN number
        for mrn_str in reversed(all_mrns): 
            if mrn_str and mrn_str.startswith("MRN-") and mrn_str[4:].isdigit():
                last_valid_num = int(mrn_str[4:])
                break
        # Fallback if no valid MRN-### found but there are entries
        if last_valid_num == 0 :
             non_empty_count = sum(1 for v in all_mrns if str(v).strip()) # Count non-empty MRN values
             last_valid_num = max(0, non_empty_count - 1) # Assuming header row exists if count > 0

        next_number = last_valid_num + 1
        
    return f"MRN-{str(next_number).zfill(3)}" # Pad with leading zeros


# --- PDF Generation Function ---
def create_indent_pdf(data: Dict[str, Any]) -> bytes:
    # Creates a PDF document for the indent request
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(10, 10, 10) # Left, Top, Right margins
    pdf.set_auto_page_break(auto=True, margin=15) # Bottom margin for page break

    # Document Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Material Indent Request", ln=True, align='C')
    pdf.ln(8) # Line break

    # Header Information
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(95, 6, f"MRN: {data.get('mrn', 'N/A')}", ln=0) # Half width
    pdf.cell(95, 6, f"Requested By: {data.get('requester', 'N/A')}", ln=1, align='R') # Other half, new line
    pdf.cell(95, 6, f"Department: {data.get('dept', 'N/A')}", ln=0)
    pdf.cell(95, 6, f"Date Required: {data.get('date', 'N/A')}", ln=1, align='R')
    pdf.ln(6)

    # Table Header for Items
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 230, 230) # Light grey fill for header
    col_widths = {'item': 90, 'qty': 20, 'unit': 25, 'note': 55} # Adjusted Qty width slightly
    pdf.cell(col_widths['item'], 7, "Item", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['qty'], 7, "Qty", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['unit'], 7, "Unit", border=1, ln=0, align='C', fill=True)
    pdf.cell(col_widths['note'], 7, "Note", border=1, ln=1, align='C', fill=True)
    
    current_category = None
    current_subcategory = None
    items_data = data.get('items', []) # List of item tuples
    if not isinstance(items_data, list): items_data = []

    for item_tuple in items_data:
        # Expected tuple: (item_name, qty (float), unit_name, note_text, category, subcategory)
        if len(item_tuple) < 6: continue # Skip malformed tuples
        item, qty_val, unit, note, category, subcategory = item_tuple # Qty is float
        
        category = category or "Uncategorized" # Default if None
        subcategory = subcategory or "General" # Default if None

        # Print Category Header if it changes
        if category != current_category:
            pdf.ln(3) # Small space before category header
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_fill_color(210, 210, 210) # Slightly darker grey for category
            pdf.cell(0, 6, f"Category: {category}", ln=1, align='L', fill=True, border='LTRB')
            current_category = category
            current_subcategory = None # Reset subcategory when category changes
            pdf.set_fill_color(230, 230, 230) # Reset fill for item rows header, if any

        # Print Sub-Category Header if it changes
        if subcategory != current_subcategory:
            pdf.ln(1) # Small space before subcategory
            pdf.set_font("Helvetica", "BI", 9) # Bold Italic for subcategory
            pdf.cell(0, 5, f"  Sub-Category: {subcategory}", ln=1, align='L') # Indent subcategory
            current_subcategory = subcategory

        # Item Row Details
        pdf.set_font("Helvetica", "", 9)
        line_height = 5.5 # Adjust for readability
        start_y = pdf.get_y() # Record Y position before multi_cell

        # Item Name (allows wrapping)
        pdf.multi_cell(col_widths['item'], line_height, str(item), border='LR', align='L')
        y1 = pdf.get_y() # Y position after item name
        pdf.set_xy(pdf.l_margin + col_widths['item'], start_y) # Reset X for next cell, keep Y

        # Quantity (formatted as float)
        pdf.multi_cell(col_widths['qty'], line_height, f"{float(qty_val):.3f}", border='R', align='C')
        y2 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['qty'], start_y)
        
        # Unit
        pdf.multi_cell(col_widths['unit'], line_height, str(unit), border='R', align='C')
        y3 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + col_widths['item'] + col_widths['qty'] + col_widths['unit'], start_y)
        
        # Note (allows wrapping)
        pdf.multi_cell(col_widths['note'], line_height, str(note if note else "-"), border='R', align='L')
        y4 = pdf.get_y()

        # Determine max height of the cells in this row and draw bottom border
        final_y = max(start_y + line_height, y1, y2, y3, y4) # Ensure border is below tallest cell
        pdf.line(pdf.l_margin, final_y, pdf.l_margin + sum(col_widths.values()), final_y) # Draw bottom border
        pdf.set_y(final_y) # Move cursor to below the drawn line
        pdf.ln(0.1) # Minimal line break to ensure next item doesn't overlap border
        
    return pdf.output(dest='S').encode('latin-1') # Output as bytes for Streamlit download button


# --- UI Tabs ---
tab1, tab2 = st.tabs(["📝 New Indent", "📊 View Indents"])

# --- TAB 1: New Indent Form ---
with tab1:
    # --- Helper Functions for managing form items ---
    def add_item(count=1):
        # Adds a specified number of new item rows to the form
        if not isinstance(count, int) or count < 1: count = 1 # Ensure count is valid
        for _ in range(count):
            new_id = f"item_{time.time_ns()}" # Unique ID for the item row
            # Initialize qty as float (1.0)
            st.session_state.form_items.append({'id': new_id, 'item': None, 'qty': 1.0, 
                                                 'note': '', 'unit': '-', 'category': None, 'subcategory': None})

    def remove_item(item_id):
        # Removes an item row from the form by its ID
        st.session_state.form_items = [item for item in st.session_state.form_items if item['id'] != item_id]
        if not st.session_state.form_items: add_item(count=1) # Ensure at least one item row is always present

    def clear_all_items():
        # Clears all items from the form, resetting to a single blank item row
        # Initialize qty as float (1.0)
        st.session_state.form_items = [{'id': f"item_{time.time_ns()}", 'item': None, 'qty': 1.0, 
                                         'note': '', 'unit': '-', 'category': None, 'subcategory': None}]
        # Note: This does not clear requester name or other header fields by default

    def handle_add_items_click():
        # Callback for the "Add Rows" button
        num_to_add = st.session_state.get('num_items_to_add', 1)
        add_item(count=num_to_add)

    def add_suggested_item(item_name_to_add: str):
        # Adds a suggested item to the form if it's not already present
        if item_name_to_add:
            current_items_in_form = [item_dict.get('item') for item_dict in st.session_state.form_items if item_dict.get('item')]
            if item_name_to_add in current_items_in_form:
                st.toast(f"'{item_name_to_add}' is already in the indent list.", icon="ℹ️")
                return
            
            # Retrieve unit and category info from session state (populated by get_reference_data)
            unit_map = st.session_state.get("item_to_unit_lower", {})
            cat_map = st.session_state.get("item_to_category_lower", {})
            subcat_map = st.session_state.get("item_to_subcategory_lower", {})
            
            item_lower = item_name_to_add.lower()
            unit = unit_map.get(item_lower, "-") # Get unit for the item
            unit = unit if unit else "-" # Ensure unit is not None
            category = cat_map.get(item_lower)
            subcategory = subcat_map.get(item_lower)
            
            new_id = f"item_{time.time_ns()}"
            # Initialize qty as float (1.0) when adding suggested item
            st.session_state.form_items.append({'id': new_id, 'item': item_name_to_add, 'qty': 1.0, 
                                                 'note': '', 'unit': unit, 'category': category, 'subcategory': subcategory})


    # --- Department Change Callback ---
    def department_changed_callback():
        # Updates the list of available items when the department selection changes
        selected_dept = st.session_state.get("selected_dept")
        dept_map = st.session_state.get("dept_items_map", defaultdict(list))
        available_items = [""] # Start with a blank option for the selectbox
        if selected_dept and selected_dept in dept_map:
            specific_items = dept_map[selected_dept] # Items are already sorted and unique from get_reference_data
            available_items.extend(specific_items) 
        
        st.session_state.available_items_for_dept = available_items
        
        # Reset item details in the form, as available items list has changed
        for i in range(len(st.session_state.form_items)):
            st.session_state.form_items[i]['item'] = None
            st.session_state.form_items[i]['unit'] = '-'
            st.session_state.form_items[i]['qty'] = 1.0 # Reset qty to float
            st.session_state.form_items[i]['note'] = '' # Optionally clear notes
            st.session_state.form_items[i]['category'] = None
            st.session_state.form_items[i]['subcategory'] = None


    # --- Item Selection Callback ---
    def item_selected_callback(item_id: str, selectbox_key: str):
        # Updates item details (unit, category, subcategory) when an item is selected from the dropdown
        unit_map = st.session_state.get("item_to_unit_lower", {})
        cat_map = st.session_state.get("item_to_category_lower", {})
        subcat_map = st.session_state.get("item_to_subcategory_lower", {})
        
        selected_item_name = st.session_state.get(selectbox_key) # Get selected item from the widget's state
        
        # Default values if item not found or not selected
        unit = "-"
        category = None
        subcategory = None

        if selected_item_name: # If an item is actually selected (not blank)
            item_lower = selected_item_name.lower()
            unit = unit_map.get(item_lower, "-") # Get unit for the selected item
            unit = unit if unit else "-" # Ensure unit is not None
            category = cat_map.get(item_lower)
            subcategory = subcat_map.get(item_lower)
            
        # Update the specific item in the form_items list in session state
        for i, item_dict in enumerate(st.session_state.form_items):
            if item_dict['id'] == item_id:
                st.session_state.form_items[i]['item'] = selected_item_name if selected_item_name else None
                st.session_state.form_items[i]['unit'] = unit
                # Optionally reset qty when item changes, or keep existing value
                # st.session_state.form_items[i]['qty'] = 1.0 
                st.session_state.form_items[i]['category'] = category
                st.session_state.form_items[i]['subcategory'] = subcategory
                break

    # --- Header Inputs: Department, Date Required, Requester Name ---
    st.subheader("Indent Details")
    col_head1, col_head2 = st.columns(2)
    with col_head1:
        last_dept_val = st.session_state.get('last_dept') # Get last selected department for persistence
        dept_idx = 0 # Default index for selectbox
        try:
            # Try to use current selection in session state, fallback to last_dept, then to default 0
            current_selection_dept = st.session_state.get("selected_dept", last_dept_val)
            if current_selection_dept and current_selection_dept in DEPARTMENTS:
                dept_idx = DEPARTMENTS.index(current_selection_dept)
        except (ValueError, TypeError): # Handle cases where current_selection_dept might not be in DEPARTMENTS or is None
            dept_idx = 0 # Default to the first option (blank)

        dept = st.selectbox("Select Department*", DEPARTMENTS, index=dept_idx, key="selected_dept",
                            help="Select department first to filter items.", on_change=department_changed_callback)
    with col_head2:
        # Ensure selected_date is initialized properly or defaults to today
        default_dt = st.session_state.get("selected_date", date.today())
        if not isinstance(default_dt, date): default_dt = date.today() # Fallback if not a date object
        delivery_date = st.date_input("Date Required*", value=default_dt, min_value=date.today(),
                                      format="DD/MM/YYYY", key="selected_date", help="Select the date materials are needed.")
    requester_name_val = st.text_input("Your Name / Requested By*", key="requested_by", value=st.session_state.requested_by,
                                 help="Enter the name of the person requesting the items.")

    # --- Initialize available items for department if not already done ---
    if 'dept_items_map' in st.session_state and 'available_items_for_dept' not in st.session_state:
        department_changed_callback() # Call if dept_items_map is loaded but available_items_for_dept isn't set
    elif st.session_state.get("selected_dept") and not st.session_state.get('available_items_for_dept', [""]):
        # This handles if a department is selected but its items haven't been populated (e.g., page reload)
        department_changed_callback()

    st.divider()

    # --- Suggested Items Section (Quick Add) ---
    selected_dept_sugg = st.session_state.get("selected_dept")
    if selected_dept_sugg and 'top_items_map' in st.session_state: # Check if suggestions are available
        suggestions = st.session_state.top_items_map.get(selected_dept_sugg, [])
        items_in_form = [item_d.get('item') for item_d in st.session_state.form_items if item_d.get('item')]
        valid_suggestions = [item for item in suggestions if item not in items_in_form] # Filter out items already in form
        
        if valid_suggestions:
            st.subheader("✨ Quick Add Common Items")
            num_sugg_cols = min(len(valid_suggestions), 5) # Max 5 columns for suggestions
            sugg_cols = st.columns(num_sugg_cols)
            for idx, item_sugg_name in enumerate(valid_suggestions):
                col_idx = idx % num_sugg_cols
                with sugg_cols[col_idx]:
                    # Ensure button key is unique and valid
                    st.button(f"+ {item_sugg_name}", key=f"suggest_{selected_dept_sugg}_{item_sugg_name.replace(' ', '_').replace('/', '_')}",
                              on_click=add_suggested_item, args=(item_sugg_name,), use_container_width=True)
            st.divider()

    st.subheader("Enter Items:")

    # --- Item Input Rows ---
    current_selected_items = [item_val['item'] for item_val in st.session_state.form_items if item_val.get('item')]
    duplicate_counts = Counter(current_selected_items) # Count occurrences of each item
    duplicates_dict = {item_val: count for item_val, count in duplicate_counts.items() if count > 1} # Identify duplicates
    
    items_to_render_list = list(st.session_state.form_items) # Iterate over a copy for stable modification if needed

    for i, item_dict_render in enumerate(items_to_render_list):
        item_id_render = item_dict_render['id']
        qty_key_render = f"qty_{item_id_render}"
        note_key_render = f"note_{item_id_render}"
        selectbox_key_render = f"item_select_{item_id_render}"

        # Persist widget state (qty, note) back to session_state.form_items for the current item
        if qty_key_render in st.session_state:
            try:
                # IMPORTANT: Ensure qty is stored as float
                st.session_state.form_items[i]['qty'] = float(st.session_state[qty_key_render])
            except (ValueError, TypeError):
                st.session_state.form_items[i]['qty'] = 1.0 # Default to 1.0 if invalid input
        if note_key_render in st.session_state:
            st.session_state.form_items[i]['note'] = st.session_state[note_key_render]
        
        # Get current values from the canonical source (session_state.form_items)
        current_item = st.session_state.form_items[i].get('item')
        # IMPORTANT: Ensure current_qty_val is float for the number_input's value parameter
        current_qty_val = float(st.session_state.form_items[i].get('qty', 1.0))
        current_note_val = st.session_state.form_items[i].get('note', '')
        current_unit_val = st.session_state.form_items[i].get('unit', '-')
        current_category_val = st.session_state.form_items[i].get('category')
        current_subcategory_val = st.session_state.form_items[i].get('subcategory')
        
        item_label_render = current_item if current_item else f"Item #{i+1}"
        is_duplicate_item = current_item and current_item in duplicates_dict
        dup_indicator = "⚠️ " if is_duplicate_item else ""
        expander_label_text = f"{dup_indicator}**{item_label_render}**"

        with st.expander(label=expander_label_text, expanded=True): # Keep expander expanded by default
            if is_duplicate_item:
                st.warning(f"DUPLICATE ITEM: '{current_item}' is selected multiple times. Please consolidate.", icon="⚠️")

            # Define columns for item input row
            col1, col2, col3, col4 = st.columns([4, 3, 1, 1]) # Adjust ratios as needed
            with col1: # Item Select & Cat/SubCat Info
                available_opts = st.session_state.get('available_items_for_dept', [""])
                try:
                    # Find index of current item in options, default to 0 (blank) if not found
                    current_item_idx = available_opts.index(current_item) if current_item in available_opts else 0
                except ValueError: # Should not happen if "" is in available_opts
                    current_item_idx = 0
                st.selectbox("Item Select", options=available_opts, index=current_item_idx, key=selectbox_key_render,
                             placeholder="Select item...", label_visibility="collapsed",
                             on_change=item_selected_callback, args=(item_id_render, selectbox_key_render))
                st.caption(f"Category: {current_category_val or '-'} | Sub-Cat: {current_subcategory_val or '-'}")
            
            with col2: # Note Input
                st.text_input("Note", value=current_note_val, key=note_key_render,
                              placeholder="Optional note...", label_visibility="collapsed")
            
            with col3: # Quantity Input & Unit Display
                # ***** THIS IS THE KEY CHANGE FOR DECIMAL QUANTITIES *****
                st.number_input(
                    "Quantity",
                    min_value=0.001,  # Allow very small positive decimal values (e.g., 0.001 for 1 gram if unit is kg)
                    value=current_qty_val,  # Ensure this is a float
                    step=0.01,       # Allow decimal steps (e.g., 0.01, 0.1)
                    format="%.3f",   # Display up to 3 decimal places, adjust as needed (e.g., "%.2f")
                    key=qty_key_render,
                    label_visibility="collapsed"
                )
                st.caption(f"Unit: {current_unit_val or '-'}") # Display the purchase unit
            
            with col4: # Remove Button
                 if len(st.session_state.form_items) > 1: # Only show remove if more than one item
                     st.button("❌", key=f"remove_{item_id_render}", on_click=remove_item, args=(item_id_render,), help="Remove this item")
                 else:
                     st.write("") # Keep layout consistent if button is not shown

    st.divider() # Divider after the list of items

    # --- Controls for Adding/Clearing Item Rows ---
    col_add1, col_add2, col_add3 = st.columns([1, 2, 2])
    with col_add1: # Number input for how many rows to add
        st.number_input("Add:", min_value=1, step=1, value=st.session_state.get('num_items_to_add', 1), key='num_items_to_add', label_visibility="collapsed")
    with col_add2: # Button to add rows
        st.button("➕ Add Rows", on_click=handle_add_items_click, use_container_width=True)
    with col_add3: # Button to clear all item rows
        st.button("🔄 Clear Item List", on_click=clear_all_items, use_container_width=True)

    # --- Validation before Submission ---
    has_duplicates_check = bool(duplicates_dict)
    # Ensure 'qty' is checked as float for validation
    has_valid_items_check = any(item_val.get('item') and float(item_val.get('qty', 0.0)) > 0 for item_val in st.session_state.form_items)
    current_dept_check = st.session_state.get("selected_dept", "") # Check if department is selected
    requester_filled_check = bool(st.session_state.get("requested_by", "").strip()) # Check if requester name is filled
    
    # Determine if submit button should be disabled
    submit_disabled_check = not has_valid_items_check or has_duplicates_check or not current_dept_check or not requester_filled_check
    
    error_msgs_list = []
    tooltip_msg_val = "Submit the current indent request." # Default tooltip

    # Populate error messages if validation fails
    if not has_valid_items_check:
        error_msgs_list.append("Add at least one valid item with quantity > 0.")
    if has_duplicates_check:
        error_msgs_list.append(f"Remove duplicate items (marked with ⚠️): {', '.join(duplicates_dict.keys())}.")
    if not current_dept_check:
        error_msgs_list.append("Select a department.")
    if not requester_filled_check:
        error_msgs_list.append("Enter the requester's name.")
    
    st.divider()
    if error_msgs_list: # Display warnings if any validation errors
        for msg_text in error_msgs_list:
            st.warning(f"⚠️ {msg_text}")
        tooltip_msg_val = "Please fix the issues listed above." # Update tooltip if errors exist

    # --- Submission Button and Logic ---
    if st.button("Submit Indent Request", type="primary", use_container_width=True, disabled=submit_disabled_check, help=tooltip_msg_val):
        # Ensure qty is float for submission processing
        final_items_to_submit_unsorted: List[Tuple[str, float, str, str, Optional[str], Optional[str]]] = []
        
        # Final check for duplicates before submission
        final_check_items_submit = [item_val['item'] for item_val in st.session_state.form_items if item_val.get('item') and float(item_val.get('qty', 0.0)) > 0]
        final_counts_submit = Counter(final_check_items_submit)
        final_duplicates_submit = {item_val: count for item_val, count in final_counts_submit.items() if count > 1}
        if bool(final_duplicates_submit):
            st.error(f"Duplicate items detected ({', '.join(final_duplicates_submit.keys())}). Please consolidate before submitting."); st.stop()

        # Process items for submission
        for item_dict_submit in st.session_state.form_items:
            selected_item_submit = item_dict_submit.get('item')
            # Ensure qty is float
            qty_submit = float(item_dict_submit.get('qty', 0.0))
            unit_submit = item_dict_submit.get('unit', '-')
            note_submit = item_dict_submit.get('note', '')
            category_submit = item_dict_submit.get('category')
            subcategory_submit = item_dict_submit.get('subcategory')
            
            # Add item to submission list if valid
            if selected_item_submit and qty_submit > 0 and unit_submit != '-': # Ensure unit is also selected/valid
                final_items_to_submit_unsorted.append((
                    selected_item_submit, qty_submit, unit_submit, note_submit,
                    category_submit or "Uncategorized", subcategory_submit or "General"
                ))
            elif selected_item_submit and qty_submit > 0 and unit_submit == '-': # Warn if item has qty but no unit
                 st.warning(f"Item '{selected_item_submit}' has a quantity but no unit defined. It will be skipped.")

        if not final_items_to_submit_unsorted: # Stop if no valid items to submit
            st.error("No valid items with defined units to submit."); st.stop()
            
        # Sort items by category, subcategory, then item name for consistent output
        final_items_to_submit_sorted = sorted(
            final_items_to_submit_unsorted,
            key=lambda x: (str(x[4] or ''), str(x[5] or ''), str(x[0])) 
        )
        
        requester_submit = st.session_state.get("requested_by", "").strip()
        # Requester name validation already handled by submit_disabled_check

        try:
            mrn_val_submit = generate_mrn() # Generate MRN
            if "ERR" in mrn_val_submit: # Check if MRN generation failed
                st.error(f"Failed to generate MRN ({mrn_val_submit}). Indent not submitted."); st.stop()
            
            # Get other indent details
            timestamp_submit = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            date_req_submit = st.session_state.get("selected_date", date.today())
            formatted_date_submit = date_req_submit.strftime("%d-%m-%Y")
            dept_submit = st.session_state.get("selected_dept", "") # Department from form

            # Prepare rows for Google Sheet, ensuring qty is formatted as string with decimals
            # Expected Google Sheet columns: MRN, Timestamp, Requested By, Department, Date Required, Item, Qty, Unit, Note
            rows_to_add_gsheet = [
                [mrn_val_submit, timestamp_submit, requester_submit, dept_submit, formatted_date_submit,
                 item, f"{qty:.3f}", unit, note if note else "N/A"] # Format qty to .3f (or .2f as needed)
                for item, qty, unit, note, cat, subcat in final_items_to_submit_sorted
            ]
            
            if rows_to_add_gsheet and log_sheet: # Check if there are rows to add and log_sheet is valid
                with st.spinner(f"Submitting indent {mrn_val_submit}..."): # Show spinner during submission
                    try:
                        log_sheet.append_rows(rows_to_add_gsheet, value_input_option='USER_ENTERED')
                        load_indent_log_data.clear() # Clear cache for log data as it's updated
                        calculate_top_items_per_dept.clear() # Clear cache for suggestions as log is updated
                    except gspread.exceptions.APIError as e_gs_api:
                        st.error(f"Google Sheets API Error: {e_gs_api}. Check sheet permissions and column count."); st.stop()
                    except Exception as e_gs_general:
                        st.error(f"Submission error to Google Sheets: {e_gs_general}"); st.exception(e_gs_general); st.stop()
                
                # Store submitted data for summary display
                st.session_state['submitted_data_for_summary'] = {
                    'mrn': mrn_val_submit, 'dept': dept_submit, 'date': formatted_date_submit,
                    'requester': requester_submit, 'items': final_items_to_submit_sorted
                }
                st.session_state['last_dept'] = dept_submit # Persist department for next indent
                clear_all_items() # Clear the form for a new indent
                st.rerun() # Rerun to show summary and refresh form state
        except Exception as e_submit_main: # Catch any other errors during submission process
            st.error(f"Overall submission error: {e_submit_main}"); st.exception(e_submit_main)

    # --- Post-Submission Summary Display ---
    if st.session_state.get('submitted_data_for_summary'):
        submitted_data_val = st.session_state['submitted_data_for_summary']
        st.success(f"Indent submitted successfully! MRN: {submitted_data_val['mrn']}")
        st.balloons(); st.divider(); st.subheader("Submitted Indent Summary")
        st.info(f"**MRN:** {submitted_data_val['mrn']} | **Dept:** {submitted_data_val['dept']} | "
                f"**Reqd Date:** {submitted_data_val['date']} | **By:** {submitted_data_val.get('requester', 'N/A')}")
        
        # Prepare DataFrame for submitted items summary
        # Tuple structure: (item, qty (float), unit, note, category, subcategory)
        summary_df_cols = ["Item", "Qty", "Unit", "Note", "Category", "Sub-Category"]
        summary_df_data = [list(item_s) for item_s in submitted_data_val['items']] # Convert list of tuples to list of lists
        submitted_summary_df = pd.DataFrame(summary_df_data, columns=summary_df_cols)
        
        # Display summary DataFrame
        st.dataframe(submitted_summary_df, hide_index=True, use_container_width=True,
                     column_config={
                         "Category": st.column_config.TextColumn("Category"),
                         "Sub-Category": st.column_config.TextColumn("Sub-Cat"),
                         "Qty": st.column_config.NumberColumn("Qty", format="%.3f") # Format Qty in summary table
                     })
        
        # Calculate total quantity (sum of float quantities)
        total_submitted_qty_val = sum(float(item_s[1]) for item_s in submitted_data_val['items'])
        st.markdown(f"**Total Submitted Items (sum of quantities):** {total_submitted_qty_val:.3f}"); st.divider() # Format total
        
        # PDF Download and WhatsApp Buttons
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1: # PDF Download
            try:
                pdf_data_bytes = create_indent_pdf(submitted_data_val) # Generate PDF bytes
                st.download_button(label="📄 Download PDF", data=pdf_data_bytes,
                                   file_name=f"Indent_{submitted_data_val['mrn']}.pdf", mime="application/pdf", use_container_width=True)
            except Exception as pdf_err:
                st.error(f"Could not generate PDF: {pdf_err}"); st.exception(pdf_err)
        with col_btn2: # WhatsApp Message
            try:
                wa_text_msg = (f"Indent Submitted:\nMRN: {submitted_data_val.get('mrn', 'N/A')}\n"
                               f"Department: {submitted_data_val.get('dept', 'N/A')}\n"
                               f"Requested By: {submitted_data_val.get('requester', 'N/A')}\n"
                               f"Date Required: {submitted_data_val.get('date', 'N/A')}\n\n"
                               "Please see attached PDF for item details.")
                encoded_text_wa = urllib.parse.quote_plus(wa_text_msg) # URL encode the text
                wa_url_link = f"https://wa.me/?text={encoded_text_wa}" # WhatsApp API link
                st.link_button("✅ Prepare WhatsApp Message", wa_url_link, use_container_width=True, target="_blank")
            except Exception as wa_err:
                st.error(f"Could not create WhatsApp link: {wa_err}")
        
        st.caption("NOTE: To share on WhatsApp, first Download PDF, then click Prepare WhatsApp Message, "
                   "choose contact/group, and MANUALLY attach the downloaded PDF before sending.")
        st.divider()
        if st.button("Start New Indent"): # Button to clear summary and start a new indent
            st.session_state['submitted_data_for_summary'] = None # Clear summary data
            # Optionally preserve requester name:
            # current_requester_name = st.session_state.get('requested_by', "")
            # clear_all_items() # This resets form_items
            # st.session_state.requested_by = current_requester_name # Re-assign if preserving
            st.rerun() # Rerun the script to refresh the page

# --- TAB 2: View Indents ---
with tab2:
    st.subheader("View Past Indent Requests")
    log_df_tab2_val = load_indent_log_data() # load_indent_log_data now handles float 'Qty'
    
    if not log_df_tab2_val.empty:
        st.divider()
        with st.expander("Filter Options", expanded=True): # Filters for viewing indents
            dept_opts_filt = sorted([d for d in log_df_tab2_val['Department'].unique() if d and d != ''])
            req_opts_filt = sorted([r for r in log_df_tab2_val['Requested By'].unique() if r and r != '']) if 'Requested By' in log_df_tab2_val.columns else []
            
            # Date range filter setup
            min_ts_filt = log_df_tab2_val['Date Required'].dropna().min()
            max_ts_filt = log_df_tab2_val['Date Required'].dropna().max()
            default_start_dt = date.today() - pd.Timedelta(days=90) # Default start date (90 days ago)
            
            min_date_log_filt = min_ts_filt.date() if pd.notna(min_ts_filt) else default_start_dt
            max_date_log_filt = max_ts_filt.date() if pd.notna(max_ts_filt) else date.today()
            
            # Calculate a sensible default start date for the filter
            calc_default_start = max(min_date_log_filt, default_start_dt) if default_start_dt < max_date_log_filt else min_date_log_filt
            if calc_default_start > max_date_log_filt : calc_default_start = min_date_log_filt # Ensure start is not after max

            # Filter input widgets
            filt_col1, filt_col2, filt_col3 = st.columns([1, 1, 2]) # Layout columns for filters
            with filt_col1: # Date filters
                filt_start_dt_val = st.date_input("Reqd. From", value=calc_default_start,
                                             min_value=min_date_log_filt, max_value=max_date_log_filt,
                                             key="filt_start", format="DD/MM/YYYY")
                valid_end_min_dt = filt_start_dt_val # End date cannot be before start date
                filt_end_dt_val = st.date_input("Reqd. To", value=max_date_log_filt,
                                           min_value=valid_end_min_dt, max_value=max_date_log_filt,
                                           key="filt_end", format="DD/MM/YYYY")
            with filt_col2: # Department and Requester filters
                selected_depts_filt = st.multiselect("Department", options=dept_opts_filt, default=[], key="filt_dept")
                if req_opts_filt: # Only show requester filter if there are options
                    selected_reqs_filt = st.multiselect("Requested By", options=req_opts_filt, default=[], key="filt_req")
            with filt_col3: # MRN and Item Name search filters
                mrn_search_val = st.text_input("MRN", key="filt_mrn", placeholder="e.g., MRN-005")
                item_search_val = st.text_input("Item Name", key="filt_item", placeholder="e.g., Salt")
        
        st.caption("Showing indents required in the last 90 days by default. Use filters above to view older records.")
        
        # Apply filters to the DataFrame
        filtered_df_display = log_df_tab2_val.copy() # Start with a copy of the full log
        try:
            start_filt_ts = pd.Timestamp(st.session_state.filt_start)
            end_filt_ts = pd.Timestamp(st.session_state.filt_end)
            
            # Date Required filter
            date_cond = (filtered_df_display['Date Required'].notna() &
                         (filtered_df_display['Date Required'].dt.normalize() >= start_filt_ts) &
                         (filtered_df_display['Date Required'].dt.normalize() <= end_filt_ts))
            filtered_df_display = filtered_df_display[date_cond]
            
            # Department filter
            if st.session_state.filt_dept:
                filtered_df_display = filtered_df_display[filtered_df_display['Department'].isin(st.session_state.filt_dept)]
            # Requested By filter (check if column exists and filter is selected)
            if req_opts_filt and 'filt_req' in st.session_state and st.session_state.filt_req:
                if 'Requested By' in filtered_df_display.columns: 
                    filtered_df_display = filtered_df_display[filtered_df_display['Requested By'].isin(st.session_state.filt_req)]
            # MRN filter (case-insensitive search)
            if st.session_state.filt_mrn:
                filtered_df_display = filtered_df_display[filtered_df_display['MRN'].astype(str).str.contains(st.session_state.filt_mrn, case=False, na=False)]
            # Item Name filter (case-insensitive search)
            if st.session_state.filt_item:
                filtered_df_display = filtered_df_display[filtered_df_display['Item'].astype(str).str.contains(st.session_state.filt_item, case=False, na=False)]
        except Exception as filter_err:
            st.error(f"Filter error: {filter_err}")
            # On error, filtered_df_display remains a copy of log_df_tab2_val (i.e., shows unfiltered data)
        
        st.divider()
        st.write(f"Displaying {len(filtered_df_display)} records based on filters:")
        
        # Display filtered DataFrame
        st.dataframe(
            filtered_df_display,
            use_container_width=True,
            hide_index=True,
            column_config={ # Configure column display properties
                "Date Required": st.column_config.DateColumn("Date Reqd.", format="DD/MM/YYYY"),
                "Timestamp": st.column_config.DatetimeColumn("Submitted", format="YYYY-MM-DD HH:mm"),
                "Requested By": st.column_config.TextColumn("Req. By"),
                "Qty": st.column_config.NumberColumn("Qty", format="%.3f"), # Display Qty with 3 decimal places
                "MRN": st.column_config.TextColumn("MRN"),
                "Department": st.column_config.TextColumn("Dept."),
                "Item": st.column_config.TextColumn("Item Name", width="medium"),
                "Unit": st.column_config.TextColumn("Unit"),
                "Note": st.column_config.TextColumn("Notes", width="large"),
            }
        )
    else: # If log is empty or unavailable
        st.info("No indent records found or log is unavailable.")

# --- Optional Debug Section (Uncomment to view session state in sidebar) ---
# with st.sidebar.expander("Session State Debug"):
#    st.json(st.session_state.to_dict())
```

This code should now correctly handle decimal quantities and the `calculate_top_items_per_dept` function. Remember to test it thoroughly with your Google Sheets set