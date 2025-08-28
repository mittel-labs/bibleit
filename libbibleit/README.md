# libbibleit

`libbibleit` is a small C library for indexing and reading Bible translations.

It generates a compact `.bidx` index file (≈ 7 bytes per verse) that maps each `(book, chapter, verse)` reference to a byte offset in a plain text translation file. This makes random access to any verse O(1).

The library exposes a C API for:

- **Creating** `.bidx` files from plain text translations.
- **Opening** and validating existing indexes.
- **Looking up** single verses by reference.
- **Iterating** over ranges, chapters, or entire books.
- **Reading** verse text lines from the translation file.

## Features

- NO external dependencies, all required libraries are included into libbibleit
- Zero allocations during iteration.
- Struct-of-Arrays index for cache-friendly lookups.
- Works with any translation text file where verses are line-separated.
- Free and open source

## How to build

```bash
make
```

This produces:

- `libbibleit.a` (static library)
- `libbibleit.so` or `libbibleit.dylib` (shared library, platform-specific)

## File formats

### Translation file

A plain text file with one verse per line, e.g.:

```txt
Genesis 1:1 In the beginning God created the heavens and the earth.
Genesis 1:2 Now the earth was formless and empty
...
```

### Index file (.bidx)

Header (5 bytes) + one record per verse (7 bytes each)

```txt
"BIDX" + version byte (numeric, e.g. 0x01)
book (1) | chapter (1) | verse (1) | offset (4)
book (1) | chapter (1) | verse (2) | offset (4)
...
```

## Basic example

This is a basic example for a program using bibleit in order to use existing translation files:

```c
#include <bibleit/bidx.h>
#include <bibleit/translation.h>
#include <stdio.h>

int main(void) {
    const char* idx = "bibleit.bidx";
    const char* txt = "../translations/niv";

    /* Create index (if missing) */
    if (bidx_create(idx, txt) == BIDX_CREATE_OK) {
        printf("Index created.\n");
    }

    /* Open index */
    bidx_file* f = bidx_open(idx);
    if (!f) { perror("bidx_open"); return 1; }

    /* Open translation text */
    bt_file* ft = bt_open(txt);

    /* Single lookup: Genesis 1:1 */
    bidx_ref ref = {
        .book    = 1,
        .chapter = 1,
        .verse  = 1
    };

    uint32_t off;
    if (bidx_read(f, ref, &off) == BIDX_LOOKUP_OK) {
        char buf[1024];
        if (bt_read(ft, off, buf, sizeof buf) == BT_OK) {
            printf("Genesis 1:1 -> %s\n", buf);
        }
    }

    /* Iterate over Psalms 23 */
    bidx_iter it;
    if (bidx_iter_init_chapter(&it, f, 19, 23) == BIDX_OK) {
        bidx_record rec;
        while (bidx_iter_next(&it, &rec) == BIDX_ITER_YIELD) {
            if (bidx_iter_read(&it, &off) == BIDX_OK) {
                char buf[1024];
                if (bt_read(ft, off, buf, sizeof buf) == BT_OK) {
                    printf("%u %u:%u %s\n",
                           rec.ref.book, rec.ref.chapter, rec.ref.verse, buf);
                }
            }
        }
    }

    bidx_close(f);
    bt_close(ft);
    return 0;
}

```

For more concrete examples, please check [example.c](src/example.c) file.
