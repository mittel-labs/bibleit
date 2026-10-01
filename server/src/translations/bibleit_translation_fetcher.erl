-module(bibleit_translation_fetcher).
-export([fetch/1, install/3]).

-define(SOURCES, ["https://bolls.life/static/translations/~s.json",
                  "https://raw.githubusercontent.com/mittel-labs/bibleit/refs/heads/main/config/~s.json"]).

fetch(Slug) ->
    case bibleit_translation_catalog:canonical_slug(Slug) of
        {ok, CanonicalSlug} ->
            case bibleit_translation_catalog:books(CanonicalSlug) of
                {ok, Books} ->
                    case download(binary_to_list(CanonicalSlug)) of
                        {ok, Entries} -> install(CanonicalSlug, Books, Entries);
                        Error -> Error
                    end;
                Error -> Error
            end;
        Error -> Error
    end.

install(Slug, Books, Entries) when is_binary(Slug), is_list(Books), is_list(Entries) ->
    case directory() of
        {ok, Directory} ->
            ok = filelib:ensure_dir(filename:join(Directory, "placeholder")),
            Name = binary_to_list(Slug),
            Unique = integer_to_list(erlang:unique_integer([positive])),
            Translation = filename:join(Directory, Name ++ ".bt"),
            Index = filename:join(Directory, Name ++ ".bidx"),
            TemporaryTranslation = Translation ++ "." ++ Unique ++ ".tmp",
            TemporaryIndex = Index ++ "." ++ Unique ++ ".tmp",
            case translation_data(Books, Entries) of
                {ok, Data} ->
                    case file:write_file(TemporaryTranslation, Data) of
                        ok -> install_index(TemporaryTranslation, TemporaryIndex, Translation, Index, Slug);
                        _ -> {error, write_failed}
                    end;
                Error -> Error
            end;
        Error -> Error
    end.

install_index(TemporaryTranslation, TemporaryIndex, Translation, Index, Slug) ->
    case bibleit_translation_nif:create_index(list_to_binary(TemporaryTranslation), list_to_binary(TemporaryIndex)) of
        ok ->
            ok = file:rename(TemporaryTranslation, Translation),
            ok = file:rename(TemporaryIndex, Index),
            _ = file:delete(Translation ++ ".bsearch"),
            maybe_invalidate(Slug),
            {ok, Slug};
        _ ->
            _ = file:delete(TemporaryTranslation), _ = file:delete(TemporaryIndex),
            {error, index_create_failed}
    end.

download(Slug) ->
    _ = application:ensure_started(inets),
    _ = application:ensure_started(ssl),
    download(Slug, ?SOURCES).
download(_Slug, []) -> {error, fetch_failed};
download(Slug, [Source | Rest]) ->
    Url = lists:flatten(io_lib:format(Source, [Slug])),
    case httpc:request(get, {Url, []}, [{connect_timeout, 3000}, {timeout, 10000}], [{body_format, binary}]) of
        {ok, {{_, 200, _}, _, Body}} ->
            try {ok, json:decode(Body)} catch _:_ -> {error, invalid_translation_data} end;
        _ -> download(Slug, Rest)
    end.

translation_data(Books, Entries) ->
    Names = maps:from_list([{maps:get(<<"bookid">>, Book), maps:get(<<"name">>, Book)} || Book <- Books]),
    try
        Rows = lists:sort([{maps:get(<<"book">>, Entry), maps:get(<<"chapter">>, Entry), maps:get(<<"verse">>, Entry), maps:get(<<"text">>, Entry)} || Entry <- Entries]),
        {ok, iolist_to_binary([line(maps:get(Book, Names), Chapter, Verse, Text) || {Book, Chapter, Verse, Text} <- Rows])}
    catch error:{badkey, _} -> {error, invalid_translation_data}; error:badarg -> {error, invalid_translation_data} end.
line(Book, Chapter, Verse, Text) ->
    CleanText = binary:replace(binary:replace(Text, <<"\r">>, <<" ">>, [global]), <<"\n">>, <<" ">>, [global]),
    [Book, " ", integer_to_binary(Chapter), ":", integer_to_binary(Verse), " ", CleanText, "\n"].
directory() ->
    case application:get_env(bibleit_server, translations_dir) of
        {ok, Value} when is_binary(Value) -> {ok, binary_to_list(Value)};
        {ok, Value} when is_list(Value) -> {ok, Value};
        undefined -> {ok, filename:join(os:getenv("HOME"), ".bibleit")}
    end.
maybe_invalidate(Slug) -> case whereis(bibleit_translation_registry) of undefined -> ok; _ -> bibleit_translation_registry:invalidate(Slug) end.
