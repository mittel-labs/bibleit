-module(bibleit_server_boot).
-export([start/0, configure/0]).

%% Runtime bootstrap. The release keeps deploy-specific values and secrets in
%% the environment, then this module configures the application before its
%% supervisor starts.

start() ->
    configure(),
    case bibleit_server:start() of
        {ok, _Started} -> ok;
        {error, {already_started, bibleit_server}} -> ok;
        Error -> erlang:error({bibleit_server_start_failed, Error})
    end.

configure() ->
    DataDir = env("BIBLEIT_DATA_DIR", "/data"),
    application:set_env(bibleit_server, host, bind_address("BIBLEIT_SERVER_BIND_ADDRESS", "0.0.0.0")),
    application:set_env(bibleit_server, port, positive_integer("BIBLEIT_SERVER_PORT", "7070")),
    application:set_env(bibleit_server, http, #{port => positive_integer("BIBLEIT_HTTP_PORT", "8080"),
                                                  host => bind_address("BIBLEIT_HTTP_BIND_ADDRESS", "0.0.0.0")}),
    application:set_env(bibleit_server, http_secure_cookies, boolean_env("BIBLEIT_HTTP_SECURE_COOKIES")),
    application:set_env(bibleit_server, proxy_protocol, boolean_env("BIBLEIT_PROXY_PROTOCOL")),
    application:set_env(bibleit_server, translations_dir, DataDir),
    application:set_env(bibleit_server, authorization_path, filename:join(DataDir, "authorization.dets")),
    application:set_env(bibleit_server, account_path, filename:join(DataDir, "accounts.dets")),
    application:set_env(bibleit_server, lives_path, filename:join(DataDir, "lives.dets")),
    configure_tls(),
    configure_google_oauth(),
    configure_github_oauth(),
    configure_resend(),
    configure_bootstrap_key(),
    configure_ssh(DataDir).

%% A release normally receives these paths from its container entrypoint. The
%% development Make targets set `tls` directly before calling start/0, so an
%% absent pair deliberately leaves that explicit configuration untouched.
configure_tls() ->
    case {os:getenv("BIBLEIT_TLS_CERTFILE"), os:getenv("BIBLEIT_TLS_KEYFILE")} of
        {false, false} -> ok;
        {Certificate, Key} when is_list(Certificate), is_list(Key), Certificate =/= "", Key =/= "" ->
            application:set_env(bibleit_server, tls,
                                #{port => positive_integer("BIBLEIT_TLS_PORT", "7443"),
                                  certfile => Certificate, keyfile => Key,
                                  handshake_timeout_ms => positive_integer("BIBLEIT_TLS_HANDSHAKE_TIMEOUT_MS", "10000")});
        _ -> erlang:error({invalid_tls_configuration, "set BIBLEIT_TLS_CERTFILE and BIBLEIT_TLS_KEYFILE together"})
    end.

