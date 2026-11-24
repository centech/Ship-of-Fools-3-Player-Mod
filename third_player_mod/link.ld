image_base = 0;
SECTIONS {
    . = 0x3837000;
    .text : { *(.text*) *(.rodata*) }
    . = 0x383b000;
    .data : { *(.data*) *(.bss*) }
    /DISCARD/ : { *(.comment*) *(.note*) *(.eh_frame*) }
}
