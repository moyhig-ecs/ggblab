#!/usr/bin/env python3
"""Quick verification of parser and test setup."""
import sys
import polars as pl
from ggblab.parser import ggb_parser

# Test fixture
simple_construction = {
    'Name': ['A', 'B', 'AB', 'M'],
    'Type': ['point', 'point', 'segment', 'point'],
    'Command': ['', '', 'Segment[A, B]', 'Midpoint[A, B]'],
    'Value': ['(0, 0)', '(3, 4)', '', '(1.5, 2)'],
    'Caption': ['', '', '', ''],
    'Layer': [0, 0, 0, 0]
}

print("Testing DataFrame creation...")
df = pl.DataFrame(simple_construction, strict=False)
print(f"DataFrame shape: {df.shape}")
print(f"DataFrame columns: {df.columns}")
print(f"DataFrame:\n{df}")

print("\nTesting parser initialization...")
parser = ggb_parser(cache_enabled=False)
print(f"Parser created: {parser}")

print("\nAssigning dataframe to parser...")
parser.df = df
print(f"Parser.df shape: {parser.df.shape}")
print(f"Parser.df columns: {parser.df.columns}")

print("\nCalling parser.parse()...")
try:
    parser.parse()
    print(f"Parse successful!")
    print(f"Roots: {parser.roots}")
    print(f"Leaves: {parser.leaves}")
    print(f"Graph nodes: {list(parser.G.nodes())}")
    print(f"Graph edges: {list(parser.G.edges())}")
except Exception as e:
    print(f"Parse failed with error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nAll checks passed!")
