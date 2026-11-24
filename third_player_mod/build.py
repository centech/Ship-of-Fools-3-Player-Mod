#!/usr/bin/env python3
"""Rebuild with Linux GCC/binutils + Capstone. Applying needs only Python stdlib."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import capstone

ROOT = Path(__file__).resolve().parent
CODE_RVA, DATA_RVA, UNWIND_RVA = 0x3837000, 0x383b000, 0x383c000

def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True)

def main():
    run('gcc', '-c', '-Os', '-mabi=ms', '-mgeneral-regs-only', '-fpie',
        '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-mno-red-zone',
        '-fno-asynchronous-unwind-tables', '-fno-unwind-tables', '-fno-shrink-wrap',
        '-fno-jump-tables', '-fno-tree-loop-distribute-patterns',
        '-fno-optimize-sibling-calls', '-fcf-protection=none', '-fvisibility=hidden',
        '-Wall', '-Wextra', '-Werror', '-o', 'third_player.o', 'third_player.c')
    run('gcc', '-c', '-o', 'trampolines.o', 'trampolines.S')
    run('ld', '--no-undefined', '-T', 'link.ld', '-o', 'payload.elf',
        'third_player.o', 'trampolines.o')
    run('objcopy', '-O', 'binary', '-j', '.text', 'payload.elf', 'code.bin')
    run('objcopy', '-O', 'binary', '-j', '.data', 'payload.elf', 'state.bin')
    code = (ROOT / 'code.bin').read_bytes()
    assert len(code) < DATA_RVA - CODE_RVA
    symbols = {}
    for line in run('nm', '-n', '-S', 'payload.elf').splitlines():
        parts = line.split()
        if len(parts) == 4:
            address, size, kind, name = parts
            symbols[name] = {'rva': int(address, 16), 'size': int(size, 16), 'kind': kind}

    # Generate genuine Windows x64 UNWIND_INFO for the GCC prologues so managed
    # exceptions can unwind through helper frames. No XMM saves/frame pointers.
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    reg = {n: i for i, n in enumerate(
        ['rax','rcx','rdx','rbx','rsp','rbp','rsi','rdi'] + [f'r{i}' for i in range(8,16)])}
    functions = []
    for name, sym in symbols.items():
        if sym['kind'].lower() != 't': continue
        begin, size = sym['rva'], sym['size']
        instructions = list(md.disasm(code[begin-CODE_RVA:begin-CODE_RVA+size], begin))
        ops = []
        prolog_end = 0
        for ins in instructions:
            end = ins.address + ins.size - begin
            if ins.mnemonic in ['call','ret'] or ins.mnemonic.startswith('j'): break
            fields = ins.op_str.split(', ')
            if ins.mnemonic == 'push':
                assert fields[0] in reg
                ops.append(bytes([end, reg[fields[0]] << 4])) # UWOP_PUSH_NONVOL
                prolog_end = end
            elif ins.mnemonic == 'sub' and fields[0] == 'rsp':
                amount = int(fields[1], 0)
                assert amount % 8 == 0
                if amount <= 128:
                    ops.append(bytes([end, ((amount-8)//8)<<4 | 2]))
                else:
                    ops.append(bytes([end, 1]) + struct.pack('<H', amount//8))
                prolog_end = end
            elif ins.mnemonic == 'mov' and fields[0].startswith('qword ptr [rsp'):
                if fields[1] in reg and reg[fields[1]] in [3,5,6,7,12,13,14,15]:
                    off = int(fields[0].split('+')[1].split(']')[0].strip(), 0)
                    ops.append(bytes([end, reg[fields[1]]<<4 | 4]) + struct.pack('<H',off//8))
                    prolog_end = end
            elif ins.mnemonic in ['pop','leave','enter']:
                raise ValueError(f'Unexpected prologue in {name}: {ins.mnemonic}')
        codes = b''.join(reversed(ops))
        info = bytes([1, prolog_end, len(codes)//2, 0]) + codes
        info += bytes((-len(info)) % 4)
        functions.append({'name':name, 'begin':begin, 'end':begin+size,
                          'unwind':info.hex()})
    manifest = {'version':1, 'code_rva':CODE_RVA, 'data_rva':DATA_RVA,
                'unwind_rva':UNWIND_RVA, 'symbols':symbols, 'functions':functions,
                'code_sha256':hashlib.sha256(code).hexdigest(),
                'state_sha256':hashlib.sha256((ROOT/'state.bin').read_bytes()).hexdigest()}
    (ROOT/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Built {len(code)} bytes of code, {len(functions)} unwind records.')

if __name__ == '__main__': main()
