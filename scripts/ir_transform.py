#!/usr/bin/env python3
"""Transform base IR or GeoGebra XML to extended IR with computed fields and inferences.

Usage:
  PYTHONPATH=/path/to/ggblab python scripts/ir_transform.py <input.xml|input_ir.json> [--out out.json] [--validate]

The script will:
 - load IR (or build from XML)
 - assign stable ids to commands and link elements.command_id
 - compute simple numeric properties (angle degrees, dot products)
 - run heuristic Thales detection and append to inferences
 - optionally validate against docs/ir_extended_schema.json
"""
import sys
import json
import math
from pathlib import Path
from ggblab.construction_io import ConstructionIO


def load_ir(path):
    p = Path(path)
    if p.suffix.lower() == '.xml':
        return ConstructionIO._ir_from_xml_file(str(p))
    else:
        return json.loads(p.read_text(encoding='utf-8'))


def assign_ids(ir):
    # assign ids to commands if missing, ensure integer ids
    for i, c in enumerate(ir.get('commands', [])):
        if 'id' not in c:
            c['id'] = i
    # index outputs -> command id
    out_map = {}
    for c in ir.get('commands', []):
        for o in c.get('outputs', []):
            out_map.setdefault(o, []).append(c['id'])
    # assign element.command_id
    name_to_elem = {e['name']: e for e in ir.get('elements', [])}
    for e in ir.get('elements', []):
        ids = out_map.get(e['name'])
        e['command_id'] = ids[0] if ids else None
    return ir


def compute_angle_info(ir):
    # compute degrees for Angle commands and attach computed to element if angle element exists
    name2elem = {e['name']: e for e in ir.get('elements', [])}
    for c in ir.get('commands', []):
        if c.get('name') == 'Angle':
            ins = c.get('inputs', [])
            if len(ins) >= 3:
                A, P, B = ins[0], ins[1], ins[2]
                pa = name2elem.get(A, {}).get('coords')
                pp = name2elem.get(P, {}).get('coords')
                pb = name2elem.get(B, {}).get('coords')
                if pa and pp and pb:
                    v1 = (pa['x'] - pp['x'], pa['y'] - pp['y'])
                    v2 = (pb['x'] - pp['x'], pb['y'] - pp['y'])
                    dot = v1[0]*v2[0] + v1[1]*v2[1]
                    n1 = math.hypot(v1[0], v1[1])
                    n2 = math.hypot(v2[0], v2[1])
                    deg = None
                    if n1 and n2:
                        cosang = max(-1.0, min(1.0, dot/(n1*n2)))
                        deg = math.degrees(math.acos(cosang))
                    # attach to vertex element
                    v_elem = name2elem.get(P)
                    if v_elem is not None:
                        v_elem.setdefault('computed', {})
                        v_elem['computed'].setdefault('angles', []).append({'at': c.get('outputs', [None])[0], 'degree': deg, 'dot': dot})
    return ir


def detect_thales(ir, eps_deg=1e-2):
    # robust Thales detection using Midpoint->Circle->Point patterns and numeric check
    cmds = ir.get('commands', [])
    name2elem = {e['name']: e for e in ir.get('elements', [])}
    id2cmd = {c['id']: c for c in cmds}
    mid_cmds = [c for c in cmds if c.get('name') == 'Midpoint']
    circles = [c for c in cmds if c.get('name') == 'Circle']
    points_on_circle_cmds = [c for c in cmds if c.get('name') == 'Point']

    inferences = []
    for m in mid_cmds:
        inputs = m.get('inputs', [])
        outs = m.get('outputs', [])
        if len(inputs) < 2 or len(outs) < 1:
            continue
        A, C = inputs[0], inputs[1]
        O = outs[0]
        # find circle with center O
        for circ in circles:
            cin = circ.get('inputs', [])
            # accept either (O,C) or (C,O)
            if len(cin) >= 2 and (cin[0] == O or (cin[1] == O)):
                c_name = circ.get('outputs', [None])[0]
                # find any point produced by that circle
                for p_cmd in points_on_circle_cmds:
                    pin = p_cmd.get('inputs', [])
                    if pin and pin[0] == c_name:
                        P = p_cmd.get('outputs', [None])[0]
                        # numeric check: angle at P between A and C
                        eP = name2elem.get(P)
                        if not eP or not eP.get('coords'):
                            continue
                        eA = name2elem.get(A)
                        eC = name2elem.get(C)
                        if not eA or not eA.get('coords') or not eC or not eC.get('coords'):
                            continue
                        v1 = (eC['coords']['x'] - eP['coords']['x'], eC['coords']['y'] - eP['coords']['y'])
                        v2 = (eA['coords']['x'] - eP['coords']['x'], eA['coords']['y'] - eP['coords']['y'])
                        dot = v1[0]*v2[0] + v1[1]*v2[1]
                        n1 = math.hypot(v1[0], v1[1])
                        n2 = math.hypot(v2[0], v2[1])
                        if n1==0 or n2==0:
                            continue
                        cosang = max(-1.0, min(1.0, dot/(n1*n2)))
                        deg = math.degrees(math.acos(cosang))
                        is_right = abs(deg - 90.0) <= eps_deg
                        evidence = [f"Midpoint({C},{A})->{O}", f"Circle(center={O})", f"Point(on={c_name})->{P}", f"angle_deg={deg}"]
                        inferences.append({'pattern':'thales', 'subjects':{'A':A,'C':C,'O':O,'P':P}, 'evidence': evidence, 'confidence': 0.99 if is_right else 0.5})
    return inferences


def build_indices(ir):
    by_layer = {}
    has_coords = []
    for e in ir.get('elements', []):
        by_layer.setdefault(str(e.get('layer')), []).append(e['name'])
        if e.get('coords') is not None:
            has_coords.append(e['name'])
    ir['by_layer'] = by_layer
    ir['has_coords'] = has_coords
    return ir


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('--out', '-o')
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()

    ir = load_ir(args.input)
    ir = assign_ids(ir)
    ir = compute_angle_info(ir)
    inferences = detect_thales(ir)
    ir.setdefault('inferences', []).extend(inferences)
    ir = build_indices(ir)

    outp = Path(args.out) if args.out else None
    if outp is None:
        outp = Path.cwd() / f"extended_ir_{Path(args.input).stem}.json"
    outp.write_text(json.dumps(ir, ensure_ascii=False, indent=2), encoding='utf-8')
    print(outp)

    if args.validate:
        try:
            from jsonschema import Draft7Validator
            schema = json.loads(Path('docs/ir_extended_schema.json').read_text(encoding='utf-8'))
            v = Draft7Validator(schema)
            errors = list(v.iter_errors(ir))
            if errors:
                print('Validation errors:')
                for e in errors:
                    print('-', '/'.join([str(p) for p in e.path]) or '(root)', e.message)
            else:
                print('Validated against docs/ir_extended_schema.json')
        except Exception as e:
            print('Validation skipped (jsonschema missing or error):', e)


if __name__ == '__main__':
    main()
