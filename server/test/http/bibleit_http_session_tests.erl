-module(bibleit_http_session_tests).
-include_lib("eunit/include/eunit.hrl").

http_session_resolves_an_actor_without_tcp_test_() ->
    {setup, fun setup/0, fun cleanup/1, fun session_is_http_only_state/1}.

setup() ->
    Path = filename:join("/tmp", "bibleit-http-session-" ++ integer_to_list(erlang:unique_integer([positive])) ++ ".dets"),
    application:set_env(bibleit_server, authorization_path, Path),
    {ok, Authorization} = bibleit_authorization:start_link(),
    ok = bibleit_authorization:create_actor(<<"email">>, <<"browser-user">>),
    {ok, Sessions} = bibleit_http_session:start_link(),
    #{path => Path, authorization => Authorization, sessions => Sessions}.

cleanup(#{path := Path, authorization := Authorization, sessions := Sessions}) ->
    unlink(Sessions),
    exit(Sessions, shutdown),
    unlink(Authorization),
    exit(Authorization, shutdown),
    file:delete(Path),
    application:unset_env(bibleit_server, authorization_path).

session_is_http_only_state(_Context) -> fun() ->
    {ok, Session, <<"browser-user">>} = bibleit_http_session:login_actor(<<"browser-user">>),
    ?assertMatch(<<"bs_", _/binary>>, Session),
    {ok, <<"browser-user">>, Permissions} = bibleit_http_session:authenticate(Session),
    ?assert(lists:member({translation, read}, Permissions)),
    ok = bibleit_http_session:logout(Session),
    ?assertEqual({error, unauthenticated}, bibleit_http_session:authenticate(Session))
end.

oauth_created_actor_can_open_a_browser_session_test() ->
    Path = filename:join("/tmp", "bibleit-http-oauth-" ++ integer_to_list(erlang:unique_integer([positive])) ++ ".dets"),
    application:set_env(bibleit_server, authorization_path, Path),
    {ok, Authorization} = bibleit_authorization:start_link(),
    {ok, Sessions} = bibleit_http_session:start_link(),
    try
        ok = bibleit_authorization:create_actor(<<"google">>, <<"google-123">>),
        ok = bibleit_authorization:set_actor_display_name(<<"google-123">>, <<"Felipe Mamud">>),
        ok = bibleit_authorization:set_actor_handle(<<"google-123">>, <<"fmamud">>),
        ?assertEqual({ok, <<"Felipe Mamud">>}, bibleit_authorization:actor_display_name(<<"google-123">>)),
        ?assertEqual({ok, <<"fmamud">>}, bibleit_authorization:actor_handle(<<"google-123">>)),
        {Actors, _} = bibleit_authorization:actor_page(10, undefined),
        ?assert(lists:member(#{actor => <<"google-123">>, created_by => <<"google">>, display_name => <<"Felipe Mamud">>, handle => <<"fmamud">>, created_at => maps:get(created_at, hd(Actors))}, Actors)),
        {ok, Session, <<"google-123">>} = bibleit_http_session:login_actor(<<"google-123">>),
        {ok, <<"google-123">>, Permissions} = bibleit_http_session:authenticate(Session),
        ?assert(lists:member({translation, read}, Permissions))
    after
        unlink(Sessions), exit(Sessions, shutdown),
        unlink(Authorization), exit(Authorization, shutdown),
        file:delete(Path),
        application:unset_env(bibleit_server, authorization_path)
    end.

github_oauth_uses_a_distinct_callback_and_csrf_state_test() ->
    application:set_env(bibleit_server, github_oauth, #{client_id => <<"github-client">>, client_secret => <<"secret">>, redirect_uri => <<"http://localhost:8080/auth/github/callback">>}),
    {ok, OAuth} = bibleit_http_oauth:start_link(),
    try
        {ok, Url} = bibleit_http_oauth:github_url(),
        ?assertMatch(<<"https://github.com/login/oauth/authorize?", _/binary>>, Url),
        ?assertNotEqual(nomatch, binary:match(Url, <<"redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fauth%2Fgithub%2Fcallback">>)),
        ?assertNotEqual(nomatch, binary:match(Url, <<"state=">>))
    after
        unlink(OAuth), exit(OAuth, shutdown),
        application:unset_env(bibleit_server, github_oauth)
    end.
