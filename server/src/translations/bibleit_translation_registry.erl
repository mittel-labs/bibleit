-module(bibleit_translation_registry).
-behaviour(gen_server).
-export([start_link/0, list/0, catalog/1, read/2, read/3, read/4, search/3, paths/1, invalidate/1, delete/1, delete_all/0]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
list() -> gen_server:call(?MODULE, list).
catalog(Slug) -> with_handle(Slug, fun(H) -> bibleit_translation_nif:catalog(H) end).
read(Slug, Book) -> with_index_book(Slug, Book, fun(H, IndexBook) -> bibleit_translation_nif:read_book(H, IndexBook) end).
read(Slug, Book, Chapter) -> with_index_book(Slug, Book, fun(H, IndexBook) -> bibleit_translation_nif:read_chapter(H, IndexBook, Chapter) end).
read(Slug, Book, Chapter, Verse) -> with_index_book(Slug, Book, fun(H, IndexBook) -> bibleit_translation_nif:read(H, IndexBook, Chapter, Verse) end).
search(Slug, Query, Limit) -> with_handle(Slug, fun(H) -> bibleit_translation_nif:search(H, Query, Limit) end).
paths(Slug) ->
    case directory() of
        {ok, Dir} ->
            case file:list_dir(Dir) of
                {ok, Files} ->
                    Matches = [filename:rootname(File) || File <- Files,
                               filename:extension(File) =:= ".bt",
                               normalize(list_to_binary(filename:rootname(File))) =:= normalize(Slug)],
                    case Matches of
                        [Name] -> {ok, list_to_binary(filename:join(Dir, Name ++ ".bt")), list_to_binary(filename:join(Dir, Name ++ ".bidx"))};
                        _ -> {error, translation_not_found}
                    end;
                _ -> {error, translations_unavailable}
            end;
        Error -> Error
    end.
invalidate(Slug) -> gen_server:call(?MODULE, {invalidate, normalize(Slug)}).
delete(Slug) -> gen_server:call(?MODULE, {delete, normalize(Slug)}).
delete_all() -> gen_server:call(?MODULE, delete_all).

init([]) -> {ok, #{translations => #{}, monitors => #{}}}.
handle_call(list, _From, State) -> {reply, list_files(), State};
handle_call({handle, Slug}, _From, State) ->
    case maps:find(Slug, maps:get(translations, State)) of
        {ok, Pid} -> {reply, bibleit_translation:handle(Pid), State};
        error -> start_translation(Slug, State)
    end;
handle_call({invalidate, Slug}, _From, State) ->
    case maps:take(Slug, maps:get(translations, State)) of
        {Pid, Translations} ->
            {Ref, Monitors} = remove_monitor_for(Slug, maps:get(monitors, State)),
            erlang:demonitor(Ref, [flush]), exit(Pid, kill),
            {reply, ok, State#{translations => Translations, monitors => Monitors}};
        error -> {reply, ok, State}
    end;
handle_call({delete, Slug}, _From, State) ->
    case delete_translation(Slug, State) of
        {ok, Next} -> {reply, {ok, Slug}, Next};
        {error, Error, Next} -> {reply, {error, Error}, Next}
    end;
handle_call(delete_all, _From, State) ->
    case list_files() of
        {ok, Slugs} ->
            {Count, Next} = lists:foldl(fun(Slug, {Total, Acc}) ->
                case delete_translation(normalize(Slug), Acc) of
                    {ok, Updated} -> {Total + 1, Updated};
                    {error, _, Updated} -> {Total, Updated}
                end
            end, {0, State}, Slugs),
            {reply, {ok, Count}, Next};
        {error, Error} -> {reply, {error, Error}, State}
    end;
handle_call(_, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_, State) -> {noreply, State}.
handle_info({'DOWN', Ref, process, _Pid, _Reason}, State) ->
    case maps:take(Ref, maps:get(monitors, State)) of
        {Slug, Monitors} -> {noreply, State#{translations => maps:remove(Slug, maps:get(translations, State)), monitors => Monitors}};
        error -> {noreply, State}
    end;
handle_info(_, State) -> {noreply, State}.
terminate(_, _) -> ok.
code_change(_, State, _) -> {ok, State}.

with_handle(Slug, Read) ->
    case gen_server:call(?MODULE, {handle, normalize(Slug)}) of
        {ok, Handle} ->
            try normalize_result(Read(Handle)) catch error:badarg -> {error, translation_error} end;
        Error -> Error
    end.
with_index_book(Slug, Book, Read) ->
    case bibleit_translation_catalog:index_book(Slug, Book) of
        {ok, IndexBook} -> with_handle(Slug, fun(Handle) -> Read(Handle, IndexBook) end);
        Error -> Error
    end.
normalize_result({ok, _} = Result) -> Result;
normalize_result(book_not_found) -> {error, book_not_found};
normalize_result(chapter_not_found) -> {error, chapter_not_found};
normalize_result(verse_not_found) -> {error, verse_not_found};
normalize_result(not_found) -> {error, not_found};
normalize_result({error, _} = Error) -> Error;
normalize_result(_) -> {error, translation_error}.
start_translation(Slug, State) ->
    case paths(Slug) of
        {ok, _, _} ->
            case bibleit_translation:start(Slug) of
                {ok, Pid} ->
                    Ref = erlang:monitor(process, Pid), {ok, Handle} = bibleit_translation:handle(Pid),
                    Translations = maps:get(translations, State), Monitors = maps:get(monitors, State),
                    {reply, {ok, Handle}, State#{translations => Translations#{Slug => Pid}, monitors => Monitors#{Ref => Slug}}};
                {error, Reason} -> {reply, {error, Reason}, State}
            end;
        Error -> {reply, Error, State}
    end.
list_files() ->
    case directory() of
        {ok, Dir} -> case file:list_dir(Dir) of {ok, Files} -> {ok, lists:sort([list_to_binary(filename:rootname(F)) || F <- Files, filename:extension(F) =:= ".bt"])}; _ -> {error, translations_unavailable} end;
        Error -> Error
    end.
directory() -> case application:get_env(bibleit_server, translations_dir) of {ok, V} when is_list(V) -> {ok, V}; {ok, V} when is_binary(V) -> {ok, binary_to_list(V)}; undefined -> {ok, filename:join(os:getenv("HOME"), ".bibleit")} end.
normalize(Value) -> unicode:characters_to_binary(string:casefold(unicode:characters_to_list(Value))).
remove_monitor_for(Slug, Monitors) ->
    [Ref] = [CandidateRef || {CandidateRef, CandidateSlug} <- maps:to_list(Monitors), CandidateSlug =:= Slug],
    {Ref, maps:remove(Ref, Monitors)}.
delete_translation(Slug, State) ->
    case paths(Slug) of
        {ok, Translation, Index} ->
            Next = invalidate_state(Slug, State),
            Files = [binary_to_list(Translation), binary_to_list(Index), binary_to_list(Translation) ++ ".bsearch"],
            case [File || File <- Files, file:delete(File) =/= ok, filelib:is_file(File)] of
                [] -> {ok, Next};
                _ -> {error, delete_failed, Next}
            end;
        {error, Error} -> {error, Error, State}
    end.
invalidate_state(Slug, State) ->
    case maps:take(Slug, maps:get(translations, State)) of
        {Pid, Translations} ->
            {Ref, Monitors} = remove_monitor_for(Slug, maps:get(monitors, State)),
            erlang:demonitor(Ref, [flush]), exit(Pid, kill),
            State#{translations => Translations, monitors => Monitors};
        error -> State
    end.
