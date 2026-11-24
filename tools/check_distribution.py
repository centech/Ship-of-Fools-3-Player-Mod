#!/usr/bin/env python3
"""Verify the tracked player ZIP, hashes and payload without any game files."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def check(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    package = load_module('package_release', ROOT / 'third_player_mod/package_release.py')
    patch = load_module('patch_third_player', ROOT / 'patch_third_player.py')
    mod = ROOT / 'third_player_mod'
    manifest = json.loads((mod / 'manifest.json').read_bytes())
    plan_bytes = (mod / 'release-plan.json').read_bytes()
    plan = json.loads(plan_bytes)
    code, state = (mod / 'code.bin').read_bytes(), (mod / 'state.bin').read_bytes()
    check(sha(code) == manifest['code_sha256'], 'Helper code does not match manifest.')
    check(sha(state) == manifest['state_sha256'], 'State does not match manifest.')
    script = (mod / 'patch.ps1').read_text()
    fingerprint = re.search(r"Get-BytesHash \$planBytes\) -ne '([0-9a-f]{64})'", script)
    check(fingerprint is not None and fingerprint[1] == sha(plan_bytes),
          'PowerShell plan fingerprint is stale.')
    check(plan['version'] == package.VERSION, 'Release versions differ.')
    check({item['original_sha256'] for item in plan['variants']} == set(patch.BASELINES),
          'Baseline fingerprints differ.')
    check(len(plan['variants']) == len(patch.BASELINES), 'Repeated input version.')

    # Check each variant without distributing any protected game files.
    for variant in plan['variants']:
        check(set(variant['actions']) == {'Install', 'Uninstall'}, 'Unexpected actions.')
        for action, key in [('Install', 'patched_sha256'), ('Uninstall', 'original_sha256')]:
            check(variant['actions'][action]['sha256'] == variant[key], 'Action hash mismatch: ' + action)
        install = variant['actions']['Install']
        writes = {int(w['offset']): base64.b64decode(w['data'], validate=True) for w in install['writes']}
        undo = {int(w['offset']): base64.b64decode(w['data'], validate=True)
                for w in variant['actions']['Uninstall']['writes']}
        for offset, data in writes.items():
            check(offset >= 0 and offset + len(data) <= install['size'], 'Write outside output.')
        _, _, _, sections = patch.pe_layout(writes[0])
        for rva, expected in [(manifest['code_rva'], code), (manifest['data_rva'], state)]:
            offset = patch.offset(sections, rva)
            part = next((data[offset-start:offset-start+len(expected)]
                         for start, data in writes.items()
                         if start <= offset and offset+len(expected) <= start+len(data)), None)
            check(part == expected, 'Portable plan embeds a different helper payload.')
        for rva, expected, symbol, opcode in patch.HOOKS:
            offset = patch.offset(sections, rva)
            data = writes[offset]
            check(data[0] == opcode, 'Unexpected hook opcode.')
            target = rva + 5 + struct.unpack_from('<i', data, 1)[0]
            check(target == manifest['symbols'][symbol]['rva'], 'Wrong hook target: ' + symbol)
            check(undo[offset].hex() == expected, 'Uninstall must restore the expected game instruction.')

    archive = ROOT / ('dist/Ship-of-Fools-3-Player-Mod-'+package.VERSION+'.zip')
    sidecar = archive.with_suffix('.zip.sha256').read_text().split()
    check(sidecar == [sha(archive.read_bytes()), archive.name], 'ZIP SHA256 mismatch.')
    check(set(package.FILES) == {'Install.cmd', 'Uninstall.cmd', 'READ ME.txt',
          'third_player_mod/LICENSE.txt', 'third_player_mod/patch.ps1',
          'third_player_mod/release-plan.json'}, 'Unexpected player package contents.')
    expected_names = set(package.FILES) | {'SHA256SUMS.txt'}
    with zipfile.ZipFile(archive) as z:
        check(z.testzip() is None, 'Corrupt release ZIP.')
        check(len(z.namelist()) == len(expected_names) and set(z.namelist()) == expected_names,
              'ZIP contains unexpected, missing or duplicate files.')
        checksum_bytes = z.read('SHA256SUMS.txt')
        check(checksum_bytes == (ROOT / 'dist/SHA256SUMS.txt').read_bytes(),
              'ZIP and external per-file checksums differ.')
        checksums = {}
        for line in checksum_bytes.decode().splitlines():
            digest, name = line.split('  ', 1)
            check(name not in checksums, 'Duplicate per-file checksum.')
            checksums[name] = digest
        check(set(checksums) == set(package.FILES), 'Per-file checksum list is incomplete.')
        for name in package.FILES:
            data = (ROOT / name).read_bytes()
            check(z.read(name) == data, 'Release ZIP is stale: ' + name)
            check(sha(data) == checksums[name], 'Per-file SHA256 mismatch: ' + name)
            check(Path(name).suffix.lower() not in {'.dll', '.exe', '.bundle', '.sav', '.log'},
                  'Game/personal file in release: ' + name)
            check(len(data) < 1_000_000, 'Unexpected large file in release: ' + name)
    for name in ('ship.PNG', 'ship2.PNG'):
        check((ROOT / name).is_file() and ']('+name+')' in (ROOT / 'README.md').read_text(),
              'README screenshot is missing: '+name)
    print('PASS: release ZIP, file hashes, plan, payload, 11 hooks for both Steam 1.5.4 inputs.')
    print('No game DLL was needed or bundled.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        sys.exit(1)
