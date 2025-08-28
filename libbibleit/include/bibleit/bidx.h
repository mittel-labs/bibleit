#ifndef BIBLEIT_BIDX_H
#define BIBLEIT_BIDX_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BIDX_MAGIC   "BIDX"
#define BIDX_VERSION 1

typedef enum {
    BIDX_ERR  = -1,
    BIDX_OK   =  0
} bidx_rc;


typedef enum {
    BIDX_ITER_ERROR = -1,
    BIDX_ITER_END   =  0,
    BIDX_ITER_YIELD =  1
} bidx_iter_rc;


typedef enum {
    BIDX_LOOKUP_ERR      = -1,
    BIDX_LOOKUP_OK       =  0,
    BIDX_LOOKUP_NOTFOUND =  1
} bidx_lookup_rc;

typedef enum {
    BIDX_CREATE_ERR         = -1,
    BIDX_CREATE_OK          =  0,
    BIDX_CREATE_EXISTS      =  1,
    BIDX_CREATE_PARSE_ERR   =  2 
} bidx_create_rc;

typedef struct bidx_file bidx_file;

typedef struct {
    uint8_t book;
    uint8_t chapter;
    uint8_t verse;
} bidx_ref;

typedef struct {
    bidx_ref ref;
    uint32_t offset;
} bidx_record;

typedef struct {
    const bidx_file* f;
    size_t index, end;
    bidx_record last;
    bool has_last;
} bidx_iter;

bidx_file*     bidx_open(const char* path);
void           bidx_close(bidx_file* f);
bidx_rc        bidx_dump(const bidx_file* f, FILE* out, size_t limit);

int            bidx_create(const char* bidx_path, const char* translation_path);
int            bidx_version(const bidx_file* f);
size_t         bidx_count(const bidx_file* f);
bidx_lookup_rc bidx_read(const bidx_file* f, bidx_ref r, uint32_t* offset);

bidx_rc        bidx_iter_init(bidx_iter* it, const bidx_file* f, bidx_ref from, bidx_ref to);
bidx_rc        bidx_iter_init_book(bidx_iter* it, const bidx_file* f, uint8_t book);
bidx_rc        bidx_iter_init_chapter(bidx_iter* it, const bidx_file* f, uint8_t book, uint8_t chapter);
bidx_rc        bidx_iter_init_from(bidx_iter* it, const bidx_file* f, bidx_ref from);
bidx_rc        bidx_iter_read(const bidx_iter* it, uint32_t* offset);
bidx_iter_rc   bidx_iter_next(bidx_iter* it, bidx_record* r);
bidx_iter_rc   bidx_iter_has_next(const bidx_iter* it);

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif // BIBLEIT_BIDX_H
