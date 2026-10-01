-module(bibleit_ssh_identity).
-behaviour(gen_server).

%% Bridges OTP SSH's key-validation callback to its channel process. The SSH
%% library invokes the key callback in the connection handler, and hands that
%% same handler pid to ssh_server_channel as Connection. Keeping this tiny
%% supervised registry lets a verified key establish identity without trusting
%% the SSH username or sending an internal protocol request over the network.

-export([start_link/0, remember/3, lookup/1]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
remember(Connection, Actor, Fingerprint) when is_pid(Connection), is_binary(Actor), is_binary(Fingerprint) ->
    gen_server:call(?MODULE, {remember, Connection, Actor, Fingerprint}).
lookup(Connection) when is_pid(Connection) -> gen_server:call(?MODULE, {lookup, Connection}).

init([]) -> {ok, #{identities => #{}, monitors => #{}}}.

handle_call({remember, Connection, Actor, Fingerprint}, _From, State0) ->
    {State, _} = remove_identity(Connection, State0),
    Reference = erlang:monitor(process, Connection),
    Identity = #{actor => Actor, key_fingerprint => Fingerprint},
    Identities = maps:put(Connection, Identity, maps:get(identities, State)),
    Monitors = maps:put(Reference, Connection, maps:get(monitors, State)),
    {reply, ok, State#{identities => Identities, monitors => Monitors}};
handle_call({lookup, Connection}, _From, State) ->
    {reply, maps:find(Connection, maps:get(identities, State)), State};
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.

handle_cast(_Message, State) -> {noreply, State}.
handle_info({'DOWN', Reference, process, _Connection, _Reason}, State) ->
    case maps:take(Reference, maps:get(monitors, State)) of
        {Connection, Monitors} ->
            {noreply, State#{identities => maps:remove(Connection, maps:get(identities, State)), monitors => Monitors}};
        error -> {noreply, State}
    end;
handle_info(_Message, State) -> {noreply, State}.
terminate(_Reason, _State) -> ok.
code_change(_OldVsn, State, _Extra) -> {ok, State}.

remove_identity(Connection, State) ->
    case maps:take(Connection, maps:get(identities, State)) of
        {_, Identities} ->
            {Reference, _} = lists:keyfind(Connection, 2, maps:to_list(maps:get(monitors, State))),
            erlang:demonitor(Reference, [flush]),
            {State#{identities => Identities, monitors => maps:remove(Reference, maps:get(monitors, State))}, ok};
        error -> {State, ok}
    end.
