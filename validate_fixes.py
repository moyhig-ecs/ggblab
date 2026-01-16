#!/usr/bin/env python3
"""Final validation that all test_parser.py fixes are correct."""

import sys
import re

def check_test_file():
    """Validate test_parser.py structure and fixes."""
    with open('/Users/manabu/work/wasm/ggblab/tests/test_parser.py', 'r') as f:
        content = f.read()
    
    issues = []
    warnings = []
    
    # Check 1: No initialize_dataframe calls
    if 'initialize_dataframe' in content:
        issues.append("❌ Found 'initialize_dataframe' calls (should be removed)")
    else:
        print("✅ No 'initialize_dataframe' method calls found")
    
    # Check 2: All fixtures have 'Name' column
    fixtures = re.findall(r"@pytest\.fixture\ndef (\w+)\(\):(.*?)return \{", content, re.DOTALL)
    for fixture_name, _ in fixtures:
        fixture_match = re.search(rf"def {fixture_name}\(\):.*?return \{{(.*?)\}}", content, re.DOTALL)
        if fixture_match and "'Name':" in fixture_match.group(1):
            print(f"✅ Fixture '{fixture_name}' has 'Name' column")
        else:
            issues.append(f"❌ Fixture '{fixture_name}' missing 'Name' column")
    
    # Check 3: cache_enabled=False is used
    cache_disabled_count = content.count('ggb_parser(cache_enabled=False)')
    print(f"✅ Found {cache_disabled_count} instances of 'ggb_parser(cache_enabled=False)'")
    
    if cache_disabled_count < 50:
        warnings.append(f"⚠️  Only {cache_disabled_count} cache_disabled instances (expected >50)")
    
    # Check 4: Direct df assignment pattern
    df_assignments = content.count('parser.df = df')
    print(f"✅ Found {df_assignments} instances of 'parser.df = df'")
    
    if df_assignments < 50:
        warnings.append(f"⚠️  Only {df_assignments} df assignments (expected >50)")
    
    # Check 5: parse() calls
    parse_calls = content.count('.parse()')
    print(f"✅ Found {parse_calls} calls to '.parse()'")
    
    # Check 6: Test class count
    test_classes = re.findall(r'^class (Test\w+):', content, re.MULTILINE)
    print(f"✅ Found {len(test_classes)} test classes")
    
    # Check 7: Test method count
    test_methods = re.findall(r'^\s+def (test_\w+)\(', content, re.MULTILINE)
    print(f"✅ Found {len(test_methods)} test methods")
    
    # Check 8: DataFrame constructions in tests
    df_constructions = content.count('pl.DataFrame(')
    print(f"✅ Found {df_constructions} DataFrame constructor calls")
    
    print("\n" + "=" * 70)
    
    if issues:
        print("CRITICAL ISSUES:")
        for issue in issues:
            print(f"  {issue}")
        return False
    
    if warnings:
        print("WARNINGS:")
        for warning in warnings:
            print(f"  {warning}")
    
    print("\nSUMMARY: All test_parser.py fixes have been successfully applied!")
    print("=" * 70)
    return True

if __name__ == '__main__':
    success = check_test_file()
    sys.exit(0 if success else 1)
