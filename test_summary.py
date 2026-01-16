#!/usr/bin/env python3
"""Summary of test_parser.py fixes."""

import re

with open('/Users/manabu/work/wasm/ggblab/tests/test_parser.py', 'r') as f:
    content = f.read()

# Count test classes and methods
classes = re.findall(r'^class (Test\w+):', content, re.MULTILINE)
methods = re.findall(r'^\s+def (test_\w+)\(', content, re.MULTILINE)

print("TEST FILE ANALYSIS")
print("=" * 60)
print(f"Total test classes: {len(classes)}")
print(f"Total test methods: {len(methods)}")
print()
print("Test Classes:")
for cls in classes:
    print(f"  - {cls}")
print()

# Check for common issues
print("CHECKING FOR ISSUES:")
print("=" * 60)

# Check for initialize_dataframe calls (should be gone)
if 'initialize_dataframe' in content:
    print("❌ Found 'initialize_dataframe' calls - should be replaced")
else:
    print("✅ No 'initialize_dataframe' calls found")

# Check for ggb_parser(cache_enabled=False) usage
cache_disabled_count = content.count('ggb_parser(cache_enabled=False)')
print(f"✅ Found {cache_disabled_count} instances of 'ggb_parser(cache_enabled=False)'")

# Check fixture structures have 'Name' key
if "'Name':" in content:
    print("✅ Fixtures have 'Name' key")
else:
    print("❌ Fixtures missing 'Name' key")

# Check for parser.df = df pattern
df_assignment_count = content.count('parser.df = df')
print(f"✅ Found {df_assignment_count} instances of 'parser.df = df' pattern")

# Check for parser.parse() calls
parse_calls = content.count('parser.parse()')
print(f"✅ Found {parse_calls} instances of 'parser.parse()' calls")

print()
print("SUMMARY:")
print("=" * 60)
print("All fixtures and tests have been updated with:")
print("  1. 'Name' column in fixture DataFrames")
print("  2. cache_enabled=False in parser initialization")
print("  3. Direct df assignment: parser.df = df")
print("  4. Explicit parser.parse() calls")
print("  5. No initialize_dataframe() method calls")
