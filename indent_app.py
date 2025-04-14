import streamlit as st

st.set_page_config(layout="wide") # Use wide layout like original app might
st.title("Minimal Test Case: Add/Remove Items")

# Initialize item count and potentially the first item's state
if "minimal_item_count" not in st.session_state:
    st.session_state.minimal_item_count = 1
    # Initialize first item state explicitly if needed, otherwise rely on render loop
    st.session_state["m_input_0"] = ""
    st.session_state["m_num_0"] = 1
    st.write("Initialized state.")

st.write(f"(Current item count: {st.session_state.minimal_item_count})")

# --- Add/Remove Buttons ---
col1_btn, col2_btn, _ = st.columns([1,1,4]) # Basic columns for buttons
with col1_btn:
    if st.button("➕ Add Item"):
        new_index = st.session_state.minimal_item_count
        # Initialize state for the NEW row ONLY
        st.session_state[f"m_input_{new_index}"] = "" # Initialize new item state
        st.session_state[f"m_num_{new_index}"] = 1
        st.session_state.minimal_item_count += 1
        # No rerun needed, button click triggers it

with col2_btn:
     if st.button("➖ Remove Last", disabled=st.session_state.minimal_item_count <= 1):
        remove_index = st.session_state.minimal_item_count - 1
        st.session_state.pop(f"m_input_{remove_index}", None) # Remove state for last item
        st.session_state.pop(f"m_num_{remove_index}", None)
        st.session_state.minimal_item_count -= 1
        # No rerun needed

st.markdown("---")
st.write("**Instructions:** Enter text in 'Field 0'. Click '+ Add Item'. Does the text in 'Field 0' reset?")
st.write("Then enter text in 'Field 1', click '+ Add Item' again. Does text in 'Field 0' or 'Field 1' reset?")
st.markdown("---")


# --- Render input fields ---
for i in range(st.session_state.minimal_item_count):
    # Initialize state using setdefault just in case (shouldn't be needed here if Add/Remove manage it)
    # Using different default to see if setdefault interferes
    st.session_state.setdefault(f"m_input_{i}", f"Default Set {i}")
    st.session_state.setdefault(f"m_num_{i}", i+1)

    col1, col2 = st.columns([3,1]) # Basic columns like original app
    with col1:
        st.text_input(
            label=f"Text Field {i}",
            key=f"m_input_{i}", # Unique key
            label_visibility="collapsed",
            placeholder=f"Enter text for item {i}"
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
