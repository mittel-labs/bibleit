-module(bibleit_translation_integration_tests).
-include_lib("eunit/include/eunit.hrl").

translation_protocol_test_() ->
    {setup, fun setup/0, fun cleanup/1,
     fun(Context) -> [fun numeric_and_named_reads/0, fun search_and_cached_actor/0, fun translation_books_describe_client_catalog/0, fun catalog_preserves_source_book_ids/0, fun available_translations_cache_is_seeded/0, fun installs_downloaded_translation/0, fun specific_translation_errors/0, fun() -> live_stack_publishes_verse_payload(Context) end] end}.

setup() ->
    Directory = filename:join("/tmp", "bibleit-server-translation-" ++
                              integer_to_list(erlang:system_time(nanosecond)) ++ "-" ++
                              integer_to_list(erlang:unique_integer([positive]))),
    ok = file:make_dir(Directory),
    Translation = filename:join(Directory, "nvipt.bt"),
    Index = filename:join(Directory, "nvipt.bidx"),
    ok = file:write_file(Translation, fixture()),
    ok = bibleit_translation_nif:create_index(list_to_binary(Translation), list_to_binary(Index)),
    KJVTranslation = filename:join(Directory, "kjv.bt"),
    KJVIndex = filename:join(Directory, "kjv.bidx"),
    ok = file:write_file(KJVTranslation, fixture()),
    ok = bibleit_translation_nif:create_index(list_to_binary(KJVTranslation), list_to_binary(KJVIndex)),
    application:set_env(bibleit_server, translations_dir, Directory),
    application:set_env(bibleit_server, search_max_results, 1),
    {ok, Available} = bibleit_translation_available:start_link(),
    {ok, Registry} = bibleit_translation_registry:start_link(),
    {ok, Sessions} = bibleit_live_session_sup:start_link(),
    {ok, Lives} = bibleit_live_registry:start_link(),
    #{directory => Directory, available => Available, registry => Registry, sessions => Sessions, lives => Lives}.

