/* crt0.S - reset entry for bare-metal execution on the phase 1 core.
 *
 * Phase 1 has no privilege modes, no traps and no wait states, so there is
 * nothing to set up beyond the C runtime's data segment: set up `sp`, copy
 * `.data` from its load address, zero `.bss`, call `main`, and report the
 * result. The final loop is a plain `j .` spin - deliberately not `wfi`,
 * which needs privileged mode the core does not have.
 */

    .section .text.init, "ax"
    .globl  _start
    .type   _start, @function

_start:
    /* gp is needed for the small-data addressing the compiler assumes. */
    .option push
    .option norelax
    la      gp, __global_pointer$
    .option pop

    la      sp, _stack_top

    /* Copy .data from its load address to its run address. With no `AT>` the
       two are equal and this is a no-op, but going through LOADADDR keeps it
       correct if the layout ever stops that way. */
    la      t0, _sdata
    la      t1, _edata
    la      t2, _sidata
1:
    bgeu    t0, t1, 2f
    lw      t3, 0(t2)
    sw      t3, 0(t0)
    addi    t0, t0, 4
    addi    t2, t2, 4
    j       1b
2:
    /* Zero .bss. */
    la      t0, _sbss
    la      t1, _ebss
3:
    sw      zero, 0(t0)
    addi    t0, t0, 4
    bltu    t0, t1, 3b

    call    main

    /* Report through `tohost`: bit 0 set means pass, the rest is the value.
     * The store itself is what ends the simulation. */
    la      t0, tohost_symbol
    slli    t1, a0, 1
    ori     t1, t1, 1
    sw      t1, 0(t0)

    /* Reached only if the testbench has not stopped on the write. */
4:  j       4b

    .size   _start, . - _start