#include <stdint.h>

#define NOINLINE __attribute__((noinline))

#ifdef MUTATE
#define K1 0x12345679
#else
#define K1 0x12345678
#endif
#define K2 0x00ABCDEF

NOINLINE int b_add(int a, int b)
{
    int s = a + b;
    s = s * 31 + K2;
    s ^= (s >> 7);
    return s * 3 + 1;
}

NOINLINE int b_mul(int a, int b)
{
    int p = a * b;
    p = (p << 2) ^ 0x7654;
    p += (p >> 3) * 5;
    return p - 0x1F;
}

NOINLINE int b_const_fn(int x)
{
    x = x * 0x9E37 + K1;
    x ^= x >> 13;
    x = x * 0x5BD1;
    return x ^ (x >> 16);
}

NOINLINE int b_dup(int x)
{
    int acc = 0x1111;
    for (int i = 0; i < 6; i++)
        acc = (acc << 1) ^ (x + i * 3);
    return acc & 0x7FFF;
}
