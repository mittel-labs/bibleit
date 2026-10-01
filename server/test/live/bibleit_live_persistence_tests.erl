-module(bibleit_live_persistence_tests).
-include_lib("eunit/include/eunit.hrl").

live_state_and_secret_survive_restart_test_() ->
    {setup, fun setup/0, fun cleanup/1, fun(Context) -> [fun() -> survives_restart(Context) end] end}.

setup() ->
    PreviousTrapExit = process_flag(trap_exit, true),
    Path = filename:join("/tmp", "bibleit-live-store-" ++ integer_to_list(erlang:unique_integer([positive])) ++ ".dets"),
    application:set_env(bibleit_server, lives_path, Path),
    {ok, Store} = bibleit_live_store:start_link(),
    {ok, Sessions} = bibleit_live_session_sup:start_link(),
    {ok, Registry} = bibleit_live_registry:start_link(),
    #{path => Path, store => Store, sessions => Sessions, registry => Registry, trap_exit => PreviousTrapExit}.

cleanup(Context) ->
    stop(maps:get(registry, Context)),
    stop(maps:get(sessions, Context)),
    stop(maps:get(store, Context)),
    application:unset_env(bibleit_server, lives_path),
    file:delete(maps:get(path, Context)),
    process_flag(trap_exit, maps:get(trap_exit, Context)).

survives_restart(Context) ->
    {ok, Id, _} = bibleit_live_registry:create(<<"owner">>, #{name => <<"Leadership">>}),
    {ok, Pid} = bibleit_live_registry:lookup(Id),
    Secret = <<"restart-secret">>,
    {ok, _} = bibleit_live_session:set_secret(Pid, <<"owner">>, Secret),
    {ok, _} = bibleit_live_session:set_reference(Pid, <<"owner">>, <<"John 3:16">>),
    Payload = #{translation => <<"kjv">>, reference => <<"John 3:16">>, text => <<"For God so loved the world.">>},
    ok = bibleit_live_store:save((bibleit_live_session:persisted(Pid))#{current => Payload, showing => true, sequence => 7}),
    ObsoleteId = <<"obsolete-live">>,
    ok = bibleit_live_store:save(#{id => ObsoleteId}),
    stop(maps:get(registry, Context)),
    stop(maps:get(sessions, Context)),
    {ok, Sessions} = bibleit_live_session_sup:start_link(),
    {ok, Registry} = bibleit_live_registry:start_link(),
    {ok, Restored} = bibleit_live_registry:lookup(Id),
    ?assertEqual(error, bibleit_live_registry:lookup(ObsoleteId)),
    ?assertEqual(not_found, bibleit_live_store:get(ObsoleteId)),
    ?assertEqual({error, forbidden}, bibleit_live_session:details(Restored, <<"reader">>)),
    ok = bibleit_live_session:authenticate_secret(Restored, Secret),
    {ok, OwnerLive} = bibleit_live_session:details(Restored, <<"owner">>),
    ?assertEqual(false, maps:is_key(showing, OwnerLive)),
    {ok, Stats} = bibleit_live_session:stats(Restored, <<"owner">>),
    ?assertEqual(7, maps:get(revision, Stats)),
    {ok, _} = bibleit_live_session:subscribe_with_secret(Restored, Secret, self()),
    receive {live_verse, Id, Payload} -> ok after 1000 -> ?assert(false) end,
    {ok, RemovedId, _} = bibleit_live_registry:create(<<"owner">>, #{}),
    ok = bibleit_live_registry:remove(RemovedId, <<"owner">>),
    ?assertEqual(not_found, bibleit_live_store:get(RemovedId)),
    stop(Registry),
    stop(Sessions),
    ok.

stop(Pid) ->
    Ref = erlang:monitor(process, Pid),
    unlink(Pid),
    exit(Pid, kill),
    receive {'DOWN', Ref, process, Pid, _} -> ok end.
