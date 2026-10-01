-module(bibleit_http_session).
-behaviour(gen_server).

-export([start_link/0, login_actor/1, authenticate/1, logout/1, logout_actor/1]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

%% Browser sessions deliberately live only in memory.  They are short-lived
%% bearer values held in an HttpOnly cookie, never durable API tokens.

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
login_actor(Actor) -> gen_server:call(?MODULE, {login_actor, Actor}).
authenticate(Session) -> gen_server:call(?MODULE, {authenticate, Session}).
logout(Session) -> gen_server:call(?MODULE, {logout, Session}).
logout_actor(Actor) ->
    case whereis(?MODULE) of undefined -> ok; _ -> gen_server:call(?MODULE, {logout_actor, Actor}) end.

init([]) -> {ok, #{sessions => #{}}}.

handle_call({login_actor, Actor}, _From, State0) ->
    State = expire(State0),
    case bibleit_authorization:actor_permissions(Actor) of
        {ok, Permissions} ->
            {ok, Session, LoginActor, Next} = new_session(Actor, Permissions, State),
            {reply, {ok, Session, LoginActor}, Next};
        {error, _} = Error -> {reply, Error, State}
    end;
handle_call({authenticate, Session}, _From, State0) ->
    State = expire(State0),
    case maps:find(Session, maps:get(sessions, State)) of
        {ok, #{actor := Actor, permissions := Permissions}} -> {reply, {ok, Actor, Permissions}, State};
        error -> {reply, {error, unauthenticated}, State}
    end;
handle_call({logout, Session}, _From, State) ->
    Sessions = maps:remove(Session, maps:get(sessions, State)),
    {reply, ok, State#{sessions => Sessions}};
handle_call({logout_actor, Actor}, _From, State) ->
    Sessions = maps:filter(fun(_Session, #{actor := SessionActor}) -> SessionActor =/= Actor end, maps:get(sessions, State)),
    {reply, ok, State#{sessions => Sessions}};
handle_call(_, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_, State) -> {noreply, State}.
handle_info(_, State) -> {noreply, State}.
terminate(_, _) -> ok.
code_change(_, State, _) -> {ok, State}.

expire(#{sessions := Sessions} = State) ->
    Now = erlang:system_time(second),
    State#{sessions => maps:filter(fun(_Session, Entry) -> maps:get(expires_at, Entry) > Now end, Sessions)}.
ttl_seconds() ->
    case application:get_env(bibleit_server, http_session_ttl_seconds, 28800) of
        Ttl when is_integer(Ttl), Ttl > 0 -> Ttl;
        _ -> 28800
    end.
session_value() -> <<"bs_", (binary:encode_hex(crypto:strong_rand_bytes(32)))/binary>>.
new_session(Actor, Permissions, State) ->
    Session = session_value(),
    ExpiresAt = erlang:system_time(second) + ttl_seconds(),
    Entry = #{actor => Actor, permissions => Permissions, expires_at => ExpiresAt},
    {ok, Session, Actor, State#{sessions => (maps:get(sessions, State))#{Session => Entry}}}.
