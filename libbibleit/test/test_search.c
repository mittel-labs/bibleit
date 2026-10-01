#include <bibleit/bidx.h>
#include <bibleit/translation.h>

#include <assert.h>
#include <stdio.h>
#include <unistd.h>

static size_t matches;

static int count_match(bt_record_view record, void *context) {
    (void)record;
    size_t *count = context;
    (*count)++;
    return 0;
}

int main(void) {
    char translation_path[128];
    char index_path[128];
    char search_index_path[140];
    snprintf(translation_path, sizeof translation_path, "/tmp/libbibleit-search-%ld.bt", (long)getpid());
    snprintf(index_path, sizeof index_path, "/tmp/libbibleit-search-%ld.bidx", (long)getpid());
    snprintf(search_index_path, sizeof search_index_path, "%s.bsearch", translation_path);
    FILE *translation = fopen(translation_path, "w");
    assert(translation);
    fputs("Genesis 1:1 The Pastor speaks.\nGenesis 1:2 Nothing here.\nGenesis 1:3 pastor again.\nO Livro de João 1:4 Nada corresponde.\nGenesis 1:5 Meu coração descansa.\n", translation);
    fclose(translation);
    assert(bidx_create(index_path, translation_path) == BIDX_CREATE_OK);
    bt_file *file = bt_open(translation_path);
    assert(file);
    matches = 0;
    assert(bt_search(file, "PASTOR", 6, 10, count_match, &matches) == 2);
    assert(matches == 2);
    matches = 0;
    assert(bt_search(file, "pastor", 6, 1, count_match, &matches) == 1);
    assert(matches == 1);
    matches = 0;
    assert(bt_search(file, "joao", 4, 10, count_match, &matches) == 0);
    assert(matches == 0);
    matches = 0;
    assert(bt_search(file, "coracao", 7, 10, count_match, &matches) == 1);
    assert(matches == 1);
    bt_close(file);
    assert(access(search_index_path, F_OK) == 0);

    file = bt_open(translation_path);
    assert(file);
    matches = 0;
    assert(bt_search(file, "PASTOR", 6, 10, count_match, &matches) == 2);
    assert(matches == 2);
    bt_close(file);

    translation = fopen(translation_path, "a");
    assert(translation);
    fputs("Genesis 1:4 Moonlight.\n", translation);
    fclose(translation);
    file = bt_open(translation_path);
    assert(file);
    matches = 0;
    assert(bt_search(file, "moon", 4, 10, count_match, &matches) == 1);
    assert(matches == 1);
    bt_close(file);
    remove(index_path);
    remove(translation_path);
    remove(search_index_path);
    return 0;
}
