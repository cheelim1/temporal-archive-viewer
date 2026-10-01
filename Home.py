import streamlit as st

st.set_page_config(page_title="Temporal Archive Viewer", page_icon="🗂️", layout="wide")

st.title("🗂️ Temporal Archive Viewer")
st.markdown(
    """
Temporal Cloud exports closed workflow histories to S3 in **Protobuf**, not
JSON, which makes them unreadable without decoding them first. This tool
decodes them on the fly using the official `temporalio` protobuf definitions.

Use the pages in the sidebar:

- **Browse** — drill down through the S3 bucket like the AWS console
  (namespace → date → hour → shard), open a file, and view its decoded
  workflow history.
- **Search** — scope a namespace + date/hour range, scan it once (cached
  locally afterwards), and filter across many archived workflows by
  workflow ID, workflow type, status, or payload contents (e.g. a ticket ID
  or user email embedded in the workflow input).

Both pages need AWS credentials for the target account available via your
local default credential chain (env vars, `~/.aws/config` profile, or an
active SSO session) — set the profile in the sidebar if you don't use the
default one.
"""
)
