-module(bibleit_http_listener).
-behaviour(gen_server).
-export([start_link/0]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).

init([]) ->
    case application:get_env(bibleit_server, http, #{port => 8080}) of
        disabled -> ignore;
        Config when is_map(Config) ->
            Port = maps:get(port, Config, 8080),
            Host = maps:get(host, Config, application:get_env(bibleit_server, host, {127, 0, 0, 1})),
            WebsocketOptions = #{idle_timeout => websocket_idle_timeout(Config)},
            Dispatch = cowboy_router:compile([
                {'_', [
                    {"/healthz", bibleit_http_handler, health},
                    {"/auth/login", bibleit_http_handler, login},
                    {"/auth/signup", bibleit_http_handler, signup},
                    {"/auth/google", bibleit_http_handler, google_login},
                    {"/auth/google/callback", bibleit_http_handler, google_callback},
                    {"/auth/github", bibleit_http_handler, github_login},
                    {"/auth/github/callback", bibleit_http_handler, github_callback},
                    {"/auth/email/verify/:token", bibleit_http_handler, email_verify},
                    {"/auth/password/reset", bibleit_http_handler, password_reset_request},
                    {"/auth/password/reset/:token", bibleit_http_handler, password_reset},
                    {"/auth/logout", bibleit_http_handler, logout},
                    {"/dashboard/keys", bibleit_http_handler, dashboard_keys},
                    {"/dashboard", bibleit_http_handler, dashboard},
                    {"/auth/:id", bibleit_http_handler, access},
                    {"/ws", bibleit_http_ws, WebsocketOptions},
                    {"/lives/:id", bibleit_http_handler, page},
                    {"/docs/[...]", cowboy_static, {dir, docs_dir()}},
                    {"/assets/[...]", cowboy_static, {dir, static_dir()}},
                    {"/:id", bibleit_http_handler, short_live},
                    {"/", bibleit_http_handler, index}
                ]}
            ]),
            {ok, _} = application:ensure_all_started(cowboy),
            {ok, _} = cowboy:start_clear(bibleit_http, [{ip, Host}, {port, Port}],
                                          #{env => #{dispatch => Dispatch}}),
            {ok, #{}}
    end.
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_Message, State) -> {noreply, State}.
handle_info(_Message, State) -> {noreply, State}.
terminate(_Reason, _State) -> cowboy:stop_listener(bibleit_http).
code_change(_OldVsn, State, _Extra) -> {ok, State}.

static_dir() ->
    case application:get_env(bibleit_server, static_dir) of
        {ok, Directory} -> Directory;
        undefined ->
            case code:priv_dir(bibleit_server) of
                {error, bad_name} -> filename:absname("priv/static");
                Priv -> filename:join(Priv, "static")
            end
    end.
docs_dir() ->
    case application:get_env(bibleit_server, docs_dir) of
        {ok, Directory} -> Directory;
        undefined -> filename:absname("docs")
    end.
websocket_idle_timeout(Config) ->
    case maps:get(websocket_idle_timeout_ms, Config, 300000) of
        Timeout when is_integer(Timeout), Timeout > 0 -> Timeout;
        _ -> 300000
    end.
