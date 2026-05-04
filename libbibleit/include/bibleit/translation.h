#ifndef BIBLEIT_TRANSLATION_H
#define BIBLEIT_TRANSLATION_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct bt_file bt_file;

typedef enum {
    BT_ERR        = -1,
    BT_OK         =  0,
    BT_TRUNCATED  =  1
} bt_rc;

typedef struct {
    const char* ptr;
    size_t len;
} bt_record_view;

bt_file* bt_open(const char* path);
void     bt_close(bt_file* f);
bt_rc    bt_read(const bt_file* f, uint32_t offset, char* buf, size_t bufsize);
bt_rc    bt_read_view(const bt_file* f, uint32_t offset, bt_record_view* out);

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif // BIBLEIT_TRANSLATION_H
