import re

with open("scripts/validate_examples.py", "r") as f:
    content = f.read()

replacement = """        if "minimum" in schema and instance < schema["minimum"]:
            raise ValidationError(f"{path}: {instance!r} is less than minimum {schema['minimum']!r}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            raise ValidationError(f"{path}: {instance!r} is less than or equal to exclusiveMinimum {schema['exclusiveMinimum']!r}")
        if "maximum" in schema and instance > schema["maximum"]:"""

content = content.replace('        if "minimum" in schema and instance < schema["minimum"]:\n            raise ValidationError(f"{path}: {instance!r} is less than minimum {schema[\'minimum\']!r}")\n        if "maximum" in schema and instance > schema["maximum"]:', replacement)

with open("scripts/validate_examples.py", "w") as f:
    f.write(content)
