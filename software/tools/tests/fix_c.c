#include <stdint.h>

#define NOINLINE __attribute__((noinline))

extern int b_add(int a, int b);

const uint32_t c_table[8] = {0x11111111, 0x22222222, 0x33333333, 0x44444444,
                             0x55555555, 0x66666666, 0x77777777, 0x88888888};
volatile uint32_t c_counter;
uint32_t c_state = 0x600DF00D;

NOINLINE int c_use(int x)
{
    int v = b_add(x, (int)c_state);
    c_state = c_state * 1103515245u + 12345u;
    return v + (int)(c_state >> 16);
}

NOINLINE int c_dup(int x)
{
    int acc = 0x1111;
    for (int i = 0; i < 6; i++)
        acc = (acc << 1) ^ (x + i * 3);
    return acc & 0x7FFF;
}

__attribute__((section(".ramfunc.c_ramfn"))) NOINLINE int c_ramfn(int x)
{
    uint32_t v = (uint32_t)x * 0x01000193u;
    v ^= c_state;
    v = (v >> 9) | (v << 23);
    return (int)(v + 0x2BAD);
}
