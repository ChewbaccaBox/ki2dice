#!/usr/bin/env python3
"""
            This tool converts a KiCad netlist (.net) into a DICE circuit .cpp file.

            Usage:
                python3 ki2dice.py dodgeball.net dodgeball.cpp

            Requires dice_parts.json in the same directory as this script.


"""

import re
import json
import argparse
from pathlib import Path


# Turn netlist into nested python lists.
def parse_sexp(text):
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', text)
    stack = [[]]
    for token in tokens:
        if token == '(':
            stack.append([])
        elif token == ')':
            item = stack.pop()
            stack[-1].append(item)
        elif token.startswith('"'):
            stack[-1].append(re.sub(r'\\(.)', r'\1', token[1:-1]))
        else:
            stack[-1].append(token)
    return stack[0][0]


def children(node, name):
    return [item for item in node[1:] if isinstance(item, list) and item and item[0] == name]


def child_value(node, name):
    found = children(node, name)
    if found and len(found[0]) > 1:
        return found[0][1]
    return ''


def read_netlist(path):
    root = parse_sexp(Path(path).read_text(encoding='utf-8'))

    # Scrape Parts
    parts = []
    for comp in children(children(root, 'components')[0], 'comp'):
        source = children(comp, 'libsource')
        fields = {}
        for group in children(comp, 'fields'):
            for field in children(group, 'field'):
                fields[child_value(field, 'name')] = field[2] if len(field) > 2 else ''
        parts.append({
            'ref': child_value(comp, 'ref'),
            'value': child_value(comp, 'value'),
            'lib': child_value(source[0], 'lib') if source else '',
            'symbol': child_value(source[0], 'part') if source else '',
            'fields': fields,
        })

    # Scrape Nets
    nets = []
    for net in children(children(root, 'nets')[0], 'net'):
        pins = []
        for node in children(net, 'node'):
            pins.append({
                'ref': child_value(node, 'ref'),
                'pin': child_value(node, 'pin'),
                'type': child_value(node, 'pintype'),
            })
        nets.append({'name': child_value(net, 'name'), 'pins': pins})

    return parts, nets


def read_config(path):
    def no_duplicates(pairs):
        keys = [key for key, _ in pairs]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise SystemExit(f'{path.name}: duplicate key(s) {", ".join(duplicates)} - each key may appear only once')
        return dict(pairs)

    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=no_duplicates)


def fill(template, values):
    missing = []

    def replace(match):
        value = values.get(match.group(1), '')
        if value == '':
            missing.append(match.group(1))
        return value

    result = re.sub(r'\$\{([^}]+)\}', replace, template)
    if missing:
        return None, missing
    return result, []


def build_chips(parts, library, game, notes):

    chips = {}
    desc_lines = []
    unmapped = []

    for part in parts:
        if part['value'] and part['value'] != '~':
            key = part['value']
        else:
            key = part['symbol']

        entry = library.get(key)
        if entry is None:
            unmapped.append(f'{part["ref"]} ({key})')
            if not part['lib']:
                notes.append(f'{part["ref"]}: symbol "{key}" has no library - it is a local copy in the schematic; '
                             f're-link it to its library symbol (Change Symbol / Update Symbol from Library)')
            continue

        values = dict(part['fields'])
        values['ref'] = part['ref']
        values['game'] = game

        for template in entry.get('desc', []):
            line, missing = fill(template, values)
            if line is None:
                notes.append(f'{part["ref"]}: no {", ".join(missing)} field, left out: {template.strip()}')
            else:
                desc_lines.append(line)

        if 'chip' in entry:
            line, _ = fill(entry['chip'], values)
        elif 'arg' in entry:
            arg, _ = fill(entry['arg'], values)
            line = f'CHIP("{part["ref"]}", {entry["type"]}, {arg})'
        else:
            line = f'CHIP("{part["ref"]}", {entry["type"]})'

        chips[part['ref']] = {
            'name': entry.get('name', part['ref']),
            'entry': entry,
            'line': line,
        }

    return chips, desc_lines, unmapped


def is_output(pin):
    return pin['type'].startswith(('output', 'open_collector', 'tri_state'))


def pin_text(pin, chips):
    chip = chips[pin['ref']]
    return f'"{chip["name"]}", {pin["pin"]}'


def pin_list(pins):
    return ', '.join(f'{pin["ref"]}.{pin["pin"]}' for pin in pins)


def build_connections(nets, chips, rails, notes):
    lines = []
    problems = []
    open_inputs = []

    for net in nets:
        pins = []

        # Strip power pins from consideration.
        for pin in net['pins']:
            if pin['ref'] not in chips:
                continue
            if pin['type'] == 'power_in':
                continue
            pins.append(pin)

        if net['name'] in rails:
            rail = rails[net['name']]
            shorted = [pin for pin in pins if is_output(pin)]
            if shorted:
                notes.append(f'output(s) tied to rail "{net["name"]}": {pin_list(shorted)}')
            for pin in pins:
                lines.append(f'CONNECTION({rail}, {pin_text(pin, chips)})')
            continue

        drivers = [pin for pin in pins if is_output(pin)]
        # Inputs marked no-connect in the schematic are intentionally left open.
        loads = [pin for pin in pins if not is_output(pin) and 'no_connect' not in pin['type']]

        if not loads:
            continue   # nothing to drive (unused output or empty net)

        if not drivers and len(net['pins']) == 1:
            open_inputs += loads   # pin with nothing attached; DICE ties it to GND
            continue

        if len(drivers) != 1:
            problem = f'{len(drivers)} drivers on net "{net["name"]}": {pin_list(pins)}'
            problems.append(problem)
            notes.append(problem)
            continue

        driver = drivers[0]
        for pin in loads:
            lines.append(f'CONNECTION({pin_text(driver, chips)}, {pin_text(pin, chips)})')

    if open_inputs:
        notes.append(f'inputs left open (DICE ties them to GND): {pin_list(open_inputs)}')

    return lines, problems


def write_cpp(path, game, chips, desc_lines, connections, problems, unmapped):
    lines = ['#include "../circuit_desc.h"', '']

    if unmapped:
        lines.append('// Not converted (no entry in dice_parts.json): ' + ', '.join(unmapped))
        lines.append('')

    if desc_lines:
        lines += desc_lines
        lines.append('')

    lines.append(f'CIRCUIT_LAYOUT( {game} )')
    for chip in chips.values():
        lines.append('\t' + chip['line'])
    lines.append('')

    for connection in connections:
        lines.append('\t' + connection)

    if problems:
        lines.append('')
        for problem in problems:
            lines.append(f'\t// NOT WIRED: {problem}')

    lines += ['CIRCUIT_LAYOUT_END', '']
    Path(path).write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('netlist')
    parser.add_argument('output')
    args = parser.parse_args()

    game = Path(args.output).stem
    config = read_config(Path(__file__).parent / 'dice_parts.json')
    parts, nets = read_netlist(args.netlist)

    notes = []
    chips, desc_lines, unmapped = build_chips(parts, config['parts'], game, notes)
    connections, problems = build_connections(nets, chips, config['rails'], notes)

    write_cpp(args.output, game, chips, desc_lines, connections, problems, unmapped)

    print(f'{len(chips)} chips, {len(connections)} connections written to {args.output}')
    if unmapped:
        print('not converted: ' + ', '.join(unmapped))
    for note in notes:
        print('note: ' + note)


if __name__ == '__main__':
    main()
