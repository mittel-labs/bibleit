-module(bibleit_rate_limiter_tests).
-include_lib("eunit/include/eunit.hrl").

rate_limiter_test_() ->
    {setup, fun setup/0, fun cleanup/1,
     fun(_Pid) -> [fun global_and_per_ip_connection_limits/0,
                   fun reconnects_share_connection_window/0,
                   fun unauthenticated_limit_is_released_after_login/0,
                   fun requests_are_shared_by_ip/0,
                   fun bad_commands_are_shared_by_ip/0,
                   fun failed_logins_disconnect_after_shared_limit/0,
                   fun release_frees_connection_capacity/0] end}.

setup() ->
    application:set_env(bibleit_server, limits, #{
        max_connections => 3,
        max_connections_per_ip => 2,
        max_unauthenticated_connections_per_ip => 1,
        new_connections_per_ip => #{limit => 2, window_ms => 60000},
        max_requests_per_ip => #{limit => 3, window_ms => 60000},
        bad_commands_per_ip => #{limit => 2, window_ms => 60000},
        failed_logins_per_ip => #{limit => 2, window_ms => 60000}
    }),
    {ok, Pid} = bibleit_rate_limiter:start_link(),
    Pid.
cleanup(Pid) ->
    unlink(Pid), exit(Pid, shutdown),
    application:unset_env(bibleit_server, limits).

global_and_per_ip_connection_limits() ->
    Ip = {127, 0, 0, 1},
    ?assertEqual(ok, bibleit_rate_limiter:admit(Ip)),
    ?assertMatch({error, rate_limited, _}, bibleit_rate_limiter:admit(Ip)),
    bibleit_rate_limiter:release(Ip, false).

reconnects_share_connection_window() ->
    Ip = {127, 0, 0, 2},
    ?assertEqual(ok, bibleit_rate_limiter:admit(Ip)),
    bibleit_rate_limiter:release(Ip, false),
    timer:sleep(1),
    ?assertEqual(ok, bibleit_rate_limiter:admit(Ip)),
    bibleit_rate_limiter:release(Ip, false),
    timer:sleep(1),
    ?assertMatch({error, rate_limited, _}, bibleit_rate_limiter:admit(Ip)).

unauthenticated_limit_is_released_after_login() ->
    Ip = {127, 0, 0, 3},
    ?assertEqual(ok, bibleit_rate_limiter:admit(Ip)),
    bibleit_rate_limiter:authenticated(Ip),
    timer:sleep(1),
    ?assertEqual(ok, bibleit_rate_limiter:admit(Ip)),
    bibleit_rate_limiter:release(Ip, true),
    bibleit_rate_limiter:release(Ip, false).

requests_are_shared_by_ip() ->
    Ip = {127, 0, 0, 4},
    ?assertEqual(ok, bibleit_rate_limiter:request(Ip, 2)),
    ?assertMatch({error, rate_limited, _}, bibleit_rate_limiter:request(Ip, 2)).

bad_commands_are_shared_by_ip() ->
    Ip = {127, 0, 0, 7},
    ?assertEqual(ok, bibleit_rate_limiter:bad_command(Ip)),
    ?assertEqual(ok, bibleit_rate_limiter:bad_command(Ip)),
    ?assertMatch({error, rate_limited, _}, bibleit_rate_limiter:bad_command(Ip)).

failed_logins_disconnect_after_shared_limit() ->
    Ip = {127, 0, 0, 5},
    ?assertEqual(ok, bibleit_rate_limiter:failed_login(Ip)),
    ?assertEqual(ok, bibleit_rate_limiter:failed_login(Ip)),
    ?assertMatch({disconnect, _}, bibleit_rate_limiter:failed_login(Ip)).

release_frees_connection_capacity() ->
    Ip = {127, 0, 0, 6},
    ?assertEqual(ok, bibleit_rate_limiter:admit(Ip)),
    bibleit_rate_limiter:authenticated(Ip),
    bibleit_rate_limiter:release(Ip, true),
    timer:sleep(1),
    ?assertEqual(ok, bibleit_rate_limiter:admit(Ip)),
    bibleit_rate_limiter:release(Ip, false).
