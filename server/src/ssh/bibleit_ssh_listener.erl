-module(bibleit_ssh_listener).
-behaviour(gen_server).
-export([start_link/0, configured/0]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

%% Native SSH is intentionally separate from the TLS line-protocol endpoint.
%% SSH provides its own encrypted transport and standard public-key proof.

start_link() ->
    case configured() of
        {ok, Config} -> gen_server:start_link({local, ?MODULE}, ?MODULE, Config, []);
        disabled -> ignore
    end.

configured() ->
    case application:get_env(bibleit_server, ssh, disabled) of
        #{port := Port, system_dir := SystemDir} = Config when is_integer(Port), Port > 0 ->
            {ok, Config#{system_dir => path(SystemDir)}};
        _ -> disabled
    end.

init(Config) ->
    {ok, _} = application:ensure_all_started(ssh),
    Host = maps:get(host, Config, application:get_env(bibleit_server, host, {127, 0, 0, 1})),
    Options = [{ip, Host}, {system_dir, maps:get(system_dir, Config)},
               %% Bibleit SSH is account-only.  `is_auth_key/3` accepts a key
               %% only after resolving it to an active Bibleit account.
               {auth_methods, "publickey"}, {key_cb, bibleit_ssh_key_cb},
               {ssh_cli, {bibleit_ssh_channel, []}}, {exec, disabled},
               {tcpip_tunnel_in, false}, {tcpip_tunnel_out, false}],
    case ssh:daemon(maps:get(port, Config), Options) of
        {ok, Daemon} -> {ok, #{daemon => Daemon}};
        {error, Reason} -> {stop, {ssh_listen_failed, Reason}}
    end.

handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_Message, State) -> {noreply, State}.
handle_info(_Info, State) -> {noreply, State}.
terminate(_Reason, #{daemon := Daemon}) -> ssh:stop_daemon(Daemon).
code_change(_OldVsn, State, _Extra) -> {ok, State}.

path(Value) when is_binary(Value) -> binary_to_list(Value);
path(Value) -> Value.
