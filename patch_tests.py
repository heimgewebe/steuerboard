# The user actually WANTS `invalid-action-approval-whitespace-approval-id.json` to fail!
# It is an intentional test that tests an INVALID example!
# But the test is written as:
# def test_action_approval_schema_rejects_whitespace_padded_identifiers():
#     ...
#     with pytest.raises(ValidationError):
#         validate_instance(...)
#
# Wait, ValidationError comes from `scripts.validate_examples`, but `validate_instance` comes from `steuerboard.schema_validation`!
# Ah! In my `test_addition`, I added:
# from steuerboard.schema_validation import SchemaValidationError, validate_instance
#
# Did that override the global `ValidationError` or `validate_instance`? Let's check `tests/test_schema_examples.py`.
