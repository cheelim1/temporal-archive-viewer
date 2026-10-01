import streamlit as st

from src import decode, s3_client, ui_components

st.set_page_config(page_title="Browse — Temporal Archive Viewer", page_icon="📂", layout="wide")
st.title("📂 Browse")

bucket, profile, root_prefix, client = ui_components.render_connection_sidebar()

if "browse_prefix" not in st.session_state or st.session_state.get("browse_root") != root_prefix:
    st.session_state.browse_prefix = root_prefix
    st.session_state.browse_root = root_prefix

prefix = st.session_state.browse_prefix

# Breadcrumb navigation: one clickable button per path segment below the root.
crumb_targets = [root_prefix]
for segment in prefix[len(root_prefix):].rstrip("/").split("/"):
    if segment:
        crumb_targets.append(crumb_targets[-1] + segment + "/")

crumb_cols = st.columns(len(crumb_targets))
for i, target in enumerate(crumb_targets):
    label = "🏠 root" if i == 0 else target.rstrip("/").split("/")[-1]
    disabled = target == prefix
    if crumb_cols[i].button(label, key=f"crumb-{i}-{target}", disabled=disabled):
        st.session_state.browse_prefix = target
        st.rerun()

common_prefixes: list[str] = []
files: list[dict] = []
try:
    common_prefixes, files = ui_components.cached_list_prefix(client, bucket, prefix)
except Exception as e:
    st.error(s3_client.friendly_error(e))
    st.stop()

if common_prefixes:
    st.write("**Folders**")
    for cp in sorted(common_prefixes):
        label = cp[len(prefix):].rstrip("/")
        if st.button(f"📁 {label}", key=f"cp-{cp}"):
            st.session_state.browse_prefix = cp
            st.rerun()

# Zero-byte "folder marker" objects (key ends in "/", created e.g. by the S3
# console's "Create folder" button) aren't real export files — decoding one
# just yields zero workflow executions, and leaving it in the dropdown shows
# a confusing blank label (nothing follows the last "/" to show).
selectable_files = [f for f in files if not f["Key"].endswith("/")]

selected_key: str | None = None
if selectable_files:
    st.write("**Files**")
    options = [f["Key"] for f in selectable_files]
    selected_key = st.selectbox(
        "Select a file", options=options, format_func=lambda k: k.split("/")[-1], key="browse_file_select"
    )
    if st.button("Open file", type="primary"):
        try:
            with st.spinner("Fetching and decoding..."):
                data, _ = ui_components.cached_get_object_bytes(client, bucket, selected_key)
                histories = decode.decode_export_bytes(data)
            st.session_state.browse_histories = histories
            st.session_state.browse_file_key = selected_key
        except Exception as e:
            st.error(f"Failed to decode this object: {e}")
            st.session_state.browse_histories = None
            st.session_state.browse_file_key = None

if not common_prefixes and not selectable_files:
    st.info("No objects found under this prefix.")

histories = st.session_state.get("browse_histories")
opened_key = st.session_state.get("browse_file_key")
if histories is not None and selectable_files and selected_key != opened_key:
    # The dropdown selection has moved on from what's actually loaded below —
    # without this, changing the selection left the OLD file's detail view
    # on screen with no indication it no longer matches the dropdown, which
    # reads as "nothing happened" or, worse, as if it were the new selection.
    st.info("Selection changed — click 'Open file' to load it.")
elif histories is not None and not histories:
    st.info("This file contains no workflow executions (it may be an empty/placeholder object).")
elif histories:
    st.divider()
    if len(histories) > 1:
        st.caption(f"This file contains {len(histories)} workflow executions.")

        def _label(i: int) -> str:
            attrs = decode.event_attrs(histories[i]["events"][0]) if histories[i].get("events") else {}
            return f"{i}: {attrs.get('workflowId', '?')}"

        idx = st.selectbox(
            "Workflow execution in this file", options=range(len(histories)), format_func=_label
        )
    else:
        idx = 0
    ui_components.render_workflow_detail(
        histories[idx], source_label=opened_key, widget_key=f"{opened_key}#{idx}"
    )
