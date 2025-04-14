import streamlit as st

st.set_page_config(layout="wide")
st.title("Minimal Test Case - Step 1: Selectbox (Static Options)")

# Initialize item count
if "minimal_item_count" not in st.session_state:
    st.session_state.minimal_item_count = 1
    st.session_state["m_select_0"] = None # Initialize first selectbox state
    st.session_state["m_num_0"] = 1
    st.write("Initialized state.")

st.write(f"(Current item count: {st.session_state.minimal_item_count})")

# --- Add/Remove Buttons ---
col1_btn, col2_btn, _ = st.columns([1,1,4])
with col1_btn:
    if st.button("➕ Add Item"):
        new_index = st.session_state.minimal_item_count
        # Initialize state for the NEW row ONLY
        st.session_state[f"m_select_{new_index}"] = None # Initialize new selectbox state
        st.session_state[f"m_num_{new_index}"] = 1
        st.session_state.minimal_item_count += 1
        # No rerun needed

with col2_btn:
     if st.button("➖ Remove Last", disabled=st.session_state.minimal_item_count <= 1):
        remove_index = st.session_state.minimal_item_count - 1
        st.session_state.pop(f"m_select_{remove_index}", None) # Remove state for last item
        st.session_state.pop(f"m_num_{remove_index}", None)
        st.session_state.minimal_item_count -= 1
        # No rerun needed

st.markdown("---")
st.write("**Instructions:** Select an option in 'Item 0'. Click '+ Add Item'. Does the selection in 'Item 0' reset?")
st.markdown("---")

# --- Render input fields ---
# Define static options list
STATIC_OPTIONS = ["", "Apple", "Banana", "Carrot", "Date", "Eggplant"]

for i in range(st.session_state.minimal_item_count):
    # Initialize state using setdefault
    st.session_state.setdefault(f"m_select_{i}", None)
    st.session_state.setdefault(f"m_num_{i}", 1)

    col1, col2 = st.columns([3,1])
    with col1:
        # Use selectbox instead of text_input
        st.selectbox(
            label=f"Item {i}",
            options=STATIC_OPTIONS, # Use static list
            key=f"m_select_{i}", # Unique key
            label_visibility="collapsed",
            placeholder="Select an item..." # Placeholder if state is None
        )
    with col2:
         st.number_input(
             label=f"Number {i}",
             key=f"m_num_{i}", # Unique key
             label_visibility="collapsed"
         )
    st.divider()


st.markdown("---")
st.subheader("Current Session State:")
st.json(st.session_state.to_dict()) # Display the raw state
