#include "bibleit/utils.h"
#include "bibleit/translation.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct bt_file {
    FILE* fp;
};

bt_file* bt_open(const char* path) {
    bt_file *f = calloc(1, sizeof(*f));
    
    FILE *fp = fopen(path, "rb");
    if (!fp) return NULL;

    f->fp = fp;

    return f;
}

void bt_close(bt_file* f) {
    if (!f) return;
    if (f->fp) fclose(f->fp);
    free(f);
}

bt_rc bt_read(const bt_file* f, uint32_t offset, char* buf, size_t bufsize) {
    if (!f || !buf || bufsize < 2) return BT_ERR;

    if (fseek(f->fp, offset, SEEK_SET) != 0) return BT_ERR;

    if (!fgets(buf, bufsize, f->fp)) return BT_ERR;

    size_t n = strlen(buf);
    if (n && buf[n-1] == '\n') buf[--n] = '\0';
    if (n && buf[n-1] == '\r') buf[--n] = '\0';

    if (n == bufsize - 1) {
        discard_until_newline(f->fp);
        return BT_TRUNCATED;
    }

    return BT_OK;
}
