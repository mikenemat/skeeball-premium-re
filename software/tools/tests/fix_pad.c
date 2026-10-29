#define NOINLINE __attribute__((noinline))

/* Kept alive with -Wl,-u,pad_fn; linked between fix_a and fix_b to shift everything after it. */
NOINLINE int pad_fn(int x)
{
    int acc = 0x2222;
    for (int i = 0; i < 9; i++)
        acc = (acc * 5) ^ (x - i * 7) ^ 0x0F0F;
    return acc + 0x3333;
}
