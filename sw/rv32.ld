/* Linker script for the phase 1 core.
 *
 * .text starts at 0x00000000 because `pc_gen` comes out of reset at the reset
 * vector and the core fetches sequentially from there. Anything else means the
 * first fetch is of whatever happens to sit at the reset address.
 *
 * There is no MMU and no operating system, so this is the whole memory map:
 *
 *   0x00000000  .text      code, read-only in practice
 *   (aligned)    .rodata    constants the compiler materialises
 *   (aligned)    .data      initialised data, copied by crt0
 *   (aligned)    .bss       zeroed by crt0
 *   _stack_top   stack, growing down
 *   0x00080000  tohost     written by the program to end the test
 *
 * `tohost` sits well past the end of the image so that a stray store cannot
 * be confused with a real access, and past the region the testbench treats as
 * RAM. It follows the riscv-tests convention: a store of `(value << 1) | 1`
 * means "passed with value", `(value << 1) | 0` means "failed with value",
 * and the testbench stops the simulation on it.
 */

OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
  RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 0x00080000
  HOST (rwx) : ORIGIN = 0x00080000, LENGTH = 0x00000010
}

SECTIONS
{
  .text : ALIGN(4)
  {
    *(.text.init)
    *(.text .text.*)
  } > RAM

  .rodata : ALIGN(4)
  {
    *(.rodata .rodata.*)
    *(.srodata .srodata.*)
  } > RAM

  .data : ALIGN(4)
  {
    _sdata = .;
    *(.data .data.*)
    *(.sdata .sdata.*)
    . = ALIGN(4);
    _edata = .;
  } > RAM
  _sidata = LOADADDR(.data);

  .bss (NOLOAD) : ALIGN(4)
  {
    _sbss = .;
    *(.sbss .sbss.*)
    *(.bss .bss.*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
  } > RAM

  . = ALIGN(16);
  . = . + 0x2000;              /* 8 KB of stack */
  _stack_top = .;

  _end = .;

  __global_pointer$ = . + 0x800;

  /* The end-of-test signal. Its address is what the testbench watches; the
     value is the riscv-tests pass/fail encoding.

     Deliberately *not* a section. Inside a `.tohost` output section the linker
     gives the symbol the section's address rather than the literal written,
     which silently relocated it to 0x100000 - and the core sat in its
     post-test spin loop while the testbench watched a different address and
     reported that the program "never finished". Defining it absolutely keeps
     the address the single value written here. */
  PROVIDE(tohost_symbol   = 0x00080000);
  PROVIDE(fromhost_symbol = 0x00080004);

  /DISCARD/ : { *(.comment) *(.note.*) *(.eh_frame) *(.riscv.attributes) }
}