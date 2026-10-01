-module(bibleit_translation_catalog).
-export([resolve_book/2, books/1, describe_books/2, index_book/2, canonical_slug/1]).

books(Slug) ->
    case file:read_file(config_path("translations_books.json")) of
        {ok, Raw} ->
            Catalog = json:decode(Raw),
            case [Value || {Key, Value} <- maps:to_list(Catalog), normalize(Key) =:= normalize(Slug)] of
                [Value] -> {ok, Value};
                _ -> {error, translation_not_found}
            end;
        _ -> {error, catalog_unavailable}
    end.

canonical_slug(Slug) ->
    case file:read_file(config_path("translations_books.json")) of
        {ok, Raw} ->
            Catalog = json:decode(Raw),
            case [Key || {Key, _} <- maps:to_list(Catalog), normalize(Key) =:= normalize(Slug)] of
                [Key] -> {ok, Key};
                _ -> {error, translation_not_found}
            end;
        _ -> {error, catalog_unavailable}
    end.

resolve_book(Slug, Name) ->
    case books(Slug) of
        {ok, TranslationBooks} ->
            Matches = [maps:get(<<"bookid">>, Book) || Book <- TranslationBooks, normalize(maps:get(<<"name">>, Book)) =:= normalize(Name)],
            case Matches of [Book] -> {ok, Book}; _ -> {error, book_not_found} end;
        Error -> Error
    end.

describe_books(Slug, IndexedBooks) ->
    case ordered_books(Slug) of
        {ok, CatalogBooks} ->
            case lists:all(fun({IndexBook, _}) -> IndexBook > 0 andalso IndexBook =< length(CatalogBooks) end, IndexedBooks) of
                true -> {ok, [describe_indexed_book(IndexedBook, CatalogBooks) || IndexedBook <- IndexedBooks]};
                false -> {error, catalog_mismatch}
            end;
        Error -> Error
    end.

index_book(Slug, SourceBookId) ->
    case ordered_books(Slug) of
        {ok, CatalogBooks} ->
            case [Index || {Index, Book} <- lists:zip(lists:seq(1, length(CatalogBooks)), CatalogBooks),
                           maps:get(<<"bookid">>, Book) =:= SourceBookId] of
                [Index] -> {ok, Index};
                _ -> {error, book_not_found}
            end;
        {error, translation_not_found} -> {ok, SourceBookId};
        Error -> Error
    end.

ordered_books(Slug) ->
    case books(Slug) of
        {ok, CatalogBooks} ->
            {ok, lists:sort(fun(Left, Right) -> maps:get(<<"bookid">>, Left) =< maps:get(<<"bookid">>, Right) end, CatalogBooks)};
        Error -> Error
    end.

describe_indexed_book({IndexBook, Chapters}, CatalogBooks) ->
    CatalogBook = lists:nth(IndexBook, CatalogBooks),
    #{book => maps:get(<<"bookid">>, CatalogBook), name => maps:get(<<"name">>, CatalogBook),
      chapters => [#{chapter => Chapter, verses => Verses} || {Chapter, Verses} <- Chapters]}.

normalize(Value) ->
    Decomposed = unicode:characters_to_list(unicode:characters_to_nfkd_binary(Value)),
    string:casefold([Character || Character <- Decomposed, not combining_mark(Character)]).
combining_mark(Character) -> Character >= 16#0300 andalso Character =< 16#036F.

config_path(Name) ->
    case code:priv_dir(bibleit_server) of
        {error, bad_name} -> bundled_config_path(Name);
        Priv ->
            Candidate = filename:join([Priv, "config", Name]),
            case filelib:is_file(Candidate) of true -> Candidate; false -> bundled_config_path(Name) end
    end.

bundled_config_path(Name) ->
    Root = filename:dirname(filename:dirname(code:which(?MODULE))),
    filename:join([Root, "..", "config", Name]).
