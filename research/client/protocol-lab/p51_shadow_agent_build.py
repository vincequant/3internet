#!/usr/bin/env python3
"""P51 shadow agent builder: assemble the D8 once-only shellcode via clang.

The agent is a position-independent x86 (32-bit) stub injected into the shadow
client's SANPK.exe by p51_shadow_inject.py. It polls (250 ms) for a trigger
file, verifies pre-start state, then performs exactly one reliable D8 submit
through the game's own Koeinm vtable-free call slots (0x4C80 -> 0x4B60) and
writes a binary receipt. No imports, no relocations, no PEB walk — every
absolute address comes from the injected data blob.

ABI rules (verified against P33/P34 static work and the production probe):
  * kernel32 APIs are stdcall (callee cleans; we do NOT add esp after calls).
  * Koeinm exported _NetMsg_* are stdcall (decorated @N).
  * Internal 0x4C80/0x4B60 are cdecl (plain ret; caller cleans).

Outputs (into --outdir): agent.s, agent.bin, smoke.s, smoke.bin,
capstone listing, manifest.json with sha256 of everything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

AGENT_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr (entry [esp0+4])
    cmp dword ptr [esi], 0x31474853 ; 'SHG1' magic; bad -> inert spin
    jne agent_spin
agent_loop:
    cmp dword ptr [esi+4], 0       ; sent flag
    jne agent_sleep_long
    lea eax, [esi+52]
    push eax
    call dword ptr [esi+12]        ; GetFileAttributesA (stdcall)
    cmp eax, -1
    je agent_sleep_short
    call dword ptr [esi+36]        ; IsConnected@0 (stdcall)
    test eax, eax
    jz agent_sleep_short
    mov eax, [esi+8]               ; netobj
    cmp dword ptr [eax+0x84A8], 1  ; pre-start state
    jne agent_sleep_short
    mov dword ptr [esp+12], 0
    lea eax, [esp+12]
    push eax
    call dword ptr [esi+40]        ; GetIPAddress@4 (stdcall, ret 4)
    mov eax, [esp+12]
    test eax, eax
    jz agent_sleep_short
    mov edi, [eax]                 ; own id
    test edi, edi
    jz agent_sleep_short
    push dword ptr [esi+8]
    call dword ptr [esi+44]        ; 0x4C80 GetHostOrSelfID (cdecl)
    add esp, 4
    test eax, eax
    jz agent_sleep_short
    cmp eax, edi
    je agent_sleep_short
    mov ebx, eax                   ; target
    sub esp, 8
    mov dword ptr [esp], 0x08000000 ; BE32(8)
    mov eax, edi
    bswap eax
    mov [esp+4], eax               ; BE32(own)
    mov edx, esp
    push 8
    push edx
    push ebx
    push dword ptr [esi+8]
    call dword ptr [esi+48]        ; 0x4B60 reliable submit (cdecl)
    add esp, 16
    add esp, 8
    mov [esp], eax                 ; rc
    mov dword ptr [esi+4], 1       ; once-only
    lea eax, [esi+180]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+16]        ; CreateFileA receipt (stdcall, ret 28)
    cmp eax, -1
    je agent_after_receipt
    mov [esp+8], eax               ; handle
    mov dword ptr [esp+16], 0x32474853 ; 'SHG2'
    mov eax, [esp]
    mov [esp+20], eax              ; rc
    mov [esp+24], edi              ; own
    mov [esp+28], ebx              ; target
    call dword ptr [esi+32]        ; GetTickCount
    mov [esp+32], eax
    mov dword ptr [esp+36], 0
    push 0
    lea eax, [esp+8]
    push eax
    push 24
    lea eax, [esp+28]
    push eax
    mov eax, [esp+24]
    push eax
    call dword ptr [esi+20]        ; WriteFileA (stdcall, ret 20)
    push dword ptr [esp+8]
    call dword ptr [esi+24]        ; CloseHandle (stdcall, ret 4)
agent_after_receipt:
    push 1000
    call dword ptr [esi+28]        ; Sleep
    jmp agent_loop
agent_sleep_short:
    push 250
    call dword ptr [esi+28]
    jmp agent_loop
agent_sleep_long:
    push 1000
    call dword ptr [esi+28]
    jmp agent_loop
agent_spin:
    push 5000
    call dword ptr [esi+28]
    jmp agent_spin
"""

CMD9_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr (entry [esp0+4])
    cmp dword ptr [esi], 0x31474853 ; 'SHG1'; bad -> inert spin
    jne c9_spin
c9_loop:
    cmp dword ptr [esi+4], 0       ; sent flag
    jne c9_sleep_long
    lea eax, [esi+52]
    push eax
    call dword ptr [esi+12]        ; GetFileAttributesA (stdcall)
    cmp eax, -1
    je c9_sleep_short
    call dword ptr [esi+36]        ; IsConnected@0 (stdcall)
    test eax, eax
    jz c9_sleep_short
    mov dword ptr [esp+12], 0
    lea eax, [esp+12]
    push eax
    call dword ptr [esi+40]        ; GetIPAddress@4 (stdcall, ret 4)
    mov eax, [esp+12]
    test eax, eax
    jz c9_sleep_short
    mov edi, [eax]                 ; own id
    test edi, edi
    jz c9_sleep_short
    push dword ptr [esi+8]
    call dword ptr [esi+44]        ; 0x4C80 GetHostOrSelfID (cdecl)
    add esp, 4
    test eax, eax
    jz c9_sleep_short
    cmp eax, edi
    je c9_sleep_short
    mov ebx, eax                   ; target = host
    sub esp, 44                    ; 36-byte cmd9 object (p30_ready CMD9)
    mov word ptr [esp], 0xFFFF
    mov word ptr [esp+2], 1
    mov word ptr [esp+4], 17
    mov dword ptr [esp+6], 0x6e615343  ; 'CSan'
    mov dword ptr [esp+10], 0x74656e49 ; 'Inet'
    mov dword ptr [esp+14], 0x4f646d43 ; 'CmdO'
    mov dword ptr [esp+18], 0x63656a62 ; 'bjec'
    mov byte ptr [esp+22], 0x74        ; 't'
    mov dword ptr [esp+23], 9          ; kind = 9
    mov dword ptr [esp+27], 1          ; a = 1 (ready)
    mov dword ptr [esp+31], 0          ; b = 0
    mov byte ptr [esp+35], 0           ; empty text
    mov edx, esp
    push 36
    push edx
    push ebx
    push dword ptr [esi+8]
    call dword ptr [esi+48]        ; 0x4B60 reliable submit (cdecl)
    add esp, 16
    add esp, 44
    mov [esp], eax                 ; rc
    mov dword ptr [esi+4], 1       ; once-only
    lea eax, [esi+180]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+16]        ; CreateFileA receipt (stdcall, ret 28)
    cmp eax, -1
    je c9_after_receipt
    mov [esp+8], eax               ; handle
    mov dword ptr [esp+16], 0x39474853 ; 'SHG9'
    mov eax, [esp]
    mov [esp+20], eax              ; rc
    mov [esp+24], edi              ; own
    mov [esp+28], ebx              ; target
    call dword ptr [esi+32]        ; GetTickCount
    mov [esp+32], eax
    mov eax, [esi+8]
    mov ecx, [eax+0x414C]          ; last received frame length (evidence)
    mov [esp+36], ecx
    push 0
    lea eax, [esp+8]
    push eax
    push 24
    lea eax, [esp+28]
    push eax
    mov eax, [esp+24]
    push eax
    call dword ptr [esi+20]        ; WriteFileA (stdcall, ret 20)
    push dword ptr [esp+8]
    call dword ptr [esi+24]        ; CloseHandle (stdcall, ret 4)
