#!/usr/bin/env python3
"""Detect geometric patterns in an IR produced by ConstructionIO.

Detectors implemented (heuristic):
- Thales: Midpoint(A,C) -> O and Circle(O,C) and Point(c) on circle + Angle(C,P,A) ~ 90° or Angle command
- Pythagoras: presence of a right angle (Angle command with degree ~90) and Distance commands for triangle
- Cosine law: presence of Angle + Distance expressions or named expressions referencing cos
- Projection / Christoffel: expressions with 'proj_' or 'Γ' (Gamma) names
- Geometric mean: expressions named g_1,g_2,g_3 or Area-based ratios

Run: PYTHONPATH=/path/to/ggblab python scripts/detect_patterns.py examples/2025_13_01.xml
"""
import sys
import math
from ggblab.construction_io import ConstructionIO


def approx_right_angle_at(ir, pt_name):
    # look for Angle command with outputs that reference an angle at pt_name
    for c in ir['commands']:
        if c.get('name') == 'Angle':
            ins = c.get('inputs', [])
            # Angle(C, P, A) -> middle is vertex
            if len(ins) >= 3 and ins[1] == pt_name:
                return True, c
    # numeric check using coords if available
    els = {e['name']: e for e in ir['elements']}
    if pt_name in els:
        # try to find two neighbors A,C that form an angle at pt_name
        P = els[pt_name].get('coords')
        if P is None:
            return False, None
        # find two points with coords connected by segments possibly
        pts = [e for e in els.values() if e.get('coords') is not None and e['name'] != pt_name]
        # bruteforce pairs and test near 90 deg
        for a in pts:
            for b in pts:
                if a['name'] == b['name']:
                    continue
                v1 = (a['coords']['x']-P['coords']['x'], a['coords']['y']-P['coords']['y'])
                v2 = (b['coords']['x']-P['coords']['x'], b['coords']['y']-P['coords']['y'])
                dot = v1[0]*v2[0] + v1[1]*v2[1]
                n1 = math.hypot(v1[0], v1[1])
                n2 = math.hypot(v2[0], v2[1])
                if n1==0 or n2==0:
                    continue
                cosang = dot/(n1*n2)
                if abs(abs(cosang) - 0) < 1e-6:
                    return True, {'approx': True, 'pair': (a['name'], b['name'])}
    return False, None


def detect_thales(ir):
    # Find Midpoint(C,A) -> O; Circle(O,C) -> c; Point(c) -> P; Angle at P is right
    cmds = ir['commands']
    els = {e['name']: e for e in ir['elements']}
    mid_cmds = [c for c in cmds if c.get('name') == 'Midpoint']
    circles = [c for c in cmds if c.get('name') == 'Circle']
    points_on_circle = [c for c in cmds if c.get('name') == 'Point']

    evidences = []
    for m in mid_cmds:
        inputs = m.get('inputs', [])
        outs = m.get('outputs', [])
        if len(inputs) >= 2 and len(outs) >= 1:
            A, C = inputs[0], inputs[1]
            O = outs[0]
            # check circle with center O and C as radius
            for circ in circles:
                if circ.get('inputs', [])[:2] == [O, C]:
                    # find point on that circle
                    for p in points_on_circle:
                        if C in circ.get('inputs', []) and p.get('inputs', []) and p.get('inputs', [])[0] == circ.get('outputs', [None])[0]:
                            P = p.get('outputs', [None])[0]
                            # check angle at P between PC and PA
                            right, evidence = approx_right_angle_at(ir, P)
                            evidences.append({'A': A, 'C': C, 'O': O, 'c': circ.get('outputs', [None])[0], 'P': P, 'right_at_P': right, 'evidence': evidence})
    return evidences


def detect_projection_and_gamma(ir):
    exprs, _, _ = ConstructionIO._parse_construction_xml(sys.argv[1]) if len(sys.argv)>1 else ({},[],[])
    found_proj = {k: v for k, v in exprs.items() if k.startswith('proj_')}
    found_gamma = {k: v for k, v in exprs.items() if 'Γ' in k or 'Gamma' in k}
    return found_proj, found_gamma


def detect_geometric_mean(ir):
    exprs, _, _ = ConstructionIO._parse_construction_xml(sys.argv[1]) if len(sys.argv)>1 else ({},[],[])
    keys = set(exprs.keys())
    gm_keys = {k: exprs.get(k) for k in ('g_1','g_2','g_3') if k in keys}
    # also detect Area[...] usage in expressions
    area_exprs = {k:v for k,v in exprs.items() if v and 'Area[' in v}
    return gm_keys, area_exprs


def detect_pythagoras_and_cosine(ir):
    # Heuristic: look for Angle + Distance commands or expressions containing cos and squared norms
    exprs, _, _ = ConstructionIO._parse_construction_xml(sys.argv[1]) if len(sys.argv)>1 else ({},[],[])
    cos_related = {k:v for k,v in exprs.items() if v and ('cos(' in v or 'cos ' in v)}
    square_related = {k:v for k,v in exprs.items() if v and ('^2' in v or '**2' in v or '(^' in v)}
    # distance commands
    dcmds = [c for c in ir['commands'] if c.get('name')=='Distance']
    return cos_related, square_related, dcmds


def main():
    if len(sys.argv) < 2:
        print('Usage: detect_patterns.py <xml_or_ir_path>')
        sys.exit(2)
    path = sys.argv[1]
    # accept xml or directly build ir
    if path.lower().endswith('.xml'):
        ir = ConstructionIO._ir_from_xml_file(path)
    else:
        import json
        ir = json.load(open(path,'r',encoding='utf-8'))

    print('\n=== Thales detections ===')
    th = detect_thales(ir)
    if not th:
        print('No Thales pattern detected')
    else:
        for t in th:
            print('Thales candidate:', t)

    print('\n=== Projection / Gamma expressions ===')
    proj, gamma = detect_projection_and_gamma(ir)
    print('proj expressions:', list(proj.keys()))
    print('Gamma expressions:', list(gamma.keys()))

    print('\n=== Geometric mean ===')
    gm, area = detect_geometric_mean(ir)
    print('g keys:', list(gm.keys()))
    print('area expressions (sample):', list(area.items())[:5])

    print('\n=== Pythagoras / Cosine detections ===')
    cos_rel, sq_rel, dcmds = detect_pythagoras_and_cosine(ir)
    print('cos expressions sample:', list(cos_rel.keys())[:10])
    print('square-related expressions sample:', list(sq_rel.keys())[:10])
    print('Distance commands count:', len(dcmds))

if __name__ == '__main__':
    main()
