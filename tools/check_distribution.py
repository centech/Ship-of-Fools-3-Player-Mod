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
    check(plan['original_sha256'] == patch.BASELINE_SHA256, 'Baseline fingerprint mismatch.')
    check(set(plan['actions']) == {'Install', 'Uninstall'}, 'Unexpected actions.')
    check(plan['version'] == package.VERSION, 'Release versions differ.')
    for action, key in [('Install', 'patched_sha256'), ('Uninstall', 'original_sha256')]:
        check(plan['actions'][action]['sha256'] == plan[key], 'Action hash mismatch: ' + action)
        check(plan[key] in plan['accepted_sha256'], 'Output is not recognized: ' + action)
    check(patch.PREVIOUS_SHA256.issubset(plan['accepted_sha256']), 'Missing upgrade input.')

    # The original game is absent. Header/hook payloads and new sections are
    # still enough to verify all embedded helper bytes and native hook targets.
    install = plan['actions']['Install']
    writes = [(int(w['offset']), base64.b64decode(w['data'], validate=True))
              for w in install['writes']]
    for offset, data in writes:
        check(offset >= 0 and offset + len(data) <= install['size'], 'Write outside output.')
    header = next(data for offset, data in writes if offset == 0)
    check(struct.unpack_from('<I', header, 0x258)[0] == 0x224080c,
          'Original game section size changed.')
    for expected_offset, expected in [(0x7a5dd9, bytes.fromhex('e8 52 8b 22 00')),
                                      (0x260d810, bytes(102))]:
        check((expected_offset, expected) in writes,
              'Normal ship cleanup was not restored when upgrading an older mod.')
    _, _, _, sections = patch.pe_layout(header)
    for rva, expected in [(manifest['code_rva'], code), (manifest['data_rva'], state)]:
        offset = patch.offset(sections, rva)
        part = next((data[offset-start:offset-start+len(expected)]
                     for start, data in writes
                     if start <= offset and offset+len(expected) <= start+len(data)), None)
        check(part == expected, 'Portable plan embeds a different helper payload.')
    hooks = [(0x6dde70, 'third_spawn'), (0x925a20, 'third_reset'),
             (0x6dd430, 'third_despawn'), (0x1187030, 'third_input_awake'),
             (0x8fed9a, 'third_dispatch'), (0x8c0e90, 'third_inventory_update'),
             (0x8c0490, 'third_inventory_match')] + [
             (rva, 'third_save_count') for rva in [0x6c5331, 0x6c5389, 0x6c563e, 0x6c5696]]
    for rva, symbol in hooks:
        offset = patch.offset(sections, rva)
        data = next(data for start, data in writes if start == offset)
        check(data[0] in (0xe8, 0xe9), 'Unexpected hook opcode.')
        target = rva + 5 + struct.unpack_from('<i', data, 1)[0]
        check(target == manifest['symbols'][symbol]['rva'], 'Wrong hook target: ' + symbol)

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
    print('PASS: release ZIP, file hashes, plan, payload, 11 hooks and normal ship cleanup.')
    print('No game DLL was needed or bundled.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        sys.exit(1)
