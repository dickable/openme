/* SPDX-License-Identifier: MIT */
/* Multiboot v1 flat-image entry for the QEMU PC test target ONLY. */
.section .multiboot,"a"
.balign 4
.globl mb_header
mb_header:
    .long 0x1badb002
    .long 0x00010000
    .long -(0x1badb002 + 0x00010000)
    .long mb_header
    .long image_start
    .long image_load_end
    .long image_end
    .long _start

.section .text
.code32
.globl _start
_start:
    cli
    cld
    mov %eax, %esi
    lgdt gdt_desc
    ljmp $0x08, $segments_ready
segments_ready:
    mov $0x10, %ax
    mov %ax, %ds
    mov %ax, %es
    mov %ax, %fs
    mov %ax, %gs
    mov %ax, %ss
    mov $stack_top, %esp
    xor %ebp, %ebp
    mov $bss_start, %edi
    mov $image_end, %ecx
    sub %edi, %ecx
    xor %eax, %eax
    rep stosb
    sub $12, %esp
    push %esi
    call firmware_main
1:  cli
    hlt
    jmp 1b

.balign 8
gdt:
    .quad 0
    .quad 0x00cf9a000000ffff
    .quad 0x00cf92000000ffff
gdt_desc:
    .word 23
    .long gdt

.bss
.balign 16
stack_bottom:
    .skip 16384
stack_top:
