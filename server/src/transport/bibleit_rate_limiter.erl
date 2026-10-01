-module(bibleit_rate_limiter).
-behaviour(gen_server).

-export([start_link/0, admit/1, release/2, authenticated/1, unauthenticated/1, request/2, bad_command/1, failed_login/1, limits/0]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

%% Transport counters intentionally live only in memory.  They are shared by
%% every TCP connection, so reconnecting does not evade an IP budget.

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
admit(Ip) -> call({admit, Ip}).
release(Ip, Authenticated) -> cast({release, Ip, Authenticated}).
authenticated(Ip) -> cast({authenticated, Ip}).
unauthenticated(Ip) -> cast({unauthenticated, Ip}).
request(Ip, Cost) -> call({request, Ip, Cost}).
bad_command(Ip) -> call({bad_command, Ip}).
failed_login(Ip) -> call({failed_login, Ip}).
limits() -> application:get_env(bibleit_server, limits, #{}).

init([]) -> {ok, #{connections => #{}, unauthenticated => #{}, windows => #{}}}.

handle_call({admit, Ip}, _From, State) ->
    case admission_allowed(Ip, State) of
        ok ->
            case charge(connection, Ip, 1, connection_limit(), State) of
                {ok, Charged} -> {reply, ok, increment_connection(Ip, Charged)};
                {Error, Charged} -> {reply, Error, Charged}
            end;
        Error -> {reply, Error, State}
    end;
handle_call({request, Ip, Cost}, _From, State) ->
    {Result, Next} = charge(request, Ip, Cost, request_limit(), State),
    {reply, Result, Next};
handle_call({bad_command, Ip}, _From, State) ->
    {Result, Next} = charge(bad_command, Ip, 1, bad_command_limit(), State),
    {reply, Result, Next};
handle_call({failed_login, Ip}, _From, State) ->
    {Result, Next} = charge(failed_login, Ip, 1, failed_login_limit(), State),
    case Result of
        ok -> {reply, ok, Next};
        {error, rate_limited, Retry} -> {reply, {disconnect, Retry}, Next}
    end;
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.

handle_cast({release, Ip, WasAuthenticated}, State) ->
    Next = decrement(Ip, connections, State),
    case WasAuthenticated of true -> {noreply, Next}; false -> {noreply, decrement(Ip, unauthenticated, Next)} end;
handle_cast({authenticated, Ip}, State) -> {noreply, decrement(Ip, unauthenticated, State)};
handle_cast({unauthenticated, Ip}, State) -> {noreply, increment(Ip, unauthenticated, State)};
handle_cast(_Message, State) -> {noreply, State}.
handle_info(_Info, State) -> {noreply, State}.
terminate(_Reason, _State) -> ok.
code_change(_OldVsn, State, _Extra) -> {ok, State}.

call(Request) -> case whereis(?MODULE) of undefined -> ok; _ -> gen_server:call(?MODULE, Request) end.
cast(Request) -> case whereis(?MODULE) of undefined -> ok; _ -> gen_server:cast(?MODULE, Request) end.

admission_allowed(Ip, State) ->
    Connections = maps:get(connections, State),
    Unauthenticated = maps:get(unauthenticated, State),
    case map_total(Connections) >= limit(max_connections, 1000) of
        true -> {error, rate_limited, retry_window_ms()};
        false -> case maps:get(Ip, Connections, 0) >= limit(max_connections_per_ip, 20) of
            true -> {error, rate_limited, retry_window_ms()};
            false -> case maps:get(Ip, Unauthenticated, 0) >= limit(max_unauthenticated_connections_per_ip, 5) of
                true -> {error, rate_limited, retry_window_ms()};
                false -> ok
            end
        end
    end.

increment_connection(Ip, State) ->
    WithConnection = increment(Ip, connections, State),
    increment(Ip, unauthenticated, WithConnection).

increment(Ip, Key, State) ->
    Values = maps:get(Key, State), State#{Key => Values#{Ip => maps:get(Ip, Values, 0) + 1}}.
decrement(Ip, Key, State) ->
    Values = maps:get(Key, State),
    case maps:get(Ip, Values, 0) of
        N when N > 1 -> State#{Key => Values#{Ip => N - 1}};
        _ -> State#{Key => maps:remove(Ip, Values)}
    end.

charge(Kind, Ip, Cost, #{limit := Limit, window_ms := Window}, State) ->
    Now = erlang:monotonic_time(millisecond),
    Windows = maps:get(windows, State),
    ByKind = maps:get(Kind, Windows, #{}),
    Previous = [Entry || Entry = {At, _} <- maps:get(Ip, ByKind, []), At > Now - Window],
    Used = lists:sum([Value || {_At, Value} <- Previous]),
    case Used + Cost =< Limit of
        true -> {ok, State#{windows => Windows#{Kind => ByKind#{Ip => [{Now, Cost} | Previous]}}}};
        false ->
            Retry = case lists:reverse(Previous) of [{Oldest, _} | _] -> max(1, Window - (Now - Oldest)); [] -> Window end,
            {{error, rate_limited, Retry}, State#{windows => Windows#{Kind => ByKind#{Ip => Previous}}}}
    end.

connection_limit() -> window_limit(new_connections_per_ip, 30, 60000).
request_limit() -> window_limit(max_requests_per_ip, 600, 60000).
bad_command_limit() -> window_limit(bad_commands_per_ip, 20, 60000).
failed_login_limit() -> window_limit(failed_logins_per_ip, 5, 60000).
retry_window_ms() -> maps:get(window_ms, connection_limit()).
window_limit(Key, DefaultLimit, DefaultWindow) ->
    case limit_value(Key, #{limit => DefaultLimit, window_ms => DefaultWindow}) of
        #{limit := Limit, window_ms := Window} when is_integer(Limit), Limit > 0, is_integer(Window), Window > 0 -> #{limit => Limit, window_ms => Window};
        _ -> #{limit => DefaultLimit, window_ms => DefaultWindow}
    end.
limit(Key, Default) ->
    case limit_value(Key, Default) of Value when is_integer(Value), Value > 0 -> Value; _ -> Default end.
limit_value(Key, Default) -> maps:get(Key, limits(), Default).
map_total(Map) -> lists:sum(maps:values(Map)).
