#!/usr/bin/env python3
"""Build a temporary ARM module probe from the exact current vendor module ABI.

The vendor driver's init/exit functions are replaced; exported symbols,
parameters, unwind tables and all original text/rodata relocations are removed.
No vendor driver initialization runs. Nothing is sent to a device by this tool.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

DONOR_SHA = 'b0c6694c35929b0b90ca6081c97fe2eb2ca6f0d8fbd0919af6e11606c621989a'


def read_elf(data):
    assert data[:7] == b'\x7fELF\x01\x01\x01'
    assert struct.unpack_from('<H', data, 18)[0] == 40  # EM_ARM
    shoff = struct.unpack_from('<I', data, 32)[0]
    entsize, count, strindex = struct.unpack_from('<3H', data, 46)
    assert entsize == 40
    entries = [struct.unpack_from('<10I', data, shoff+i*40) for i in range(count)]
    st = entries[strindex]
    names = data[st[4]:st[4]+st[5]]
    sections = {}
    for i, entry in enumerate(entries):
        name = names[entry[0]:].split(b'\0', 1)[0].decode()
        sections[name] = {'index': i, 'offset': entry[4], 'size': entry[5], 'entry': entry}
    sym, strings = sections['.symtab'], sections['.strtab']
    text = data[strings['offset']:strings['offset']+strings['size']]
    symbols = {}
    for offset in range(sym['offset'], sym['offset']+sym['size'], 16):
        name, value, size, info, other, index = struct.unpack_from('<IIIBBH', data, offset)
        name = text[name:].split(b'\0', 1)[0].decode()
        if name:
            symbols[name] = {'value': value, 'size': size, 'index': index}
    return sections, symbols


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--donor', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--name', default='xiaodu_probe_noop')
    p.add_argument('--payload', type=Path, help='Already reviewed, relocation-free ARM init code')
    a = p.parse_args()
    data = bytearray(a.donor.read_bytes())
    assert hashlib.sha256(data).hexdigest() == DONOR_SHA
    assert a.name.startswith('xiaodu_probe_') and len(a.name.encode()) < 56
    sections, symbols = read_elf(data)
    text = sections['.text']
    init, exit_ = symbols['init_module'], symbols['cleanup_module']
    assert init['index'] == text['index'] == exit_['index']
    payload = a.payload.read_bytes() if a.payload else bytes.fromhex('0000a0e31eff2fe1')
    assert len(payload) <= init['size'] and len(payload) % 4 == 0
    offset = text['offset']+init['value']
    data[offset:offset+init['size']] = bytes.fromhex('0000a0e1')*(init['size']//4)
    data[offset:offset+len(payload)] = payload
    offset = text['offset']+exit_['value']
    data[offset:offset+4] = bytes.fromhex('1eff2fe1')  # BX LR
    module = sections['.gnu.linkonce.this_module']
    raw = data[module['offset']:module['offset']+module['size']]
    name_offset = raw.find(b'wmt_chrdev_wifi\0')
    assert name_offset == 12 and module['size'] == 512
    start = module['offset']+name_offset
    data[start:start+56] = a.name.encode().ljust(56, b'\0')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    temp = a.out.with_suffix('.working.ko')
    temp.write_bytes(data)
    removed = ['__ksymtab', '.rel__ksymtab', '__kcrctab', '.rel__kcrctab',
               '__ksymtab_strings', '__param', '.rel__param', '.ARM.exidx',
               '.rel.ARM.exidx', '.ARM.extab', '.rel.text', '.rel.rodata']
    cmd = ['arm-linux-gnueabi-objcopy', '--strip-debug']
    cmd += ['--remove-section='+name for name in removed]
    subprocess.run(cmd+[str(temp), str(a.out)], check=True, capture_output=True)
    temp.unlink()
    final = a.out.read_bytes()
    secs, syms = read_elf(final)
    assert '.rel.text' not in secs and '__ksymtab' not in secs and '__param' not in secs
    assert '.rel.gnu.linkonce.this_module' in secs and '__versions' in secs
    text = secs['.text']
    start = text['offset']+syms['init_module']['value']
    assert final[start:start+len(payload)] == payload
    report = {'file': str(a.out), 'sha256': hashlib.sha256(final).hexdigest(),
              'size': len(final), 'name': a.name, 'donor_sha256': DONOR_SHA,
              'payload_bytes': len(payload), 'payload_from': str(a.payload) if a.payload else 'ARM return-zero only',
              'original_init_replaced': True, 'original_cleanup_replaced': True,
              'original_exports_parameters_and_text_relocations_removed': True,
              'same_vendor_vermagic_modversions_and_module_layout_preserved': True,
              'device_connected_or_written': False}
    a.out.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
