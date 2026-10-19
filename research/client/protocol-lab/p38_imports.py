#!/usr/bin/env python3
# p38_imports.py — 解出 Koeinm.dll 导入槽 VA → (DLL, 名称/序号)
import struct, sys, os

DLL = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Documents/Coding/三国志internet/research/protocol-archive/disasm/Koeinm.dll")
data = open(DLL, "rb").read()

pe = struct.unpack_from("<I", data, 0x3c)[0]
nsec = struct.unpack_from("<H", data, pe+6)[0]
opt = pe + 24
sizeopt = struct.unpack_from("<H", data, pe+20)[0]
imagebase = struct.unpack_from("<I", data, opt+28)[0]
# data directory 1 = import
imp_rva, imp_size = struct.unpack_from("<II", data, opt+96+8)
sects = []
so = opt + sizeopt
for i in range(nsec):
    off = so + i*40
    name = data[off:off+8].rstrip(b"\0").decode("latin1")
    vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, off+8)
    sects.append((name, vaddr, vsize, rawptr, rawsize))

def rva2off(rva):
    for name, vaddr, vsize, rawptr, rawsize in sects:
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return rawptr + (rva - vaddr)
    raise ValueError(hex(rva))

def cstr(rva):
    off = rva2off(rva)
    end = data.index(b"\0", off)
    return data[off:end].decode("latin1")

out = []
rva = imp_rva
while True:
    desc = struct.unpack_from("<IIIII", data, rva2off(rva))
    orig, timedate, fwd, szname, firstthunk = desc
    if orig == 0 and szname == 0 and firstthunk == 0:
        break
    dllname = cstr(szname)
    thunk_rva = orig or firstthunk
    thunk_off = rva2off(thunk_rva)
    i = 0
    while True:
        t = struct.unpack_from("<I", data, thunk_off + 4*i)[0]
        if t == 0:
            break
        slot_va = imagebase + firstthunk + 4*i
        if t & 0x80000000:
            out.append((slot_va, dllname, "ordinal %d" % (t & 0xffff)))
        else:
            out.append((slot_va, dllname, cstr(t + 2)))
        i += 1
    rva += 20

for va, dll, name in sorted(out):
    print("%08x  %-14s %s" % (va, dll, name))
