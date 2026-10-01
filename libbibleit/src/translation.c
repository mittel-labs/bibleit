#include "bibleit/utils.h"
#include "bibleit/translation.h"

#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <limits.h>

enum { SEARCH_MAGIC_SIZE = 4, SEARCH_VERSION = 2, SEARCH_BUCKETS = 65537 };

typedef struct {
    uint32_t key;
    uint32_t *postings;
    size_t count;
    size_t capacity;
    size_t next;
} search_term;

typedef struct {
    uint32_t *line_offsets;
    size_t line_count;
    search_term *terms;
    size_t term_count;
} search_index;

struct bt_file {
    int fd;
    const char* data;
    size_t size;
    char *path;
    search_index *search;
};

static unsigned char fold_ascii(unsigned char c) {
    return c >= 'A' && c <= 'Z' ? (unsigned char)(c + ('a' - 'A')) : c;
}

static unsigned char fold_latin1(unsigned char first, unsigned char second) {
    if (first != 0xC3) return 0;
    switch (second) {
        case 0x80: case 0x81: case 0x82: case 0x83: case 0x84: case 0x85:
        case 0xA0: case 0xA1: case 0xA2: case 0xA3: case 0xA4: case 0xA5: return 'a';
        case 0x87: case 0xA7: return 'c';
        case 0x88: case 0x89: case 0x8A: case 0x8B:
        case 0xA8: case 0xA9: case 0xAA: case 0xAB: return 'e';
        case 0x8C: case 0x8D: case 0x8E: case 0x8F:
        case 0xAC: case 0xAD: case 0xAE: case 0xAF: return 'i';
        case 0x91: case 0xB1: return 'n';
        case 0x92: case 0x93: case 0x94: case 0x95: case 0x96:
        case 0xB2: case 0xB3: case 0xB4: case 0xB5: case 0xB6: return 'o';
        case 0x99: case 0x9A: case 0x9B: case 0x9C:
        case 0xB9: case 0xBA: case 0xBB: case 0xBC: return 'u';
        case 0x9D: case 0xBD: case 0xBF: return 'y';
        default: return 0;
    }
}

static unsigned char *normalize_search_text(const char *text, size_t text_len, size_t *out_len) {
    unsigned char *normalized = malloc(text_len ? text_len : 1);
    if (!normalized) return NULL;
    size_t write = 0;
    for (size_t read = 0; read < text_len; ++read) {
        unsigned char folded = read + 1 < text_len ? fold_latin1((unsigned char)text[read], (unsigned char)text[read + 1]) : 0;
        if (folded) { normalized[write++] = folded; ++read; }
        else normalized[write++] = fold_ascii((unsigned char)text[read]);
    }
    *out_len = write;
    return normalized;
}

static size_t verse_text_offset(const char *line, size_t length) {
    const char *colon = memchr(line, ':', length);
    if (!colon) return 0;
    size_t offset = (size_t)(colon - line) + 1;
    while (offset < length && line[offset] >= '0' && line[offset] <= '9') ++offset;
    if (offset == (size_t)(colon - line) + 1) return 0;
    while (offset < length && (line[offset] == ' ' || line[offset] == '\t')) ++offset;
    return offset;
}

