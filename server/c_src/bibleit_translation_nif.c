#include <erl_nif.h>
#include <bibleit/bidx.h>
#include <bibleit/translation.h>
#include <string.h>

typedef struct { bt_file *translation; bidx_file *index; } handle_t;
static ErlNifResourceType *HANDLE;

static void close_handle(ErlNifEnv *env, void *object) {
    (void)env;
    handle_t *handle = object;
    bt_close(handle->translation);
    bidx_close(handle->index);
}

static ERL_NIF_TERM error(ErlNifEnv *env, const char *reason) {
    return enif_make_tuple2(env, enif_make_atom(env, "error"), enif_make_atom(env, reason));
}

static ERL_NIF_TERM create_index_nif(ErlNifEnv *env, int argc, const ERL_NIF_TERM argv[]) {
    ErlNifBinary translation_path, index_path;
    if (argc != 2 || !enif_inspect_binary(env, argv[0], &translation_path) ||
        !enif_inspect_binary(env, argv[1], &index_path) ||
        memchr(translation_path.data, '\0', translation_path.size) || memchr(index_path.data, '\0', index_path.size))
        return enif_make_badarg(env);
    char *translation_name = enif_alloc(translation_path.size + 1);
    char *index_name = enif_alloc(index_path.size + 1);
    if (!translation_name || !index_name) { enif_free(translation_name); enif_free(index_name); return error(env, "out_of_memory"); }
    memcpy(translation_name, translation_path.data, translation_path.size); translation_name[translation_path.size] = '\0';
    memcpy(index_name, index_path.data, index_path.size); index_name[index_path.size] = '\0';
    bidx_create_rc result = bidx_create(index_name, translation_name);
    enif_free(translation_name); enif_free(index_name);
    return result == BIDX_CREATE_OK ? enif_make_atom(env, "ok") : error(env, "index_create_failed");
}

static ERL_NIF_TERM open_nif(ErlNifEnv *env, int argc, const ERL_NIF_TERM argv[]) {
    ErlNifBinary translation_path, index_path;
    if (argc != 2 || !enif_inspect_binary(env, argv[0], &translation_path) ||
        !enif_inspect_binary(env, argv[1], &index_path) ||
        memchr(translation_path.data, '\0', translation_path.size) || memchr(index_path.data, '\0', index_path.size))
        return enif_make_badarg(env);
    char *translation_name = enif_alloc(translation_path.size + 1);
    char *index_name = enif_alloc(index_path.size + 1);
    if (!translation_name || !index_name) { enif_free(translation_name); enif_free(index_name); return error(env, "out_of_memory"); }
    memcpy(translation_name, translation_path.data, translation_path.size); translation_name[translation_path.size] = '\0';
    memcpy(index_name, index_path.data, index_path.size); index_name[index_path.size] = '\0';
    bt_file *translation = bt_open(translation_name); bidx_file *index = bidx_open(index_name);
    enif_free(translation_name); enif_free(index_name);
    if (!translation || !index) { bt_close(translation); bidx_close(index); return error(env, "open_failed"); }
    handle_t *handle = enif_alloc_resource(HANDLE, sizeof(*handle));
    handle->translation = translation; handle->index = index;
    ERL_NIF_TERM resource = enif_make_resource(env, handle); enif_release_resource(handle);
    return enif_make_tuple2(env, enif_make_atom(env, "ok"), resource);
}

