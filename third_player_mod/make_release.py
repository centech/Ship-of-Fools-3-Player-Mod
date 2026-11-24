#!/usr/bin/env python3
"""Build the portable mod plan from local Steam 1.5.4 DLLs."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parent
VERSION = '0.5.0'
GAME_VERSION = '1.5.4'


def writes(data, spans):
    return [{'offset': start, 'data': base64.b64encode(data[start:start + size]).decode()}
            for start, size in spans]


def variant_plan(patch, original, name):
    final = patch.build_patch(original)
    _, opt, _, sections = patch.pe_layout(original)
    spans = [(0, 0x400)] + [(patch.offset(sections, rva), len(bytes.fromhex(expected)))
                            for rva, expected, _, _ in patch.HOOKS]
    variant = {
        'name': name,
        'label': patch.BASELINES[patch.sha(original)],
        'original_sha256': patch.sha(original),
        'patched_sha256': patch.sha(final),
        'backup_suffix': f'.backup-before-3-player-mod-{GAME_VERSION}' + ('-siren' if name == 'siren' else ''),
        'actions': {},
    }
    for action, data in [('Install', final), ('Uninstall', original)]:
        ops = writes(data, spans)
        copies = [{'source': 0, 'offset': 0, 'length': len(original)}]
        if action == 'Install':
            _, newopt, _, newsections = patch.pe_layout(data)
            oldrva, oldsize = struct.unpack_from('<II', original, opt + 112 + 3 * 8)
            ro_rva, _, ro_off = newsections[-1]
            tabrva, tabsz = struct.unpack_from('<II', data, newopt + 112 + 3 * 8)
            ops += writes(data, [(off, size) for _, size, off in newsections[-3:-1]])
            table_start = ro_off + tabrva - ro_rva
            ops += writes(data, [(ro_off, table_start - ro_off),
                                 (table_start + oldsize, tabsz - oldsize)])
            copies.append({'source': patch.offset(sections, oldrva),
                           'offset': table_start, 'length': oldsize})
        operation = {'size': len(data), 'sha256': patch.sha(data), 'copies': copies, 'writes': ops}
        variant['actions'][action] = operation
        for source in (original, final):
            if patch.reconstruct(source, operation) != data:
                raise ValueError(f'Plan reconstruction mismatch for {name} {action}.')
    return variant


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-dll', type=Path, required=True)
    parser.add_argument('--siren-dll', type=Path, required=True, help='Uncombined Siren Update 1.2 DLL.')
    parser.add_argument('--output-dir', type=Path, default=ROOT)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('patch', ROOT.parent / 'patch_third_player.py')
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    inputs = [('stock', args.original_dll, patch.BASELINE_SHA256), ('siren', args.siren_dll, patch.SIREN_SHA256)]
    variants = []
    for name, path, expected in inputs:
        original = path.read_bytes()
        if patch.sha(original) != expected:
            raise ValueError(f'Unexpected input DLL for {name}: {path}')
        variants.append(variant_plan(patch, original, name))
        print(f"{name} DLL SHA256: {variants[-1]['patched_sha256']}")
    plan = {'version': VERSION, 'game_version': GAME_VERSION, 'variants': variants}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(plan, indent=2) + '\n').encode()
    script = (ROOT / 'patch.ps1').read_text()
    script, count = re.subn(r"(Get-BytesHash \$planBytes\) -ne ')[0-9a-f]{64}",
                            lambda match: match[1] + patch.sha(encoded), script)
    if count != 1:
        raise ValueError('Cannot find installer plan fingerprint.')
    (args.output_dir / 'release-plan.json').write_bytes(encoded)
    (args.output_dir / 'patch.ps1').write_text(script)
    print('Plan SHA256: ' + patch.sha(encoded))


if __name__ == '__main__':
    main()
