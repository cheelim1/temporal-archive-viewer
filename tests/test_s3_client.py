from botocore.exceptions import ClientError, NoCredentialsError

from src import s3_client


def test_blank_exception_never_renders_a_blank_message():
    # streamlit.errors.NoSessionContext (and anything else raised with no
    # args) has str(e) == "" — a blank st.error() box is worse than no
    # message at all. This is exactly what the real NoSessionContext bug
    # (progress_cb called from a worker thread) rendered before the fix.
    class _BlankError(Exception):
        pass

    message = s3_client.friendly_error(_BlankError())
    assert message.strip() != ""
    assert "_BlankError" in message


def test_no_credentials_error_is_actionable():
    message = s3_client.friendly_error(NoCredentialsError())
    assert "AWS_PROFILE" in message or "sso login" in message


def test_access_denied_client_error_is_actionable():
    e = ClientError(
        error_response={"Error": {"Code": "AccessDenied", "Message": "denied"}},
        operation_name="ListObjectsV2",
    )
    message = s3_client.friendly_error(e)
    assert "Access denied" in message
