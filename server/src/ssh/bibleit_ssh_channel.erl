-module(bibleit_ssh_channel).
-behaviour(ssh_server_channel).
-export([init/1, handle_ssh_msg/2, handle_msg/2, terminate/2]).
%% Kept public for focused transport tests; not part of the TCP protocol API.
-export([handle_input/2, terminal_output/1]).

%% A deliberately small SSH shell: commands and responses use the same line
%% protocol as the TCP endpoint, while OpenSSH completes public-key auth before
%% this process exists.

init([]) -> {ok, #{connection => undefined, channel => undefined, actor => undefined, key_fingerprint => undefined,
                   protocol => #{}, buffer => <<>>, cursor => 0, escape => <<>>, shell => false}}.

handle_msg({ssh_channel_up, Channel, Connection}, State) ->
    Identity = case bibleit_ssh_identity:lookup(Connection) of
        {ok, Value} -> Value;
        error -> #{}
    end,
    {ok, State#{connection => Connection, channel => Channel,
                actor => maps:get(actor, Identity, undefined),
                key_fingerprint => maps:get(key_fingerprint, Identity, undefined)}};
handle_msg({live_event, Id, Live}, State) -> send_event({event, live, Id, Live}, State);
handle_msg({live_verse, _Id, Payload}, State) -> send_event({event, verse, Payload}, State);
handle_msg({live_clear, _Id}, State) -> send_event({event, clear}, State);
handle_msg({live_paused, _Id}, State) -> send_event({event, paused}, State);
handle_msg({live_closed, _Id}, State) -> send_event({event, closed}, State);
handle_msg({live_access_revoked, _Id}, State) ->
    send_data(bibleit_protocol:encode({event, revoked}), State),
    {stop, maps:get(channel, State), State};
handle_msg(_Message, State) -> {ok, State}.

