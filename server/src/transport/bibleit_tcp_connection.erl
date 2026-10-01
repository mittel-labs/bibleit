-module(bibleit_tcp_connection).
-behaviour(gen_server).
-export([start_link/0]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

start_link() -> gen_server:start_link(?MODULE, [], []).
init([]) -> {ok, #{socket => undefined, actor => undefined, peer_ip => undefined,
                   transport => gen_tcp,
                   limiter_admitted => false, authenticated => false,
                   auth_timer => undefined, auth_timer_handle => undefined,
                   idle_timer => undefined, idle_timer_handle => undefined,
                   request_window => []}}.
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_Message, State) -> {noreply, State}.

%% The two-argument message is retained for unit-level connection supervision.
handle_info({socket_ready, Socket}, State) -> socket_ready(Socket, undefined, State);
handle_info({socket_ready, Socket, Ip}, State) -> socket_ready(Socket, Ip, State);
handle_info({socket_ready, Transport, Socket, Ip}, State) -> socket_ready(Transport, Socket, Ip, State);
handle_info({tcp, Socket, Line}, State) ->
    handle_command(Socket, Line, State);
handle_info({ssl, Socket, Line}, State) ->
    handle_command(Socket, Line, State);
handle_info({authentication_timeout, Token}, #{auth_timer := Token, actor := undefined, socket := Socket} = State) ->
    send_and_stop(Socket, {error, authentication_timeout}, State);
handle_info({authentication_timeout, _Token}, State) -> {noreply, State};
handle_info({idle_timeout, Token}, #{idle_timer := Token, socket := Socket} = State) ->
    send_and_stop(Socket, {error, idle_timeout}, State);
handle_info({idle_timeout, _Token}, State) -> {noreply, State};
handle_info({live_event, Id, Live}, #{socket := Socket} = State) -> send_event(Socket, {event, live, Id, Live}, State);
handle_info({live_verse, _Id, Payload}, #{socket := Socket} = State) -> send_event(Socket, {event, verse, Payload}, State);
handle_info({live_clear, _Id}, #{socket := Socket} = State) -> send_event(Socket, {event, clear}, State);
handle_info({live_paused, _Id}, #{socket := Socket} = State) -> send_event(Socket, {event, paused}, State);
handle_info({live_closed, _Id}, #{socket := Socket} = State) -> send_event(Socket, {event, closed}, State);
handle_info({live_access_revoked, _Id}, #{socket := Socket} = State) -> send_event_and_stop(Socket, {event, revoked}, State);
handle_info({live_event, _Id, _Live}, State) -> {noreply, State};
handle_info({live_verse, _Id, _Payload}, State) -> {noreply, State};
handle_info({live_clear, _Id}, State) -> {noreply, State};
handle_info({live_paused, _Id}, State) -> {noreply, State};
handle_info({live_closed, _Id}, State) -> {noreply, State};
handle_info({live_access_revoked, _Id}, State) -> {noreply, State};
handle_info({tcp_closed, _Socket}, State) -> {stop, normal, State};
handle_info({tcp_error, _Socket, _Reason}, State) -> {stop, normal, State};
handle_info({ssl_closed, _Socket}, State) -> {stop, normal, State};
handle_info({ssl_error, _Socket, _Reason}, State) -> {stop, normal, State};
handle_info(_Info, State) -> {noreply, State}.

terminate(_Reason, State) ->
    cancel_timer(maps:get(auth_timer_handle, State)),
    cancel_timer(maps:get(idle_timer_handle, State)),
    case maps:get(limiter_admitted, State, false) of
        true -> bibleit_rate_limiter:release(maps:get(peer_ip, State), maps:get(authenticated, State));
        false -> ok
    end,
    case maps:get(socket, State) of undefined -> ok; Socket -> _ = socket_close(maps:get(transport, State), Socket), ok end.
code_change(_OldVsn, State, _Extra) -> {ok, State}.

socket_ready(Socket, Ip, State) -> socket_ready(gen_tcp, Socket, Ip, State).
socket_ready(Transport, Socket, Ip, State) ->
    Next0 = State#{socket => Socket, transport => Transport, peer_ip => Ip, limiter_admitted => Ip =/= undefined},
    Hello = {ok, [{server, <<"bibleit">>}, {protocol_version, 1}, {version, bibleit_protocol:version()}, {auth, false}]},
    case send_response(Transport, Socket, Hello) of
        ok ->
            Next = schedule_auth_timeout(refresh_idle(Next0)),
            case arm(Transport, Socket) of ok -> {noreply, Next}; {error, _} -> {stop, normal, Next} end;
        {error, _} -> {stop, normal, Next0}
    end.

handle_command(Socket, Line, State) ->
    Reply = case bibleit_protocol:decode(trim_newline(Line)) of
        {ok, Request} ->
            Cost = bibleit_protocol:request_cost(Request),
            case charge_connection_request(Cost, State) of
                {ok, Charged} -> case bibleit_rate_limiter:request(maps:get(peer_ip, State), Cost) of
                    ok ->
                        {reply, CommandResponse, Handled} = bibleit_protocol:handle(Request, Charged),
                        apply_auth_result(Request, CommandResponse, Charged, Handled);
                    {error, rate_limited, Retry} -> {{error, rate_limited, Retry}, Charged}
                end;
                {error, Retry} -> {{error, rate_limited, Retry}, State}
            end;
        {error, Code} ->
            case bibleit_rate_limiter:bad_command(maps:get(peer_ip, State)) of
                ok -> {{error, Code}, State};
                {error, rate_limited, Retry} -> {{error, rate_limited, Retry}, State}
            end
    end,
    reply_and_arm(Socket, Reply).

apply_auth_result({auth_login_prove, _, _}, {ok, _} = Response, #{authenticated := false} = Old, Next) ->
    mark_authenticated(Response, Old, Next);
apply_auth_result({auth_login_prove, _, _}, {error, _} = Response, Old, Next) ->
    case bibleit_rate_limiter:failed_login(maps:get(peer_ip, Old)) of
        {disconnect, Retry} -> {{error, rate_limited, Retry}, Next#{close_after_reply => true}};
        _ -> {Response, Next}
    end;
apply_auth_result(auth_logout, {ok, _} = Response, #{authenticated := true} = Old, Next) ->
    bibleit_rate_limiter:unauthenticated(maps:get(peer_ip, Old)),
    {Response, schedule_auth_timeout(Next#{authenticated => false})};
apply_auth_result(_Request, Response, _Old, Next) -> {Response, Next}.
mark_authenticated(Response, Old, Next) ->
    bibleit_rate_limiter:authenticated(maps:get(peer_ip, Old)),
    cancel_timer(maps:get(auth_timer_handle, Old)),
    {Response, Next#{authenticated => true, auth_timer => undefined, auth_timer_handle => undefined}}.

reply_and_arm(Socket, {Response, Next0}) ->
    Next = refresh_idle(Next0),
    Transport = maps:get(transport, Next),
    case send_response(Transport, Socket, Response) of
        ok ->
            case maps:get(close_after_reply, Next, false) of
                true -> {stop, normal, Next};
                false -> case arm(Transport, Socket) of ok -> {noreply, Next}; {error, _} -> {stop, normal, Next} end
            end;
        {error, _} -> {stop, normal, Next}
    end.

send_event(Socket, Event, State) ->
    case mailbox_overloaded() of
        true -> send_and_stop(Socket, {error, slow_consumer}, State);
        false -> case send_response(maps:get(transport, State), Socket, Event) of
            ok -> {noreply, refresh_idle(State)};
            {error, _} -> {stop, normal, State}
        end
    end.
send_event_and_stop(Socket, Event, State) -> _ = send_response(maps:get(transport, State), Socket, Event), {stop, normal, State}.
send_and_stop(Socket, Response, State) -> _ = send_response(maps:get(transport, State), Socket, Response), {stop, normal, State}.

send_response(Transport, Socket, Response) ->
    Encoded = bibleit_protocol:encode(Response),
    case iolist_size(Encoded) =< max_response_bytes() of
        true -> socket_send(Transport, Socket, Encoded);
        false -> socket_send(Transport, Socket, bibleit_protocol:encode({error, response_too_large}))
    end.

mailbox_overloaded() ->
    case process_info(self(), message_queue_len) of
        {message_queue_len, Count} -> Count >= limit(max_event_queue_per_connection, 100);
        undefined -> false
    end.
schedule_auth_timeout(State) ->
    cancel_timer(maps:get(auth_timer_handle, State, undefined)),
    case maps:get(authentication_timeout_ms, bibleit_rate_limiter:limits(), disabled) of
        Timeout when is_integer(Timeout), Timeout > 0 ->
            Token = make_ref(),
            Timer = erlang:send_after(Timeout, self(), {authentication_timeout, Token}),
            State#{auth_timer => Token, auth_timer_handle => Timer};
        _ -> State#{auth_timer => undefined, auth_timer_handle => undefined}
    end.
refresh_idle(State) ->
    case maps:get(socket, State) of
        undefined -> State;
        _ ->
            cancel_timer(maps:get(idle_timer_handle, State, undefined)),
            Token = make_ref(),
            Timer = erlang:send_after(idle_timeout_ms(State), self(), {idle_timeout, Token}),
            State#{idle_timer => Token, idle_timer_handle => Timer}
    end.
idle_timeout_ms(#{authenticated := true}) -> limit(authenticated_idle_timeout_ms, 3600000);
idle_timeout_ms(_State) -> limit(idle_timeout_ms, 300000).
cancel_timer(undefined) -> ok;
cancel_timer(Ref) when is_reference(Ref) -> _ = erlang:cancel_timer(Ref), ok;
cancel_timer(_) -> ok.
arm(gen_tcp, Socket) -> inet:setopts(Socket, [{active, once}]);
arm(ssl, Socket) -> ssl:setopts(Socket, [{active, once}]).
socket_send(gen_tcp, Socket, Data) -> gen_tcp:send(Socket, Data);
socket_send(ssl, Socket, Data) -> ssl:send(Socket, Data).
socket_close(gen_tcp, Socket) -> gen_tcp:close(Socket);
socket_close(ssl, Socket) -> ssl:close(Socket).
max_response_bytes() -> limit(max_response_bytes, 1048576).
limit(Key, Default) ->
    Limits = bibleit_rate_limiter:limits(),
    case maps:get(Key, Limits, Default) of Value when is_integer(Value), Value > 0 -> Value; _ -> Default end.
charge_connection_request(Cost, State) ->
    Limits = bibleit_rate_limiter:limits(),
    #{limit := Maximum, window_ms := Window} = window_limit(maps:get(max_requests_per_connection, Limits, #{limit => 120, window_ms => 60000})),
    Now = erlang:monotonic_time(millisecond),
    Previous = [Entry || Entry = {At, _} <- maps:get(request_window, State, []), At > Now - Window],
    Used = lists:sum([Value || {_At, Value} <- Previous]),
    case Used + Cost =< Maximum of
        true -> {ok, State#{request_window => [{Now, Cost} | Previous]}};
        false ->
            Retry = case lists:reverse(Previous) of [{Oldest, _} | _] -> max(1, Window - (Now - Oldest)); [] -> Window end,
            {error, Retry}
    end.
window_limit(#{limit := Limit, window_ms := Window}) when is_integer(Limit), Limit > 0, is_integer(Window), Window > 0 -> #{limit => Limit, window_ms => Window};
window_limit(_) -> #{limit => 120, window_ms => 60000}.

trim_newline(Line) -> trim_last(Line, $\n).
trim_last(<<>>, _Character) -> <<>>;
trim_last(Line, Character) ->
    Last = binary:at(Line, byte_size(Line) - 1),
    case Last =:= Character of true -> trim_last(binary:part(Line, 0, byte_size(Line) - 1), $\r); false -> trim_carriage_return(Line) end.
trim_carriage_return(<<>>) -> <<>>;
trim_carriage_return(Line) ->
    case binary:at(Line, byte_size(Line) - 1) =:= $\r of true -> binary:part(Line, 0, byte_size(Line) - 1); false -> Line end.
