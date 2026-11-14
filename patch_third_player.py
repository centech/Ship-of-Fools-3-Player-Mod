#!/usr/bin/env python3
"""Developer PE builder and command-line installer for the 3 Player Mod.

Installation for players uses Install.cmd and Uninstall.cmd. Native builds use
an exact original game DLL supplied by the developer, outside the repository.
"""
import argparse
import base64
import re
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile

BASELINE_SHA256 = 'c9e858959f9d6c4d45b74e5d9a60532bb4ea4298b652f06f7272aace61242f67'
PREVIOUS_SHA256 = {'5e84ddb03ca605c79e4b3f5d61bae30a7a60efbf1bfb88b69ae444e9931822b1','c634edc51ac12e57ae523df8f4bea250572e78ee78529bcaca231cbd8f131998','c740d78166c28841567c7cd6875f9f7f28be37d5a141dd3021ef078c6aa84fe6','a225b05eee16ef7168c9a6e7c3e6f7576e39ab7ab0ed141a69eb47886e18390a','d9dfa912f09d733c4118d582496f8081124e58dfeb7f24dee12b72f41b7122e6'}
ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / 'third_player_mod'

def sha(data): return hashlib.sha256(data).hexdigest()
def align(n, a): return (n + a - 1) // a * a
def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]

def pe_layout(data):
    pe = u32(data, 0x3c)
    if data[pe:pe+4] != b'PE\0\0' or u16(data,pe+4) != 0x8664:
        raise ValueError('Expected Windows x64 PE image.')
    optional = pe+24
    section_table = optional+u16(data,pe+20)
    sections = []
    for i in range(u16(data, pe+6)):
        h = section_table + i*40
        sections.append((u32(data,h+12), u32(data,h+16), u32(data,h+20)))
    return pe, optional, section_table, sections

def offset(sections, rva):
    for address, size, file in sections:
        if address <= rva < address+size: return file+rva-address
    raise ValueError(f'RVA outside file-backed sections: {rva:x}')

def build_patch(baseline):
    if sha(baseline) != BASELINE_SHA256:
        raise ValueError('Unsupported DLL. The builder requires the exact original game build.')
    m = json.loads((PAYLOAD/'manifest.json').read_text())
    code, state = (PAYLOAD/'code.bin').read_bytes(), (PAYLOAD/'state.bin').read_bytes()
    if sha(code) != m['code_sha256'] or sha(state) != m['state_sha256']:
        raise ValueError('Payload files failed verification.')
    pe, opt, table, sections = pe_layout(baseline)
    count = u16(baseline, pe+6)
    header = table + count*40
    if any(baseline[header:header+120]) or header+120 > min(x[2] for x in sections):
        raise ValueError('No unused space for the new section headers.')
    file_align, section_align = u32(baseline,opt+36), u32(baseline,opt+32)
    if m['code_rva'] != align(u32(baseline,opt+56),section_align):
        raise ValueError('Unexpected image size.')

    # Retain every existing RUNTIME_FUNCTION record and append helpers in RVA
    # order. Put unwind data/table in a read-only section, code RX, state RW.
    old_rva, old_size = struct.unpack_from('<II',baseline,opt+112+3*8)
    old_table = baseline[offset(sections,old_rva):offset(sections,old_rva)+old_size]
    ro = bytearray()
    entries = bytearray(old_table)
    for f in sorted(m['functions'], key=lambda f:f['begin']):
        info = bytes.fromhex(f['unwind'])
        entries.extend(struct.pack('<III',f['begin'],f['end'],m['unwind_rva']+len(ro)))
        ro.extend(info)
    table_rva = m['unwind_rva']+len(ro)
    ro.extend(entries)
    result = bytearray(baseline)
    added = [(b'.sofcode',m['code_rva'],code,0x60000020),
             (b'.sofdata',m['data_rva'],state,0xc0000040),
             (b'.sofunw',m['unwind_rva'],bytes(ro),0x40000040)]
    code_size = data_size = 0
    for i, (name, address, blob, flags) in enumerate(added):
        file = align(len(result),file_align)
        size = align(len(blob),file_align)
        result.extend(bytes(file-len(result)))
        result.extend(blob)
        result.extend(bytes(size-len(blob)))
        # Windows requires contiguous section coverage. Reserve the code-to-data
        # gap as zero-filled executable virtual space rather than leaving a hole.
        virtual_size = (added[i+1][1]-address) if i==0 else len(blob)
        struct.pack_into('<8sIIIIIIHHI',result,header+i*40,name,virtual_size,address,
                         size,file,0,0,0,0,flags)
        if flags & 0x20: code_size += size
        else: data_size += size
    struct.pack_into('<H',result,pe+6,count+3)
    struct.pack_into('<I',result,opt+4,u32(baseline,opt+4)+code_size)
    struct.pack_into('<I',result,opt+8,u32(baseline,opt+8)+data_size)
    struct.pack_into('<I',result,opt+56,align(m['unwind_rva']+len(ro),section_align))
    struct.pack_into('<I',result,opt+64,0) # unsigned user-mode DLL; checksum optional
    struct.pack_into('<II',result,opt+112+3*8,table_rva,len(entries))
    hooks = [
        (0x6dde70,'48895c2408','third_spawn',b'\xe9'),
        (0x925a20,'405641554156','third_reset',b'\xe9'),
        (0x6dd430,'40564883ec20','third_despawn',b'\xe9'),
        (0x1187030,'40534883ec20','third_input_awake',b'\xe9'),
        (0x8fed9a,'e851daddff','third_dispatch',b'\xe8'),
        (0x8c0e90,'48895c2410','third_inventory_update',b'\xe9'),
        (0x8c0490,'40534881ec60010000','third_inventory_match',b'\xe9'),
        (0x6c5331,'e8aad3e3ff','third_save_count',b'\xe8'),
        (0x6c5389,'e852d3e3ff','third_save_count',b'\xe8'),
        (0x6c563e,'e89dd0e3ff','third_save_count',b'\xe8'),
        (0x6c5696,'e845d0e3ff','third_save_count',b'\xe8'),
    ]
    for address, expected, symbol, opcode in hooks:
        expected = bytes.fromhex(expected)
        file = offset(sections,address)
        if baseline[file:file+len(expected)] != expected:
            raise ValueError(f'Hook bytes mismatch at {address:x}.')
        target = m['symbols'][symbol]['rva']
        result[file:file+len(expected)] = opcode+struct.pack('<i',target-address-5)+b'\x90'*(len(expected)-5)
    return bytes(result)

