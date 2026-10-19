ENTRY(_start)
SECTIONS
{
    . = 0x00100000;
    image_start = .;
    .text : { KEEP(*(.multiboot)) *(.text*) }
    .rodata : { *(.rodata*) *(.rdata*) }
    .data : { *(.data*) }
    image_load_end = .;
    .bss (NOLOAD) : { bss_start = .; *(.bss*) *(COMMON) }
    image_end = .;
    /DISCARD/ : { *(.comment*) *(.eh_frame*) *(.note*) *(.idata*) *(.reloc*) }
    ASSERT(image_end < 0x00200000, "OpenME test image exceeds its 1 MiB budget")
}
