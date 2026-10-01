-module(bibleit_live_session_tests).
-include_lib("eunit/include/eunit.hrl").

open_live_is_readable_without_tokens_test() ->
    {ok, Pid} = bibleit_live_session:start_link(<<"abc123">>, <<"owner">>, #{name => <<"Sunday">>}),
    ?assertEqual(#{id => <<"abc123">>, name => <<"Sunday">>, status => running, paused => false},
                 bibleit_live_session:public(Pid)),
    ?assertMatch({ok, _}, bibleit_live_session:details(Pid, undefined)),
    ?assertEqual({ok, []}, bibleit_live_session:stack_info(Pid, undefined)),
    {ok, OwnerDetails} = bibleit_live_session:details(Pid, <<"owner">>),
    ?assert(is_integer(maps:get(created_at, OwnerDetails))),
    ?assertEqual(false, maps:is_key(running_for_seconds, OwnerDetails)),
    unlink(Pid), exit(Pid, shutdown).

live_stats_identify_actor_and_anonymous_subscribers_test() ->
    {ok, Pid} = bibleit_live_session:start_link(<<"stats1">>, <<"owner">>, #{}),
    {ok, _} = bibleit_live_session:subscribe(Pid, <<"owner">>, self()),
    Anonymous = spawn(fun() -> receive stop -> ok end end),
    {ok, _} = bibleit_live_session:subscribe(Pid, Anonymous),
    {ok, Stats} = bibleit_live_session:stats(Pid, <<"owner">>),
    ?assertEqual(2, maps:get(connections, Stats)),
    ?assertEqual(1, maps:get(actor_connections, Stats)),
    ?assertEqual(1, maps:get(anonymous_connections, Stats)),
    ?assertEqual(0, maps:get(stack_entries, Stats)),
    ?assertEqual({error, forbidden}, bibleit_live_session:stats(Pid, <<"other">>)),
    ?assert(lists:any(fun(#{actor := Actor, access := actor}) -> Actor =:= <<"owner">>; (_) -> false end,
                      maps:get(subscribers, Stats))),
    ?assert(lists:any(fun(#{actor := <<"anonymous">>, access := open}) -> true; (_) -> false end,
                      maps:get(subscribers, Stats))),
    Anonymous ! stop,
    unlink(Pid), exit(Pid, shutdown).

live_can_stop_and_restart_test() ->
    {ok, Pid} = bibleit_live_session:start_link(<<"abc123">>, <<"owner">>, #{}),
    {ok, _} = bibleit_live_session:subscribe(Pid, self()),
    {ok, Stopped} = bibleit_live_session:stop(Pid, <<"owner">>),
    ?assertEqual(stopped, maps:get(status, Stopped)),
    receive {live_event, <<"abc123">>, Event} -> ?assertEqual(stopped, maps:get(status, Event)) after 1000 -> ?assert(false) end,
    {ok, Started} = bibleit_live_session:start(Pid, <<"owner">>),
    ?assertEqual(running, maps:get(status, Started)),
    receive {live_event, <<"abc123">>, Restarted} -> ?assertEqual(running, maps:get(status, Restarted)) after 1000 -> ?assert(false) end,
    {ok, Stats} = bibleit_live_session:stats(Pid, <<"owner">>),
    ?assert(maps:get(running_for_seconds, Stats) >= 0),
    unlink(Pid), exit(Pid, shutdown).

secret_protected_live_access_is_revocable_test() ->
    Secret = <<"initial-secret">>,
    {ok, Pid} = bibleit_live_session:start_link(<<"private1">>, <<"owner">>, #{secret => Secret}),
    ?assertEqual({error, forbidden}, bibleit_live_session:subscribe(Pid, <<"viewer">>, self())),
    ?assertEqual({error, unauthorized}, bibleit_live_session:authenticate_secret(Pid, <<"wrong-secret">>)),
    ok = bibleit_live_session:authenticate_secret(Pid, Secret),
    {ok, _} = bibleit_live_session:subscribe_with_secret(Pid, Secret, self()),
    {ok, #{secret := Rotated}} = bibleit_live_session:rotate_secret(Pid, <<"owner">>),
    receive {live_access_revoked, <<"private1">>} -> ok after 1000 -> ?assert(false) end,
    ?assertEqual({error, unauthorized}, bibleit_live_session:subscribe_with_secret(Pid, Secret, self())),
    ?assertMatch({ok, _}, bibleit_live_session:subscribe_with_secret(Pid, Rotated, self())),
    {ok, _} = bibleit_live_session:delete_secret(Pid, <<"owner">>),
    ?assertMatch({ok, _}, bibleit_live_session:subscribe(Pid, self())),
    unlink(Pid), exit(Pid, shutdown).

secret_protected_live_requires_secret_for_subscription_test() ->
    Secret = <<"private-secret">>,
    {ok, Pid} = bibleit_live_session:start_link(<<"private1">>, <<"owner">>, #{secret => Secret}),
    ?assertEqual({error, forbidden}, bibleit_live_session:details(Pid, undefined)),
    ?assertEqual({error, forbidden}, bibleit_live_session:subscribe(Pid, self())),
    ?assertEqual({error, forbidden}, bibleit_live_session:subscribe(Pid, undefined, self())),
    ?assertMatch({ok, _}, bibleit_live_session:details(Pid, <<"owner">>)),
    ?assertMatch({ok, _}, bibleit_live_session:subscribe_with_secret(Pid, Secret, self())),
    unlink(Pid), exit(Pid, shutdown).

only_writers_may_change_live_and_subscribers_receive_public_state_test() ->
    {ok, Pid} = bibleit_live_session:start_link(<<"abc123">>, <<"owner">>, #{}),
    ?assertEqual({error, forbidden}, bibleit_live_session:set_reference(Pid, <<"stranger">>, <<"John 3:16">>)),
    {ok, _} = bibleit_live_session:subscribe(Pid, self()),
    {ok, Stats} = bibleit_live_session:stats(Pid, <<"owner">>),
    ?assertEqual(1, maps:get(connections, Stats)),
    {ok, OwnerDetails} = bibleit_live_session:details(Pid, <<"owner">>),
    ?assertEqual(false, maps:is_key(showing, OwnerDetails)),
    ?assertEqual({error, nothing_to_resume}, bibleit_live_session:resume(Pid, <<"owner">>)),
    ok = bibleit_live_session:pause(Pid, <<"owner">>),
    receive {live_event, <<"abc123">>, #{paused := true}} -> ok after 1000 -> ?assert(false) end,
    receive {live_paused, <<"abc123">>} -> ok after 1000 -> ?assert(false) end,
    {ok, Live} = bibleit_live_session:set_reference(Pid, <<"owner">>, <<"John 3:16">>),
    ?assertEqual(<<"John 3:16">>, maps:get(reference, Live)),
    receive
        {live_event, <<"abc123">>, Event} -> ?assertEqual(<<"John 3:16">>, maps:get(reference, Event))
    after 1000 -> ?assert(false)
    end,
    unlink(Pid), exit(Pid, shutdown).

subscriber_limit_is_enforced_test() ->
    application:set_env(bibleit_server, limits, #{max_subscribers_per_live => 1}),
    try
        {ok, Pid} = bibleit_live_session:start_link(<<"limited">>, <<"owner">>, #{}),
        {ok, _} = bibleit_live_session:subscribe(Pid, self()),
        {Other, Ref} = spawn_monitor(fun() -> receive stop -> ok end end),
        ?assertEqual({error, subscriber_limit_reached}, bibleit_live_session:subscribe(Pid, Other)),
        Other ! stop,
        receive {'DOWN', Ref, process, Other, _} -> ok after 1000 -> ?assert(false) end,
        unlink(Pid), exit(Pid, shutdown)
    after
        application:unset_env(bibleit_server, limits)
    end.
