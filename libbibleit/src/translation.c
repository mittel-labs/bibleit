#include "bibleit/utils.h"
#include "bibleit/translation.h"

#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct bt_file {
    int fd;
    const char* data;
    size_t size;
};

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

    return f;
}

void bt_close(bt_file* f) {
    if (!f) return;
    if (f->data) munmap((void*)f->data, f->size);
    if (f->fd >= 0) close(f->fd);
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