c9_after_receipt:
    push 1000
    call dword ptr [esi+28]        ; Sleep
    jmp c9_loop
c9_sleep_short:
    push 250
    call dword ptr [esi+28]
    jmp c9_loop
c9_sleep_long:
    push 1000
    call dword ptr [esi+28]
    jmp c9_loop
c9_spin:
    push 5000
    call dword ptr [esi+28]
    jmp c9_spin
"""

SPOOF_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]
    cmp dword ptr [esi], 0x31474853
    jne sp_spin
sp_loop:
    cmp dword ptr [esi+4], 0
    jne sp_sleep_long
    lea eax, [esi+0x100]
    push eax
    call dword ptr [esi+12]        ; GetFileAttributesA(flag)
    cmp eax, -1
    je sp_sleep_short
    call dword ptr [esi+36]        ; IsConnected@0
    test eax, eax
    jz sp_sleep_short
    mov dword ptr [esp+12], 0
    lea eax, [esp+12]
    push eax
    call dword ptr [esi+40]        ; GetIPAddress@4 -> &own_id
    mov eax, [esp+12]
    test eax, eax
    jz sp_sleep_short
    mov edi, [eax]                 ; own id (restore value)
    test edi, edi
    jz sp_sleep_short
    mov dword ptr [esp+20], eax    ; keep &own_id
    ; swap identity for exactly one send, then restore
    mov ecx, [esi+0x200]           ; spoofed sender id
    mov [eax], ecx
    mov edx, esi
    add edx, 0x38
    push dword ptr [esi+0x34]      ; len
    push edx                       ; buf
    push -1                        ; target = -1 (broadcast)
    push dword ptr [esi+8]         ; netobj
    call dword ptr [esi+48]        ; 0x100023a0 direct send
    add esp, 16
    mov [esp], eax                 ; rc
    mov eax, [esp+20]
    mov [eax], edi                 ; restore own id immediately
    mov dword ptr [esi+4], 1
    lea eax, [esi+0x180]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+16]        ; CreateFileA receipt
    cmp eax, -1
    je sp_after_receipt
    mov [esp+8], eax
    mov dword ptr [esp+16], 0x39474853 ; 'SHG9'
    mov eax, [esp]
    mov [esp+20], eax
    mov [esp+24], edi
    mov ecx, [esi+0x200]
    mov [esp+28], ecx
    call dword ptr [esi+32]
    mov [esp+32], eax
    mov eax, [esi+0x34]
    mov [esp+36], eax
    push 0
    lea eax, [esp+8]
    push eax
    push 24
    lea eax, [esp+28]
    push eax
    mov eax, [esp+24]
    push eax
    call dword ptr [esi+20]
    push dword ptr [esp+8]
    call dword ptr [esi+24]
sp_after_receipt:
    push 1000
    call dword ptr [esi+28]
    jmp sp_loop
sp_sleep_short:
    push 250
    call dword ptr [esi+28]
    jmp sp_loop
sp_sleep_long:
    push 1000
    call dword ptr [esi+28]
    jmp sp_loop
sp_spin:
    push 5000
    call dword ptr [esi+28]
    jmp sp_spin
"""

BCAST_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr
    cmp dword ptr [esi], 0x31474853
    jne bc_spin
bc_loop:
    cmp dword ptr [esi+4], 0
    jne bc_sleep_long
    lea eax, [esi+0x100]
    push eax
    call dword ptr [esi+12]        ; GetFileAttributesA(flag)
    cmp eax, -1
    je bc_sleep_short
    call dword ptr [esi+36]        ; IsConnected@0
    test eax, eax
    jz bc_sleep_short
    mov dword ptr [esp+12], 0
    lea eax, [esp+12]
    push eax
    call dword ptr [esi+40]        ; GetIPAddress@4
    mov eax, [esp+12]
    test eax, eax
    jz bc_sleep_short
    mov edi, [eax]                 ; own id (receipt only)
    test edi, edi
    jz bc_sleep_short
    mov edx, esi
    add edx, 0x38
    push dword ptr [esi+0x34]      ; len
    push edx                       ; buf
    push -1                        ; target = -1 (broadcast, SendData semantics)
    push dword ptr [esi+8]         ; netobj
    call dword ptr [esi+48]        ; 0x100023a0 direct/broadcast send
    add esp, 16
    mov [esp], eax                 ; rc
    mov dword ptr [esi+4], 1
    lea eax, [esi+0x180]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+16]        ; CreateFileA receipt
    cmp eax, -1
    je bc_after_receipt
    mov [esp+8], eax
    mov dword ptr [esp+16], 0x38474853 ; 'SHG8'
    mov eax, [esp]
    mov [esp+20], eax
    mov [esp+24], edi
    mov dword ptr [esp+28], -1
    call dword ptr [esi+32]
    mov [esp+32], eax
    mov eax, [esi+0x34]
    mov [esp+36], eax
    push 0
    lea eax, [esp+8]
    push eax
    push 24
    lea eax, [esp+28]
    push eax
    mov eax, [esp+24]
    push eax
    call dword ptr [esi+20]
    push dword ptr [esp+8]
    call dword ptr [esi+24]
