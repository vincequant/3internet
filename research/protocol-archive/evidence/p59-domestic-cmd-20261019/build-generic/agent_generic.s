
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 0x160
    mov esi, [esp+0x170]            // blob ptr (0x160 + 3 pushes + ret)
    cmp dword ptr [esi], 0x36474853 // 'SHG6'
    jne g_spin
g_loop:
    cmp dword ptr [esi+4], 0
    jne g_sleep_long
    lea eax, [esi+0x48]
    push eax
    call dword ptr [esi+8]          // GetFileAttributesA(flag)
    cmp eax, -1
    je g_sleep_short
    call dword ptr [esi+0x20]       // IsConnected
    test eax, eax
    jz g_sleep_short
    mov eax, [esi+0x28]             // &core
    test eax, eax
    jz g_sleep_short
    mov ebx, [eax]                  // core
    test ebx, ebx
    jz g_sleep_short
    mov eax, [esi+0x148]            // phase gate (0 = any)
    test eax, eax
    jz g_phase_ok
    movzx ecx, word ptr [ebx+0x4d8]
    cmp ecx, eax
    jne g_sleep_short
g_phase_ok:
    mov ecx, [ebx+0x6c0]            // my_slot
    cmp ecx, 7
    ja g_sleep_short
    mov dword ptr [esp+0x108], 0
    lea eax, [esp+0x108]
    push eax
    call dword ptr [esi+0x24]       // GetIPAddress(&ptr)
    mov eax, [esp+0x108]
    test eax, eax
    jz g_sleep_short
    mov eax, [eax]
    test eax, eax
    jz g_sleep_short
    mov [esp+0x10C], eax            // own id
    mov [esp+0x100], ebx            // core
    mov eax, ebx
    sub eax, 0x912
    mov eax, [eax+0x80]
    mov [esp+0x104], eax            // gate before
    lea ecx, [esp]
    call dword ptr [esi+0x2C]       // the game's own ctor
    mov ecx, [esi+0x3C]
    test ecx, ecx
    jz g_fields_done
    mov edi, [esi+0x40]
    add edi, esi
g_floop:
    mov eax, [edi]
    mov edx, [edi+4]
    mov [esp+eax], edx
    add edi, 8
    dec ecx
    jnz g_floop
g_fields_done:
    mov ecx, [esi+0x34]
    lea eax, [esp]
    push eax
    call dword ptr [esi+0x30]       // 0x42a7d4 SendObject(this,&obj), ret 4
    mov dword ptr [esi+4], 1
    mov dword ptr [esp+0x110], 0x53365243
    mov [esp+0x114], eax            // rc
    mov ecx, [esp+0x100]
    mov [esp+0x118], ecx            // core
    mov ecx, [esp+0x10C]
    mov [esp+0x11C], ecx            // own
    mov ecx, [esp+0x104]
    mov [esp+0x120], ecx            // gate before
    mov ecx, [esp+0x100]
    sub ecx, 0x912
    mov ecx, [ecx+0x80]
    mov [esp+0x124], ecx            // gate after
    mov ecx, [esp+0x100]
    movzx ecx, word ptr [ecx+0x4d8]
    mov [esp+0x128], ecx            // phase
    call dword ptr [esi+0x1C]       // GetTickCount
    mov [esp+0x12C], eax            // tick
    mov eax, [esp+0x00]
    mov [esp+0x130], eax
    mov eax, [esp+0x04]
    mov [esp+0x134], eax
    mov eax, [esp+0x08]
    mov [esp+0x138], eax
    mov eax, [esp+0x0C]
    mov [esp+0x13C], eax
    mov eax, [esp+0x14]
    mov [esp+0x140], eax
    mov eax, [esp+0x18]
    mov [esp+0x144], eax
    mov eax, [esp+0x1C]
    mov [esp+0x148], eax
    mov eax, [esp+0x20]
    mov [esp+0x14C], eax
    lea eax, [esi+0xC8]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+0x0C]       // CreateFileA receipt
    cmp eax, -1
    je g_after_receipt
    mov [esp+0x150], eax
    push 0
    lea eax, [esp+0x158]
    push eax
    push 64
    lea eax, [esp+0x11C]
    push eax
    mov eax, [esp+0x160]
    push eax
    call dword ptr [esi+0x10]       // WriteFileA
    push dword ptr [esp+0x150]
    call dword ptr [esi+0x14]       // CloseHandle
g_after_receipt:
    push 1000
    call dword ptr [esi+0x18]
    jmp g_loop
g_sleep_short:
    push 250
    call dword ptr [esi+0x18]
    jmp g_loop
g_sleep_long:
    push 1000
    call dword ptr [esi+0x18]
    jmp g_loop
g_spin:
    push 5000
    call dword ptr [esi+0x18]
    jmp g_spin
