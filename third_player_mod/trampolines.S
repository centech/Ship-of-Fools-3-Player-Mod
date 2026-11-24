.text
.globl original_spawn
.type original_spawn,@function
original_spawn:
    mov %rbx, 8(%rsp)
    jmp image_base + 0x6ddf05
.size original_spawn, .-original_spawn

.globl original_reset
.type original_reset,@function
original_reset:
    push %rsi
    push %r13
    push %r14
    jmp image_base + 0x911a86
.size original_reset, .-original_reset

.globl original_despawn
.type original_despawn,@function
original_despawn:
    push %rsi
    sub $0x20, %rsp
    jmp image_base + 0x6dd4c6
.size original_despawn, .-original_despawn

.globl original_input_awake
.type original_input_awake,@function
original_input_awake:
    push %rbx
    sub $0x20, %rsp
    jmp image_base + 0x1172ef6
.size original_input_awake, .-original_input_awake
.globl original_inventory_update
.type original_inventory_update,@function
original_inventory_update:
    mov %rbx, 0x10(%rsp)
    jmp image_base + 0x8ad005
.size original_inventory_update, .-original_inventory_update

.globl original_inventory_match
.type original_inventory_match,@function
original_inventory_match:
    push %rbx
    sub $0x160, %rsp
    jmp image_base + 0x8ac609
.size original_inventory_match, .-original_inventory_match
.section .note.GNU-stack,"",@progbits
