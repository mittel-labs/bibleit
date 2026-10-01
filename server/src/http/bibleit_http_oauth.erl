-module(bibleit_http_oauth).
-behaviour(gen_server).

-export([start_link/0, google_url/0, github_url/0, complete_google/2, complete_github/2]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

%% Google is deliberately configured at deployment time.  No OAuth client
%% material is embedded in the application or exposed to the browser.

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
google_url() -> gen_server:call(?MODULE, {authorize, google}).
github_url() -> gen_server:call(?MODULE, {authorize, github}).
complete_google(State, Code) -> gen_server:call(?MODULE, {complete, google, State, Code}, 30000).
complete_github(State, Code) -> gen_server:call(?MODULE, {complete, github, State, Code}, 30000).

init([]) -> {ok, #{states => #{}}}.

handle_call({authorize, Provider}, _From, State0) ->
    State = expire(State0),
    case config(Provider) of
        {ok, #{client_id := ClientId, redirect_uri := RedirectUri}} ->
            Nonce = binary:encode_hex(crypto:strong_rand_bytes(32)),
            Url = authorization_url(Provider, ClientId, RedirectUri, Nonce),
            States = maps:get(states, State),
            Entry = #{provider => Provider, expires_at => erlang:system_time(second) + 600},
            {reply, {ok, Url}, State#{states => States#{Nonce => Entry}}};
        Error -> {reply, Error, State}
    end;
handle_call({complete, Provider, Nonce, Code}, _From, State0) ->
    State = expire(State0),
    case maps:find(Nonce, maps:get(states, State)) of
        {ok, #{provider := Provider}} ->
            Next = State#{states => maps:remove(Nonce, maps:get(states, State))},
            Result = exchange(Provider, Code),
            log_failure(Provider, Result),
            {reply, Result, Next};
        {ok, _} -> {reply, {error, invalid_oauth_state}, State};
        error -> {reply, {error, invalid_oauth_state}, State}
    end;
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_Message, State) -> {noreply, State}.
handle_info(_Message, State) -> {noreply, State}.
terminate(_, _) -> ok.
code_change(_, State, _) -> {ok, State}.

config(Provider) ->
    case application:get_env(bibleit_server, config_key(Provider)) of
        {ok, #{client_id := ClientId, client_secret := ClientSecret, redirect_uri := RedirectUri}}
          when is_binary(ClientId), is_binary(ClientSecret), is_binary(RedirectUri) ->
            {ok, #{client_id => ClientId, client_secret => ClientSecret, redirect_uri => RedirectUri}};
        _ -> {error, oauth_not_configured}
    end.

config_key(google) -> google_oauth;
config_key(github) -> github_oauth.

authorization_url(google, ClientId, RedirectUri, Nonce) ->
    Params = [{"client_id", ClientId}, {"redirect_uri", RedirectUri},
              {"response_type", "code"}, {"scope", "openid email profile"},
              {"state", Nonce}, {"prompt", "select_account"}],
    <<"https://accounts.google.com/o/oauth2/v2/auth?", (query(Params))/binary>>;
authorization_url(github, ClientId, RedirectUri, Nonce) ->
    Params = [{"client_id", ClientId}, {"redirect_uri", RedirectUri},
              {"scope", "read:user"}, {"state", Nonce}],
    <<"https://github.com/login/oauth/authorize?", (query(Params))/binary>>.

exchange(google, Code) ->
    case config(google) of
        {ok, #{client_id := ClientId, client_secret := ClientSecret, redirect_uri := RedirectUri}} ->
            Params = [{"code", Code}, {"client_id", ClientId}, {"client_secret", ClientSecret},
                      {"redirect_uri", RedirectUri}, {"grant_type", "authorization_code"}],
            case request(post, "https://oauth2.googleapis.com/token", query(Params), []) of
                {ok, #{<<"access_token">> := AccessToken}} -> google_identity(AccessToken);
                _ -> {error, google_token_exchange_failed}
            end;
        Error -> Error
    end;
exchange(github, Code) ->
    case config(github) of
        {ok, #{client_id := ClientId, client_secret := ClientSecret, redirect_uri := RedirectUri}} ->
            Params = [{"code", Code}, {"client_id", ClientId}, {"client_secret", ClientSecret},
                      {"redirect_uri", RedirectUri}],
            case request(post, "https://github.com/login/oauth/access_token", query(Params), [{"accept", "application/json"}]) of
                {ok, #{<<"access_token">> := AccessToken}} -> github_identity(AccessToken);
                _ -> {error, github_token_exchange_failed}
            end;
        Error -> Error
    end.

google_identity(AccessToken) ->
    case request(get, "https://openidconnect.googleapis.com/v1/userinfo", <<>>, [{"authorization", "Bearer " ++ binary_to_list(AccessToken)}]) of
        {ok, #{<<"sub">> := Subject} = Profile} when is_binary(Subject) ->
            Actor = <<"google-", Subject/binary>>,
            case bibleit_authorization:ensure_member_actor(<<"google">>, Actor) of
                ok -> save_display_name(Actor, display_name(Profile));
                {error, actor_exists} -> save_display_name(Actor, display_name(Profile));
                Error -> Error
            end;
        _ -> {error, google_identity_failed}
    end.

save_display_name(Actor, Name) ->
    case bibleit_authorization:set_actor_display_name(Actor, Name) of
        ok -> {ok, Actor};
        Error -> Error
    end.

display_name(#{<<"name">> := Name}) when is_binary(Name), byte_size(Name) > 0 -> Name;
display_name(#{<<"given_name">> := Name}) when is_binary(Name), byte_size(Name) > 0 -> Name;
display_name(_) -> <<"Bibleit member">>.

github_identity(AccessToken) ->
    Headers = [{"authorization", "Bearer " ++ binary_to_list(AccessToken)},
               {"accept", "application/vnd.github+json"},
               {"user-agent", "Bibleit/0.0.1"}],
    case request(get, "https://api.github.com/user", <<>>, Headers) of
        {ok, #{<<"id">> := Id} = Profile} ->
            Actor = <<"github-", (github_id(Id))/binary>>,
            case bibleit_authorization:ensure_member_actor(<<"github">>, Actor) of
                ok -> save_github_profile(Actor, Profile);
                {error, actor_exists} -> save_github_profile(Actor, Profile);
                Error -> Error
            end;
        _ -> {error, github_identity_failed}
    end.

github_id(Id) when is_integer(Id) -> integer_to_binary(Id);
github_id(Id) when is_binary(Id) -> Id.
github_display_name(#{<<"name">> := Name}) when is_binary(Name), byte_size(Name) > 0 -> Name;
github_display_name(#{<<"login">> := Login}) when is_binary(Login), byte_size(Login) > 0 -> Login;
github_display_name(_) -> <<"Bibleit member">>.

save_github_profile(Actor, Profile) ->
    case save_display_name(Actor, github_display_name(Profile)) of
        {ok, Actor} ->
            case maps:get(<<"login">>, Profile, undefined) of
                Handle when is_binary(Handle), byte_size(Handle) > 0 ->
                    case bibleit_authorization:set_actor_handle(Actor, Handle) of
                        ok -> {ok, Actor};
                        Error -> Error
                    end;
                _ -> {ok, Actor}
            end;
        Error -> Error
    end.

request(Method, Url, Body, Headers) ->
    Request = case Method of
        get -> {Url, Headers};
        post -> {Url, Headers, "application/x-www-form-urlencoded", Body}
    end,
    case httpc:request(Method, Request, [{timeout, 15000}], [{body_format, binary}]) of
        {ok, {{_, 200, _}, _ResponseHeaders, ResponseBody}} ->
            try {ok, json:decode(ResponseBody)} catch _:_ -> {error, invalid_json} end;
        _ -> {error, request_failed}
    end.

log_failure(_Provider, {ok, _Actor}) -> ok;
log_failure(Provider, Error) -> logger:warning("OAuth callback failed for ~p: ~p", [Provider, Error]).

query(Params) -> unicode:characters_to_binary(uri_string:compose_query([{Key, value(Value)} || {Key, Value} <- Params])).
value(Value) when is_binary(Value) -> binary_to_list(Value);
value(Value) -> Value.
expire(#{states := States} = State) ->
    Now = erlang:system_time(second),
    State#{states => maps:filter(fun(_Nonce, #{expires_at := ExpiresAt}) -> ExpiresAt > Now end, States)}.
