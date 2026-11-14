image_base = 0;
SECTIONS {
    . = 0x3835000;
    .text : { *(.text*) *(.rodata*) }
    . = 0x3839000;
    .data : { *(.data*) *(.bss*) }
    /DISCARD/ : { *(.comment*) *(.note*) *(.eh_frame*) }
}
