# Wait! In the trace I saw:
#        with pytest.raises(ValidationError):
# >           validate_instance(invalid_scope, _action_approval_schema(), EXAMPLES_DIR / "invalid-action-approval-scope-false.json")
#
# tests/test_schema_examples.py:573:
# _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
# steuerboard/schema_validation.py:177: in validate_instance
#    _validate(instance, schema, path)
#
# Wait! `tests/test_schema_examples.py` is calling `validate_instance` from `steuerboard/schema_validation.py`?!
# Let's check imports in `tests/test_schema_examples.py`.
