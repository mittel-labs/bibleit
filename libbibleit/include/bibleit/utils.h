#ifndef BIBLEIT_UTILS_H
#define BIBLEIT_UTILS_H

#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif

static inline void discard_until_newline(FILE* fp) {
    int ch;
    while ((ch = fgetc(fp)) != EOF) {
        if (ch == '\n') break;
    }
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif // BIBLEIT_UTILS_H
