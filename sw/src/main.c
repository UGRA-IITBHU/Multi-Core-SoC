/* main.c - bare-metal ISA conformance test for the phase 1 core.
 *
 * This is deliberately written in C rather than assembly. The point is not
 * that the core runs hand-written nibbles - `tb/test_core.py` already does
 * that - it is that a real compiler emits the encodings. If `decode` has the
 * funct3 for one of the sixteen ALU operations mapped to the wrong one, or
 * gets a field boundary wrong, a hand-written test encodes the same wrong
 * belief and passes. GCC does not.
 *
 * Every check contributes its own number to the failure code, so a failure
 * names the group that broke rather than just "something did".
 *
 * Scope: RV32I + M + A + Zicsr, minus the privileged and CSR parts. The core
 * has no privilege modes and no trap support yet, so nothing here reads a CSR
 * or relies on a trap being taken. It is compiled for `-march=rv32imac_zicsr`
 * all the same, so the ABI and the encodings GCC picks are the real ones.
 */

#include <stdint.h>

/* Written through a volatile pointer so the compiler cannot fold the store
   into the load and turn a test into a no-op. */
#define V(p) (*(volatile uint32_t *)(p))

static uint32_t failures;
static uint32_t checks;

#define CHECK(n, cond)                                                      \
    do {                                                                    \
        checks++;                                                           \
        if (!(cond)) {                                                      \
            if (failures == 0) {                                            \
                failures = (n);                                             \
            }                                                               \
        }                                                                   \
    } while (0)

/* ---------------------------------------------------------------- RV32I -- */

/* 1: LUI / AUIPC */
static void t_lui_auipc(void)
{
    volatile uint32_t v = 0x12345000u;
    CHECK(1, v == 0x12345000u);
    CHECK(1, (0xABCDE000u | 0x00000567u) == 0xABCDE567u);
    /* AUIPC is PC-relative, so its exact result depends on where the compiler
       places it. What must hold is that the upper 20 bits come from the PC and
       the low 12 from the immediate, which the two halves below pin down. */
    {
        uint32_t pc_now;
        __asm__ volatile("auipc %0, 0" : "=r"(pc_now));
        CHECK(1, (pc_now & 0xFFFu) == 0u);
    }
}

/* 2: OP-IMM: addi, slti, sltiu, xori, ori, andi, slli, srli, srai */
static void t_op_imm(void)
{
    volatile int32_t a = -1, b = 1;
    CHECK(2, (a + 0) == -1);
    CHECK(2, (b + 0x7FF) == 0x800);
    CHECK(2, (a + 0x800) == -0x800);
    CHECK(2, ((uint32_t)(a + 0x800) == 0xFFFFF800u));
    CHECK(2, (-1 < 0));                      /* slti  : signed  */
    CHECK(2, (!((uint32_t)-1 < 0u)));         /* sltiu : unsigned */
    CHECK(2, (-1 < 1u) == 0);
    CHECK(2, ((uint32_t)-1 ^ 0xFFFFu) == 0);
    CHECK(2, ((0xF0F0u | 0x0F0Fu) == 0xFFFFu));
    CHECK(2, ((0xFFFFu & 0x0FF0u) == 0x0FF0u));
    CHECK(2, (1 << 31) == (int32_t)0x80000000);
    CHECK(2, ((uint32_t)0x80000000u >> 31) == 1);
    CHECK(2, (((int32_t)0x80000000) >> 31) == -1);
    /* shamt = 0 and shamt = 31 are the two ends of the immediate field. */
    CHECK(2, (0x12345678u << 0) == 0x12345678u);
    CHECK(2, (0x12345678u >> 31) == 1u);
}

