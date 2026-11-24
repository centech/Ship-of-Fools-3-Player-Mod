#!/usr/bin/env python3
"""Create the patch-only ZIP from an explicit allowlist. Never package game data."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent.parent
VERSION='0.5.0'
ROOT_FILES=['Install.cmd','Uninstall.cmd','READ ME.txt']
MOD_FILES=['LICENSE.txt','patch.ps1','release-plan.json']
FILES=ROOT_FILES+['third_player_mod/'+name for name in MOD_FILES]
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'dist')
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    contents={name:(ROOT/name).read_bytes() for name in FILES}
    sums=''.join(sha(data)+'  '+name+'\n' for name,data in sorted(contents.items()))
    contents['SHA256SUMS.txt']=sums.encode()
    archive=args.output_dir/('Ship-of-Fools-3-Player-Mod-'+VERSION+'.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(contents.items()):
            info=zipfile.ZipInfo(name,date_time=(2026,11,14,0,0,0))
            info.external_attr=0o100644<<16;info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('ZIP verification failed.')
        for name,data in contents.items():
            if z.read(name)!=data:raise ValueError('Archive content mismatch: '+name)
    (args.output_dir/'SHA256SUMS.txt').write_text(sums)
    archive_hash=sha(archive.read_bytes())
    archive.with_suffix('.zip.sha256').write_text(archive_hash+'  '+archive.name+'\n')
    print(f'{archive.name}: {archive.stat().st_size:,} bytes; {len(contents)} files')
    print('SHA256: '+archive_hash)

if __name__=='__main__':main()
