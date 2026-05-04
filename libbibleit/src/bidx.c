#include "bibleit/utils.h"
#include "bibleit/bidx.h"

#include <sys/mman.h>
#include <sys/stat.h>
#include <ctype.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#include <inttypes.h>
#include <fcntl.h>
#include <unistd.h>

enum {
    BIDX_MAX_BOOKS = 84,
    BIDX_MAX_CHAPTERS = 152,
    BIDX_HEADER_SIZE = 5,
    BIDX_RECORD_SIZE = 7,
    BIDX_MAX_BUF_SIZE = 4096,

    BIDX_OFF_BOOK    = 0,
    BIDX_OFF_CHAPTER = 1,
    BIDX_OFF_VERSE   = 2,
    BIDX_OFF_OFFSET  = 3,
    BIDX_SIZE_OFFSET = 4
};

struct bidx_file {
    int fd;
    uint8_t* data;
    size_t size;

    const uint8_t* records_base;
    const uint8_t* records_end;
    
    size_t  count;
    uint8_t version;

    size_t start_index[BIDX_MAX_BOOKS + 1][BIDX_MAX_CHAPTERS + 1];
    size_t verse_count[BIDX_MAX_BOOKS + 1][BIDX_MAX_CHAPTERS + 1];
    size_t max_chapter[BIDX_MAX_BOOKS + 1];
};

uint8_t bidx_view_book(bidx_record_view v) {
    return v.ptr[0];
}

uint8_t bidx_view_chapter(bidx_record_view v) {
    return v.ptr[1];
}

uint8_t bidx_view_verse(bidx_record_view v) {
    return v.ptr[2];
}

uint32_t bidx_view_offset(bidx_record_view v) {
    uint32_t x;
    memcpy(&x, v.ptr + BIDX_OFF_OFFSET, BIDX_SIZE_OFFSET);
    return x;
}

static inline bool bidx_get_view(const bidx_file* f,
                                size_t index,
                                bidx_record_view* v)
{
    if (!f || !v) return false;

    const uint8_t* p = f->records_base + index * BIDX_RECORD_SIZE;

    if (p + BIDX_RECORD_SIZE > f->records_end)
        return false;

    v->ptr = p;
    return true;
}

static void bidx_error(bidx_file* f, const char* msg) {
    if (!f) return;
    fprintf(stderr, "bidx error: %s\n", msg);
}

static bool read_header(const uint8_t* data, uint8_t* v) {
    if (memcmp(data, BIDX_MAGIC, 4) != 0) return false;

    uint8_t version = data[4];
    if (version == BIDX_VERSION) {
        *v = version;
        return true;
    }
    return false;
}

static bool build_idx(bidx_file* f) {
    memset(f->max_chapter, 0, sizeof(f->max_chapter));
    memset(f->verse_count, 0, sizeof(f->verse_count));
    memset(f->start_index, 0xFF, sizeof(f->start_index));

    bidx_record_view v;
    for (size_t i = 0; i < f->count; ++i) {
        if (!bidx_get_view(f, i, &v)) return false;

        uint8_t book    = bidx_view_book(v);
        uint8_t chapter = bidx_view_chapter(v);

        if (book == 0 || book > BIDX_MAX_BOOKS) return false;
        if (chapter == 0 || chapter > BIDX_MAX_CHAPTERS) return false;

        if (f->start_index[book][chapter] == SIZE_MAX) {
            f->start_index[book][chapter] = i;
            if (chapter > f->max_chapter[book])
                f->max_chapter[book] = chapter;
        }

        f->verse_count[book][chapter]++;
    }
    return true;
}

void bidx_close(bidx_file* f) {
    if (!f) return;
    if (f->data) munmap(f->data, f->size);
    if (f->fd >= 0) close(f->fd);
    free(f);
}

