#!/usr/bin/env python3
"""Match an unflashed AVB1 image's AlgorithmIdentifier to its stock reference.

The algorithm field is outside the signed payload/attributes. Magisk 30.7 signs
SHA256 but labels it with its certificate's SHA1 self-signature OID; this device
uses SHA256withRSA metadata. Preserve the signature and normalize only that
unsigned metadata, then independently verify the complete result with OpenSSL.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from .verify_avb1 import children, tlv, verify


def root(data):
    page = struct.unpack_from("<I", data, 36)[0]
    align = lambda n: (n + page - 1) // page * page
    end = page + sum(align(struct.unpack_from("<I", data, i)[0]) for i in [8, 16, 24])
    item = tlv(data, end)
    return end, item, children(data, item)


def der_length(value):
    if value < 128:
        return bytes([value])
    encoded = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return bytes([128 | len(encoded)]) + encoded


def normalize(source, reference, output, pad_size=None):
    original = Path(reference).read_bytes()
    data = Path(source).read_bytes()
    _, _, ref = root(original)
    offset, signature, parts = root(data)
    cert = lambda d, item: hashlib.sha256(d[item[1]:item[3]]).hexdigest()
    if cert(data, parts[1]) != cert(original, ref[1]):
        raise ValueError("Candidate certificate differs from the stock reference")
    body = b"".join(original[ref[2][1]:ref[2][3]] if i == 2 else data[p[1]:p[3]]
                    for i, p in enumerate(parts))
    encoded = b"\x30" + der_length(len(body)) + body
    result = bytearray(data)
    old_size = signature[3] - offset
    if len(encoded) > old_size:
        raise ValueError("Normalization would enlarge the signature region")
    result[offset:signature[3]] = encoded + b"\0" * (old_size - len(encoded))
    if pad_size:
        if len(result) > pad_size:
            raise ValueError("Image exceeds its partition size")
        result.extend(b"\0" * (pad_size - len(result)))
    Path(output).write_bytes(result)
    proof = verify(output)
    proof["normalized_from_reference"] = str(reference)
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pad-size", type=int)
    args = parser.parse_args()
    print(json.dumps(normalize(args.source, args.reference, args.output, args.pad_size), indent=2))