handle_ssh_msg({ssh_cm, Connection, {pty, Channel, WantReply, _Pty}}, State) ->
    ssh_connection:reply_request(Connection, WantReply, success, Channel),
    {ok, State#{connection => Connection, channel => Channel}};
handle_ssh_msg({ssh_cm, Connection, {shell, Channel, WantReply}}, State0) ->
    ssh_connection:reply_request(Connection, WantReply, success, Channel),
    State = authenticated_state(State0#{connection => Connection, channel => Channel, shell => true}),
    send_data([shell_greeting(State), prompt(State)], State),
    {ok, State};
handle_ssh_msg({ssh_cm, Connection, {exec, Channel, WantReply, Command}}, State0) ->
    ssh_connection:reply_request(Connection, WantReply, success, Channel),
    State = authenticated_state(State0#{connection => Connection, channel => Channel}),
    {Next, _Close} = safe_execute(trim(iolist_to_binary(Command)), State),
    ssh_connection:exit_status(Connection, Channel, 0),
    ssh_connection:send_eof(Connection, Channel),
    {stop, Channel, Next};
handle_ssh_msg({ssh_cm, _Connection, {data, _Channel, _Type, Data}}, #{shell := true} = State) ->
    %% SSH transports are permitted to hand callback code iodata. Normalize it
    %% before buffering so terminal clients cannot terminate a channel merely
    %% by sending an input fragment.
    try
        Input = iolist_to_binary(Data),
        %% This shell has no OS PTY behind it, so it owns input echoing and
        %% line editing. OpenSSH sends Return as CR, not LF.
        handle_input(Input, State)
    of
        Result -> Result
    catch
        Class:Reason:Stacktrace ->
            logger:error("Bibleit SSH channel input failed: ~p:~p ~p", [Class, Reason, Stacktrace]),
            send_data("ERR internal_error\n", State),
            {ok, State#{buffer => <<>>}}
    end;
handle_ssh_msg(_Message, State) -> {ok, State}.

terminate(_Reason, State) ->
    unsubscribe(maps:get(subscriptions, maps:get(protocol, State, #{}), #{})).

authenticated_state(#{actor := Actor} = State) when is_binary(Actor) ->
    case bibleit_authorization:actor_permissions(Actor) of
        {ok, Permissions} -> State#{protocol => #{actor => Actor, permissions => Permissions, roles => [], subscriptions => #{}}};
        {error, _} -> State#{actor => undefined,
                             protocol => #{actor => undefined, permissions => [], roles => [], subscriptions => #{}}}
    end.

handle_input(<<>>, State) -> {ok, State};
handle_input(Input, State0) ->
    Escape = maps:get(escape, State0, <<>>),
    consume_input(<<Escape/binary, Input/binary>>, State0#{escape => <<>>}).

consume_input(<<>>, State) -> {ok, State};
consume_input(<<$\r, $\n, Rest/binary>>, State) ->
    continue_input(Rest, submit_line(State));
consume_input(<<$\r, Rest/binary>>, State) ->
    continue_input(Rest, submit_line(State));
consume_input(<<$\n, Rest/binary>>, State) ->
    continue_input(Rest, submit_line(State));
consume_input(<<3, Rest/binary>>, State) ->
    %% Ctrl-C is a terminal interrupt, not part of a protocol command.
    %% Clear any partial input so an accidental interrupt cannot turn `exit`
    %% (or another valid command) into an invisible malformed command.
    send_data("^C\r\n", State),
    send_data(prompt(State), State),
    consume_input(Rest, State#{buffer => <<>>, cursor => 0});
consume_input(<<4, _Rest/binary>>, #{buffer := <<>>} = State) ->
    %% Ctrl-D is EOF at an empty prompt, matching a normal interactive shell.
    send_data("\r\n", State),
    {stop, maps:get(channel, State), State};
consume_input(<<4, Rest/binary>>, State) ->
    %% Within a line Ctrl-D deletes the character under the cursor.
    continue_input(Rest, delete_character(State));
consume_input(<<1, Rest/binary>>, State) ->
    continue_input(Rest, move_cursor(home, State));
consume_input(<<5, Rest/binary>>, State) ->
    continue_input(Rest, move_cursor('end', State));
consume_input(<<8, Rest/binary>>, State) ->
    continue_input(Rest, erase_character(State));
consume_input(<<127, Rest/binary>>, State) ->
    continue_input(Rest, erase_character(State));
consume_input(<<27, Rest/binary>>, State) ->
    consume_escape(<<27, Rest/binary>>, State);
consume_input(<<Byte, Rest/binary>>, State) when Byte < 32 ->
    %% Never let unrecognised terminal controls become invisible command data.
    consume_input(Rest, State);
consume_input(<<Byte, Rest/binary>>, State) ->
    continue_input(Rest, insert_character(Byte, State)).

consume_escape(<<27>>, State) -> {ok, State#{escape => <<27>>}};
consume_escape(<<27, $[, Rest/binary>>, State) -> consume_csi(Rest, State);
consume_escape(<<27, $O, Rest/binary>>, State) -> consume_ss3(Rest, State);
consume_escape(<<27, _Rest/binary>>, State) -> {ok, State}.

consume_ss3(<<>>, State) -> {ok, State#{escape => <<27, $O>>}};
consume_ss3(<<$H, Rest/binary>>, State) -> continue_input(Rest, move_cursor(home, State));
consume_ss3(<<$F, Rest/binary>>, State) -> continue_input(Rest, move_cursor('end', State));
consume_ss3(<<_Final, Rest/binary>>, State) -> consume_input(Rest, State).

consume_csi(<<>>, State) -> {ok, State#{escape => <<27, $[>>}};
consume_csi(<<$D, Rest/binary>>, State) -> continue_input(Rest, move_cursor(left, State));
consume_csi(<<$C, Rest/binary>>, State) -> continue_input(Rest, move_cursor(right, State));
consume_csi(<<$H, Rest/binary>>, State) -> continue_input(Rest, move_cursor(home, State));
consume_csi(<<$F, Rest/binary>>, State) -> continue_input(Rest, move_cursor('end', State));
consume_csi(<<$3, $~, Rest/binary>>, State) -> continue_input(Rest, delete_character(State));
consume_csi(Csi, State) ->
    %% CSI sequences may arrive in fragments. Keep a short incomplete prefix;
    %% once a final byte is present, safely discard unsupported controls (for
    %% example bracketed-paste markers) instead of polluting the command line.
    case csi_complete(Csi) of
        false when byte_size(Csi) < 32 -> {ok, State#{escape => <<27, $[, Csi/binary>>}};
        false -> {ok, State};
        {true, Rest} -> consume_input(Rest, State)
    end.

csi_complete(<<>>) -> false;
csi_complete(<<Byte, Rest/binary>>) when Byte >= $@, Byte =< $~ -> {true, Rest};
csi_complete(<<_Byte, Rest/binary>>) -> csi_complete(Rest).

continue_input(_Rest, {stop, _Channel, _State} = Result) -> Result;
continue_input(Rest, {ok, State}) -> consume_input(Rest, State).

submit_line(State0) ->
    send_data(<<"\r\n">>, State0),
    Line = trim(maps:get(buffer, State0)),
    {State, Close} = safe_execute(Line, State0#{buffer => <<>>, cursor => 0}),
    case Close of
        true -> {stop, maps:get(channel, State), State};
        false -> {ok, State}
    end.

erase_character(#{buffer := Buffer, cursor := 0} = State) when Buffer =/= <<>> -> {ok, State};
erase_character(#{buffer := <<>>} = State) -> {ok, State};
erase_character(#{buffer := Buffer, cursor := Cursor} = State) ->
    Previous = previous_character_start(Buffer, Cursor),
    {Left, Right} = split_at(Buffer, Previous),
    Next = State#{buffer => <<Left/binary, (binary:part(Right, Cursor - Previous, byte_size(Right) - (Cursor - Previous)))/binary>>, cursor => Previous},
    redraw_line(Next),
    {ok, Next}.

delete_character(#{buffer := Buffer, cursor := Cursor} = State) when Cursor >= byte_size(Buffer) -> {ok, State};
delete_character(#{buffer := Buffer, cursor := Cursor} = State) ->
    NextCursor = next_character_start(Buffer, Cursor),
    {Left, _} = split_at(Buffer, Cursor),
    Right = binary:part(Buffer, NextCursor, byte_size(Buffer) - NextCursor),
    Next = State#{buffer => <<Left/binary, Right/binary>>},
    redraw_line(Next),
    {ok, Next}.

insert_character(Byte, #{buffer := Buffer, cursor := Cursor} = State) ->
    {Left, Right} = split_at(Buffer, Cursor),
    Next = State#{buffer => <<Left/binary, Byte, Right/binary>>, cursor => Cursor + 1},
    redraw_line(Next),
    {ok, Next}.

move_cursor(left, #{buffer := Buffer, cursor := Cursor} = State) ->
    Next = State#{cursor => previous_character_start(Buffer, Cursor)},
    redraw_line(Next),
    {ok, Next};
move_cursor(right, #{buffer := Buffer, cursor := Cursor} = State) ->
    Next = State#{cursor => next_character_start(Buffer, Cursor)},
    redraw_line(Next),
    {ok, Next};
move_cursor(home, State) ->
    Next = State#{cursor => 0},
    redraw_line(Next),
    {ok, Next};
move_cursor('end', #{buffer := Buffer} = State) ->
    Next = State#{cursor => byte_size(Buffer)},
    redraw_line(Next),
    {ok, Next}.

previous_character_start(_Buffer, 0) -> 0;
previous_character_start(Buffer, Cursor) ->
    Position = Cursor - 1,
    case binary:at(Buffer, Position) band 16#C0 of
        16#80 -> previous_character_start(Buffer, Position);
        _ -> Position
    end.

next_character_start(Buffer, Cursor) when Cursor >= byte_size(Buffer) -> Cursor;
next_character_start(Buffer, Cursor) ->
    Byte = binary:at(Buffer, Cursor),
    Width = case Byte of
        _ when Byte < 16#80 -> 1;
        _ when Byte < 16#E0 -> 2;
        _ when Byte < 16#F0 -> 3;
        _ when Byte < 16#F8 -> 4;
        _ -> 1
    end,
    erlang:min(Cursor + Width, byte_size(Buffer)).

split_at(Buffer, Position) ->
    {binary:part(Buffer, 0, Position), binary:part(Buffer, Position, byte_size(Buffer) - Position)}.

redraw_line(#{buffer := Buffer, cursor := Cursor} = State) ->
    {Before, _} = split_at(Buffer, Cursor),
    send_data(["\r", prompt(State), Buffer, "\e[K\r", prompt(State), Before], State).

execute(<<>>, State) ->
    send_data(prompt(State), State),
    {State, false};
execute(Line, #{protocol := Protocol0} = State0) ->
    {Response, Protocol} = case bibleit_protocol:decode(Line) of
        {ok, Request} ->
            {reply, Result, Next} = bibleit_protocol:handle(Request, Protocol0),
            {Result, Next};
        {error, Code} -> {{error, Code}, Protocol0}
    end,
    State = State0#{protocol => Protocol},
    send_data(bibleit_protocol:encode(Response), State),
    Close = maps:get(close_after_reply, Protocol, false),
    case Close of false -> send_data(prompt(State), State); true -> ok end,
    {State, Close}.

safe_execute(Line, State) ->
    try execute(Line, State) of
        Result -> Result
    catch
        Class:Reason:Stacktrace ->
            logger:error("Bibleit SSH command failed: ~p:~p ~p", [Class, Reason, Stacktrace]),
            send_data("ERR internal_error\n", State),
            {State, false}
    end.

send_event(Event, State) ->
    send_data(bibleit_protocol:encode(Event), State),
    {ok, State}.
send_data(Data, #{connection := Connection, channel := Channel, shell := true}) when Connection =/= undefined ->
    %% A terminal interprets LF as “move down” but leaves the cursor in its
    %% current column. The shared TCP protocol deliberately emits LF; convert
    %% it at the SSH boundary so each protocol line starts at column zero.
    ssh_connection:send(Connection, Channel, terminal_output(iolist_to_binary(Data)));
send_data(Data, #{connection := Connection, channel := Channel}) when Connection =/= undefined ->
    ssh_connection:send(Connection, Channel, iolist_to_binary(Data));
send_data(_, _) -> ok.
terminal_output(Data) -> iolist_to_binary(terminal_output_lines(Data)).
terminal_output_lines(<<>>) -> [];
terminal_output_lines(<<"\r\n", Rest/binary>>) -> [<<"\r\n">> | terminal_output_lines(Rest)];
terminal_output_lines(<<"\n", Rest/binary>>) -> [<<"\r\n">> | terminal_output_lines(Rest)];
terminal_output_lines(<<"\r", Rest/binary>>) -> [<<"\r">> | terminal_output_lines(Rest)];
terminal_output_lines(<<Byte, Rest/binary>>) -> [Byte | terminal_output_lines(Rest)].
shell_greeting(#{actor := Actor}) ->
    DisplayName = display_name(Actor),
    ["BIBLEIT  /  member\r\n", DisplayName, "  /  SSH key verified\r\nType help to explore. Ctrl-C clears a line; Ctrl-D exits.\r\n\r\n"].
prompt(_State) -> "> ".
display_name(Actor) ->
    try bibleit_authorization:actor_display_name(Actor) of
        {ok, Name} when is_binary(Name), Name =/= <<>> -> Name;
        _ -> Actor
    catch
        exit:_ -> Actor
    end.
trim(Line) -> trim_right(trim_left(Line)).
trim_left(<<$\r, Rest/binary>>) -> trim_left(Rest);
trim_left(<<$\n, Rest/binary>>) -> trim_left(Rest);
trim_left(Line) -> Line.
trim_right(<<>>) -> <<>>;
trim_right(Line) ->
    case binary:last(Line) of
        $\r -> trim_right(binary:part(Line, 0, byte_size(Line) - 1));
        _ -> Line
    end.
unsubscribe(Subscriptions) ->
    maps:foreach(fun(_Id, Pid) ->
                         try bibleit_live_session:unsubscribe(Pid, self()) of _ -> ok catch exit:_ -> ok end
                 end, Subscriptions).