static ERL_NIF_TERM read_nif(ErlNifEnv *env, int argc, const ERL_NIF_TERM argv[]) {
    handle_t *handle; unsigned book, chapter, verse; uint32_t offset; bt_record_view text;
    if (argc != 4 || !enif_get_resource(env, argv[0], HANDLE, (void **)&handle) ||
        !enif_get_uint(env, argv[1], &book) || !enif_get_uint(env, argv[2], &chapter) || !enif_get_uint(env, argv[3], &verse) ||
        book > 255 || chapter > 255 || verse > 255) return enif_make_badarg(env);
    bidx_ref reference = {(uint8_t)book, (uint8_t)chapter, (uint8_t)verse};
    if (!bidx_has_book(handle->index, reference.book)) return enif_make_atom(env, "book_not_found");
    if (!bidx_has_chapter(handle->index, reference.book, reference.chapter)) return enif_make_atom(env, "chapter_not_found");
    if (bidx_read(handle->index, reference, &offset) != BIDX_LOOKUP_OK) return enif_make_atom(env, "verse_not_found");
    if (bt_read_view(handle->translation, offset, &text) != BT_OK) return error(env, "read_failed");
    ERL_NIF_TERM result; unsigned char *output = enif_make_new_binary(env, text.len, &result);
    memcpy(output, text.ptr, text.len); return enif_make_tuple2(env, enif_make_atom(env, "ok"), result);
}
static ERL_NIF_TERM read_range_nif(ErlNifEnv *env, int argc, const ERL_NIF_TERM argv[]) {
    handle_t *handle; unsigned book, chapter = 0; bidx_iter iterator; bidx_record_view record;
    if ((argc != 2 && argc != 3) || !enif_get_resource(env, argv[0], HANDLE, (void **)&handle) ||
        !enif_get_uint(env, argv[1], &book) || (argc == 3 && !enif_get_uint(env, argv[2], &chapter)) ||
        book == 0 || book > 255 || chapter > 255) return enif_make_badarg(env);
    if (!bidx_has_book(handle->index, (uint8_t)book)) return enif_make_atom(env, "book_not_found");
    if (argc == 3 && !bidx_has_chapter(handle->index, (uint8_t)book, (uint8_t)chapter)) return enif_make_atom(env, "chapter_not_found");
    int status = argc == 3 ? bidx_iter_init_chapter(&iterator, handle->index, (uint8_t)book, (uint8_t)chapter)
                           : bidx_iter_init_book(&iterator, handle->index, (uint8_t)book);
    if (status != BIDX_OK) return error(env, "read_failed");
    ERL_NIF_TERM values = enif_make_list(env, 0);
    while (bidx_iter_next(&iterator, &record) == BIDX_ITER_YIELD) {
        if (bidx_view_book(record) != book || (argc == 3 && bidx_view_chapter(record) != chapter)) break;
        bt_record_view text; if (bt_read_view(handle->translation, bidx_view_offset(record), &text) != BT_OK) return error(env, "read_failed");
        ERL_NIF_TERM binary; unsigned char *output = enif_make_new_binary(env, text.len, &binary);
        memcpy(output, text.ptr, text.len); values = enif_make_list_cell(env, binary, values);
    }
    ERL_NIF_TERM ordered; enif_make_reverse_list(env, values, &ordered);
    return enif_make_tuple2(env, enif_make_atom(env, "ok"), ordered);
}
typedef struct { ErlNifEnv *env; ERL_NIF_TERM values; } search_context;
static int collect_match(bt_record_view text, void *context) {
    search_context *result = context;
    ERL_NIF_TERM binary;
    unsigned char *output = enif_make_new_binary(result->env, text.len, &binary);
    memcpy(output, text.ptr, text.len);
    result->values = enif_make_list_cell(result->env, binary, result->values);
    return 0;
}
static ERL_NIF_TERM search_nif(ErlNifEnv *env, int argc, const ERL_NIF_TERM argv[]) {
    handle_t *handle; ErlNifBinary query; unsigned limit;
    if (argc != 3 || !enif_get_resource(env, argv[0], HANDLE, (void **)&handle) || !enif_inspect_binary(env, argv[1], &query) || !enif_get_uint(env, argv[2], &limit) || !query.size || !limit || limit > 1000) return enif_make_badarg(env);
    search_context context = {env, enif_make_list(env, 0)};
    bt_search(handle->translation, (const char *)query.data, query.size, limit, collect_match, &context);
    ERL_NIF_TERM ordered; enif_make_reverse_list(env, context.values, &ordered);
    return enif_make_tuple2(env, enif_make_atom(env, "ok"), ordered);
}
static ERL_NIF_TERM catalog_nif(ErlNifEnv *env, int argc, const ERL_NIF_TERM argv[]) {
    handle_t *handle;
    if (argc != 1 || !enif_get_resource(env, argv[0], HANDLE, (void **)&handle)) return enif_make_badarg(env);
    ERL_NIF_TERM books = enif_make_list(env, 0);
    for (int book = 255; book >= 1; --book) {
        if (!bidx_has_book(handle->index, (uint8_t)book)) continue;
        ERL_NIF_TERM chapters = enif_make_list(env, 0);
        for (int chapter = 255; chapter >= 1; --chapter) {
            size_t verses = bidx_chapter_verse_count(handle->index, (uint8_t)book, (uint8_t)chapter);
            if (!verses) continue;
            ERL_NIF_TERM entry = enif_make_tuple2(env, enif_make_uint(env, (unsigned)chapter),
                                                   enif_make_uint64(env, (ErlNifUInt64)verses));
            chapters = enif_make_list_cell(env, entry, chapters);
        }
        ERL_NIF_TERM entry = enif_make_tuple2(env, enif_make_uint(env, (unsigned)book), chapters);
        books = enif_make_list_cell(env, entry, books);
    }
    return enif_make_tuple2(env, enif_make_atom(env, "ok"), books);
}

static int load(ErlNifEnv *env, void **priv, ERL_NIF_TERM info) {
    (void)priv; (void)info;
    HANDLE = enif_open_resource_type(env, NULL, "bibleit_translation_handle", close_handle, ERL_NIF_RT_CREATE, NULL);
    return HANDLE ? 0 : -1;
}
static ErlNifFunc functions[] = {{"create_index", 2, create_index_nif, ERL_NIF_DIRTY_JOB_IO_BOUND}, {"open", 2, open_nif, ERL_NIF_DIRTY_JOB_IO_BOUND}, {"read", 4, read_nif, 0}, {"read_book", 2, read_range_nif, ERL_NIF_DIRTY_JOB_CPU_BOUND}, {"read_chapter", 3, read_range_nif, ERL_NIF_DIRTY_JOB_CPU_BOUND}, {"search", 3, search_nif, ERL_NIF_DIRTY_JOB_CPU_BOUND}, {"catalog", 1, catalog_nif, ERL_NIF_DIRTY_JOB_CPU_BOUND}};
ERL_NIF_INIT(bibleit_translation_nif, functions, load, NULL, NULL, NULL)
