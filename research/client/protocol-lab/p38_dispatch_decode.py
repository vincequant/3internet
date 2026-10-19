#!/usr/bin/env python3
# p38_dispatch_decode.py — 解出 Koeinm 0x100072c0 收包分派器的 cmd→处理器映射
# 输入: Koeinm.dll (归档副本, 与运行文件比对见 P33 native-source-binding)
# 纯离线, 不加载 PE 执行, 只读字节。
import struct, sys, hashlib, json, os

DLL = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Documents/Coding/三国志internet/research/protocol-archive/disasm/Koeinm.dll")

data = open(DLL, "rb").read()
print("dll:", DLL)
print("sha256:", hashlib.sha256(data).hexdigest())
print("size:", len(data))

# --- PE 解析（最小） ---
pe = struct.unpack_from("<I", data, 0x3c)[0]
assert data[pe:pe+4] == b"PE\0\0", "not PE"
nsec = struct.unpack_from("<H", data, pe+6)[0]
opt = pe + 24
magic = struct.unpack_from("<H", data, opt)[0]
assert magic == 0x10b, hex(magic)
imagebase = struct.unpack_from("<I", data, opt+28)[0]
sizeopt = struct.unpack_from("<H", data, pe+20)[0]
sects = []
so = opt + sizeopt
for i in range(nsec):
    off = so + i*40
    name = data[off:off+8].rstrip(b"\0").decode("latin1")
    vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, off+8)
    sects.append((name, vaddr, vsize, rawptr, rawsize))
    print(f"  sec {name}: VA {vaddr:#x} vsize {vsize:#x} raw {rawptr:#x} rawsize {rawsize:#x}")

def va2off(va):
    rva = va - imagebase
    for name, vaddr, vsize, rawptr, rawsize in sects:
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return rawptr + (rva - vaddr)
    raise ValueError(hex(va))

def read(va, n):
    off = va2off(va)
    return data[off:off+n]

IMAGEBASE = imagebase
TBL_BYTE = 0x100075b4   # 98 字节: cmd-2 -> 处理器索引
TBL_JMP  = 0x10007570   # 跳转表: 索引*4 -> 目标 VA
NCMD = 0x62             # cmds 0x02..0x63

byt = read(TBL_BYTE, NCMD)
jmp_raw = read(TBL_JMP, 4*32)

jmp = [struct.unpack_from("<I", jmp_raw, 4*i)[0] for i in range(32)]

print("\n--- 字节表 (0x100075b4, cmd=0x02..0x63) ---")
from collections import defaultdict
buckets = defaultdict(list)
for i, b in enumerate(byt):
    cmd = i + 2
    buckets[b].append(cmd)

# 确定跳转表有效条目数 = max index+1
maxidx = max(byt)
print("max handler index:", maxidx)
print("\n--- 跳转表 0x10007570 ---")
for i in range(maxidx+1):
    tgt = jmp[i]
    print(f"  [{i:2d}] -> {tgt:#010x}")

print("\n--- cmd -> handler 分组 ---")
for b in sorted(buckets):
    cmds = buckets[b]
    rng = []
    start = prev = cmds[0]
    for c in cmds[1:]:
        if c == prev+1:
            prev = c
        else:
            rng.append((start, prev)); start = prev = c
    rng.append((start, prev))
    rs = ",".join(f"{a:#04x}" if a==b_ else f"{a:#04x}-{b_:#04x}" for a,b_ in rng)
    print(f"  handler[{b:2d}] @ {jmp[b]:#010x}  cmds: {rs}  (n={len(cmds)})")
