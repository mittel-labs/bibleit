#include "bibleit/utils.h"
#include "bibleit/bidx.h"

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
    BIDX_MAX_BUF_SIZE = 4096
};

struct bidx_file {
    FILE*   fp;
    size_t  count;
    uint8_t version;

    size_t start_index[BIDX_MAX_BOOKS + 1][BIDX_MAX_CHAPTERS + 1];
    size_t verse_count[BIDX_MAX_BOOKS + 1][BIDX_MAX_CHAPTERS + 1];
    size_t max_chapter[BIDX_MAX_BOOKS + 1];
};

static inline bool bidx_read_record(const bidx_file* f, 
                            size_t index,
                            bidx_record* r) 
{
    if (!f || !r) return false;

    long pos = BIDX_HEADER_SIZE + (long)(index * (size_t) BIDX_RECORD_SIZE);
    if (fseek(f->fp, pos, SEEK_SET) != 0) return false;

    unsigned char bcv[3];
    if (fread(bcv, 1, 3, f->fp) != 3) return false;
    if (fread(&r->offset, 1, 4, f->fp) != 4) return false;

    r->ref.book    = bcv[0];
    r->ref.chapter = bcv[1];
    r->ref.verse   = bcv[2];

    return true;
}

static void bidx_error(bidx_file* f, const char* msg) {
    if (!f) return;
    fprintf(stderr, "bidx error: %s\n", msg);
}

static bool read_header(FILE* fp, uint8_t* v) {
    unsigned char hdr[BIDX_HEADER_SIZE];
    if (fread(hdr, 1, BIDX_HEADER_SIZE, fp) != BIDX_HEADER_SIZE) return false;
    if (memcmp(hdr, BIDX_MAGIC, 4) != 0) return false;

    unsigned char version = hdr[4];
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

    bidx_record r;
    for (size_t i = 0; i < f->count; ++i) {
        if (!bidx_read_record(f, i, &r)) return false;

        if (r.ref.book == 0 || r.ref.book > BIDX_MAX_BOOKS) return false;
        if (r.ref.chapter == 0 || r.ref.chapter > BIDX_MAX_CHAPTERS) return false;

        if (f->start_index[r.ref.book][r.ref.chapter] == SIZE_MAX) {
            f->start_index[r.ref.book][r.ref.chapter] = i;
            if (r.ref.chapter > f->max_chapter[r.ref.book]) f->max_chapter[r.ref.book] = r.ref.chapter;
        }
        f->verse_count[r.ref.book][r.ref.chapter]++;
    }
    return true;
}

void bidx_close(bidx_file* f) {
    if (!f) return;
    if (f->fp) fclose(f->fp);
    free(f);
}

bidx_file* bidx_open(const char* path) {
    if (!path) return NULL;
    
    FILE* fp = fopen(path, "rb");
    if (!fp) return NULL;

    bidx_file *f = calloc(1, sizeof(*f));
    if (!f) {
        fclose(fp);
        return NULL;
    }
    f->fp = fp;

    if (!read_header(fp, &f->version)) {
        bidx_error(f, "bad bidx header");
        bidx_close(f);
        return NULL;
    }

    if (fseek(fp, 0, SEEK_END) != 0) {
        bidx_error(f, "invalid END file pointer");
        bidx_close(f);
        return NULL;
    }

    long ffp = ftell(fp);
    if (ffp < 0 || ffp < BIDX_HEADER_SIZE) {
        bidx_error(f, "invalid file size");
        bidx_close(f);
        return NULL;
    }

    long data = ffp - BIDX_HEADER_SIZE;
    if (data % BIDX_RECORD_SIZE != 0) {
        bidx_error(f, "bad record alignment");
        bidx_close(f);
        return NULL;
    }
    f->count = ((size_t) (data / BIDX_RECORD_SIZE));

    if (fseek(fp, BIDX_HEADER_SIZE, SEEK_SET) != 0) {
        bidx_error(f, "invalid START file pointer");
        bidx_close(f);
        return NULL;
    }

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

static int bidx_read_index(const bidx_file* f, bidx_ref r)
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
    if (offset) {
        bidx_record r;
        if (!bidx_read_record(f, idx, &r)) return BIDX_LOOKUP_NOTFOUND;
        *offset = r.offset;
    }
    return BIDX_LOOKUP_OK;
}

static inline bool bidx_iter_ref_check(bidx_ref a, bidx_ref b) {
    if (a.book   != b.book)    return a.book   < b.book;
    if (a.chapter!= b.chapter) return a.chapter< b.chapter;
    return a.verse <= b.verse;
}

static ptrdiff_t bidx_iter_ref(const bidx_file* f, bidx_ref r) {
    if (!f || r.book== 0 || r.chapter == 0) return -1;
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
    it->index = (size_t)i0;
    it->end = (size_t)i1 + 1;
    it->has_last = false;

    return BIDX_OK;
}

bidx_iter_rc bidx_iter_next(bidx_iter* it, bidx_record* r) {
    if (!it || !r || !it->f) return BIDX_ITER_ERROR;
    if (it->index >= it->end) return BIDX_ITER_END;
    if (!bidx_read_record(it->f, it->index, r)) return BIDX_ITER_ERROR;

    it->last = *r;
    it->index++;
    it->has_last = true;

    return BIDX_ITER_YIELD;
}

bidx_rc bidx_iter_read(const bidx_iter* it, uint32_t* offset) {
    if (!it || !it->f || !offset) return BIDX_ERR;
    if (!it->has_last) return BIDX_ERR;
    *offset = it->last.offset;
    return BIDX_OK;
}

bidx_iter_rc bidx_iter_has_next(const bidx_iter* it) {
    if (!it || !it->f) return BIDX_ITER_ERROR;
    return it->index < it->end ? BIDX_ITER_YIELD : BIDX_ITER_END;
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
    it->has_last = false;
    return bidx_iter_init(it, f, from, to);
}

bidx_rc bidx_iter_init_chapter(bidx_iter* it, const bidx_file* f, uint8_t book, uint8_t chapter) {
    if (!it || !f || book == 0 || chapter == 0) return BIDX_ERR;

    size_t base = f->start_index[book][chapter];
    size_t nvs  = f->verse_count[book][chapter];
    if (base == SIZE_MAX || nvs == 0) return BIDX_ERR;

    bidx_ref from = { book, chapter, 1 };
    bidx_ref to   = { book, chapter, (uint8_t) nvs };
    it->has_last = false;
    return bidx_iter_init(it, f, from, to);
}

bidx_rc bidx_iter_init_from(bidx_iter* it, const bidx_file* f, bidx_ref from) {
    if (!it || !f) return BIDX_ERR;

    ptrdiff_t index = bidx_iter_ref(f, from);

    if (index < 0) return BIDX_ERR;

    it->f = f;
    it->index = (size_t)index;
    it->end = f->count;
    it->has_last = false;

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

    bidx_record r;
    for (size_t i = 0; i < ttotal; ++i) {
        if (!bidx_read_record(f, i, &r)) return -1;
        fprintf(out, "%3u %4u %5u %10" PRIu32 "\n",
                (unsigned)r.ref.book,
                (unsigned)r.ref.chapter,
                (unsigned)r.ref.verse,
                r.offset);
    }
    return BIDX_OK;
}