bc_after_receipt:
    push 1000
    call dword ptr [esi+28]
    jmp bc_loop
bc_sleep_short:
    push 250
    call dword ptr [esi+28]
    jmp bc_loop
bc_sleep_long:
    push 1000
    call dword ptr [esi+28]
    jmp bc_loop
bc_spin:
    push 5000
    call dword ptr [esi+28]
    jmp bc_spin
"""

UPLINK_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr
    cmp dword ptr [esi], 0x31474853 ; 'SHG1'
    jne up_spin
up_loop:
    cmp dword ptr [esi+4], 0       ; sent flag
    jne up_sleep_long
    lea eax, [esi+0x100]           ; flag path
    push eax
    call dword ptr [esi+12]        ; GetFileAttributesA
    cmp eax, -1
    je up_sleep_short
    call dword ptr [esi+36]        ; IsConnected@0
    test eax, eax
    jz up_sleep_short
    mov dword ptr [esp+12], 0
    lea eax, [esp+12]
    push eax
    call dword ptr [esi+40]        ; GetIPAddress@4
    mov eax, [esp+12]
    test eax, eax
    jz up_sleep_short
    mov edi, [eax]                 ; own id
    test edi, edi
    jz up_sleep_short
    push dword ptr [esi+8]
    call dword ptr [esi+44]        ; 0x4C80 GetHostOrSelfID (cdecl)
    add esp, 4
    test eax, eax
    jz up_sleep_short
    cmp eax, edi
    je up_sleep_short
    mov ebx, eax                   ; target = host
    mov edx, esi
    add edx, 0x38                  ; payload bytes live in the blob
    push dword ptr [esi+0x34]      ; payload length
    push edx
    push ebx
    push dword ptr [esi+8]
    call dword ptr [esi+48]        ; 0x4B60 reliable submit (cdecl)
    add esp, 16
    mov [esp], eax                 ; rc
    mov dword ptr [esi+4], 1       ; once-only
    lea eax, [esi+0x180]           ; receipt path
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+16]        ; CreateFileA
    cmp eax, -1
    je up_after_receipt
    mov [esp+8], eax
    mov dword ptr [esp+16], 0x37474853 ; 'SHG7'
    mov eax, [esp]
    mov [esp+20], eax              ; rc
    mov [esp+24], edi              ; own
    mov [esp+28], ebx              ; target
    call dword ptr [esi+32]        ; GetTickCount
    mov [esp+32], eax
    mov eax, [esi+0x34]
    mov [esp+36], eax              ; payload length
    push 0
    lea eax, [esp+8]
    push eax
    push 24
    lea eax, [esp+28]
    push eax
    mov eax, [esp+24]
    push eax
    call dword ptr [esi+20]        ; WriteFileA
    push dword ptr [esp+8]
    call dword ptr [esi+24]        ; CloseHandle
up_after_receipt:
    push 1000
    call dword ptr [esi+28]
    jmp up_loop
up_sleep_short:
    push 250
    call dword ptr [esi+28]
    jmp up_loop
up_sleep_long:
    push 1000
    call dword ptr [esi+28]
    jmp up_loop
up_spin:
    push 5000
    call dword ptr [esi+28]
    jmp up_spin
"""

SMOKE_ASM = r"""
.intel_syntax noprefix
.text
.globl smoke_start
smoke_start:
    push esi
    mov esi, [esp+8]               ; blob ptr
    sub esp, 8
    mov dword ptr [esp], 0         ; written
    mov dword ptr [esp+4], 0       ; handle
    lea eax, [esi+180]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+16]        ; CreateFileA (stdcall, ret 28)
    cmp eax, -1
    je smoke_done
    mov [esp+4], eax
    push 0
    lea eax, [esp+4]
    push eax
    push 16
    mov eax, esi
    push eax
    mov eax, [esp+20]
    push eax
    call dword ptr [esi+20]        ; WriteFileA 16 bytes of blob magic (stdcall, ret 20)
    push dword ptr [esp+4]
    call dword ptr [esi+24]        ; CloseHandle
smoke_done:
    add esp, 8
    pop esi
    ret
"""

ROUNDS_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr
    cmp dword ptr [esi], 0x31474853 ; 'SHG1'
    jne rr_spin
rr_main:
    cmp dword ptr [esi+4], 0       ; fired flag
    jne rr_idle
    lea eax, [esi+0x34]
    push eax
    call dword ptr [esi+0x0C]      ; GetFileAttributesA(flag)
    cmp eax, -1
    je rr_sleep
    mov dword ptr [esi+4], 1       ; once
    mov dword ptr [esi+0x13C], 0   ; round_index = 0
    lea eax, [esi+0xB4]
    push 0
    push 128
    push 4                         ; OPEN_ALWAYS
    push 0
    push 3                         ; share read|write
    push 0x40000004                ; GENERIC_WRITE | FILE_APPEND_DATA (wine-safe append)
    push eax
    call dword ptr [esi+0x10]      ; CreateFileA receipt (stdcall, ret 28)
    mov [esi+0x138], eax           ; handle (may be -1)
rr_cycle:
    mov eax, [esi+0x2C]            ; G68 addr
    mov dword ptr [eax], 3         ; app round state := 3 (as the UI spawner does)
    xor eax, eax                   ; event 0 = spawn
    call rr_emit
    mov ecx, [esi+0x24]            ; core
    call dword ptr [esi+0x28]      ; round driver D (blocking until round completes)
    mov eax, 1                     ; event 1 = done
    call rr_emit
    inc dword ptr [esi+0x13C]
    mov eax, [esi+0x134]           ; max rounds
    cmp dword ptr [esi+0x13C], eax
    jb rr_cycle
    mov eax, 2                     ; event 2 = finished
    call rr_emit
rr_idle:
    push 1000
    call dword ptr [esi+0x1C]
    jmp rr_main
rr_sleep:
    push 250
    call dword ptr [esi+0x1C]
    jmp rr_main
rr_spin:
    push 5000
    call dword ptr [esi+0x1C]
    jmp rr_spin
