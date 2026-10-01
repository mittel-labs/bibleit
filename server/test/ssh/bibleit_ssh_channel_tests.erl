-module(bibleit_ssh_channel_tests).
-include_lib("eunit/include/eunit.hrl").

arrow_keys_edit_inside_a_line_test() ->
    {ok, First} = bibleit_ssh_channel:handle_input(<<"exit", 27, $[>>, state()),
    {ok, Result} = bibleit_ssh_channel:handle_input(<<$D, $X>>, First),
    ?assertEqual(<<"exiXt">>, maps:get(buffer, Result)),
    ?assertEqual(4, maps:get(cursor, Result)),
    ?assertEqual(<<>>, maps:get(escape, Result)).

backspace_and_delete_remove_visible_characters_test() ->
    {ok, Backspace} = bibleit_ssh_channel:handle_input(<<"exit", 127>>, state()),
    ?assertEqual(<<"exi">>, maps:get(buffer, Backspace)),
    {ok, Delete} = bibleit_ssh_channel:handle_input(<<"exait", 27, $[, $D, 27, $[, $D, 27, $[, $D, 27, $[, $3, $~>>, state()),
    ?assertEqual(<<"exit">>, maps:get(buffer, Delete)).

control_c_clears_the_pending_line_test() ->
    {ok, Result} = bibleit_ssh_channel:handle_input(<<"not-a-command", 3>>, state()),
    ?assertEqual(<<>>, maps:get(buffer, Result)),
    ?assertEqual(0, maps:get(cursor, Result)).

control_d_closes_an_empty_shell_test() ->
    ?assertMatch({stop, undefined, _}, bibleit_ssh_channel:handle_input(<<4>>, state())).

terminal_output_uses_crlf_without_breaking_carriage_return_test() ->
    ?assertEqual(<<"one\r\ntwo\r\nthree\rfour">>,
                 bibleit_ssh_channel:terminal_output(<<"one\ntwo\r\nthree\rfour">>)).

member_prompt_is_stable_during_line_editing_test() ->
    {ok, Result} = bibleit_ssh_channel:handle_input(<<"he", 27, $[, $D, $l>>, state()),
    ?assertEqual(<<"hle">>, maps:get(buffer, Result)),
    ?assertEqual(<<"admin">>, maps:get(actor, Result)).

state() ->
    #{connection => undefined, channel => undefined, actor => <<"admin">>,
      protocol => #{}, buffer => <<>>, cursor => 0, escape => <<>>, shell => true}.
