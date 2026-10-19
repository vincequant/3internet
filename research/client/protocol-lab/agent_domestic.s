
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 112
    mov esi, [esp+128]             // blob ptr (entry [esp0+4])
    cmp dword ptr [esi], 0x35474853 // 'SHG5'// bad -> inert spin
    jne d_spin
d_loop:
    cmp dword ptr [esi+4], 0       // once-only sent flag
    jne d_sleep_long
    lea eax, [esi+0x50]
    push eax
    call dword ptr [esi+8]         // GetFileAttributesA(flag) stdcall
    cmp eax, -1
    je d_sleep_short
    call dword ptr [esi+0x20]      // _NetMsg_IsConnected@0
    test eax, eax
    jz d_sleep_short
    mov eax, [esi+0x28]            // &core
    test eax, eax
    jz d_sleep_short
    mov ebx, [eax]                 // core
    test ebx, ebx
    jz d_sleep_short
    mov ecx, [ebx+0x6c0]           // my_slot must be sane
    cmp ecx, 7
    ja d_sleep_short
    cmp dword ptr [esi+0x38], 32   // actor 0..31
    jae d_sleep_short
    cmp dword ptr [esi+0x3c], 3    // parameter 0..2
    jae d_sleep_short
    mov dword ptr [esp+0x58], 0
    lea eax, [esp+0x58]
    push eax
    call dword ptr [esi+0x24]      // _NetMsg_GetIPAddress@4(&ptr)
    mov eax, [esp+0x58]
    test eax, eax
    jz d_sleep_short
    mov edi, [eax]                 // own id
    test edi, edi
    jz d_sleep_short
    mov [esp+0x24], ebx            // save core
    mov eax, ebx
    sub eax, 0x912                 // G
    mov eax, [eax+0x80]            // match gate before
    mov [esp+0x5c], eax
    lea ecx, [esp]                 // &obj
    call dword ptr [esi+0x2c]      // CSanInetDomesticCmd::ctor
    mov eax, [esi+0x38]
    mov [esp+0x14], eax            // actor
    mov eax, [esi+0x3c]
    mov [esp+0x18], eax            // parameter (0/1/2)
    mov eax, [esi+0x40]
    mov [esp+0x1c], eax            // value
    mov eax, [esi+0x44]
    mov [esp+0x20], eax            // extra
    mov ecx, [esi+0x34]            // CSanInet member (static)
    lea eax, [esp]
    push eax
    call dword ptr [esi+0x30]      // 0x42a7d4 SendObject(this, &obj), ret 4
    mov dword ptr [esi+4], 1       // once-only, before any I/O
    // ---- receipt (48 bytes at esp+0x28) ----
    mov dword ptr [esp+0x28], 0x43523553
    mov [esp+0x2c], eax            // rc (1 = SendCmd accepted, 0 = error)
    mov ecx, [esp+0x24]
    mov [esp+0x30], ecx            // core
    mov ecx, [esi+0x38]
    mov [esp+0x34], ecx            // actor
    mov ecx, [esi+0x3c]
    mov [esp+0x38], ecx            // parameter
    mov ecx, [esi+0x40]
    mov [esp+0x3c], ecx            // value
    mov ecx, [esi+0x44]
    mov [esp+0x40], ecx            // extra
    mov ecx, [esp+0x5c]
    mov [esp+0x48], ecx            // gate before
    mov ecx, [esp+0x24]
    sub ecx, 0x912
    mov ecx, [ecx+0x80]
    mov [esp+0x4c], ecx            // gate after
    mov ecx, [esp+0x24]
    movzx ecx, word ptr [ecx+0x4d8]
    mov [esp+0x50], ecx            // phase/season step
    mov [esp+0x54], edi            // own id
    call dword ptr [esi+0x1c]      // GetTickCount
    mov [esp+0x44], eax            // tick
    lea eax, [esi+0xD0]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+0x0C]      // CreateFileA receipt, stdcall ret 28
    cmp eax, -1
    je d_after_receipt
    mov [esp+0x60], eax            // handle
    push 0                         // lpOverlapped
    lea eax, [esp+0x6C]            // &written  (= E+0x68)
    push eax
    push 48                        // nBytes
    lea eax, [esp+0x34]            // buffer    (= E+0x28)
    push eax
    mov eax, [esp+0x70]            // handle    (= E+0x60)
    push eax
    call dword ptr [esi+0x10]      // WriteFileA, stdcall ret 20
    push dword ptr [esp+0x60]
    call dword ptr [esi+0x14]      // CloseHandle, stdcall ret 4
d_after_receipt:
    push 1000
    call dword ptr [esi+0x18]      // Sleep
    jmp d_loop
d_sleep_short:
    push 250
    call dword ptr [esi+0x18]
    jmp d_loop
d_sleep_long:
    push 1000
    call dword ptr [esi+0x18]
    jmp d_loop
d_spin:
    push 5000
    call dword ptr [esi+0x18]
    jmp d_spin
