import json
from ggblab.construction_io import ConstructionIO

def validate(ir):
    errors = []
    if not isinstance(ir, dict):
        errors.append(('(root)', 'not object'))
    if 'schema_version' not in ir or not isinstance(ir.get('schema_version'), int):
        errors.append(('schema_version','missing or not integer'))
    if 'elements' not in ir or not isinstance(ir.get('elements'), list):
        errors.append(('elements','missing or not array'))

    for i,e in enumerate(ir.get('elements', [])):
        p=f'elements[{i}]'
        if not isinstance(e, dict):
            errors.append((p,'not object'))
            continue
        if 'id' not in e or not isinstance(e['id'], int):
            errors.append((p+'.id','missing or not int'))
        if 'name' not in e or not isinstance(e['name'], str):
            errors.append((p+'.name','missing or not str'))
        if 'type' not in e or not isinstance(e['type'], str):
            errors.append((p+'.type','missing or not str'))
    return errors

if __name__ == '__main__':
    ir = ConstructionIO._ir_from_xml_file('examples/2025_13_01.xml')
    errs = validate(ir)
    print('errors_count', len(errs))
    for p,m in errs[:50]:
        print(p+':', m)
    # dump sample
    print('\nsample element 0:')
    print(json.dumps(ir['elements'][0], ensure_ascii=False, indent=2))
    print('\ncommands count:', len(ir.get('commands',[])))
