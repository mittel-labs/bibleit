-module(bibleit_ssh_identity_tests).
-include_lib("eunit/include/eunit.hrl").

identity_is_bound_to_the_connection_process_test_() ->
    {setup, fun setup/0, fun cleanup/1, fun(_Pid) -> fun() ->
        Connection = spawn(fun connection_loop/0),
        try
            ok = bibleit_ssh_identity:remember(Connection, <<"member">>, <<"SHA256:key">>),
            ?assertEqual({ok, #{actor => <<"member">>, key_fingerprint => <<"SHA256:key">>}},
                         bibleit_ssh_identity:lookup(Connection)),
            exit(Connection, shutdown),
            await_removal(Connection, 20)
        after
            try exit(Connection, shutdown) catch exit:_ -> ok end
        end
    end end}.

connection_loop() -> receive stop -> ok end.

await_removal(Connection, 0) -> ?assertEqual(error, bibleit_ssh_identity:lookup(Connection));
await_removal(Connection, Attempts) ->
    case bibleit_ssh_identity:lookup(Connection) of
        error -> ok;
        {ok, _} -> timer:sleep(5), await_removal(Connection, Attempts - 1)
    end.

setup() ->
    {ok, Pid} = bibleit_ssh_identity:start_link(),
    Pid.

cleanup(Pid) -> unlink(Pid), exit(Pid, shutdown).