configure_ssh(DataDir) ->
    case os:getenv("BIBLEIT_SSH_PORT") of
        false -> application:unset_env(bibleit_server, ssh);
        "" -> erlang:error({missing_environment_variable, "BIBLEIT_SSH_PORT"});
        _ ->
            SystemDir = env("BIBLEIT_SSH_SYSTEM_DIR", filename:join(DataDir, "ssh")),
            application:set_env(bibleit_server, ssh,
                                #{port => positive_integer("BIBLEIT_SSH_PORT", undefined), system_dir => SystemDir})
    end.

configure_bootstrap_key() ->
    case os:getenv("BIBLEIT_BOOTSTRAP_PUBLIC_KEY") of
        false -> ok;
        %% Make exports an empty value when no bootstrap key was requested.
        %% Treat it as absent: a development server must never gain an admin
        %% merely because a local default happened to exist.
        "" -> ok;
        PublicKey ->
            Actor = unicode:characters_to_binary(env("BIBLEIT_BOOTSTRAP_ACTOR", "admin")),
            application:set_env(bibleit_server, bootstrap_keys,
                                #{unicode:characters_to_binary(PublicKey) => #{actor => Actor, roles => [server_admin]}})
    end.

configure_google_oauth() ->
    configure_oauth(google_oauth, "BIBLEIT_GOOGLE_CLIENT_ID", "BIBLEIT_GOOGLE_CLIENT_SECRET", "/auth/google/callback").

configure_github_oauth() ->
    configure_oauth(github_oauth, "BIBLEIT_GITHUB_CLIENT_ID", "BIBLEIT_GITHUB_CLIENT_SECRET", "/auth/github/callback").

configure_resend() ->
    case {os:getenv("BIBLEIT_RESEND_API_KEY"), os:getenv("BIBLEIT_EMAIL_FROM"), os:getenv("BIBLEIT_PUBLIC_URL")} of
        {false, false, _} -> ok;
        {ApiKey, From, PublicUrl} when is_list(ApiKey), is_list(From), is_list(PublicUrl), PublicUrl =/= "" ->
            Base = trim_trailing_slashes(unicode:characters_to_binary(PublicUrl)),
            case Base of
                <<>> -> erlang:error({invalid_resend_configuration, "BIBLEIT_PUBLIC_URL must not be only slashes"});
                _ -> application:set_env(bibleit_server, resend, #{api_key => unicode:characters_to_binary(ApiKey), from => unicode:characters_to_binary(From), public_url => Base})
            end;
        _ -> erlang:error({invalid_resend_configuration, "set BIBLEIT_RESEND_API_KEY, BIBLEIT_EMAIL_FROM, and BIBLEIT_PUBLIC_URL together"})
    end.

configure_oauth(Key, ClientIdName, ClientSecretName, CallbackPath) ->
    case {os:getenv(ClientIdName), os:getenv(ClientSecretName), os:getenv("BIBLEIT_PUBLIC_URL")} of
        {false, false, _} -> ok;
        {ClientId, ClientSecret, PublicUrl} when is_list(ClientId), is_list(ClientSecret), is_list(PublicUrl), PublicUrl =/= "" ->
            Base = trim_trailing_slashes(unicode:characters_to_binary(PublicUrl)),
            case Base of
                <<>> -> erlang:error({invalid_oauth_configuration, "BIBLEIT_PUBLIC_URL must not be only slashes"});
                _ -> application:set_env(bibleit_server, Key, #{client_id => unicode:characters_to_binary(ClientId), client_secret => unicode:characters_to_binary(ClientSecret), redirect_uri => <<Base/binary, (unicode:characters_to_binary(CallbackPath))/binary>>})
            end;
        _ -> erlang:error({invalid_oauth_configuration, "set the provider client ID, client secret, and BIBLEIT_PUBLIC_URL together"})
    end.

trim_trailing_slashes(<<>>) -> <<>>;
trim_trailing_slashes(Value) ->
    case binary:last(Value) of
        $/ -> trim_trailing_slashes(binary:part(Value, 0, byte_size(Value) - 1));
        _ -> Value
    end.

bind_address(Name, Default) ->
    Value = env(Name, Default),
    case inet:parse_address(Value) of
        {ok, Address} -> Address;
        {error, _} ->
            case inet:getaddr(Value, inet6) of
                {ok, Address} -> Address;
                {error, Reason} -> erlang:error({invalid_bind_address, Value, Reason})
            end
    end.

positive_integer(Name, Default) ->
    case string:to_integer(case Default of undefined -> required_env(Name); _ -> env(Name, Default) end) of
        {Value, []} when Value > 0 -> Value;
        _ -> erlang:error({invalid_positive_integer, Name})
    end.

boolean_env(Name) ->
    case string:lowercase(env(Name, "false")) of
        "true" -> true;
        "false" -> false;
        _ -> erlang:error({invalid_boolean, Name})
    end.

required_env(Name) ->
    case os:getenv(Name) of
        false -> erlang:error({missing_environment_variable, Name});
        "" -> erlang:error({missing_environment_variable, Name});
        Value -> Value
    end.

env(Name, Default) ->
    case os:getenv(Name) of false -> Default; Value -> Value end.