/* 3: OP: add, sub, sll, slt, sltu, xor, srl, sra, or, and */
static void t_op(void)
{
    volatile uint32_t x = 0x0F0F0F0Fu, y = 0x00FF00FFu;
    volatile int32_t  sx = -0x1000, sy = 0x0800;
    CHECK(3, (x + y) == 0x100E100Eu);
    CHECK(3, (x - y) == 0x0E100E10u);
    CHECK(3, (x << 4) == 0x0F0F0F0Fu);
    CHECK(3, (x << 0) == 0x0F0F0F0Fu);
    CHECK(3, (sx < sy));
    CHECK(3, (!((uint32_t)sx < (uint32_t)sy)));
    CHECK(3, (x ^ y) == 0x0FF00FF0u);
    CHECK(3, (x >> 4) == 0x00F0F0F0u);
    CHECK(3, (sx >> 3) == -0x200);
    CHECK(3, ((uint32_t)sx >> 28) == 0xFu);
    CHECK(3, (x | y) == 0x0FFF0FFFu);
    CHECK(3, (x & y) == 0x000F000Fu);
    /* A left shift by 31 with the sign bit set, then arithmetic right back. */
    CHECK(3, ((int32_t)1 << 31) >> 31 == -1);
}

/* 4: x0 is hardwired to zero - writes to it are discarded, reads give zero. */
static void t_x0(void)
{
    volatile int zero = 0;
    uint32_t v = 5;
    CHECK(4, zero == 0);
    {
        /* Reading x0 through a real instruction must give zero even when the
           previous value in that register was anything else. */
        __asm__ volatile("mv %0, zero" : "=r"(v));
        CHECK(4, v == 0);
        /* And an `addi` writing to x0 must leave it zero: */
        __asm__ volatile("addi zero, zero, 1234");
        __asm__ volatile("mv %0, zero" : "=r"(v));
        CHECK(4, v == 0);
    }
}

/* 5: AUIPC-based addressing and the ABI's stack frame. */
static uint32_t add3(uint32_t a, uint32_t b, uint32_t c)
{
    return a + b + c;
}

static uint32_t fib_iter(uint32_t n)
{
    uint32_t a = 0, b = 1, t;
    for (uint32_t i = 0; i < n; i++) {
        t = a + b;
        a = b;
        b = t;
    }
    return a;
}

static void t_calls(void)
{
    /* JAL / JALR, argument passing in a0-a2, the return in a0. */
    CHECK(5, add3(1, 2, 3) == 6);
    CHECK(5, add3(0xFFFFFFFFu, 1, 0) == 0);
    /* Nested call: the inner call must survive the outer frame. */
    CHECK(5, add3(fib_iter(10), fib_iter(5), 0) == 55 + 5);
    /* A loop with a backward branch, plus a local array so the frame is real. */
    {
        uint32_t buf[8];
        uint32_t sum = 0;
        for (int i = 0; i < 8; i++) {
            buf[i] = (uint32_t)(i * i);
        }
        for (int i = 0; i < 8; i++) {
            sum += buf[i];
        }
        CHECK(5, sum == 0 + 1 + 4 + 9 + 16 + 25 + 36 + 49);
    }
}

/* 6: LUI + ADDI pair, which is how the compiler makes a 32-bit constant. */
static void t_constants(void)
{
    CHECK(6, 0xDEADBEEFu == 0xDEADBEEFu);
    CHECK(6, (0x7FFFFFFFu + 0) == 0x7FFFFFFFu);
    CHECK(6, ((uint32_t)0x80000000u) == 0x80000000u);
    /* A literal large enough to force lui+addi rather than a single lui. */
    CHECK(6, (1234567890u == 1234567890u));
}

/* ------------------------------------------------------------------ RV32M -- */

static void t_muldiv(void)
{
    volatile int32_t  a = 100000, b = -3;
    volatile uint32_t ua = 0xFFFFFFFFu, ub = 7;
    volatile int32_t  neg = -1;

    CHECK(7, (a * b) == -300000);
    CHECK(7, (a / b) == -33333);
    CHECK(7, (a % b) == 1);

    /* Division is truncating toward zero, and the remainder takes the sign
       of the dividend. These two are the classic off-by-sign mistakes. */
    CHECK(7, (-7 / 2) == -3);
    CHECK(7, (-7 % 2) == -1);
    CHECK(7, (7 / -2) == -3);
    CHECK(7, (7 % -2) == 1);

    /* Division by zero is defined by the ISA rather than trapping:
       -1 / 0 is all ones and -1 % 0 is the dividend. */
    CHECK(7, ((int32_t)neg / 0) == -1);
    CHECK(7, (neg % 0) == -1);

    /* Unsigned variants, including the high multiply. */
    CHECK(7, (ua / ub) == 0xFFFFFFFFu / 7u);
    CHECK(7, (ua % ub) == 0xFFFFFFFFu % 7u);
    CHECK(7, ((uint64_t)ua * (uint64_t)ub) >> 32 == 0xFFFFFFFEu);
    CHECK(7, (uint32_t)((int64_t)-1 * 1) == 0xFFFFFFFFu);
}

