-module(bibleit_http_ws).
-behaviour(cowboy_websocket).
-export([init/2, websocket_init/1, websocket_handle/2, websocket_info/2, terminate/3]).

init(Req0, Options) ->
    Id = proplists:get_value(<<"live">>, cowboy_req:parse_qs(Req0)),
    case valid_live_id(Id) of
        false -> {ok, cowboy_req:reply(404, Req0), undefined};
        true -> case bibleit_api:live(Id) of
            {ok, Pid} ->
                Actor = case bibleit_http_auth:current(Req0) of {ok, Value, _Permissions} -> Value; _ -> undefined end,
                {cowboy_websocket, Req0, #{id => Id, pid => Pid, actor => Actor, secret => secret(Id, Req0)}, Options};
            error -> {ok, cowboy_req:reply(404, Req0), undefined}
        end
    end.

websocket_init(#{pid := Pid, secret := Secret, actor := Actor, id := Id} = State) ->
    Result = bibleit_api:subscribe_live(Id, Actor, Secret, self()),
    case Result of
        {ok, _Pid, _Live} -> {[{text, json(live_message_from_pid(<<"live">>, Id, Pid))}], State};
        {error, forbidden} -> {[{text, json(#{<<"type">> => <<"error">>, <<"live">> => Id, <<"line">> => <<"ERR forbidden">>})}], State};
        {error, Reason} -> {[{text, json(#{<<"type">> => <<"error">>, <<"live">> => Id, <<"line">> => error_line(Reason)})}], State}
    end.
websocket_handle(_Frame, State) -> {ok, State}.
websocket_info({live_verse, Id, Payload}, State) -> {[{text, json(#{<<"type">> => <<"verse">>, <<"live">> => Id, <<"verse">> => Payload})}], State};
websocket_info({live_clear, Id}, State) -> {[{text, json(#{<<"type">> => <<"clear">>, <<"live">> => Id})}], State};
websocket_info({live_paused, Id}, State) -> {[{text, json(#{<<"type">> => <<"paused">>, <<"live">> => Id})}], State};
websocket_info({live_closed, Id}, State) -> {[{text, json(#{<<"type">> => <<"closed">>, <<"live">> => Id})}], State};
websocket_info({live_access_revoked, Id}, State) -> {[{text, json(#{<<"type">> => <<"revoked">>, <<"live">> => Id})}, {close, 1008, <<"access revoked">>}], State};
websocket_info({live_event, Id, Live}, State) -> {[{text, json(live_message(<<"live_state">>, Id, Live))}], State};
websocket_info(_, State) -> {ok, State}.
terminate(_Reason, _Req, #{pid := Pid}) -> bibleit_api:unsubscribe_live(Pid, self());
terminate(_, _, _) -> ok.

secret(Id, Req) -> proplists:get_value(<<"bibleit_live_", Id/binary>>, cowboy_req:parse_cookies(Req)).
live_message_from_pid(Type, Id, Pid) ->
    Live = bibleit_api:live_public(Pid),
    live_message(Type, Id, Live).
live_message(Type, Id, Live) ->
    #{<<"type">> => Type, <<"live">> => Id, <<"name">> => maps:get(name, Live, <<>>),
      <<"status">> => atom_to_binary(maps:get(status, Live), utf8), <<"paused">> => maps:get(paused, Live, false)}.
json(Value) -> json:encode(Value).
error_line(Reason) -> iolist_to_binary([<<"ERR ">>, atom_to_binary(Reason, utf8)]).
valid_live_id(Id) when is_binary(Id), byte_size(Id) > 0, byte_size(Id) =< 64 ->
    lists:all(fun(Character) -> (Character >= $0 andalso Character =< $9) orelse (Character >= $A andalso Character =< $Z) orelse (Character >= $a andalso Character =< $z) end, binary_to_list(Id));
valid_live_id(_) -> false.
