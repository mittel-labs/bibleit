-module(bibleit_tls_listener).
-behaviour(gen_server).
-export([start_link/0, configured/0]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

%% Optional native TLS endpoint. Production deployments may instead terminate
%% TLS at a trusted edge and retain the plaintext listener privately.

start_link() ->
    case configured() of
        {ok, Config} -> gen_server:start_link({local, ?MODULE}, ?MODULE, Config, []);
        disabled -> ignore
    end.

configured() ->
    case application:get_env(bibleit_server, tls, disabled) of
        #{port := Port, certfile := Certificate, keyfile := Key} = Config
          when is_integer(Port), Port > 0 -> {ok, Config#{certfile => path(Certificate), keyfile => path(Key)}};
        _ -> disabled
    end.

init(Config) ->
    {ok, _} = application:ensure_all_started(ssl),
    Host = maps:get(host, Config, application:get_env(bibleit_server, host, {127, 0, 0, 1})),
    Options = [binary, {packet, line}, {packet_size, max_command_bytes()}, {active, false},
               {reuseaddr, true}, {ip, Host}, {certfile, maps:get(certfile, Config)},
               {keyfile, maps:get(keyfile, Config)}, {versions, ['tlsv1.2', 'tlsv1.3']}],
    {ok, ListenSocket} = ssl:listen(maps:get(port, Config), Options),
    Acceptor = spawn_link(fun() -> accept(ListenSocket, Config) end),
    {ok, #{socket => ListenSocket, acceptor => Acceptor}}.
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_Message, State) -> {noreply, State}.
handle_info(_Info, State) -> {noreply, State}.
terminate(_Reason, #{socket := Socket}) -> ssl:close(Socket).
code_change(_OldVsn, State, _Extra) -> {ok, State}.

accept(ListenSocket, Config) ->
    case ssl:transport_accept(ListenSocket) of
        {ok, TransportSocket} ->
            _ = spawn(fun() -> handshake(TransportSocket, Config) end),
            accept(ListenSocket, Config);
        {error, closed} -> ok;
        {error, _Reason} -> accept(ListenSocket, Config)
    end.

handshake(TransportSocket, Config) ->
    case ssl:handshake(TransportSocket, handshake_timeout_ms(Config)) of
        {ok, Socket} ->
            case ssl:peername(Socket) of
                {ok, {Ip, _Port}} -> case bibleit_rate_limiter:admit(Ip) of
                    ok -> start_connection(Socket, Ip);
                    {error, rate_limited, Retry} ->
                        _ = ssl:send(Socket, ["ERR rate_limited retry_after_ms=", integer_to_list(Retry), "\n"]),
                        _ = ssl:close(Socket)
                end;
                _ -> ssl:close(Socket)
            end;
        {error, _Reason} -> ssl:close(TransportSocket)
    end.

start_connection(Socket, Ip) ->
    case bibleit_tcp_connection_sup:start_child() of
        {ok, Pid} ->
            ok = ssl:controlling_process(Socket, Pid),
            Pid ! {socket_ready, ssl, Socket, Ip};
        {error, _Reason} ->
            bibleit_rate_limiter:release(Ip, false),
            _ = ssl:close(Socket)
    end.

handshake_timeout_ms(Config) ->
    case maps:get(handshake_timeout_ms, Config, 10000) of Value when is_integer(Value), Value > 0 -> Value; _ -> 10000 end.
max_command_bytes() ->
    Limits = bibleit_rate_limiter:limits(),
    case maps:get(max_command_bytes, Limits, application:get_env(bibleit_server, max_command_bytes, 8192)) of
        Bytes when is_integer(Bytes), Bytes > 0 -> Bytes;
        _ -> 8192
    end.
path(Value) when is_binary(Value) -> binary_to_list(Value);
path(Value) -> Value.
