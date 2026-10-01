-module(bibleit_translation_available).
-behaviour(gen_server).
-export([start_link/0, list/0, info/1]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
list() -> gen_server:call(?MODULE, list).
info(Slug) -> gen_server:call(?MODULE, {info, Slug}).

init([]) ->
    Path = cache_path(),
    case ensure_cache(Path) of
        ok -> {ok, #{path => Path}};
        _ -> {stop, available_translations_unavailable}
    end.
handle_call(list, _From, #{path := Path} = State) ->
    case translations(Path) of
        {ok, Translations} -> {reply, {ok, lists:sort([maps:get(<<"short_name">>, Translation) || Translation <- Translations])}, State};
        Error -> {reply, Error, State}
    end;
handle_call({info, Slug}, _From, #{path := Path} = State) ->
    case translations(Path) of
        {ok, Translations} ->
            Matches = [Translation || Translation <- Translations, normalize(maps:get(<<"short_name">>, Translation)) =:= normalize(Slug)],
            case Matches of
                [Translation] -> {reply, {ok, translation_info(Translation)}, State};
                _ -> {reply, {error, translation_not_found}, State}
            end;
        Error -> {reply, Error, State}
    end;
handle_call(_, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_, State) -> {noreply, State}.
handle_info(_, State) -> {noreply, State}.
terminate(_, _) -> ok.
code_change(_, State, _) -> {ok, State}.

cache_path() -> filename:join(directory(), "available_translations.json").
directory() ->
    case application:get_env(bibleit_server, translations_dir) of
        {ok, Value} when is_binary(Value) -> binary_to_list(Value);
        {ok, Value} when is_list(Value) -> Value;
        undefined -> filename:join(os:getenv("HOME"), ".bibleit")
    end.
ensure_cache(Path) ->
    case filelib:is_file(Path) of
        true -> ok;
        false ->
            Source = config_path("languages.json"),
            ok = filelib:ensure_dir(Path),
            case file:read_file(Source) of {ok, Data} -> file:write_file(Path, Data); Error -> Error end
    end.
translations(Path) ->
    case file:read_file(Path) of
        {ok, Data} ->
            try {ok, [Translation || Language <- json:decode(Data), Translation <- maps:get(<<"translations">>, Language)]}
            catch _:_ -> {error, available_translations_unavailable} end;
        _ -> {error, available_translations_unavailable}
    end.
translation_info(Translation) ->
    maps:with([<<"short_name">>, <<"full_name">>, <<"updated">>], Translation).
normalize(Value) -> unicode:characters_to_binary(string:casefold(unicode:characters_to_list(Value))).

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