rr_emit:                           ; in: eax=event; clobbers eax/ecx/edx/edi; row at locals
    mov edi, eax
    call dword ptr [esi+0x20]      ; GetTickCount
    mov dword ptr [esp+4], 0x34474853 ; 'SHG4'
    mov ecx, [esi+0x13C]
    mov [esp+8], ecx               ; round index
    mov [esp+12], edi              ; event
    mov [esp+16], eax              ; tick
    mov ecx, [esi+0x30]
    mov ecx, [ecx]
    mov [esp+20], ecx              ; f6bc
    mov edx, [esi+0x2C]
    mov edx, [edx]
    mov [esp+24], edx              ; G68
    mov eax, [esi+0x138]
    cmp eax, -1
    je rr_emit_done
    test eax, eax
    je rr_emit_done
    push 0                         ; lpOverlapped        (esp=A-8)
    lea eax, [esp+36]              ; &written = A+28
    push eax                       ;                     (esp=A-12)
    push 24                        ; nBytes              (esp=A-16)
    lea eax, [esp+16]              ; buffer = A+4
    push eax                       ;                     (esp=A-20)
    push dword ptr [esi+0x138]     ; hFile               (esp=A-24)
    call dword ptr [esi+0x14]      ; WriteFileA (stdcall, ret 20)
rr_emit_done:
    ret
"""

ROUNDS_B_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr
    cmp dword ptr [esi], 0x31474853 ; 'SHG1'
    jne rb_spin
rb_main:
    cmp dword ptr [esi+4], 0       ; fired flag
    jne rb_idle
    lea eax, [esi+0x34]
    push eax
    call dword ptr [esi+0x0C]      ; GetFileAttributesA(flag)
    cmp eax, -1
    je rb_sleep
    mov dword ptr [esi+4], 1       ; once
    mov dword ptr [esi+0x13C], 0   ; round_index = 0
    lea eax, [esi+0xB4]
    push 0
    push 128
    push 4                         ; OPEN_ALWAYS
    push 0
    push 3                         ; share read|write
    push 0x40000004                ; GENERIC_WRITE | FILE_APPEND_DATA (wine-safe append)
    push eax
    call dword ptr [esi+0x10]      ; CreateFileA receipt (stdcall, ret 28)
    mov [esi+0x138], eax           ; handle (may be -1)
rb_cycle:
    mov edi, 50                    ; pre-wait: not mid-round (f6bc != 1)
rb_prewait:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 1
    jne rb_fire
    push 200
    call dword ptr [esi+0x1C]
    dec edi
    jnz rb_prewait
    jmp rb_timeout
rb_fire:
    mov eax, [esi+0x2C]            ; G68 addr
    mov dword ptr [eax], 3         ; app round state := 3 (as the UI spawner does)
    mov ecx, [esi+0x24]            ; core
    call dword ptr [esi+0x28]      ; spawner 0x44B88E (AfxBeginThread -> D)
    mov [esi+0x140], eax           ; CWinThread* (or NULL)
    xor eax, eax                   ; event 0 = spawn
    call rb_emit
    mov edi, 75                    ; wait round start: f6bc==1 within ~15s
rb_waitstart:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 1
    je rb_started
    push 200
    call dword ptr [esi+0x1C]
    dec edi
    jnz rb_waitstart
    mov eax, 4                     ; event 4 = start timeout
    call rb_emit
    jmp rb_idle
rb_started:
    mov eax, 1                     ; event 1 = started
    call rb_emit
    mov edi, 4500                  ; wait round done: f6bc==2 within ~15min
rb_waitdone:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 2
    je rb_done
    push 200
    call dword ptr [esi+0x1C]
    dec edi
    jnz rb_waitdone
    mov eax, 4                     ; event 4 = done timeout
    call rb_emit
    jmp rb_idle
rb_done:
    mov eax, 2                     ; event 2 = done
    call rb_emit
    inc dword ptr [esi+0x13C]
    mov eax, [esi+0x134]           ; max rounds
    cmp dword ptr [esi+0x13C], eax
    jb rb_cycle
    mov eax, 3                     ; event 3 = finished
    call rb_emit
rb_idle:
    push 1000
    call dword ptr [esi+0x1C]
    jmp rb_main
rb_sleep:
    push 250
    call dword ptr [esi+0x1C]
    jmp rb_main
rb_spin:
    push 5000
    call dword ptr [esi+0x1C]
    jmp rb_spin
rb_timeout:
    mov eax, 4
    call rb_emit
    jmp rb_idle
rb_emit:                           ; in: eax=event; clobbers eax/ecx/edx/edi; row at locals
    mov edi, eax
    call dword ptr [esi+0x20]      ; GetTickCount
    mov dword ptr [esp+4], 0x34474853 ; 'SHG4'
    mov ecx, [esi+0x13C]
    mov [esp+8], ecx               ; round index
    mov [esp+12], edi              ; event
    mov [esp+16], eax              ; tick
    mov ecx, [esi+0x30]
    mov ecx, [ecx]
    mov [esp+20], ecx              ; f6bc
    mov edx, [esi+0x2C]
    mov edx, [edx]
    mov [esp+24], edx              ; G68
    mov eax, [esi+0x138]
    cmp eax, -1
    je rb_emit_done
    test eax, eax
    je rb_emit_done
    push 0                         ; lpOverlapped        (esp=A-8)
    lea eax, [esp+36]              ; &written = A+28
    push eax                       ;                     (esp=A-12)
    push 24                        ; nBytes              (esp=A-16)
    lea eax, [esp+16]              ; buffer = A+4
    push eax                       ;                     (esp=A-20)
    push dword ptr [esi+0x138]     ; hFile               (esp=A-24)
    call dword ptr [esi+0x14]      ; WriteFileA (stdcall, ret 20)
rb_emit_done:
    ret
"""

ROUNDS_C_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
; Pre-arm variant: after the one spawn per round it waits (up to ~4 h) for the
; round-complete flag [f6bc]==2, because in an idle room the first batch only
; arrives when the operator starts the match. No 15 s "started" gate.
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr
    cmp dword ptr [esi], 0x31474853 ; 'SHG1'
    jne rc_spin
rc_main:
    cmp dword ptr [esi+4], 0       ; fired flag
    jne rc_idle
    lea eax, [esi+0x34]
    push eax
    call dword ptr [esi+0x0C]      ; GetFileAttributesA(flag)
    cmp eax, -1
    je rc_sleep
    mov dword ptr [esi+4], 1       ; once
    mov dword ptr [esi+0x13C], 0   ; round_index = 0
    lea eax, [esi+0xB4]
    push 0
    push 128
    push 4                         ; OPEN_ALWAYS
    push 0
    push 3                         ; share read|write
    push 0x40000004                ; GENERIC_WRITE | FILE_APPEND_DATA (wine-safe append)
    push eax
    call dword ptr [esi+0x10]      ; CreateFileA receipt (stdcall, ret 28)
    mov [esi+0x138], eax           ; handle (may be -1)
