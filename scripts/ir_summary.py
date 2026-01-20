#!/usr/bin/env python3
from ggblab.construction_io import ConstructionIO
from collections import Counter
import json

def summarize(xml_path='examples/2025_13_01.xml'):
    ir = ConstructionIO._ir_from_xml_file(xml_path)
    els = ir['elements']
    cmds = ir['commands']
    types = Counter(e.get('type') for e in els)
    coords_have = sum(1 for e in els if e.get('coords') is not None)
    with_cmd = sum(1 for e in els if e.get('command') is not None)
    cmd_names = Counter(c.get('name') for c in cmds)
    layers = Counter(e.get('layer') for e in els)
    show_obj = Counter(e.get('show_object') for e in els)
    show_lbl = Counter(e.get('show_label') for e in els)

    summary = {
        'elements': len(els),
        'commands': len(cmds),
        'type_counts': dict(types),
        'elements_with_coords': coords_have,
        'elements_with_command_obj': with_cmd,
        'command_name_counts': dict(cmd_names),
        'layer_counts': dict(layers),
        'show_object_counts': dict(show_obj),
        'show_label_counts': dict(show_lbl)
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    summarize()
