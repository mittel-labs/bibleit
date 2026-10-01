-module(bibleit_http_auth).

-export([current/1, login_actor/2, logout/1, cookie_name/0]).

%% HTTP handlers use this boundary to resolve a browser session directly to an
%% Erlang actor.  It intentionally does not speak the TCP line protocol.

current(Req) ->
    Cookies = cowboy_req:parse_cookies(Req),
    case proplists:get_value(cookie_name(), Cookies) of
        undefined -> {error, unauthenticated};
        Session -> bibleit_http_session:authenticate(Session)
    end.

login_actor(Actor, Req0) ->
    case bibleit_http_session:login_actor(Actor) of
        {ok, Session, LoginActor} ->
            Options = #{path => <<"/">>, http_only => true, same_site => lax,
                        secure => application:get_env(bibleit_server, http_secure_cookies, false),
                        max_age => session_ttl()},
            {ok, LoginActor, cowboy_req:set_resp_cookie(cookie_name(), Session, Req0, Options)};
        {error, _} = Error -> Error
    end.

logout(Req0) ->
    case proplists:get_value(cookie_name(), cowboy_req:parse_cookies(Req0)) of
        undefined -> ok;
        Session -> bibleit_http_session:logout(Session)
    end,
    cowboy_req:set_resp_cookie(cookie_name(), <<>>, Req0,
                               #{path => <<"/">>, http_only => true, same_site => lax,
                                 secure => application:get_env(bibleit_server, http_secure_cookies, false), max_age => 0}).

cookie_name() -> <<"bibleit_session">>.
session_ttl() -> application:get_env(bibleit_server, http_session_ttl_seconds, 28800).