rc_cycle:
    mov edi, 50                    ; pre-wait: not mid-round (f6bc != 1)
rc_prewait:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 1
    jne rc_fire
    push 200
    call dword ptr [esi+0x1C]
    dec edi
    jnz rc_prewait
    jmp rc_timeout
rc_fire:
    mov eax, [esi+0x2C]            ; G68 addr
    mov dword ptr [eax], 3         ; app round state := 3 (as the UI spawner does)
    mov ecx, [esi+0x24]            ; core
    call dword ptr [esi+0x28]      ; spawner 0x44B88E (AfxBeginThread -> D)
    mov [esi+0x140], eax           ; CWinThread* (or NULL)
    xor eax, eax                   ; event 0 = spawn
    call rc_emit
    mov edi, 72000                 ; wait done: f6bc==2 within ~4 h (pre-arm)
rc_waitdone:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 2
    je rc_done
    push 200
    call dword ptr [esi+0x1C]
    dec edi
    jnz rc_waitdone
    mov eax, 4                     ; event 4 = done timeout
    call rc_emit
    jmp rc_idle
rc_done:
    mov eax, 2                     ; event 2 = done
    call rc_emit
    inc dword ptr [esi+0x13C]
    mov eax, [esi+0x134]           ; max rounds
    cmp dword ptr [esi+0x13C], eax
    jb rc_cycle
    mov eax, 3                     ; event 3 = finished
    call rc_emit
rc_idle:
    push 1000
    call dword ptr [esi+0x1C]
    jmp rc_main
rc_sleep:
    push 250
    call dword ptr [esi+0x1C]
    jmp rc_main
rc_spin:
    push 5000
    call dword ptr [esi+0x1C]
    jmp rc_spin
rc_timeout:
    mov eax, 4
    call rc_emit
    jmp rc_idle
rc_emit:                           ; in: eax=event; clobbers eax/ecx/edx/edi; row at locals
    mov edi, eax
    call dword ptr [esi+0x20]      ; GetTickCount
    mov dword ptr [esp+4], 0x34474853 ; 'SHG4'
    mov ecx, [esi+0x13C]
    mov [esp+8], ecx               ; round index
    mov [esp+12], edi              ; event
    mov [esp+16], eax              ; tick
    mov ecx, [esi+0x30]
    mov ecx, [ecx]
    mov [esp+20], ecx              ; f6bc
    mov edx, [esi+0x2C]
    mov edx, [edx]
    mov [esp+24], edx              ; G68
    mov eax, [esi+0x138]
    cmp eax, -1
    je rc_emit_done
    test eax, eax
    je rc_emit_done
    push 0                         ; lpOverlapped        (esp=A-8)
    lea eax, [esp+36]              ; &written = A+28
    push eax                       ;                     (esp=A-12)
    push 24                        ; nBytes              (esp=A-16)
    lea eax, [esp+16]              ; buffer = A+4
    push eax                       ;                     (esp=A-20)
    push dword ptr [esi+0x138]     ; hFile               (esp=A-24)
    call dword ptr [esi+0x14]      ; WriteFileA (stdcall, ret 20)
rc_emit_done:
    ret
"""

ROUNDS_D_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
; Queue-gated anti-spin variant (2026-10-18): a cycle fires ONLY while the
; client round-batch queue [netobj+0x84b4] is non-empty, and the queue must
; shrink afterwards (proof of real progress). Pathological states where the
; done flag flaps without work can no longer spin: with an empty queue the
; agent just polls (200 ms), and with a stuck queue it backs off and trips the
; guard (event 6) after 8 no-progress cycles. netobj==0 disables the gate
; (legacy behaviour). Events: 0 spawn, 2 done, 3 finished, 4 timeout,
; 5 no-progress, 6 guard tripped.
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr
    cmp dword ptr [esi], 0x31474853 ; 'SHG1'
    jne rc_spin
    mov dword ptr [esi+0x144], 0   ; no-progress streak (alloc slack, zeroed)
    mov dword ptr [esi+0x148], 0   ; queue_before
rc_main:
    cmp dword ptr [esi+4], 0       ; fired flag
    jne rc_idle
    lea eax, [esi+0x34]
    push eax
    call dword ptr [esi+0x0C]      ; GetFileAttributesA(flag)
    cmp eax, -1
    je rc_sleep
    mov dword ptr [esi+4], 1       ; once
    mov dword ptr [esi+0x13C], 0   ; round_index = 0
    lea eax, [esi+0xB4]
    push 0
    push 128
    push 4                         ; OPEN_ALWAYS
    push 0
    push 3                         ; share read|write
    push 0x40000004                ; GENERIC_WRITE | FILE_APPEND_DATA
    push eax
    call dword ptr [esi+0x10]      ; CreateFileA receipt
    mov [esi+0x138], eax           ; handle (may be -1)
rc_cycle:
    mov eax, [esi+0x08]            ; netobj (0 -> gate disabled)
    test eax, eax
    je rc_gate_ok
    mov eax, [eax+0x84B4]          ; round-batch queue count
    test eax, eax
    jne rc_gate_ok
    push 200
    call dword ptr [esi+0x1C]      ; nothing queued: poll, never fire
    jmp rc_cycle
rc_gate_ok:
    mov edi, 50                    ; pre-wait: not mid-round (f6bc != 1)
rc_prewait:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 1
    jne rc_fire
    push 200
    call dword ptr [esi+0x1C]
    dec edi
    jnz rc_prewait
    jmp rc_timeout
rc_fire:
    mov eax, [esi+0x08]
    test eax, eax
    je rc_fire_go
    mov eax, [eax+0x84B4]
rc_fire_go:
    mov [esi+0x148], eax           ; queue_before
    mov eax, [esi+0x2C]            ; G68 addr
    mov dword ptr [eax], 3         ; app round state := 3 (as the UI spawner does)
    mov ecx, [esi+0x24]            ; core
    call dword ptr [esi+0x28]      ; spawner 0x44B88E (AfxBeginThread -> D)
    mov [esi+0x140], eax           ; CWinThread* (or NULL)
    xor eax, eax                   ; event 0 = spawn
    call rc_emit
    mov edi, 72000                 ; wait done: f6bc==2 within ~4 h
rc_waitdone:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 2
    je rc_done
    push 200
    call dword ptr [esi+0x1C]
    dec edi
    jnz rc_waitdone
    mov eax, 4                     ; event 4 = done timeout
    call rc_emit
    jmp rc_idle
rc_done:
    mov eax, [esi+0x08]
    test eax, eax
    je rc_progress
    mov eax, [eax+0x84B4]          ; queue_after
    cmp eax, [esi+0x148]
    jb rc_progress
    inc dword ptr [esi+0x144]      ; no progress this cycle
    mov eax, 5                     ; event 5 = no-progress cycle
    call rc_emit
    cmp dword ptr [esi+0x144], 8
    jae rc_trip
    push 2000
    call dword ptr [esi+0x1C]
    jmp rc_cycle
rc_trip:
    mov eax, 6                     ; event 6 = spin guard tripped (idle)
    call rc_emit
    jmp rc_idle
rc_progress:
    mov dword ptr [esi+0x144], 0
    mov eax, 2                     ; event 2 = done
    call rc_emit
    inc dword ptr [esi+0x13C]
    mov eax, [esi+0x134]           ; max rounds
    cmp dword ptr [esi+0x13C], eax
    jb rc_cycle
    mov eax, 3                     ; event 3 = finished
    call rc_emit
rc_idle:
    push 1000
    call dword ptr [esi+0x1C]
    jmp rc_main
rc_sleep:
    push 250
    call dword ptr [esi+0x1C]
    jmp rc_main
rc_spin:
    push 5000
    call dword ptr [esi+0x1C]
    jmp rc_spin
rc_timeout:
    mov eax, 4
    call rc_emit
    jmp rc_idle
rc_emit:                           ; in: eax=event; clobbers eax/ecx/edx/edi; row at locals
    mov edi, eax
    call dword ptr [esi+0x20]      ; GetTickCount
    mov dword ptr [esp+4], 0x34474853 ; 'SHG4'
    mov ecx, [esi+0x13C]
    mov [esp+8], ecx               ; round index
    mov [esp+12], edi              ; event
    mov [esp+16], eax              ; tick
    mov ecx, [esi+0x30]
    mov ecx, [ecx]
    mov [esp+20], ecx              ; f6bc
    mov edx, [esi+0x2C]
    mov edx, [edx]
    mov [esp+24], edx              ; G68
    mov eax, [esi+0x138]
    cmp eax, -1
    je rc_emit_done
    test eax, eax
    je rc_emit_done
    push 0                         ; lpOverlapped        (esp=A-8)
    lea eax, [esp+36]              ; &written = A+28
    push eax                       ;                     (esp=A-12)
    push 24                        ; nBytes              (esp=A-16)
    lea eax, [esp+16]              ; buffer = A+4
    push eax                       ;                     (esp=A-20)
    push dword ptr [esi+0x138]     ; hFile               (esp=A-24)
    call dword ptr [esi+0x14]      ; WriteFileA (stdcall, ret 20)
rc_emit_done:
    ret
"""

