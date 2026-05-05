#include <bibleit/bidx.h>
#include <bibleit/translation.h>
#include <stdio.h>
#include <errno.h>

static void test_header(const char* txt) {
    printf("===================================\n");
    printf("%s\n", txt);
    printf("===================================\n");
}

static void print_verse(const bt_file* ft, uint32_t offset) {
    bt_record_view v;

    if (bt_read_view(ft, offset, &v) == BT_OK) {
        printf("(offset %u) %.*s\n", offset, (int)v.len, v.ptr);
    } else {
        fprintf(stderr, "bt_read_view failed at offset %u\n", offset);
    }
}

static void single_ref(const bidx_file* f, const bt_file* ft)
{
    test_header("example simple lookup: Genesis 1:1");

    uint32_t offset;
    if (bidx_read(f, (bidx_ref){1, 1, 1}, &offset) == BIDX_LOOKUP_OK) {
        print_verse(ft, offset);
    }
}

static void iter_range(const bidx_file* f, const bt_file* ft) {
    test_header("example cursor: Psalms 119:1-5");

    bidx_iter it;
    if (bidx_iter_init(&it, f, (bidx_ref){19, 119, 1}) != BIDX_OK)
        return;

    bidx_record_view v;
    for (int i = 0; i < 5; ++i) {
        if (bidx_iter_next(&it, &v) != BIDX_ITER_YIELD)
            break;

        print_verse(ft, bidx_view_offset(v));
    }
}

static void iter_range_reverse(const bidx_file* f, const bt_file* ft) {
    test_header("example cursor reverse: Psalms 119:5-1");

    bidx_iter it;
    if (bidx_iter_init(&it, f, (bidx_ref){19, 119, 5}) != BIDX_OK)
        return;

    bidx_record_view v;
    for (int i = 0; i < 5; ++i) {
        if (bidx_iter_previous(&it, &v) != BIDX_ITER_YIELD)
            break;

        print_verse(ft, bidx_view_offset(v));
    }
}

static void iter_from(const bidx_file* f, const bt_file* ft) {
    test_header("example cursor from: Psalms 119:1 + 2 verses");

    bidx_iter it;
    if (bidx_iter_init(&it, f, (bidx_ref){19, 119, 1}) == BIDX_OK) {
        bidx_record_view v;
        for (int i = 0; i < 3; i++) {
            if (bidx_iter_next(&it, &v) == BIDX_ITER_YIELD) {
                print_verse(ft, bidx_view_offset(v));
            }
        }
    }
}

static void invalid_ref(const bidx_file* f) {
    test_header("invalid simple lookup: Genesis 100:1");

    uint32_t offset;
    switch(bidx_read(f, (bidx_ref){1, 100, 1}, &offset)) {
        case BIDX_LOOKUP_OK:
            printf("lookup found: %u\n", offset);
            break;
        case BIDX_LOOKUP_ERR:
            printf("lookup error\n");
            break;
        case BIDX_LOOKUP_NOTFOUND:
            printf("lookup not found\n");
            break;
        default:
            printf("wrong lookup code\n");
    }
}

static void iter_book(const bidx_file* f, const bt_file* ft) {
    test_header("example cursor book: Obadiah");

    bidx_iter it;
    if (bidx_iter_init_book(&it, f, 31) != BIDX_OK)
        return;

    bidx_record_view v;
    while (bidx_iter_next(&it, &v) == BIDX_ITER_YIELD) {
        if (bidx_view_book(v) != 31)
            break;  // manual stop

        print_verse(ft, bidx_view_offset(v));
    }
}

static void iter_chapter(const bidx_file* f, const bt_file* ft) {
    test_header("example cursor chapter: Psalms 23");

    bidx_iter it;
    if (bidx_iter_init_chapter(&it, f, 19, 23) != BIDX_OK)
        return;

    bidx_record_view v;
    while (bidx_iter_next(&it, &v) == BIDX_ITER_YIELD) {
        if (bidx_view_book(v) != 19 || bidx_view_chapter(v) != 23)
            break;  // manual stop

        print_verse(ft, bidx_view_offset(v));
    }
}

int main(void) {
    const char* bidx_path = "build/KJV.bidx";
    const char* translation_path = "build/KJV.bt";

    bidx_file* f = bidx_open(bidx_path);
    if (!f) {
        if (errno != ENOENT) {
            fprintf(stderr, "failed to open index %s\n", bidx_path);
            return -1;
        }
        if (bidx_create(bidx_path, translation_path) != BIDX_CREATE_OK) {
            fprintf(stderr, "error: failed to create bidx file\n");
            return -1;
        }
        f = bidx_open(bidx_path);
    }

    bt_file* ft = bt_open(translation_path);

    single_ref(f, ft);
    iter_range(f, ft);
    iter_range_reverse(f, ft);
    iter_book(f, ft);
    iter_chapter(f, ft);
    iter_from(f, ft);
    invalid_ref(f);

    test_header("bidx dump file");
    bidx_dump(f, stdout, 0);

    bidx_close(f);
    bt_close(ft);

    return 0;
}