static uint64_t content_hash(const char *data, size_t size) {
    uint64_t hash = UINT64_C(1469598103934665603);
    for (size_t i = 0; i < size; ++i) {
        hash ^= (unsigned char)data[i];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static void search_index_close(search_index *index) {
    if (!index) return;
    for (size_t i = 0; i < index->term_count; ++i) free(index->terms[i].postings);
    free(index->terms);
    free(index->line_offsets);
    free(index);
}

static int compare_terms(const void *left, const void *right) {
    const search_term *a = left, *b = right;
    return (a->key > b->key) - (a->key < b->key);
}

static search_term *find_term(const search_index *index, uint32_t key) {
    size_t first = 0, last = index->term_count;
    while (first < last) {
        size_t middle = first + (last - first) / 2;
        if (index->terms[middle].key == key) return &index->terms[middle];
        if (index->terms[middle].key < key) first = middle + 1;
        else last = middle;
    }
    return NULL;
}

static int read_exact(FILE *file, void *data, size_t size) {
    return fread(data, 1, size, file) == size;
}

static int write_exact(FILE *file, const void *data, size_t size) {
    return fwrite(data, 1, size, file) == size;
}

static search_index *load_search_index(const char *path, size_t source_size, uint64_t source_hash) {
    static const char magic[SEARCH_MAGIC_SIZE] = {'B', 'T', 'S', '1'};
    char found_magic[SEARCH_MAGIC_SIZE];
    uint32_t version, line_count, term_count;
    uint64_t indexed_size, indexed_hash;
    FILE *file = fopen(path, "rb");
    if (!file) return NULL;
    if (!read_exact(file, found_magic, sizeof found_magic) || memcmp(found_magic, magic, sizeof magic) ||
        !read_exact(file, &version, sizeof version) || version != SEARCH_VERSION ||
        !read_exact(file, &indexed_size, sizeof indexed_size) || indexed_size != source_size ||
        !read_exact(file, &indexed_hash, sizeof indexed_hash) || indexed_hash != source_hash ||
        !read_exact(file, &line_count, sizeof line_count) || !read_exact(file, &term_count, sizeof term_count)) {
        fclose(file);
        return NULL;
    }
    search_index *index = calloc(1, sizeof *index);
    if (!index) { fclose(file); return NULL; }
    index->line_count = line_count;
    index->term_count = term_count;
    index->line_offsets = calloc(line_count ? line_count : 1, sizeof *index->line_offsets);
    index->terms = calloc(term_count ? term_count : 1, sizeof *index->terms);
    if (!index->line_offsets || !index->terms ||
        !read_exact(file, index->line_offsets, (size_t)line_count * sizeof *index->line_offsets)) {
        fclose(file); search_index_close(index); return NULL;
    }
    for (size_t i = 0; i < index->line_count; ++i) {
        if (index->line_offsets[i] >= source_size) { fclose(file); search_index_close(index); return NULL; }
    }
    for (size_t i = 0; i < index->term_count; ++i) {
        uint32_t count;
        if (!read_exact(file, &index->terms[i].key, sizeof index->terms[i].key) ||
            !read_exact(file, &count, sizeof count)) {
            fclose(file); search_index_close(index); return NULL;
        }
        index->terms[i].count = count;
        index->terms[i].capacity = count;
        index->terms[i].postings = calloc(count ? count : 1, sizeof *index->terms[i].postings);
        if (!index->terms[i].postings ||
            !read_exact(file, index->terms[i].postings, (size_t)count * sizeof *index->terms[i].postings)) {
            fclose(file); search_index_close(index); return NULL;
        }
        for (size_t j = 0; j < count; ++j) {
            if (index->terms[i].postings[j] >= line_count) { fclose(file); search_index_close(index); return NULL; }
        }
        if (i && index->terms[i - 1].key >= index->terms[i].key) { fclose(file); search_index_close(index); return NULL; }
    }
    fclose(file);
    return index;
}

static int append_posting(search_term *term, uint32_t line) {
    if (term->count == term->capacity) {
        size_t capacity = term->capacity ? term->capacity * 2 : 8;
        uint32_t *postings = realloc(term->postings, capacity * sizeof *postings);
        if (!postings) return 0;
        term->postings = postings;
        term->capacity = capacity;
    }
    term->postings[term->count++] = line;
    return 1;
}

static search_index *build_search_index(const char *data, size_t size) {
    search_term *terms = NULL;
    size_t term_count = 0, term_capacity = 0;
    size_t *buckets = malloc(SEARCH_BUCKETS * sizeof *buckets);
    uint32_t *offsets = NULL;
    size_t lines = 0, offset_capacity = 0;
    if (!buckets) return NULL;
    for (size_t i = 0; i < SEARCH_BUCKETS; ++i) buckets[i] = SIZE_MAX;
    for (size_t offset = 0; offset < size;) {
        if (lines == offset_capacity) {
            size_t capacity = offset_capacity ? offset_capacity * 2 : 1024;
            uint32_t *next = realloc(offsets, capacity * sizeof *offsets);
            if (!next) goto failed;
            offsets = next; offset_capacity = capacity;
        }
        offsets[lines] = (uint32_t)offset;
        const char *end = memchr(data + offset, '\n', size - offset);
        size_t length = end ? (size_t)(end - (data + offset)) : size - offset;
        size_t text_offset = verse_text_offset(data + offset, length), normalized_length;
        unsigned char *normalized = normalize_search_text(data + offset + text_offset, length - text_offset, &normalized_length);
        if (!normalized) goto failed;
        for (size_t i = 0; i + 2 < normalized_length; ++i) {
            uint32_t key = ((uint32_t)normalized[i] << 16) |
                           ((uint32_t)normalized[i + 1] << 8) |
                           normalized[i + 2];
            size_t bucket = key % SEARCH_BUCKETS, term = buckets[bucket];
            while (term != SIZE_MAX && terms[term].key != key) term = terms[term].next;
            if (term == SIZE_MAX) {
                if (term_count == term_capacity) {
                    size_t capacity = term_capacity ? term_capacity * 2 : 1024;
                    search_term *next = realloc(terms, capacity * sizeof *terms);
                    if (!next) goto failed;
                    terms = next; term_capacity = capacity;
                }
                term = term_count++;
                memset(&terms[term], 0, sizeof terms[term]);
                terms[term].key = key;
                terms[term].next = buckets[bucket];
                buckets[bucket] = term;
            }
            if (!append_posting(&terms[term], (uint32_t)lines)) { free(normalized); goto failed; }
        }
        free(normalized);
        ++lines;
        offset = end ? (size_t)(end - data) + 1 : size;
    }
    for (size_t i = 0; i < term_count; ++i) {
        size_t unique = 0;
        for (size_t j = 0; j < terms[i].count; ++j)
            if (!unique || terms[i].postings[j] != terms[i].postings[unique - 1]) terms[i].postings[unique++] = terms[i].postings[j];
        terms[i].count = unique;
    }
    qsort(terms, term_count, sizeof *terms, compare_terms);
    free(buckets);
    search_index *index = calloc(1, sizeof *index);
    if (!index) goto failed_without_buckets;
    index->line_offsets = offsets;
    index->line_count = lines;
    index->terms = terms;
    index->term_count = term_count;
    return index;
failed:
    free(buckets);
failed_without_buckets:
    if (terms) for (size_t i = 0; i < term_count; ++i) free(terms[i].postings);
    free(terms); free(offsets);
    return NULL;
}

static void write_search_index(const char *path, const search_index *index, size_t source_size, uint64_t source_hash) {
    static const char magic[SEARCH_MAGIC_SIZE] = {'B', 'T', 'S', '1'};
    uint32_t version = SEARCH_VERSION, lines = (uint32_t)index->line_count, terms = (uint32_t)index->term_count;
    size_t temporary_size = strlen(path) + 32;
    char *temporary = malloc(temporary_size);
    if (!temporary) return;
    snprintf(temporary, temporary_size, "%s.%ld.tmp", path, (long)getpid());
    FILE *file = fopen(temporary, "wb");
    if (!file) { free(temporary); return; }
    int ok = write_exact(file, magic, sizeof magic) && write_exact(file, &version, sizeof version) &&
             write_exact(file, &source_size, sizeof source_size) && write_exact(file, &source_hash, sizeof source_hash) &&
             write_exact(file, &lines, sizeof lines) && write_exact(file, &terms, sizeof terms) &&
             write_exact(file, index->line_offsets, index->line_count * sizeof *index->line_offsets);
    for (size_t i = 0; ok && i < index->term_count; ++i) {
        uint32_t count = (uint32_t)index->terms[i].count;
        ok = write_exact(file, &index->terms[i].key, sizeof index->terms[i].key) &&
             write_exact(file, &count, sizeof count) &&
             write_exact(file, index->terms[i].postings, index->terms[i].count * sizeof *index->terms[i].postings);
    }
    ok = ok && fclose(file) == 0;
    if (ok) rename(temporary, path); else remove(temporary);
    free(temporary);
}

static search_index *open_search_index(const char *translation_path, const char *data, size_t size) {
    if (size > UINT32_MAX) return NULL;
    size_t path_size = strlen(translation_path) + strlen(".bsearch") + 1;
    char *path = malloc(path_size);
    if (!path) return NULL;
    snprintf(path, path_size, "%s.bsearch", translation_path);
    uint64_t hash = content_hash(data, size);
    search_index *index = load_search_index(path, size, hash);
    if (!index) {
        index = build_search_index(data, size);
        if (index) write_search_index(path, index, size, hash);
    }
    free(path);
    return index;
}

bt_file* bt_open(const char* path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return NULL;

    struct stat st;
    if (fstat(fd, &st) != 0) {
        close(fd);
        return NULL;
    }

    char* data = mmap(NULL, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (data == MAP_FAILED) {
        close(fd);
        return NULL;
    }

    bt_file* f = calloc(1, sizeof(*f));
    if (!f) {
        munmap(data, st.st_size);
        close(fd);
        return NULL;
    }

    f->fd = fd;
    f->data = data;
    f->size = st.st_size;
    f->path = malloc(strlen(path) + 1);
    if (!f->path) {
        bt_close(f);
        return NULL;
    }
    strcpy(f->path, path);
    f->search = open_search_index(f->path, f->data, f->size);

    return f;
}

void bt_close(bt_file* f) {
    if (!f) return;
    if (f->data) munmap((void*)f->data, f->size);
    if (f->fd >= 0) close(f->fd);
    free(f->path);
    search_index_close(f->search);
    free(f);
}

bt_rc bt_read(const bt_file* f, uint32_t offset, char* buf, size_t bufsize) {
    if (!f || !buf || bufsize < 2) return BT_ERR;

    bt_record_view v;
    bt_rc rc = bt_read_view(f, offset, &v);
    if (rc != BT_OK) return rc;

    if (v.len >= bufsize) {
        memcpy(buf, v.ptr, bufsize - 1);
        buf[bufsize - 1] = '\0';
        return BT_TRUNCATED;
    }

    memcpy(buf, v.ptr, v.len);
    buf[v.len] = '\0';

    return BT_OK;
}

bt_rc bt_read_view(const bt_file* f, uint32_t offset, bt_record_view* out) {
    if (!f || !out) return BT_ERR;
    if (offset >= f->size) return BT_ERR;

    const char* start = f->data + offset;
    const char* end   = memchr(start, '\n', f->size - offset);

    size_t len = end ? (size_t)(end - start)
                     : (size_t)(f->data + f->size - start);

    if (len && start[len - 1] == '\r')
        len--;

    out->ptr = start;
    out->len = len;

    return BT_OK;
}

static int contains_normalized(const char* text, size_t text_len, const unsigned char* query, size_t query_len) {
    size_t normalized_length;
    unsigned char *normalized = normalize_search_text(text, text_len, &normalized_length);
    if (!normalized) return 0;
    if (!query_len || query_len > normalized_length) { free(normalized); return 0; }
    for (size_t i = 0; i <= normalized_length - query_len; ++i) {
        size_t j = 0;
        for (; j < query_len; ++j) {
            if (normalized[i + j] != query[j]) break;
        }
        if (j == query_len) { free(normalized); return 1; }
    }
    free(normalized);
    return 0;
}

size_t bt_search(const bt_file* f, const char* query, size_t query_len,
                       size_t limit, bt_search_visitor visitor, void* context) {
    if (!f || !query || !query_len || !limit || !visitor) return 0;
    size_t normalized_query_len;
    unsigned char *normalized_query = normalize_search_text(query, query_len, &normalized_query_len);
    if (!normalized_query || !normalized_query_len) { free(normalized_query); return 0; }
    const uint32_t *candidates = NULL;
    size_t candidate_count = 0;
    if (f->search && normalized_query_len >= 3) {
        search_term *best = NULL;
        for (size_t i = 0; i + 2 < normalized_query_len; ++i) {
            uint32_t key = ((uint32_t)normalized_query[i] << 16) |
                           ((uint32_t)normalized_query[i + 1] << 8) |
                           normalized_query[i + 2];
            search_term *term = find_term(f->search, key);
            if (!term) { free(normalized_query); return 0; }
            if (!best || term->count < best->count) best = term;
        }
        candidates = best->postings;
        candidate_count = best->count;
    }
    size_t found = 0, offset = 0;
    size_t records = candidates ? candidate_count : SIZE_MAX;
    for (size_t record_index = 0; record_index < records && found < limit; ++record_index) {
        offset = candidates ? f->search->line_offsets[candidates[record_index]] : offset;
        bt_record_view record;
        if (bt_read_view(f, (uint32_t)offset, &record) != BT_OK) break;
        size_t text_offset = verse_text_offset(record.ptr, record.len);
        if (contains_normalized(record.ptr + text_offset, record.len - text_offset, normalized_query, normalized_query_len)) {
            found++;
            if (visitor(record, context)) break;
        }
        if (!candidates) {
            const char* end = memchr(f->data + offset, '\n', f->size - offset);
            offset = end ? (size_t)(end - f->data) + 1 : f->size;
            if (offset == f->size) break;
        }
    }
    free(normalized_query);
    return found;
}
