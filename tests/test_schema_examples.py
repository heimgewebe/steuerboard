from scripts.validate_examples import validate_examples, validate_schemas


def test_schemas_are_valid():
    validated = validate_schemas()
    assert validated
    assert any(path.name == "falsification-case.v1.schema.json" for path in validated)


def test_examples_validate_against_schemas():
    validated = validate_examples()
    assert len(validated) == 23
    assert any(path.name == "duplicate_repo.json" for path in validated)
    assert any(path.name == "unknown_default_branch.json" for path in validated)