bidx_file* bidx_open(const char* path) {
    if (!path) return NULL;

    int fd = open(path, O_RDONLY);
    if (fd < 0) return NULL;

    struct stat st;
    if (fstat(fd, &st) != 0) {
        close(fd);
        return NULL;
    }

    uint8_t* data = mmap(NULL, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (data == MAP_FAILED) {
        close(fd);
        return NULL;
    }

    bidx_file *f = calloc(1, sizeof(*f));
    if (!f) {
        munmap(data, st.st_size);
        close(fd);
        return NULL;
    }

    f->fd = fd;
    f->data = data;
    f->size = st.st_size;

    if (f->size < BIDX_HEADER_SIZE) {
        bidx_error(f, "invalid file size");
        bidx_close(f);
        return NULL;
    }

    if (!read_header(f->data, &f->version)) {
        bidx_error(f, "bad bidx header");
        bidx_close(f);
        return NULL;
    }

    size_t data_size = f->size - BIDX_HEADER_SIZE;

    if (data_size % BIDX_RECORD_SIZE != 0) {
        bidx_error(f, "bad record alignment");
        bidx_close(f);
        return NULL;
    }

    f->count = data_size / BIDX_RECORD_SIZE;
    f->records_base = f->data + BIDX_HEADER_SIZE;
    f->records_end  = f->records_base + f->count * BIDX_RECORD_SIZE;

    if (!build_idx(f)) {
        bidx_error(f, "build index failed");
        bidx_close(f);
        return NULL;
    }

    return f;
}

int bidx_version(const bidx_file* f) {
    if (!f) return -1;
    return f->version; 
}

size_t bidx_count(const bidx_file* f) {
    if (!f) return -1;
    return f->count;
}

static ptrdiff_t bidx_read_index(const bidx_file* f, bidx_ref r)
{
    if (!f) return -1;
    if (r.book == 0 || r.book > BIDX_MAX_BOOKS) return BIDX_LOOKUP_ERR;
    if (r.chapter == 0 || r.chapter > f->max_chapter[r.book]) return BIDX_LOOKUP_ERR;

    size_t start = f->start_index[r.book][r.chapter];
    if (start == SIZE_MAX) return -1;

    uint16_t vcount = f->verse_count[r.book][r.chapter];
    if (r.verse == 0 || r.verse > vcount) return -1;

    size_t idx = start + ((size_t)(r.verse - 1));
    return idx;
}


bidx_lookup_rc bidx_read(const bidx_file* f, bidx_ref r, uint32_t* offset) 
{
    if (!f || !offset) return BIDX_LOOKUP_ERR;

    int idx = bidx_read_index(f, r);
    if (idx < 0) return BIDX_LOOKUP_NOTFOUND;

    bidx_record_view v;
    if (!bidx_get_view(f, idx, &v)) return BIDX_LOOKUP_NOTFOUND;

    *offset = bidx_view_offset(v);
    return BIDX_LOOKUP_OK;
}

static inline bool bidx_iter_ref_check(bidx_ref a, bidx_ref b) {
    if (a.book   != b.book)    return a.book   < b.book;
    if (a.chapter!= b.chapter) return a.chapter< b.chapter;
    return a.verse <= b.verse;
}

static ptrdiff_t bidx_iter_ref(const bidx_file* f, bidx_ref r) {
    if (!f || r.book <= 0 || r.chapter <= 0) return -1;
    size_t base = f->start_index[r.book][r.chapter];
    size_t nvs  = f->verse_count[r.book][r.chapter];
    if (base == SIZE_MAX || nvs == 0) return -1;
    if (r.verse == 0 || r.verse > nvs) return -1;
    return (ptrdiff_t)(base + (size_t)(r.verse - 1));
}

bidx_rc bidx_iter_init(bidx_iter* it, const bidx_file* f,
                       bidx_ref from, bidx_ref to)
{
    if (!it || !f || !bidx_iter_ref_check(from, to)) return BIDX_ERR;

    ptrdiff_t i0 = bidx_iter_ref(f, from);
    ptrdiff_t i1 = bidx_iter_ref(f, to);

    if (i0 < 0 || i1 < 0 || i0 > i1) return BIDX_ERR;

    it->f = f;

    it->start = f->records_base + i0 * BIDX_RECORD_SIZE;
    it->end   = it->start + (size_t)(i1 - i0 + 1) * BIDX_RECORD_SIZE;

    it->ptr = it->start;

    return BIDX_OK;
}

bidx_rc bidx_iter_init_reverse(bidx_iter* it, const bidx_file* f,
                               bidx_ref from, bidx_ref to)
{
    if (bidx_iter_init(it, f, from, to) != BIDX_OK) return BIDX_ERR;

    it->ptr = it->end;
    return BIDX_OK;
}

bidx_iter_rc bidx_iter_previous(bidx_iter* it, bidx_record_view* v) {
    if (!it || !v || !it->f) return BIDX_ITER_ERROR;
    if (it->ptr <= it->start) return BIDX_ITER_DONE;

    it->ptr -= BIDX_RECORD_SIZE;
    v->ptr = it->ptr;

    return BIDX_ITER_YIELD;
}

bidx_iter_rc bidx_iter_next(bidx_iter* it, bidx_record_view* v) {
    if (!it || !v || !it->f) return BIDX_ITER_ERROR;
    if (it->ptr >= it->end) return BIDX_ITER_DONE;

    v->ptr = it->ptr;
    it->ptr += BIDX_RECORD_SIZE;

    return BIDX_ITER_YIELD;
}

bidx_rc bidx_iter_init_book(bidx_iter* it, const bidx_file* f, uint8_t book) {
    if (!it || !f || book == 0) return BIDX_ERR;

    size_t first = 0, last = f->max_chapter[book];
    if (last == 0) return BIDX_ERR;

    for (size_t ch = 1; ch <= last; ++ch) {
        if (f->start_index[book][ch] != SIZE_MAX) { 
            first = ch; 
            break; 
        }
    }
    if (first == 0) return BIDX_ERR;

    bidx_ref from = { book, first, 1 };
    bidx_ref to   = { book, last, f->verse_count[book][last] };

    return bidx_iter_init(it, f, from, to);
}

bidx_rc bidx_iter_init_chapter(bidx_iter* it, const bidx_file* f, uint8_t book, uint8_t chapter) {
    if (!it || !f || book == 0 || chapter == 0) return BIDX_ERR;

    size_t base = f->start_index[book][chapter];
    size_t nvs  = f->verse_count[book][chapter];
    if (base == SIZE_MAX || nvs == 0) return BIDX_ERR;

    bidx_ref from = { book, chapter, 1 };
    bidx_ref to   = { book, chapter, (uint8_t)nvs };

    return bidx_iter_init(it, f, from, to);
}

bidx_rc bidx_iter_init_from(bidx_iter* it, const bidx_file* f, bidx_ref from) {
    if (!it || !f) return BIDX_ERR;

    ptrdiff_t index = bidx_iter_ref(f, from);
    if (index < 0) return BIDX_ERR;

    it->f = f;

    it->start = f->records_base + (size_t)index * BIDX_RECORD_SIZE;
    it->end   = f->records_end;
    it->ptr = it->start;

    return BIDX_OK;
}

static bool parse_chapter_verse(const char* buf, size_t len, bidx_record *r)
{
    if (len && buf[len-1] == '\n') len--;

    const char* start = buf;
    const char* end   = buf + len;
    const char* colon = memchr(start, ':', (size_t)(end - start));
    if (!colon) return false;

    const char* p = colon + 1;
    while (p < end && isspace((unsigned char)*p)) p++;
    if (p == end || !isdigit((unsigned char)*p)) return false;

    unsigned long v = 0;
    while (p < end && isdigit((unsigned char)*p)) {
        v = v * 10 + (unsigned)(*p - '0');
        if (v > 255UL) return false;
        p++;
    }

    const char* q = colon;
    while (q > start && isspace((unsigned char)q[-1])) q--;
    const char* chap_end = q;
    while (q > start && isdigit((unsigned char)q[-1])) q--;
    if (q == chap_end) return false;
    if (q == start || !isspace((unsigned char)q[-1])) return false;

    unsigned long c = 0;
    const char* t = q;
    while (t < chap_end) {
        if (!isdigit((unsigned char)*t)) return false;
        c = c * 10 + (unsigned)(*t - '0');
        if (c > 255UL) return false;
        t++;
    }

    r->ref.chapter = (uint8_t)c;
    r->ref.verse   = (uint8_t)v;
    return true;
}

bidx_create_rc bidx_create(const char* bidx_path, const char* translation_path) {
    if (!bidx_path || !translation_path) return BIDX_CREATE_ERR;

    int fd = open(bidx_path, O_CREAT | O_EXCL | O_WRONLY, 0644);
    if (fd < 0) {
        if (errno == EEXIST) {
            return BIDX_CREATE_EXISTS;
        }
        perror("error opening bidx file");
        return BIDX_CREATE_ERR;
    }
    
    FILE* out = fdopen(fd, "wb");
    if (!out) { 
        fprintf(stderr, "error: failed to open bidx file: %s\n", bidx_path);
        return BIDX_CREATE_ERR; 
    }

    FILE* in  = fopen(translation_path, "rb");
    if (!in) {
        fprintf(stderr, "error: failed to open translation file: %s\n", translation_path);
        fclose(out);
        return BIDX_CREATE_ERR;
    }

    if (fwrite(BIDX_MAGIC, 1, 4, out) != 4) {
        fprintf(stderr, "error on parsing bidx magic\n");
        fclose(out);
        fclose(in);
        return BIDX_CREATE_ERR;
    }
    
    uint8_t version = (uint8_t)BIDX_VERSION;
    if (fwrite(&version, 1, 1, out) != 1) {
        fprintf(stderr, "error on parsing bidx version\n");
        fclose(out);
        fclose(in);
        return BIDX_CREATE_ERR;
    }

    char buf[BIDX_MAX_BUF_SIZE];
    size_t count = 0;
    uint8_t book_id = 1;

    while (true) {
        long offset = ftell(in);
        if (offset < 0) { 
            fprintf(stderr, "error: negative offset %ld\n", offset);
            fclose(out); 
            fclose(in); 
            return BIDX_CREATE_ERR; 
        }

        if (!fgets(buf, sizeof buf, in)) break;

        size_t n = strlen(buf);
        int complete = (n > 0 && buf[n-1] == '\n');
        if (!complete) discard_until_newline(in);

        bidx_record r;
        r.ref.book = book_id;
        r.offset   = (uint32_t)offset;
        if (!parse_chapter_verse(buf, n, &r)) {
            fprintf(stderr, "parse line error @%ld: %s\n", offset, buf);
            fclose(out);
            fclose(in);
            return BIDX_CREATE_PARSE_ERR;
        }

        if (count > 0 && r.ref.chapter == 1 && r.ref.verse == 1) {
            if (book_id < BIDX_MAX_BOOKS) book_id++;
            r.ref.book = book_id;
        }

        if (fputc(r.ref.book, out) == EOF) {
            fprintf(stderr, "error on writting book: %hhu\n", r.ref.book);
            fclose(out); 
            fclose(in); 
            return BIDX_CREATE_ERR; 
        }
        if (fputc(r.ref.chapter, out) == EOF) {
            fprintf(stderr, "error on writting chapter: %hhu\n", r.ref.chapter);
            fclose(out); 
            fclose(in); 
            return BIDX_CREATE_ERR;
        }
        if (fputc(r.ref.verse, out) == EOF) {
            fprintf(stderr, "error on writting verse: %hhu\n", r.ref.verse);
            fclose(out); 
            fclose(in); 
            return BIDX_CREATE_ERR; 
        }
        if (fwrite(&r.offset, 1, 4, out) != 4)   {
            fprintf(stderr, "error on writting offset: %" PRIu32 "\n", r.offset);
            fclose(out); 
            fclose(in); 
            return BIDX_CREATE_ERR; 
        }

        count++;
    }

    fclose(out);
    fclose(in);
    return BIDX_CREATE_OK;
}

bidx_rc bidx_dump(const bidx_file* f, FILE* out, size_t limit) {
    if (!f || !out) return BIDX_ERR;

    const size_t total = bidx_count(f);
    size_t ttotal = (limit == 0 || limit > total) ? total : limit;

    fprintf(out, "Magic   : %s\n", "BIDX");
    fprintf(out, "Version : %d\n", bidx_version(f));
    fprintf(out, "Records : %zu\n", total);
    fprintf(out, "BOOK CHAP VERSE     OFFSET\n");

    bidx_record_view v;
    for (size_t i = 0; i < ttotal; ++i) {
        if (!bidx_get_view(f, i, &v)) return -1;

        fprintf(out, "%3u %4u %5u %10" PRIu32 "\n",
                (unsigned)bidx_view_book(v),
                (unsigned)bidx_view_chapter(v),
                (unsigned)bidx_view_verse(v),
                bidx_view_offset(v));
    }
    return BIDX_OK;
}
