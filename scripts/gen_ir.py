#!/usr/bin/env python3
"""Generate a temporary IR JSON from a GeoGebra file and validate it.

Usage:
  python scripts/gen_ir.py input_file [--schema PATH] [--out-dir PATH]

Writes the path to the generated IR JSON on success.
"""
import argparse
import sys

def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate temporary IR JSON from GeoGebra file')
    parser.add_argument('input', help='Path to .xml/.ggb/.json input file')
    parser.add_argument('--schema', default='docs/ir_schema.json', help='Path to IR JSON Schema')
    parser.add_argument('--out-dir', default=None, help='Directory to write temp IR into (optional)')
    args = parser.parse_args(argv)

    try:
        from ggblab.construction_io import DataFrameIO
    except Exception as e:
        print('ERROR: could not import ggblab.dataframe_io:', e, file=sys.stderr)
        return 2

    try:
        import asyncio
        out_path = asyncio.run(DataFrameIO.save_temp_ir_from_file(args.input, schema_path=args.schema, out_dir=args.out_dir))
        print(out_path)
        return 0
    except Exception as e:
        print('ERROR: failed to generate IR:', e, file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
