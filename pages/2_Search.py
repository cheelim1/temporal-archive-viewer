from datetime import date, timedelta

import streamlit as st

from src import index_store, s3_client, scan, ui_components

st.set_page_config(page_title="Search — Temporal Archive Viewer", page_icon="🔍", layout="wide")
st.title("🔍 Search")

bucket, profile, root_prefix, client = ui_components.render_connection_sidebar()
conn = index_store.get_connection()

st.markdown(
    "Scan a namespace + date/hour range once (results are cached locally in "
    "`~/.cache/temporal-archive-viewer/index.db`), then filter across everything "
    "you've scanned so far without re-hitting S3. "
    "**To abort a scan in progress, use Streamlit's own Stop button** "
    "(top-right of this page) — per-request timeouts are capped short, so "
    "it takes effect within seconds rather than hanging."
)


def _pick_namespace(ns: str) -> None:
    # Runs before the script body reruns, so mutating the text_input's own
    # session_state key here is safe (doing it after the widget has already
    # been instantiated in a normal run raises StreamlitWidgetAlreadyInstantiatedError).
    st.session_state.search_namespace = ns


namespace_raw = st.text_input("Namespace", key="search_namespace")
namespace = namespace_raw.strip().rstrip("/")
if namespace and namespace == bucket:
    st.warning(
        "Namespace is the same as the S3 bucket name — that's almost always a mistake "
        "(the namespace is a subfolder *inside* the bucket, e.g. `your-namespace.anoxj`). "
        "Use 'Discover it from the bucket' below to find the real one."
    )
with st.expander("Don't know the namespace? Discover it from the bucket"):
    if st.button("List namespaces under root prefix"):
        try:
            namespace_prefixes, _ = ui_components.cached_list_prefix(client, bucket, root_prefix)
            st.session_state.discovered_namespaces = sorted(
                cp[len(root_prefix):].rstrip("/") for cp in namespace_prefixes
            )
        except Exception as e:
            st.error(s3_client.friendly_error(e))

    # Rendered outside the button's `if` so these survive the rerun that
    # picking one of them triggers (st.button() is only True on the exact
    # run it was clicked, so nesting these inside it would make the list
    # disappear before the click could be registered).
    discovered = st.session_state.get("discovered_namespaces", [])
    if discovered:
        for ns in discovered:
            st.button(ns, key=f"ns-{ns}", on_click=_pick_namespace, args=(ns,))
    elif "discovered_namespaces" in st.session_state:
        st.info("No namespaces found under this root prefix.")

col1, col2, col3 = st.columns(3)
start_date = col1.date_input("From date", value=date.today() - timedelta(days=1))
end_date = col2.date_input("To date", value=date.today())
hours_text = col3.text_input("Hours (optional, e.g. 13-17 or 0,6,12)", value="")

num_days = max((end_date - start_date).days + 1, 0)
confirm_large_scan = True
if num_days > 14:
    st.warning(f"That's a {num_days}-day range — listing alone is {num_days} S3 calls (parallelized).")
    confirm_large_scan = st.checkbox(f"Yes, scan all {num_days} days")
else:
    st.caption(f"Will list {num_days} day(s), one S3 call per day (run concurrently).")

scan_col, warn_col = st.columns([1, 3])
if scan_col.button("Scan range", type="primary", disabled=not confirm_large_scan):
    if not namespace:
        st.error("Namespace is required.")
    else:
        hours: list[int] | None = None
        try:
            hours = scan.parse_hours(hours_text)
        except ValueError as e:
            st.error(f"Could not parse the hours field: {e}")
            st.stop()

        summaries: list[dict] = []
        list_errors: list[tuple[str, str]] = []
        list_progress = st.progress(0.0)
        list_status = st.empty()

        def _list_progress(done: int, total: int) -> None:
            list_progress.progress(done / total if total else 1.0)
            list_status.text(f"Listed {done}/{total} day(s)")

        try:
            summaries, list_errors = scan.list_object_summaries(
                client, bucket, root_prefix, namespace, start_date, end_date, hours,
                progress_cb=_list_progress,
            )
        except Exception as e:
            st.error(s3_client.friendly_error(e))
            st.stop()
        list_progress.empty()
        list_status.empty()

        if list_errors:
            with st.expander(f"⚠️ {len(list_errors)} day(s) failed to list and were skipped"):
                for day_str, msg in list_errors:
                    st.text(f"{day_str}: {msg}")

        if not summaries:
            st.info("No objects found for that namespace/date/hour range.")
        else:
            if len(summaries) > 500:
                warn_col.warning(f"{len(summaries)} files matched — fetching may take a while.")
            progress = st.progress(0.0)
            status_text = st.empty()

            def _progress(done: int, total: int) -> None:
                progress.progress(done / total if total else 1.0)
                status_text.text(f"{done}/{total} files processed")

            failures = scan.scan_and_index(client, bucket, summaries, conn, progress_cb=_progress)
            st.success(f"Indexed {len(summaries) - len(failures)}/{len(summaries)} file(s).")
            if failures:
                with st.expander(f"⚠️ {len(failures)} file(s) failed to fetch/decode and were skipped"):
                    for key, msg in failures:
                        st.text(f"{key}: {msg}")

st.divider()
st.subheader("Filter cached results")

f1, f2, f3 = st.columns(3)
workflow_id_filter = f1.text_input("Workflow ID contains")
workflow_type_filter = f2.text_input("Workflow type contains")
text_filter = f3.text_input("Payload text contains (ticket id, email, etc.)")
status_filter = st.multiselect(
    "Status", ["COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT", "CANCELED", "RUNNING"]
)

key_prefix = f"{root_prefix}{namespace}/" if namespace else root_prefix
rows = index_store.search(
    conn,
    bucket=bucket,
    key_prefix=key_prefix,
    workflow_id=workflow_id_filter,
    workflow_type=workflow_type_filter,
    text=text_filter,
    statuses=status_filter or None,
)

st.caption(f"{len(rows)} matching workflow execution(s) in the local cache.")
if rows:
    st.dataframe(rows, width="stretch", hide_index=True)

    def _row_label(i: int) -> str:
        r = rows[i]
        return f"{r['workflow_id']} · {r['workflow_type']} · {r['status']} · {r['key'].split('/')[-1]}"

    selected_idx = st.selectbox("Open a result", options=range(len(rows)), format_func=_row_label)

    def _open_selected() -> None:
        st.session_state.search_selected_row = rows[selected_idx]

    # Stored in session_state (not just gated behind `if st.button(...)`)
    # because the detail view below renders its own widgets (checkbox,
    # expanders) — interacting with ANY of them triggers a rerun on which
    # st.button() is no longer "clicked", so a button-gated render would
    # vanish the instant the user touched anything inside it.
    st.button("View workflow", on_click=_open_selected)

selected_row = st.session_state.get("search_selected_row")
if selected_row:
    history = index_store.get_history_json(conn, selected_row["bucket"], selected_row["key"], selected_row["item_index"])
    st.divider()
    if history is None:
        st.error("Cached history not found — try re-scanning this range.")
    else:
        ui_components.render_workflow_detail(
            history,
            source_label=selected_row["key"],
            widget_key=f"{selected_row['key']}#{selected_row['item_index']}",
        )