ROUNDS_E_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
; Effect-verified variant E (2026-10-18, F7-round-2 consensus): no queue gate.
; Fire gates: first fire = flag only; afterwards require a NEW received frame
; [netobj+0x8444] or the previous cycle made progress (momentum for catch-up).
; Completion = f6bc==2, OR f6bc==0 after >=300 ms dwell (missed-2 case).
; Progress = phase [core+0x4d8] changed; no progress -> exponential backoff
; (500 ms <<n, cap 32 s) and fuse (event 6) after 6 no-op cycles.
; Stuck (no completion in 45 s) -> SetEvent([netobj+0x84A4]) abort (event 7),
; retry; 3 aborts -> fuse (event 6, idle). Events: 0 spawn, 2 done, 3 finished,
; 4 prewait timeout, 5 no-progress, 6 fuse tripped, 7 aborted.
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr
    cmp dword ptr [esi], 0x31474853 ; 'SHG1'
    jne rc_spin
    mov dword ptr [esi+0x144], 0   ; no-op streak
    mov dword ptr [esi+0x148], 0   ; rx_last
    mov dword ptr [esi+0x14C], 0   ; phase_before
    mov dword ptr [esi+0x150], 0   ; abort streak
    mov dword ptr [esi+0x154], 0   ; last_progress
    mov dword ptr [esi+0x158], 0   ; tick_fire
    mov dword ptr [esi+0x15C], 0   ; turn|round baseline
    mov dword ptr [esi+0x160], 0   ; prewait streak
    mov dword ptr [esi+0x164], 0   ; saw_1 (evidence the worker really ran)
rc_main:
    cmp dword ptr [esi+4], 0       ; fired flag
    jne rc_idle
    lea eax, [esi+0x34]
    push eax
    call dword ptr [esi+0x0C]      ; GetFileAttributesA(flag)
    cmp eax, -1
    je rc_sleep
    mov dword ptr [esi+4], 1       ; once
    mov dword ptr [esi+0x13C], 0   ; round_index = 0
    lea eax, [esi+0xB4]
    push 0
    push 128
    push 4                         ; OPEN_ALWAYS
    push 0
    push 3                         ; share read|write
    push 0x40000004                ; GENERIC_WRITE | FILE_APPEND_DATA
    push eax
    call dword ptr [esi+0x10]      ; CreateFileA receipt
    mov [esi+0x138], eax
rc_cycle:
    ; ---- work gate (after the first cycle) ----
    cmp dword ptr [esi+0x13C], 0
    je rc_gate_ok
    cmp dword ptr [esi+0x154], 0   ; last cycle made progress -> momentum
    jne rc_gate_ok
    mov eax, [esi+0x08]            ; netobj
    test eax, eax
    je rc_gate_ok
    mov eax, [eax+0x8444]          ; received-frame counter
    cmp eax, [esi+0x148]
    jne rc_gate_refresh
    push 500
    call dword ptr [esi+0x1C]      ; nothing new from the session: poll
    jmp rc_cycle
rc_gate_refresh:
    mov [esi+0x148], eax
rc_gate_ok:
    mov edi, 300                   ; pre-wait: not mid-round (f6bc != 1), up to 60 s
rc_prewait:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 1
    jne rc_fire
    push 200
    call dword ptr [esi+0x1C]
    dec edi
    jnz rc_prewait
    inc dword ptr [esi+0x160]      ; prewait streak: retry a few times, then idle
    mov eax, 4
    call rc_emit
    cmp dword ptr [esi+0x160], 3
    jne rc_pw1
    mov eax, [esi+0x30]            ; 3rd timeout: force-clear a stuck mid-round flag once
    mov dword ptr [eax], 0
