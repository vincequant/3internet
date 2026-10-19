
.intel_syntax noprefix
.text
.globl resident_boot, resident_worker, resident_d_guard, resident_ui_wait
.globl resident_ui_return, resident_sync_begin, resident_sync_end
resident_boot:
    push ebx
    mov ebx, [esp+8]
    mov ecx, [ebx+8]
    call dword ptr [ebx+0x58]
    mov [ebx+0x7c], eax
    pop ebx
    xor eax, eax
    ret 4

resident_worker:
    push ebx
    push esi
    push edi
    call worker_pc
worker_pc:
    pop ebx
    .set delta_worker_pc, worker_pc-resident_boot
    sub ebx, offset delta_worker_pc
    add ebx, 0x1000
    call dword ptr [ebx+0x3c]
    mov edx, eax
    xor eax, eax
    lock cmpxchg [ebx+0x10], edx
    jnz worker_duplicate
worker_flag:
    lea eax, [ebx+0x80]
    push eax
    call dword ptr [ebx+0x40]
    cmp eax, -1
    jne worker_open
    push 100
    call dword ptr [ebx+0x38]
    jmp worker_flag
worker_open:
    lea eax, [ebx+0x100]
    push 0
    push 128
    push 4
    push 0
    push 3
    push 0x40000004
    push eax
    call dword ptr [ebx+0x68]
    mov [ebx+0x74], eax
worker_ready:
    mov esi, [ebx+8]
    cmp dword ptr [esi+0x6bc], 0
    jne worker_wait_ui
    cmp dword ptr [esi+0x660], 0
    jne worker_wait_ui
    mov dword ptr [esi-0x8aa], 3
    mov dword ptr [ebx+0x30], 1
    mov edi, [ebx+0x1c]
    mov ecx, esi
    xor eax, eax
    call resident_emit
    mov ecx, esi
    call dword ptr [ebx+0x44]
    // Only the actual return of D releases the ownership gate.
    mov dword ptr [ebx+0x14], 0
    inc dword ptr [ebx+0x24]
    mov dword ptr [ebx+0x30], 2
    inc edi
    cmp [ebx+0x1c], edi
    jne worker_fault
    cmp [ebx+0x20], edi
    jne worker_fault
    mov eax, 2
    call resident_emit
worker_wait_ui:
    mov dword ptr [ebx+0x30], 3
    push 1
    call dword ptr [ebx+0x38]
    jmp worker_ready
worker_fault:
    mov dword ptr [ebx+0x30], 9
    mov dword ptr [ebx+0x34], 1
    mov eax, 9
    call resident_emit
worker_park:
    push 1000
    call dword ptr [ebx+0x38]
    jmp worker_park
worker_duplicate:
    lock inc dword ptr [ebx+0x28]
    pop edi
    pop esi
    pop ebx
    xor eax, eax
    ret

resident_emit:
    pushad
    mov [ebx+0x188], eax
    call dword ptr [ebx+0x54]
    mov [ebx+0x18c], eax
    mov dword ptr [ebx+0x180], 0x35474853
    mov eax, [ebx+0x24]
    mov [ebx+0x184], eax
    mov eax, [esi+0x6bc]
    mov [ebx+0x190], eax
    mov eax, [esi-0x8aa]
    mov [ebx+0x194], eax
    cmp dword ptr [ebx+0x74], -1
    je emit_done
    push 0
    lea eax, [ebx+0x198]
    push eax
    push 24
    lea eax, [ebx+0x180]
    push eax
    push dword ptr [ebx+0x74]
    call dword ptr [ebx+0x6c]
emit_done:
    popad
    ret

resident_d_guard:
    pushfd
    pushad
    call d_pc
d_pc:
    pop ebx
    .set delta_d_pc, d_pc-resident_boot
    sub ebx, offset delta_d_pc
    add ebx, 0x1000
    call dword ptr [ebx+0x3c]
    cmp eax, [ebx+0x10]
    jne d_reject
    xor eax, eax
    mov edx, 1
    lock cmpxchg [ebx+0x14], edx
    jne d_reject
    lock inc dword ptr [ebx+0x18]
    popad
    popfd
    mov eax, 0x4f1f88
    push 0x44b8cf
    ret
d_reject:
    lock inc dword ptr [ebx+0x28]
    popad
    popfd
    xor eax, eax
    ret

resident_ui_wait:
    pushfd
    pushad
    call ui_pc
ui_pc:
    pop ebx
    .set delta_ui_pc, ui_pc-resident_boot
    sub ebx, offset delta_ui_pc
    add ebx, 0x1000
    mov esi, [esp+24]
    jmp ui_choose
// Recovery return address for an already-blocked, identity-checked waiter.
// Its volatile ECX is unspecified after kernel32; use the bound core instead.
resident_ui_return:
    pushfd
    pushad
    call return_pc
return_pc:
    pop ebx
    .set delta_return_pc, return_pc-resident_boot
    sub ebx, offset delta_return_pc
    add ebx, 0x1000
    mov esi, [ebx+8]
    add esi, 0x654
ui_choose:
    mov eax, [ebx+8]
    add eax, 0x654
    cmp esi, eax
    jne ui_other_queue
    call dword ptr [ebx+0x3c]
    mov edi, eax
    cmp eax, [ebx+0x0c]
    je ui_pump
ui_worker:
    // A warm recovery can release old D callbacks in observed order.
    cmp edi, [ebx+0x10]
    je ui_queue_test
    cmp dword ptr [ebx+0x64], 0
    je ui_queue_test
    cmp edi, [ebx+0x64]
    jne ui_hold
ui_queue_test:
    cmp dword ptr [esi+0x1c], 0
    je ui_done
    cmp dword ptr [esi+0xc], 0
    je ui_done
    push -1
    push dword ptr [esi+0x24]
    call dword ptr [ebx+0x50]
ui_hold:
    push 1
    call dword ptr [ebx+0x38]
    jmp ui_worker
ui_pump:
    lock inc dword ptr [ebx+0x2c]
    cmp dword ptr [esi+0xc], 0
    je ui_done
    mov ecx, [ebx+8]
    sub ecx, 0x912
    call dword ptr [ebx+0x5c]
    jmp ui_pump
ui_other_queue:
    cmp dword ptr [esi+0x1c], 0
    je ui_done
    push -1
    push dword ptr [esi+0x24]
    call dword ptr [ebx+0x50]
ui_done:
    popad
    popfd
    ret

resident_sync_begin:
    pushfd
    pushad
    call begin_pc
begin_pc:
    pop ebx
    .set delta_begin_pc, begin_pc-resident_boot
    sub ebx, offset delta_begin_pc
    add ebx, 0x1000
    lock inc dword ptr [ebx+0x1c]
    popad
    popfd
    push 8
    mov [esi+0x6c4], ebx
    push 0x44b92c
    ret

resident_sync_end:
    pushfd
    pushad
    call end_pc
end_pc:
    pop ebx
    .set delta_end_pc, end_pc-resident_boot
    sub ebx, offset delta_end_pc
    add ebx, 0x1000
    lock inc dword ptr [ebx+0x20]
    popad
    popfd
    lea edi, [esi+0x87]
    push 0x44bb16
    ret

.globl resident_legacy_park
resident_legacy_park:
    push 1000
    call dword ptr [esi+0x1c]
    jmp resident_legacy_park
