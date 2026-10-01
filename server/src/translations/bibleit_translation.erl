-module(bibleit_translation).
-behaviour(gen_server).
-export([start/1, handle/1]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

start(Slug) -> gen_server:start(?MODULE, Slug, []).
handle(Pid) -> gen_server:call(Pid, handle).
init(Slug) ->
    case bibleit_translation_registry:paths(Slug) of
        {ok, Translation, Index} ->
            case bibleit_translation_nif:open(Translation, Index) of
                {ok, Handle} -> {ok, #{handle => Handle}};
                {error, _} -> {stop, translation_not_found}
            end;
        {error, Reason} -> {stop, Reason}
    end.
handle_call(handle, _From, #{handle := Handle} = State) -> {reply, {ok, Handle}, State};
handle_call(_, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_, State) -> {noreply, State}.
handle_info(_, State) -> {noreply, State}.
terminate(_, _) -> ok.
code_change(_, State, _) -> {ok, State}.
