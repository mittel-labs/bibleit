-module(bibleit_tcp_listener).
-behaviour(gen_server).
-export([start_link/0]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
init([]) ->
    Port = application:get_env(bibleit_server, port, 7070),
    Host = application:get_env(bibleit_server, host, {127, 0, 0, 1}),
    Options = [binary, {packet, line}, {packet_size, max_command_bytes()}, {active, false}, {reuseaddr, true}, {ip, Host}],
    {ok, ListenSocket} = gen_tcp:listen(Port, Options),
    Pid = spawn_link(fun() -> accept(ListenSocket) end),
    {ok, #{socket => ListenSocket, acceptor => Pid}}.
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_Message, State) -> {noreply, State}.
handle_info(_Info, State) -> {noreply, State}.
terminate(_Reason, #{socket := Socket}) -> gen_tcp:close(Socket).
code_change(_OldVsn, State, _Extra) -> {ok, State}.

accept(ListenSocket) ->
    case gen_tcp:accept(ListenSocket) of
        {ok, Socket} ->
            case peer_ip(Socket) of
                {ok, Ip} -> case bibleit_rate_limiter:admit(Ip) of
                    ok -> start_connection(Socket, Ip);
                    {error, rate_limited, Retry} ->
                        _ = gen_tcp:send(Socket, ["ERR rate_limited retry_after_ms=", integer_to_list(Retry), "\n"]),
                        _ = gen_tcp:close(Socket)
                end;
                {error, _Reason} ->
                    _ = gen_tcp:send(Socket, "ERR invalid_proxy_header\n"),
                    _ = gen_tcp:close(Socket)
            end,
            accept(ListenSocket);
        {error, closed} -> ok;
        {error, _Reason} -> accept(ListenSocket)
    end.

start_connection(Socket, Ip) ->
    case bibleit_tcp_connection_sup:start_child() of
        {ok, Pid} ->
            ok = gen_tcp:controlling_process(Socket, Pid),
            Pid ! {socket_ready, Socket, Ip},
            ok;
        {error, _Reason} ->
            bibleit_rate_limiter:release(Ip, false),
            _ = gen_tcp:close(Socket),
            ok
    end.

max_command_bytes() ->
    Limits = bibleit_rate_limiter:limits(),
    case maps:get(max_command_bytes, Limits, application:get_env(bibleit_server, max_command_bytes, 8192)) of
        Bytes when is_integer(Bytes), Bytes > 0 -> Bytes;
        _ -> 8192
    end.

peer_ip(Socket) ->
    case application:get_env(bibleit_server, proxy_protocol, false) of
        true -> case gen_tcp:recv(Socket, 0, proxy_timeout_ms()) of
            {ok, Header} -> bibleit_proxy_protocol:parse_v1(Header);
            {error, Reason} -> {error, Reason}
        end;
        false -> case inet:peername(Socket) of {ok, {Ip, _Port}} -> {ok, Ip}; Error -> Error end
    end.
proxy_timeout_ms() ->
    Limits = bibleit_rate_limiter:limits(),
    case maps:get(proxy_protocol_timeout_ms, Limits, 5000) of Value when is_integer(Value), Value > 0 -> Value; _ -> 5000 end.