def replace(path, data):
    fd, name = tempfile.mkstemp(prefix='.third-player-',suffix='.tmp',dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(staged,stat.S_IMODE(path.stat().st_mode))
        if staged.read_bytes() != data: raise ValueError('Staged DLL verification failed.')
        os.replace(staged,path)
    finally:
        if staged.exists(): staged.unlink()

def read_plan():
    encoded = (PAYLOAD/'release-plan.json').read_bytes()
    script = (PAYLOAD/'patch.ps1').read_text()
    expected = re.search(r"Get-BytesHash \$planBytes\) -ne '([0-9a-f]{64})'", script)
    if expected is None or sha(encoded) != expected[1]:
        raise ValueError('Patch data failed verification.')
    return json.loads(encoded)


def reconstruct(source, operation):
    result = bytearray(operation['size'])
    for part in operation['copies']:
        start, size, target = part['source'], part['length'], part['offset']
        value = source[start:start+size]
        if len(value) != size: raise ValueError('Incomplete source DLL.')
        result[target:target+size] = value
    for part in operation['writes']:
        value = base64.b64decode(part['data'], validate=True)
        result[part['offset']:part['offset']+len(value)] = value
    if len(result) != operation['size'] or sha(result) != operation['sha256']:
        raise ValueError('Generated DLL failed verification.')
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply','check','restore'])
    parser.add_argument('--dll', type=Path, default=ROOT/'GameAssembly.dll')
    args = parser.parse_args()
    dll = args.dll.resolve()
    current = dll.read_bytes()
    plan = read_plan()
    if sha(current) not in plan['accepted_sha256']:
        raise ValueError('Unsupported game DLL. Nothing was changed.')
    if args.action == 'check':
        status = 'INSTALLED' if sha(current)==plan['patched_sha256'] else (
            'not installed' if sha(current)==BASELINE_SHA256 else 'older revision installed')
        print('3 Player Mod: '+status)
        print('SHA256: '+sha(current))
        return
    operation = plan['actions']['Install' if args.action=='apply' else 'Uninstall']
    output = reconstruct(current, operation)
    if output != current:
        backup = dll.with_name(dll.name+'.backup-before-3-player-mod')
        if backup.exists():
            if sha(backup.read_bytes()) not in plan['accepted_sha256']:
                raise ValueError('Existing backup is unrecognized; nothing was changed.')
        else:
            with backup.open('xb') as out: out.write(current)
            if backup.read_bytes()!=current: raise ValueError('Backup verification failed.')
        replace(dll, output)
    print('3 Player Mod installed.' if args.action=='apply' else '3 Player Mod removed.')


if __name__ == '__main__':
    try: main()
    except (OSError,ValueError) as error:
        print('Error: '+str(error),file=sys.stderr);sys.exit(1)