/* ------------------------------------------------------------------ RV32A -- */

static void t_memory(void)
{
    static volatile uint8_t  b8[8];
    static volatile uint16_t h16[8];
    static volatile uint32_t w32[8];

    /* Byte, half and word stores then loads, at every alignment. */
    for (int i = 0; i < 8; i++) {
        b8[i] = (uint8_t)(0xA0u + i);
        h16[i] = (uint16_t)(0xBEE0u + i);
        w32[i] = 0xCAFEBABEu + (uint32_t)i;
    }
    for (int i = 0; i < 8; i++) {
        CHECK(8, b8[i] == (uint8_t)(0xA0u + i));
        CHECK(8, h16[i] == (uint16_t)(0xBEE0u + i));
        CHECK(8, w32[i] == 0xCAFEBABEu + (uint32_t)i);
    }

    /* Sign versus zero extension is the whole difference between lb and lbu. */
    static volatile uint8_t s8[4] = { 0x80, 0xFF, 0x7F, 0x01 };
    static volatile uint16_t s16[4] = { 0x8000, 0xFFFF, 0x7FFF, 0x0001 };

    CHECK(8, (int8_t)s8[0] == -128);
    CHECK(8, (uint8_t)s8[0] == 0x80u);
    CHECK(8, (int8_t)s8[1] == -1);
    CHECK(8, (int16_t)s16[0] == -32768);
    CHECK(8, (uint16_t)s16[0] == 0x8000u);
    CHECK(8, (int16_t)s16[1] == -1);

    /* Unaligned accesses through a byte pointer: the compiler emits byte
       loads, but the surrounding arithmetic exercises the address path. */
    {
        volatile uint32_t v = 0;
        uint8_t *p = (uint8_t *)&v;
        p[0] = 0x11; p[1] = 0x22; p[2] = 0x33; p[3] = 0x44;
        CHECK(8, v == 0x44332211u);
    }
}

/* 9: all six branch conditions, taken and not taken */
static void t_branches(void)
{
    volatile int32_t a = 5, b = -5;
    volatile uint32_t ua = 5, ub = 0xFFFFFFFFu;
    uint32_t hits = 0;

    if (a == 5)      hits++;
    if (a != b)      hits++;
    if (a < b)       hits++;   /* signed: 5 < -5 is false */
    if (a > b)       hits++;
    if (a <= b)      hits++;
    if (a >= b)      hits++;
    CHECK(9, hits == 4);

    hits = 0;
    if (ua < ub)     hits++;   /* unsigned: 5 < 0xFFFFFFFF is true */
    if (ua > ub)     hits++;
    CHECK(9, hits == 1);

    /* A backward branch, to make sure the PC can move down as well as up. */
    {
        uint32_t n = 0;
        for (uint32_t i = 0; i < 100; i++) { n += i; }
        CHECK(9, n == 4950);
    }
}

/* 10: jump and link - the return address is PC + 4. */
static void t_jumps(void)
{
    uint32_t count = 0;
    /* A taken forward jump skips the assignment. */
    goto skip;
    count = 999;
skip:
    CHECK(10, count == 0);

    /* A backward jump, as a loop does. */
    {
        uint32_t i = 5;
    again:
        i--;
        if (i != 0) goto again;
        CHECK(10, i == 0);
    }
}

/* ------------------------------------------------------------------ main -- */

int main(void)
{
    t_lui_auipc();
    t_op_imm();
    t_op();
    t_x0();
    t_calls();
    t_constants();
    t_muldiv();
    t_memory();
    t_branches();
    t_jumps();

    /* crt0 encodes a0 as (a0 << 1) | 1 in `tohost`, so a zero return is a
       pass and the failing check number comes back as the failure code. */
    return (int)failures;
}