rc_pw1:
    cmp dword ptr [esi+0x160], 5
    jae rc_idle
    push 3000
    call dword ptr [esi+0x1C]
    jmp rc_cycle
rc_fire:
    mov eax, [esi+0x24]            ; core
    mov ecx, [eax+0x4D0]           ; baseline: year|season dword
    mov [esi+0x14C], ecx
    mov ecx, [eax+0x4D4]           ; baseline: turn|round dword
    mov [esi+0x15C], ecx
    mov eax, [esi+0x2C]            ; G68 addr
    mov dword ptr [eax], 3         ; app round state := 3
    mov ecx, [esi+0x24]
    call dword ptr [esi+0x28]      ; spawner 0x44B88E
    mov [esi+0x140], eax
    call dword ptr [esi+0x20]      ; GetTickCount
    mov [esi+0x158], eax           ; tick_fire
    mov dword ptr [esi+0x164], 0   ; saw_1 := 0 for this fire
    xor eax, eax                   ; event 0 = spawn
    call rc_emit
    mov ecx, 20                    ; settle: wait until a stale f6bc==2 moves
rc_settle:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 2
    jne rc_waitdone
    push 50
    call dword ptr [esi+0x1C]
    dec ecx
    jnz rc_settle
rc_waitdone:
    mov eax, [esi+0x30]
    mov eax, [eax]
    cmp eax, 1
    jne rc_wd_not1
    mov dword ptr [esi+0x164], 1   ; saw_1: evidence the worker really ran
    jmp rc_wt_sleep
rc_wd_not1:
    cmp dword ptr [esi+0x164], 0
    je rc_wt_sleep                 ; no evidence yet: never accept completion
    cmp eax, 2
    je rc_done_early
    cmp eax, 0
    je rc_maybe_cleared
    jmp rc_wt_sleep
rc_maybe_cleared:
    push 300                       ; f6bc==0 is "done" only after 300 ms dwell
    call rc_elapsed_ge
    test eax, eax
    jnz rc_done
rc_wt_sleep:
    push 45000                     ; stuck past 45 s -> abort
    call rc_elapsed_ge
    test eax, eax
    jnz rc_abort
    push 100
    call dword ptr [esi+0x1C]
    jmp rc_waitdone
rc_done_early:
    push 100                       ; f6bc==2 seen: accept (settle already cleared stale)
    call rc_elapsed_ge
    test eax, eax
    jz rc_wt_sleep                 ; <100 ms: likely still the old value; keep polling
    jmp rc_done
rc_abort:
    mov eax, [esi+0x08]
    test eax, eax
    je rc_abort_skip
    push dword ptr [eax+0x84A4]    ; SetEvent(netobj+0x84A4)
    call dword ptr [esi+0x18]      ; SetEvent
rc_abort_skip:
    mov eax, 7                     ; event 7 = round aborted
    call rc_emit
    inc dword ptr [esi+0x150]      ; abort streak
    push 3000
    call dword ptr [esi+0x1C]      ; give the aborted worker time to exit
    mov eax, [esi+0x30]            ; f6bc still 1 -> orphan worker: force-clear
    cmp dword ptr [eax], 1
    jne rc_abort_cleared
    mov dword ptr [eax], 0
rc_abort_cleared:
    cmp dword ptr [esi+0x150], 3
    jae rc_trip
    push 2000
    call dword ptr [esi+0x1C]
    jmp rc_cycle
rc_trip:
    mov eax, 6                     ; event 6 = fuse tripped (idle)
    call rc_emit
    jmp rc_idle
rc_done:
    mov eax, [esi+0x24]
    mov ecx, [eax+0x4D0]           ; year|season
    cmp ecx, [esi+0x14C]
    jne rc_progress
    mov ecx, [eax+0x4D4]           ; turn|round (steps every round)
    cmp ecx, [esi+0x15C]
    jne rc_progress
    mov dword ptr [esi+0x154], 0   ; no progress this cycle
    inc dword ptr [esi+0x144]
    mov eax, 5                     ; event 5 = no-progress cycle
    call rc_emit
    cmp dword ptr [esi+0x144], 6
    jae rc_trip
    mov ecx, [esi+0x144]
    dec ecx
    cmp ecx, 6
    jbe rc_bo1
    mov ecx, 6
rc_bo1:
    mov eax, 500                   ; backoff = 500 << (streak-1), cap 32 s
    shl eax, cl
    cmp eax, 32000
    jbe rc_bo2
    mov eax, 32000
rc_bo2:
    push eax
    call dword ptr [esi+0x1C]
    jmp rc_cycle
rc_progress:
    mov dword ptr [esi+0x154], 1   ; momentum for catch-up
    mov dword ptr [esi+0x144], 0
    mov dword ptr [esi+0x150], 0
    mov dword ptr [esi+0x160], 0
    mov eax, 2                     ; event 2 = done
    call rc_emit
    inc dword ptr [esi+0x13C]
    mov eax, [esi+0x134]           ; max rounds
    cmp dword ptr [esi+0x13C], eax
    jb rc_cycle
    mov eax, 3                     ; event 3 = finished
    call rc_emit
rc_idle:
    push 1000
    call dword ptr [esi+0x1C]
    jmp rc_main
rc_sleep:
    push 250
    call dword ptr [esi+0x1C]
    jmp rc_main
rc_spin:
    push 5000
    call dword ptr [esi+0x1C]
    jmp rc_spin
rc_timeout:
    mov eax, 4
    call rc_emit
    jmp rc_idle
rc_elapsed_ge:                     ; in: [esp+4]=limit ms; out: eax=1 if elapsed>=limit
    call dword ptr [esi+0x20]      ; GetTickCount
    sub eax, [esi+0x158]
    xor ecx, ecx
    cmp eax, [esp+4]
    setae cl
    mov eax, ecx
    ret 4
