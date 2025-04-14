import streamlit as st

st.set_page_config(layout="wide")
st.title("Minimal Test Case - Step 3: Selectbox + Options from State + Callback")

# --- Simulate loading data into session state ONCE ---
if 'test_master_list' not in st.session_state:
    st.session_state['test_master_list'] = ["Apple", "Banana", "Carrot", "Date", "Eggplant", "Fig"]
    st.write("Initialized master list in session state.")
# ---

# Initialize item count
if "minimal_item_count" not in st.session_state:
    st.session_state.minimal_item_count = 1
    st.session_state["m_select_0"] = None
    st.session_state["m_num_0"] = 1
    st.session_state["m_cb_status_0"] = "Not triggered"
    # st.write("Initialized row state.") # Less verbose

st.write(f"(Current item count: {st.session_state.minimal_item_count})")

# --- Callback Function ---
def simple_test_callback(index):
    st.session_state[f"m_cb_status_{index}"] = f"Triggered for index {index}!"
    # st.write(f"DEBUG: Callback fired for index {index}")


# --- Add/Remove Buttons ---
col1_btn, col2_btn, _ = st.columns([1,1,4])
with col1_btn:
    if st.button("➕ Add Item"):
        new_index = st.session_state.minimal_item_count
        st.session_state[f"m_select_{new_index}"] = None
        st.session_state[f"m_num_{new_index}"] = 1
        st.session_state[f"m_cb_status_{new_index}"] = "Not triggered"
        st.session_state.minimal_item_count += 1
        # No rerun needed

with col2_btn:
     if st.button("➖ Remove Last", disabled=st.session_state.minimal_item_count <= 1):
        remove_index = st.session_state.minimal_item_count - 1
        st.session_state.pop(f"m_select_{remove_index}", None)
        st.session_state.pop(f"m_num_{remove_index}", None)
        st.session_state.pop(f"m_cb_status_{remove_index}", None)
        st.session_state.minimal_item_count -= 1
        # No rerun needed

st.markdown("---")
st.write("**Instructions:** Select an option in 'Item 0'. Click '+ Add Item'. Does the selection in 'Item 0' reset?")
st.markdown("---")

# --- Render input fields ---
# Get the options list from session state
options_from_state = [""] + st.session_state.get('test_master_list', [])

for i in range(st.session_state.minimal_item_count):
    # Initialize state using setdefault
    st.session_state.setdefault(f"m_select_{i}", None)
    st.session_state.setdefault(f"m_num_{i}", 1)
    st.session_state.setdefault(f"m_cb_status_{i}", "Not triggered")

    col1, col2, col3 = st.columns([3, 1, 2])
    with col1:
        # Use selectbox with options derived from session state
        st.selectbox(
            label=f"Item {i}",
            options=options_from_state, # *** Use list from session state ***
            key=f"m_select_{i}",
            label_visibility="collapsed",
            placeholder="Select an item...",
            on_change=simple_test_callback,
            args=(i,)
        )
    with col2:
         st.number_input(
             label=f"Number {i}", key=f"m_num_{i}", label_visibility="collapsed"
         )
    with col3:
        st.text(f"Cb Status: {st.session_state.get(f'm_cb_status_{i}', 'N/A')}")

    st.divider()


st.markdown("---")
st.subheader("Current Session State:")
st.json(st.session_state.to_dict())
