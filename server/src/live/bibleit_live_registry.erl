-module(bibleit_live_registry).
-behaviour(gen_server).
-export([start_link/0, create/2, create/3, remove/2, remove_all/1, lookup/1, list/1, count_owned/1]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
create(Owner, Options) -> gen_server:call(?MODULE, {create, Owner, Options}).
create(Owner, Options, Limit) -> gen_server:call(?MODULE, {create, Owner, Options, Limit}).
remove(Id, Actor) -> gen_server:call(?MODULE, {remove, Id, Actor}).
remove_all(Actor) -> gen_server:call(?MODULE, {remove_all, Actor}).
lookup(Id) -> gen_server:call(?MODULE, {lookup, Id}).
list(Actor) -> gen_server:call(?MODULE, {list, Actor}).
count_owned(Actor) -> gen_server:call(?MODULE, {count_owned, Actor}).
init([]) -> {ok, restore_lives(#{lives => #{}, monitors => #{}})}.
handle_call({create, Owner, Options}, _From, State) ->
    create_live(Owner, Options, unlimited, State);
handle_call({create, Owner, Options, Limit}, _From, State) ->
    create_live(Owner, Options, Limit, State);
handle_call({lookup, Id}, _From, State) ->
    {reply, maps:find(Id, maps:get(lives, State)), State};
handle_call({remove, Id, Actor}, _From, State) ->
    case remove_live(Id, Actor, State) of
        {ok, Next} -> {reply, ok, Next};
        {error, Error} -> {reply, {error, Error}, State}
    end;
handle_call({remove_all, Actor}, _From, State) ->
    {Count, Next} = lists:foldl(fun(Id, {Removed, Current}) ->
        case remove_live(Id, Actor, Current) of
            {ok, Updated} -> {Removed + 1, Updated};
            {error, _} -> {Removed, Current}
        end
    end, {0, State}, maps:keys(maps:get(lives, State))),
    {reply, {ok, Count}, Next};
handle_call({list, Actor}, _From, State) ->
    Result = maps:fold(fun(_Id, Pid, Acc) ->
        Owner = bibleit_live_session:owner(Pid),
        case bibleit_authorization:can_manage_actor(Actor, Owner) of
            true -> [(bibleit_live_session:public(Pid))#{created_by => Owner} | Acc];
            false -> Acc
        end
    end, [], maps:get(lives, State)),
    {reply, {ok, lists:sort(fun(A, B) -> maps:get(id, A) =< maps:get(id, B) end, Result)}, State};
handle_call({count_owned, Actor}, _From, State) ->
    {reply, count_owned(Actor, State), State};
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.

create_live(Owner, Options, Limit, State) ->
    case quota_available(Owner, Limit, State) of
        false -> {reply, {error, quota_exceeded}, State};
        true -> create_live_unchecked(Owner, Options, State)
    end.
create_live_unchecked(Owner, Options, State) ->
    Id = unique_id(maps:get(lives, State)),
    case bibleit_live_session_sup:start_child(Id, Owner, Options) of
        {ok, Pid} ->
            case save_live(Pid) of
                ok ->
                    Ref = erlang:monitor(process, Pid),
                    Lives = maps:get(lives, State), Monitors = maps:get(monitors, State),
                    {reply, {ok, Id, bibleit_live_session:public(Pid)},
                     State#{lives => Lives#{Id => Pid}, monitors => Monitors#{Ref => Id}}};
                {error, _} -> exit(Pid, shutdown), {reply, {error, persistence_failed}, State}
            end;
        {error, Reason} -> {reply, {error, Reason}, State}
    end.
handle_cast(_Message, State) -> {noreply, State}.
handle_info({'DOWN', Ref, process, _Pid, _Reason}, State) ->
    Monitors = maps:get(monitors, State),
    case maps:take(Ref, Monitors) of
        {Id, Remaining} ->
            Lives = maps:remove(Id, maps:get(lives, State)),
            Cleared = State#{lives => Lives, monitors => Remaining},
            {noreply, restore_live(Id, Cleared)};
        error -> {noreply, State}
    end;
handle_info(_Info, State) -> {noreply, State}.
terminate(_Reason, _State) -> ok.
code_change(_OldVsn, State, _Extra) -> {ok, State}.

unique_id(Lives) ->
    Id = base62(crypto:strong_rand_bytes(8)),
    case maps:is_key(Id, Lives) of true -> unique_id(Lives); false -> Id end.

base62(Bytes) ->
    Alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    Value = binary:decode_unsigned(Bytes),
    list_to_binary(base62(Value, Alphabet, [])).
base62(0, _Alphabet, []) -> "0";
base62(0, _Alphabet, Acc) -> Acc;
base62(Value, Alphabet, Acc) ->
    Index = Value rem 62,
    base62(Value div 62, Alphabet, [lists:nth(Index + 1, Alphabet) | Acc]).
quota_available(_Owner, unlimited, _State) -> true;
quota_available(Owner, Limit, State) when is_integer(Limit), Limit > 0 ->
    count_owned(Owner, State) < Limit.
count_owned(Actor, State) ->
    maps:fold(fun(_Id, Pid, Total) ->
        case bibleit_live_session:owner(Pid) of Actor -> Total + 1; _ -> Total end
    end, 0, maps:get(lives, State)).

save_live(Pid) ->
    case whereis(bibleit_live_store) of
        undefined -> ok;
        _ -> bibleit_live_store:save(bibleit_live_session:persisted(Pid))
    end.

restore_lives(State) ->
    case whereis(bibleit_live_store) of
        undefined -> State;
        _ ->
            case bibleit_live_store:list() of
                {ok, Lives} -> lists:foldl(fun restore_saved_live/2, State, Lives);
                _ -> State
            end
    end.
restore_saved_live(#{schema_version := 1, id := Id} = Live, State) ->
    case bibleit_live_session_sup:start_child(Id, undefined, #{saved => Live}) of
        {ok, Pid} ->
            Ref = erlang:monitor(process, Pid),
            State#{lives => (maps:get(lives, State))#{Id => Pid}, monitors => (maps:get(monitors, State))#{Ref => Id}};
        _ -> State
    end;
restore_saved_live(#{id := Id}, State) ->
    ok = delete_live(Id),
    State.
restore_live(Id, State) ->
    case whereis(bibleit_live_store) of
        undefined -> State;
        _ ->
            case bibleit_live_store:get(Id) of
                {ok, Live} -> restore_saved_live(Live, State);
                _ -> State
            end
    end.
delete_live(Id) ->
    case whereis(bibleit_live_store) of
        undefined -> ok;
        _ -> bibleit_live_store:delete(Id)
    end.
monitor_for(Id, Monitors) ->
    case [Ref || {Ref, MonitoredId} <- maps:to_list(Monitors), MonitoredId =:= Id] of
        [Ref] -> {Ref, maps:remove(Ref, Monitors)}
    end.
remove_live(Id, Actor, State) ->
    case maps:find(Id, maps:get(lives, State)) of
        error -> {error, not_found};
        {ok, Pid} ->
            case bibleit_live_session:remove(Pid, Actor) of
                {error, Error} -> {error, Error};
                ok ->
                    case delete_live(Id) of
                        ok ->
                            {Ref, RemainingMonitors} = monitor_for(Id, maps:get(monitors, State)),
                            erlang:demonitor(Ref, [flush]),
                            exit(Pid, shutdown),
                            {ok, State#{lives => maps:remove(Id, maps:get(lives, State)), monitors => RemainingMonitors}};
                        {error, _} -> {error, persistence_failed}
                    end
            end
    end.