cleanup(#{directory := Directory, available := Available, registry := Registry, sessions := Sessions, lives := Lives}) ->
    unlink(Lives), exit(Lives, shutdown),
    unlink(Sessions), exit(Sessions, shutdown),
    unlink(Registry), exit(Registry, shutdown),
    unlink(Available), exit(Available, shutdown),
    application:unset_env(bibleit_server, translations_dir),
    application:unset_env(bibleit_server, search_max_results),
    [file:delete(filename:join(Directory, Name)) || Name <- ["nvipt.bt", "nvipt.bidx", "nvipt.bt.bsearch", "kjv.bt", "kjv.bidx", "kjv.bt.bsearch", "downloaded.bt", "downloaded.bidx", "downloaded.bt.bsearch", "available_translations.json"]],
    ok = file:del_dir(Directory).

numeric_and_named_reads() ->
    State = #{actor => <<"reader">>, permissions => []},
    {ok, Numeric} = bibleit_protocol:decode(<<"read nvipt 19 23">>),
    {reply, {ok, {verses, NumericFields, NumericLines}}, _} = bibleit_protocol:handle(Numeric, State),
    ?assertEqual(19, proplists:get_value(book, NumericFields)),
    ?assertEqual(2, length(NumericLines)),
    {ok, Named} = bibleit_protocol:decode(<<"READ NVIPT salmos 23 1">>),
    {reply, {ok, NamedFields}, _} = bibleit_protocol:handle(Named, State),
    ?assertEqual(19, proplists:get_value(book, NamedFields)),
    ?assertMatch(<<"Salmos 23:1" , _/binary>>, proplists:get_value(text, NamedFields)),
    {ok, Compact} = bibleit_protocol:decode(<<"read nvipt salmos 23:1">>),
    {reply, {ok, CompactFields}, _} = bibleit_protocol:handle(Compact, State),
    ?assertEqual(1, proplists:get_value(verse, CompactFields)).

search_and_cached_actor() ->
    State = #{actor => <<"searcher">>, permissions => [{translation, search}]},
    {ok, Search} = bibleit_protocol:decode(<<"search NVIPT pastor">>),
    {reply, {ok, {verses, Fields, Lines}}, _} = bibleit_protocol:handle(Search, State),
    ?assertEqual(1, proplists:get_value(results, Fields)),
    ?assertEqual(1, length(Lines)),
    RegistryState = sys:get_state(bibleit_translation_registry),
    ?assertEqual(1, map_size(maps:get(translations, RegistryState))).

translation_books_describe_client_catalog() ->
    State = #{actor => <<"catalog-reader">>, permissions => [{translation, get}]},
    {ok, Request} = bibleit_protocol:decode(<<"translation catalog nvipt">>),
    {reply, {ok, {books, <<"nvipt">>, Books}}, _} = bibleit_protocol:handle(Request, State),
    Psalms = lists:keyfind(19, 1, [{maps:get(book, Book), Book} || Book <- Books]),
    {19, PsalmBook} = Psalms,
    ?assertEqual(<<"Salmos">>, maps:get(name, PsalmBook)),
    ?assertEqual([#{chapter => 1, verses => 1}, #{chapter => 23, verses => 2}], maps:get(chapters, PsalmBook)),
    Encoded = iolist_to_binary(bibleit_protocol:encode({ok, {books, <<"nvipt">>, Books}})),
    ?assertMatch(<<"OK translation=\"nvipt\" books=19\n", _/binary>>, Encoded),
    ?assertNotEqual(nomatch, binary:match(Encoded, <<"CHAPTER book=19 chapter=23 verses=2">>)).

catalog_preserves_source_book_ids() ->
    {ok, [Azariah]} = bibleit_translation_catalog:describe_books(<<"KJV">>, [{81, [{1, 68}]}]),
    ?assertEqual(88, maps:get(book, Azariah)),
    ?assertEqual(<<"Azariah">>, maps:get(name, Azariah)),
    ?assertEqual({ok, 81}, bibleit_translation_catalog:index_book(<<"KJV">>, 88)).

available_translations_cache_is_seeded() ->
    {ok, Slugs} = bibleit_translation_available:list(),
    ?assert(lists:member(<<"CEVD">>, Slugs)),
    {ok, Info} = bibleit_translation_available:info(<<"kja">>),
    ?assertEqual(<<"KJA">>, maps:get(<<"short_name">>, Info)),
    ?assert(is_binary(maps:get(<<"full_name">>, Info))).

installs_downloaded_translation() ->
    Books = [#{<<"bookid">> => 1, <<"name">> => <<"Genesis">>}],
    Entries = [#{<<"book">> => 1, <<"chapter">> => 1, <<"verse">> => 1, <<"text">> => <<"Downloaded text.">>}],
    {ok, <<"downloaded">>} = bibleit_translation_fetcher:install(<<"downloaded">>, Books, Entries),
    State = #{actor => <<"reader">>, permissions => []},
    {ok, Request} = bibleit_protocol:decode(<<"read downloaded 1 1 1">>),
    {reply, {ok, Fields}, _} = bibleit_protocol:handle(Request, State),
    ?assertMatch(<<"Genesis 1:1 Downloaded text.">>, proplists:get_value(text, Fields)),
    {ok, <<"downloaded">>} = bibleit_translation_registry:delete(<<"downloaded">>),
    {reply, {error, translation_not_found}, _} = bibleit_protocol:handle(Request, State).

specific_translation_errors() ->
    State = #{actor => <<"reader">>, permissions => []},
    {ok, MissingBook} = bibleit_protocol:decode(<<"read nvipt 20">>),
    {reply, {error, book_not_found}, _} = bibleit_protocol:handle(MissingBook, State),
    {ok, MissingChapter} = bibleit_protocol:decode(<<"read nvipt 19 99">>),
    {reply, {error, chapter_not_found}, _} = bibleit_protocol:handle(MissingChapter, State),
    {ok, MissingTranslation} = bibleit_protocol:decode(<<"read missing 1">>),
    {reply, {error, translation_not_found}, _} = bibleit_protocol:handle(MissingTranslation, State).

live_stack_publishes_verse_payload(_Context) ->
    {ok, Id, _} = bibleit_live_registry:create(<<"owner">>, #{translations => [<<"kjv">>, <<"nvipt">>]}),
    {ok, Pid} = bibleit_live_registry:lookup(Id),
    {ok, _} = bibleit_live_session:subscribe(Pid, <<"owner">>, self()),
    {ok, Request} = bibleit_protocol:decode(<<"live ", Id/binary, " stack push salmos 23 1">>),
    {reply, {ok, {live_verse, Payload}}, _} = bibleit_protocol:handle(Request, #{actor => <<"owner">>}),
    ?assertEqual(<<"owner">>, maps:get(publisher_id, Payload)),
    ?assertEqual(2, length(maps:get(translations, Payload))),
    ?assertEqual([<<"kjv">>, <<"nvipt">>], [maps:get(translation, Verse) || Verse <- maps:get(translations, Payload)]),
    receive
        {live_verse, Id, Broadcast} -> ?assertEqual(Payload, Broadcast)
    after 1000 -> ?assert(false)
    end,
    {ok, StackRequest} = bibleit_protocol:decode(<<"live ", Id/binary, " stack push salmos 23 2">>),
    {reply, {ok, {live_verse, Stacked}}, _} = bibleit_protocol:handle(StackRequest, #{actor => <<"owner">>}),
    ?assertEqual(4, length(maps:get(translations, Stacked))),
    receive
        {live_verse, Id, StackBroadcast} -> ?assertEqual(Stacked, StackBroadcast)
    after 1000 -> ?assert(false)
    end,
    {ok, StackInfoRequest} = bibleit_protocol:decode(<<"live ", Id/binary, " stack info">>),
    {reply, {ok, {live_stack, Id, StackEntries}}, _} = bibleit_protocol:handle(StackInfoRequest, #{actor => <<"owner">>, permissions => [{live, get}]}),
    ?assertEqual(4, length(StackEntries)),
    ?assertEqual(<<"kjv">>, maps:get(translation, hd(StackEntries))),
    {ok, PopRequest} = bibleit_protocol:decode(<<"live ", Id/binary, " stack pop 2">>),
    {reply, {ok, {live_verse, Popped}}, _} = bibleit_protocol:handle(PopRequest, #{actor => <<"owner">>}),
    ?assertEqual(2, length(maps:get(translations, Popped))),
    receive
        {live_verse, Id, PopBroadcast} -> ?assertEqual(Popped, PopBroadcast)
    after 1000 -> ?assert(false)
    end,
    {ok, PushAgainRequest} = bibleit_protocol:decode(<<"live ", Id/binary, " stack push salmos 23 2">>),
    {reply, {ok, {live_verse, _}}, _} = bibleit_protocol:handle(PushAgainRequest, #{actor => <<"owner">>}),
    receive {live_verse, Id, _} -> ok after 1000 -> ?assert(false) end,
    {ok, ReversePopRequest} = bibleit_protocol:decode(<<"live ", Id/binary, " stack pop -2">>),
    {reply, {ok, {live_verse, ReversePopped}}, _} = bibleit_protocol:handle(ReversePopRequest, #{actor => <<"owner">>}),
    ?assert(lists:all(fun(Verse) -> binary:match(maps:get(reference, Verse), <<"23:2">>) =/= nomatch end, maps:get(translations, ReversePopped))),
    receive {live_verse, Id, ReversePopBroadcast} -> ?assertEqual(ReversePopped, ReversePopBroadcast) after 1000 -> ?assert(false) end,
    {ok, EmptyRequest} = bibleit_protocol:decode(<<"live ", Id/binary, " stack pop 5">>),
    {reply, {ok, live_cleared}, _} = bibleit_protocol:handle(EmptyRequest, #{actor => <<"owner">>}),
    receive {live_clear, Id} -> ok after 1000 -> ?assert(false) end,
    {ok, EmptyPopRequest} = bibleit_protocol:decode(<<"live ", Id/binary, " stack pop">>),
    {reply, {error, stack_empty}, _} = bibleit_protocol:handle(EmptyPopRequest, #{actor => <<"owner">>}),
    {ok, ClearRequest} = bibleit_protocol:decode(<<"live ", Id/binary, " clear">>),
    {reply, {ok, live_cleared}, _} = bibleit_protocol:handle(ClearRequest, #{actor => <<"owner">>}),
    receive
        {live_clear, Id} -> ok
    after 1000 -> ?assert(false)
    end.

fixture() ->
    Prefix = [io_lib:format("Book ~B 1:1 filler~n", [Book]) || Book <- lists:seq(1, 18)],
    iolist_to_binary([Prefix,
                      "Salmos 1:1 filler.\n",
                      "Salmos 23:1 O Senhor é o meu pastor.\n",
                      "Salmos 23:2 O pastor me guia.\n"]).
