.intel_syntax noprefix
.text
.globl hidden_0
hidden_0:
push edx
mov edx, 0
jmp hidden_common
.globl hidden_1
hidden_1:
push edx
mov edx, 1
jmp hidden_common
.globl hidden_2
hidden_2:
push edx
mov edx, 2
jmp hidden_common
.globl hidden_3
hidden_3:
push edx
mov edx, 3
jmp hidden_common
.globl hidden_4
hidden_4:
push edx
mov edx, 4
jmp hidden_common
.globl hidden_5
hidden_5:
push edx
mov edx, 5
jmp hidden_common
.globl hidden_6
hidden_6:
push edx
mov edx, 6
jmp hidden_common
.globl hidden_7
hidden_7:
push edx
mov edx, 7
jmp hidden_common
.globl hidden_8
hidden_8:
push edx
mov edx, 8
jmp hidden_common
.globl hidden_9
hidden_9:
push edx
mov edx, 9
jmp hidden_common
.globl hidden_10
hidden_10:
push edx
mov edx, 10
jmp hidden_common
.globl hidden_11
hidden_11:
push edx
mov edx, 11
jmp hidden_common
.globl hidden_12
hidden_12:
push edx
mov edx, 12
jmp hidden_common
.globl hidden_13
hidden_13:
push edx
mov edx, 13
jmp hidden_common
.globl hidden_14
hidden_14:
push edx
mov edx, 14
jmp hidden_common
.globl hidden_15
hidden_15:
push edx
mov edx, 15
jmp hidden_common
.globl hidden_16
hidden_16:
push edx
mov edx, 16
jmp hidden_common
.globl hidden_17
hidden_17:
push edx
mov edx, 17
jmp hidden_common
.globl hidden_18
hidden_18:
push edx
mov edx, 18
jmp hidden_common
.globl hidden_19
hidden_19:
push edx
mov edx, 19
jmp hidden_common
.globl hidden_20
hidden_20:
push edx
mov edx, 20
jmp hidden_common
.globl hidden_21
hidden_21:
push edx
mov edx, 21
jmp hidden_common
.globl hidden_22
hidden_22:
push edx
mov edx, 22
jmp hidden_common
.globl hidden_23
hidden_23:
push edx
mov edx, 23
jmp hidden_common
.globl hidden_24
hidden_24:
push edx
mov edx, 24
jmp hidden_common
.globl hidden_25
hidden_25:
push edx
mov edx, 25
jmp hidden_common
.globl hidden_26
hidden_26:
push edx
mov edx, 26
jmp hidden_common
.globl hidden_27
hidden_27:
push edx
mov edx, 27
jmp hidden_common
.globl hidden_28
hidden_28:
push edx
mov edx, 28
jmp hidden_common
.globl hidden_29
hidden_29:
push edx
mov edx, 29
jmp hidden_common
.globl hidden_30
hidden_30:
push edx
mov edx, 30
jmp hidden_common
.globl hidden_31
hidden_31:
push edx
mov edx, 31
jmp hidden_common
hidden_common:
push ebx
push esi
mov ebx, edx
mov esi, ecx
test esi, esi
jz hidden_false
cmp dword ptr [eax+0x60], 0x4490d2
je hidden_typed
cmp dword ptr [eax+0x60], 0x4491e5
jne hidden_original
hidden_typed:
mov edx, [esi+0x1c]
test edx, edx
jz hidden_false
mov edx, [edx]
cmp edx, 0x50a0f0
je hidden_group_0
cmp edx, 0x50a1a8
je hidden_group_1
cmp edx, 0x50a260
je hidden_group_2
cmp edx, 0x508678
je hidden_group_3
cmp edx, 0x508878
je hidden_group_3
cmp edx, 0x508a60
je hidden_group_3
cmp edx, 0x508c48
je hidden_group_3
cmp edx, 0x508e30
je hidden_group_3
cmp edx, 0x509018
je hidden_group_3
cmp edx, 0x509200
je hidden_group_3
cmp edx, 0x5093e8
je hidden_group_3
cmp edx, 0x5095d0
je hidden_group_3
cmp edx, 0x5097b8
je hidden_group_3
cmp edx, 0x5099d0
je hidden_group_3
cmp edx, 0x50bdb8
je hidden_group_3
cmp edx, 0x507e10
je hidden_group_4
cmp edx, 0x507ee8
je hidden_group_4
cmp edx, 0x507fc0
je hidden_group_4
jmp hidden_original
hidden_group_0:
test ebx, 1
jz hidden_original
jmp hidden_base_flags
hidden_group_1:
test ebx, 2
jz hidden_original
jmp hidden_base_flags
hidden_group_2:
test ebx, 4
jz hidden_original
jmp hidden_base_flags
hidden_group_3:
test ebx, 8
jz hidden_original
jmp hidden_base_flags
hidden_group_4:
test ebx, 16
jz hidden_original
jmp hidden_base_flags
hidden_base_flags:
xor eax, eax
test dword ptr [esi+0x20], 0xa0000000
sete al
jmp hidden_done
hidden_original:
mov ecx, esi
call dword ptr [eax+0x60]
jmp hidden_done
hidden_false:
xor eax, eax
hidden_done:
pop esi
pop ebx
pop edx
test eax, eax
ret
