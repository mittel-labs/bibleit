-module(bibleit_translation_nif).
-on_load(init/0).
-export([create_index/2, open/2, read/4, read_book/2, read_chapter/3, search/3, catalog/1]).

init() ->
    Root = filename:dirname(filename:dirname(code:which(?MODULE))),
    erlang:load_nif(filename:join([Root, "priv", "bibleit_translation_nif"]), 0).
open(_TranslationPath, _IndexPath) -> erlang:nif_error(nif_not_loaded).
create_index(_TranslationPath, _IndexPath) -> erlang:nif_error(nif_not_loaded).
read(_Handle, _Book, _Chapter, _Verse) -> erlang:nif_error(nif_not_loaded).
read_book(_Handle, _Book) -> erlang:nif_error(nif_not_loaded).
read_chapter(_Handle, _Book, _Chapter) -> erlang:nif_error(nif_not_loaded).
search(_Handle, _Query, _Limit) -> erlang:nif_error(nif_not_loaded).
catalog(_Handle) -> erlang:nif_error(nif_not_loaded).
