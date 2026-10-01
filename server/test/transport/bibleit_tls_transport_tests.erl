-module(bibleit_tls_transport_tests).
-include_lib("eunit/include/eunit.hrl").

proxy_protocol_v1_uses_the_forwarded_address_test() ->
    ?assertEqual({ok, {203, 0, 113, 9}},
                 bibleit_proxy_protocol:parse_v1(<<"PROXY TCP4 203.0.113.9 10.0.0.2 54321 7070\r\n">>)),
    ?assertEqual({ok, {16#2001, 16#db8, 0, 0, 0, 0, 0, 1}},
                 bibleit_proxy_protocol:parse_v1(<<"PROXY TCP6 2001:db8::1 2001:db8::2 54321 7070\r\n">>)).

proxy_protocol_v1_rejects_non_proxy_input_test() ->
    ?assertEqual({error, invalid_proxy_header}, bibleit_proxy_protocol:parse_v1(<<"read nvipt 19 23\n">>)).

native_tls_listener_is_opt_in_test() ->
    application:unset_env(bibleit_server, tls),
    ?assertEqual(disabled, bibleit_tls_listener:configured()),
    application:set_env(bibleit_server, tls, #{port => 7443, certfile => <<"cert.pem">>, keyfile => "key.pem"}),
    try
        ?assertEqual({ok, #{port => 7443, certfile => "cert.pem", keyfile => "key.pem"}}, bibleit_tls_listener:configured())
    after
        application:unset_env(bibleit_server, tls)
    end.

native_ssh_listener_is_opt_in_test() ->
    application:unset_env(bibleit_server, ssh),
    ?assertEqual(disabled, bibleit_ssh_listener:configured()),
    application:set_env(bibleit_server, ssh, #{port => 2222, system_dir => <<"priv/ssh">>}),
    try
        ?assertEqual({ok, #{port => 2222, system_dir => "priv/ssh"}}, bibleit_ssh_listener:configured())
    after
        application:unset_env(bibleit_server, ssh)
    end.
