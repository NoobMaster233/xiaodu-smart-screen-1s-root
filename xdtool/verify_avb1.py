#!/usr/bin/env python3
"""Independently verify a legacy Android boot/recovery AVB1 signature.

Uses OpenSSL, checks the authenticated target and payload length, and reports
public certificate/image/kernel hashes. Does not communicate with the device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile


def tlv(data, offset):
    start = offset
    tag, length = data[offset:offset + 2]
    offset += 2
    if length & 128:
        count = length & 127
        if not 0 < count <= 4:
            raise ValueError("Unexpected ASN.1 length")
        length = int.from_bytes(data[offset:offset + count], "big")
        offset += count
    end = offset + length
    if end > len(data):
        raise ValueError("Truncated ASN.1 object")
    return tag, start, offset, end


def children(data, item):
    offset = item[2]
    result = []
    while offset < item[3]:
        entry = tlv(data, offset)
        result.append(entry)
        offset = entry[3]
    if offset != item[3]:
        raise ValueError("ASN.1 boundary mismatch")
    return result


def verify(path, expected_target=None):
    data = Path(path).read_bytes()
    if data[:8] != b"ANDROID!":
        raise ValueError("Expected a legacy Android boot image")
    page = struct.unpack_from("<I", data, 36)[0]
    if page not in [512, 1024, 2048, 4096, 8192, 16384]:
        raise ValueError("Unexpected boot page size")
    sizes = [struct.unpack_from("<I", data, p)[0] for p in [8, 16, 24]]
    aligned = lambda value: (value + page - 1) // page * page
    payload_end = page + sum(aligned(size) for size in sizes)
    signature = tlv(data, payload_end)
    fields = children(data, signature)
    if signature[0] != 0x30 or [x[0] for x in fields] != [2, 0x30, 0x30, 0x30, 4]:
        raise ValueError("Unexpected AVB1 BootSignature layout")
    version, certificate, algorithm, attributes, value = fields
    if data[version[2]:version[3]] != b"\x01":
        raise ValueError("Unsupported AVB1 format version")
    oid = children(data, algorithm)[0]
    # This device's legacy verifier expects SHA256withRSA. Magisk 30.7's signer
    # copies the certificate's SHA1 self-signature OID despite signing SHA256.
    # Correct crypto alone must not hide that metadata mismatch.
    if oid[0] != 6 or data[oid[2]:oid[3]] != bytes.fromhex("2a864886f70d01010b"):
        raise ValueError("AVB1 algorithm metadata is not SHA256withRSA")
    attr = children(data, attributes)
    target = data[attr[0][2]:attr[0][3]].decode("ascii")
    signed_size = int.from_bytes(data[attr[1][2]:attr[1][3]], "big")
    if signed_size != payload_end:
        raise ValueError("Authenticated payload size does not match the boot header")
    if expected_target and target != expected_target:
        raise ValueError(f"Wrong authenticated target: {target}")
    der = data[certificate[1]:certificate[3]]
    with tempfile.TemporaryDirectory(prefix="xiaodu-avb1-") as folder:
        temp = Path(folder)
        (temp / "cert.der").write_bytes(der)
        pub = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", temp / "cert.der",
                              "-pubkey", "-noout"], check=True, capture_output=True).stdout
        (temp / "key.pem").write_bytes(pub)
        (temp / "signature").write_bytes(data[value[2]:value[3]])
        (temp / "signed-data").write_bytes(data[:payload_end] + data[attributes[1]:attributes[3]])
        result = subprocess.run(["openssl", "dgst", "-sha256", "-verify", temp / "key.pem",
                                 "-signature", temp / "signature", temp / "signed-data"],
                                check=True, capture_output=True, text=True)
    return {"image": str(path), "image_bytes": len(data),
            "image_sha256": hashlib.sha256(data).hexdigest(),
            "avb1_valid": result.stdout.strip() == "Verified OK", "target": target,
            "payload_bytes": payload_end, "certificate_sha256": hashlib.sha256(der).hexdigest(),
            "algorithm_der": data[algorithm[1]:algorithm[3]].hex(),
            "kernel_bytes": sizes[0], "kernel_sha256": hashlib.sha256(data[page:page + sizes[0]]).hexdigest(),
            "ramdisk_bytes": sizes[1]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--expect-target")
    args = parser.parse_args()
    print(json.dumps(verify(args.image, args.expect_target), indent=2))
