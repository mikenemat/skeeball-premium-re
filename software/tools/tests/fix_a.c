#include <stdint.h>

#define NOINLINE __attribute__((noinline))

extern int b_add(int a, int b);
extern int b_mul(int a, int b);
extern int b_const_fn(int x);
extern int b_dup(int x);
extern int c_use(int x);
extern int c_dup(int x);
extern int c_ramfn(int x);
extern const uint32_t c_table[8];
extern volatile uint32_t c_counter;

NOINLINE int a_caller(int x)
{
    return b_add(x, 3) * b_mul(x, 5) + 7;
}

NOINLINE int a_table_sum(int n)
{
    int s = 0;
    for (int i = 0; i < n && i < 8; i++)
        s += c_table[i] * (i + 1);
    c_counter += s;
    return s;
}

NOINLINE int a_local_only(int x)
{
    x ^= 0x5A5A5A5A;
    x = (x << 3) | ((unsigned)x >> 29);
    x += 0x1234;
    x *= 7;
    return x ^ (x >> 5);
}

NOINLINE int a_tiny(int x)
{
    return x + 1;
}

void _start(void)
{
    volatile int r = 0;
    r += a_caller(1);
    r += a_table_sum(4);
    r += a_local_only(9);
    r += a_tiny(2);
    r += b_const_fn(3);
    r += b_dup(4);
    r += c_use(5);
    r += c_dup(6);
    r += c_ramfn(7);
    for (;;)
        ;
}