rc_emit:                           ; in: eax=event; clobbers eax/ecx/edx/edi; row at locals
    mov edi, eax
    call dword ptr [esi+0x20]      ; GetTickCount
    mov dword ptr [esp+4], 0x34474853 ; 'SHG4'
    mov ecx, [esi+0x13C]
    mov [esp+8], ecx               ; round index
    mov [esp+12], edi              ; event
    mov [esp+16], eax              ; tick
    mov ecx, [esi+0x30]
    mov ecx, [ecx]
    mov [esp+20], ecx              ; f6bc
    mov edx, [esi+0x2C]
    mov edx, [edx]
    mov [esp+24], edx              ; G68
    mov eax, [esi+0x138]
    cmp eax, -1
    je rc_emit_done
    test eax, eax
    je rc_emit_done
    push 0                         ; lpOverlapped        (esp=A-8)
    lea eax, [esp+36]              ; &written = A+28
    push eax                       ;                     (esp=A-12)
    push 24                        ; nBytes              (esp=A-16)
    lea eax, [esp+16]              ; buffer = A+4
    push eax                       ;                     (esp=A-20)
    push dword ptr [esi+0x138]     ; hFile               (esp=A-24)
    call dword ptr [esi+0x14]      ; WriteFileA (stdcall, ret 20)
rc_emit_done:
    ret
"""

ACCEPTEXIT_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 40
    mov esi, [esp+56]              ; blob ptr
    cmp dword ptr [esi], 0x31474853
    jne agent_spin
agent_loop:
    cmp dword ptr [esi+4], 0       ; sent flag
    jne agent_sleep_long
    lea eax, [esi+52]
    push eax
    call dword ptr [esi+12]        ; GetFileAttributesA
    cmp eax, -1
    je agent_sleep_short
    call dword ptr [esi+36]        ; IsConnected@0
    test eax, eax
    jz agent_sleep_short
    mov dword ptr [esp+12], 0
    lea eax, [esp+12]
    push eax
    call dword ptr [esi+40]        ; GetIPAddress@4
    mov eax, [esp+12]
    test eax, eax
    jz agent_sleep_short
    mov edi, [eax]                 ; own id
    test edi, edi
    jz agent_sleep_short
    push edi
    call dword ptr [esi+44]        ; AcceptEXIT@4(own) (stdcall, ret 4)
    mov [esp], eax                 ; rc
    mov dword ptr [esi+4], 1       ; once-only
    lea eax, [esi+180]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+16]        ; CreateFileA receipt (stdcall, ret 28)
    cmp eax, -1
    je agent_after_receipt
    mov [esp+8], eax
    mov dword ptr [esp+16], 0x33474853 ; 'SHG3'
    mov eax, [esp]
    mov [esp+20], eax              ; rc
    mov [esp+24], edi              ; own
    mov dword ptr [esp+28], 0      ; unused
    call dword ptr [esi+32]        ; GetTickCount
    mov [esp+32], eax
    mov dword ptr [esp+36], 0
    push 0
    lea eax, [esp+8]
    push eax
    push 24
    lea eax, [esp+28]
    push eax
    mov eax, [esp+24]
    push eax
    call dword ptr [esi+20]        ; WriteFileA (stdcall, ret 20)
    push dword ptr [esp+8]
    call dword ptr [esi+24]        ; CloseHandle (stdcall, ret 4)
agent_after_receipt:
    push 1000
    call dword ptr [esi+28]
    jmp agent_loop
agent_sleep_short:
    push 250
    call dword ptr [esi+28]
    jmp agent_loop
agent_sleep_long:
    push 1000
    call dword ptr [esi+28]
    jmp agent_loop
agent_spin:
    push 5000
    call dword ptr [esi+28]
    jmp agent_spin
"""


def assemble(asm_text, name, workdir):
    src = workdir / (name + '.s')
    obj = workdir / (name + '.obj')
    asm_text = asm_text.replace('; ', '// ')
    src.write_text(asm_text, encoding='utf-8')
    clang = shutil.which('clang')
    if clang is None:
        raise SystemExit('clang not found')
    subprocess.run(
        [clang, '--target=i386-pc-windows-msvc', '-x', 'assembler', '-c', str(src), '-o', str(obj)],
        check=True)
    data = obj.read_bytes()
    machine, nsec = struct.unpack_from('<HH', data, 0)
    if machine != 0x14C:
        raise SystemExit('unexpected COFF machine %x' % machine)
    text = None
    for i in range(nsec):
        off = 20 + i * 40
        sec_name = data[off:off + 8].rstrip(b'\0')
        vsize, va, rawsize, rawptr = struct.unpack_from('<IIII', data, off + 8)
        nreloc = struct.unpack_from('<H', data, off + 32)[0]
        if sec_name == b'.text':
            if nreloc != 0:
                raise SystemExit('%s .text has %d relocations (must be none)' % (name, nreloc))
            text = data[rawptr:rawptr + rawsize]
    if not text:
        raise SystemExit('%s: .text not found' % name)
    return text


def disassemble(code):
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [(i.address, i.mnemonic, i.op_str, i.size) for i in md.disasm(code, 0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', required=True)
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {'schema': 'p51-shadow-agent-1', 'target': 'i386-pc-windows-msvc'}
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for name, asm in (('agent', AGENT_ASM), ('smoke', SMOKE_ASM),
                          ('agent_cmd9', CMD9_ASM), ('agent_uplink', UPLINK_ASM),
                          ('agent_bcast', BCAST_ASM), ('agent_spoof', SPOOF_ASM),
                          ('agent_acceptexit', ACCEPTEXIT_ASM), ('agent_rounds', ROUNDS_ASM),
                          ('agent_rounds_b', ROUNDS_B_ASM), ('agent_rounds_c', ROUNDS_C_ASM),
                          ('agent_rounds_d', ROUNDS_D_ASM), ('agent_rounds_e', ROUNDS_E_ASM)):
            asm = asm.replace('; ', '// ')
            code = assemble(asm, name, tmpdir)
            # sanity: entry must be the first instruction
            listing = disassemble(code)
            if name == 'agent' and listing[0][1] != 'push':
                raise SystemExit('agent entry does not start with push')
            (outdir / (name + '.s')).write_text(asm, encoding='utf-8')
            (outdir / (name + '.bin')).write_bytes(code)
            textlines = ['%04x: %-7s %s' % (a, m, o) for a, m, o, s in listing]
            (outdir / (name + '.listing.txt')).write_text('\n'.join(textlines) + '\n', encoding='utf-8')
            manifest[name] = {
                'size': len(code),
                'sha256': hashlib.sha256(code).hexdigest(),
                'instructions': len(listing),
            }
            # structural asserts
            if name == 'agent':
                ops = [m for _, m, _, _ in listing]
                for must in ('call', 'bswap', 'jmp'):
                    if must not in ops:
                        raise SystemExit('agent missing expected op: ' + must)
                if len(code) > 640:
                    raise SystemExit('agent too large: %d' % len(code))
    (outdir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
