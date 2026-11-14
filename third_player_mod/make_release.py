#!/usr/bin/env python3
"""Build the portable mod plan using your own original game DLL."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parent
VERSION = '0.4.0'
HOOKS = [(0x6dde70,5),(0x925a20,6),(0x6dd430,6),(0x1187030,6),
         (0x8fed9a,5),(0x8c0e90,5),(0x8c0490,9)]+[
         (r,5) for r in [0x6c5331,0x6c5389,0x6c563e,0x6c5696]]
# Reset writes from older combined packages when upgrading. No new gameplay
# hook or helper is installed at these locations.
LEGACY_CLEANUP = [(0x7a5dd9,5),(0x260d810,102)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-dll', type=Path, required=True)
    parser.add_argument('--previous-dll', type=Path, action='append', default=[])
    parser.add_argument('--output-dir', type=Path, default=ROOT)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('patch',ROOT.parent/'patch_third_player.py')
    patch = importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
    original = args.original_dll.read_bytes()
    final = patch.build_patch(original)
    _, opt, _, sections = patch.pe_layout(original)
    ranges = [(0,0x400)] + LEGACY_CLEANUP + [
        (patch.offset(sections,rva),size) for rva,size in HOOKS]
    def writes(data, spans):
        return [{'offset':o,'data':base64.b64encode(data[o:o+n]).decode()} for o,n in spans]
    plan = {'version':VERSION,'original_sha256':patch.sha(original),
            'patched_sha256':patch.sha(final),'accepted_sha256':{
                patch.sha(original):'Game without 3 Player Mod',
                **{s:'Earlier local mod' for s in sorted(patch.PREVIOUS_SHA256)},
                patch.sha(final):'3 Player Mod '+VERSION},'actions':{}}
    sources = [original,final]
    for path in args.previous_dll:
        data = path.read_bytes()
        if patch.sha(data) not in plan['accepted_sha256']:
            raise ValueError('Unrecognized previous DLL: '+str(path))
        sources.append(data)
    for name,data in [('Install',final),('Uninstall',original)]:
        ops = writes(data,ranges)
        copies = [{'source':0,'offset':0,'length':len(original)}]
        if name=='Install':
            _,newopt,_,newsections = patch.pe_layout(data)
            oldrva,oldsize = struct.unpack_from('<II',original,opt+112+3*8)
            ro_rva,_,ro_off = newsections[-1]
            tabrva,tabsz = struct.unpack_from('<II',data,newopt+112+3*8)
            for _,rawsize,off in newsections[-3:-1]:ops += writes(data,[(off,rawsize)])
            ops += writes(data,[(ro_off,tabrva-ro_rva),
                               (ro_off+tabrva-ro_rva+oldsize,tabsz-oldsize)])
            copies.append({'source':patch.offset(sections,oldrva),
                           'offset':ro_off+tabrva-ro_rva,'length':oldsize})
        operation = {'size':len(data),'sha256':patch.sha(data),'copies':copies,'writes':ops}
        plan['actions'][name] = operation
        for source in sources:
            if patch.reconstruct(source,operation)!=data:
                raise ValueError('Plan reconstruction mismatch: '+name)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    encoded = (json.dumps(plan,indent=2)+'\n').encode()
    script = (ROOT/'patch.ps1').read_text()
    script,count = re.subn(r"(Get-BytesHash \$planBytes\) -ne ')[0-9a-f]{64}",
                          lambda m:m[1]+patch.sha(encoded),script)
    if count!=1:raise ValueError('Cannot find installer plan fingerprint.')
    (args.output_dir/'release-plan.json').write_bytes(encoded)
    (args.output_dir/'patch.ps1').write_text(script)
    print('DLL SHA256: '+patch.sha(final))
    print('Plan SHA256: '+patch.sha(encoded))


if __name__=='__main__':main()
