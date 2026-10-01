-module(bibleit_live_session).
-behaviour(gen_server).
-export([start_link/3, public/1, owner/1, details/2, stats/2, stack_info/2, set_reference/3, set_option/4, push/3, pop/3, clear/2, resume/2, pause/2, start/2, stop/2, set_secret/3, rotate_secret/2, delete_secret/2, authenticate_secret/2, remove/2, subscribe/2, subscribe/3, subscribe_with_secret/3, unsubscribe/2, persisted/1]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

start_link(Id, Owner, Options) -> gen_server:start_link(?MODULE, {Id, Owner, Options}, []).
public(Pid) -> gen_server:call(Pid, public).
owner(Pid) -> gen_server:call(Pid, owner).
details(Pid, Actor) -> gen_server:call(Pid, {details, Actor}).
stats(Pid, Actor) -> gen_server:call(Pid, {stats, Actor}).
stack_info(Pid, Actor) -> gen_server:call(Pid, {stack_info, Actor}).
set_reference(Pid, Actor, Reference) -> set_option(Pid, Actor, reference, Reference).
set_option(Pid, Actor, Option, Value) -> gen_server:call(Pid, {set_option, Actor, Option, Value}).
push(Pid, Actor, Reference) -> gen_server:call(Pid, {push, Actor, Reference}).
pop(Pid, Actor, Count) -> gen_server:call(Pid, {pop, Actor, Count}).
clear(Pid, Actor) -> gen_server:call(Pid, {clear, Actor}).
resume(Pid, Actor) -> gen_server:call(Pid, {resume, Actor}).
pause(Pid, Actor) -> gen_server:call(Pid, {pause, Actor}).
start(Pid, Actor) -> gen_server:call(Pid, {start, Actor}).
stop(Pid, Actor) -> gen_server:call(Pid, {stop, Actor}).
set_secret(Pid, Actor, Secret) -> gen_server:call(Pid, {set_secret, Actor, Secret}).
rotate_secret(Pid, Actor) -> gen_server:call(Pid, {rotate_secret, Actor}).
delete_secret(Pid, Actor) -> gen_server:call(Pid, {delete_secret, Actor}).
authenticate_secret(Pid, Secret) -> gen_server:call(Pid, {authenticate_secret, Secret}).
remove(Pid, Actor) -> gen_server:call(Pid, {remove, Actor}).
subscribe(Pid, Subscriber) -> gen_server:call(Pid, {subscribe, Subscriber}).
subscribe(Pid, Actor, Subscriber) -> gen_server:call(Pid, {subscribe, Actor, Subscriber}).
subscribe_with_secret(Pid, Secret, Subscriber) -> gen_server:call(Pid, {subscribe_with_secret, Secret, Subscriber}).
unsubscribe(Pid, Subscriber) -> gen_server:call(Pid, {unsubscribe, Subscriber}).
persisted(Pid) -> gen_server:call(Pid, persisted).

init({Id, Owner, Options}) ->
    case maps:find(saved, Options) of
        {ok, Saved} -> {ok, Saved#{subscribers => #{}}};
        error ->
            Name = maps:get(name, Options, <<>>),
            Translations = maps:get(translations, Options, []),
            Now = now_seconds(),
            Base = #{schema_version => 1, id => Id, owner => Owner, name => Name, status => running, created_at => Now, running_since => Now, running_seconds => 0,
                     reference => undefined, translations => Translations, current => undefined, showing => false, paused => false, sequence => 0,
                     subscribers => #{}},
            State = case maps:find(secret, Options) of
                {ok, Secret} -> Base#{secret_hash => secret_hash(Secret)};
                error -> Base
            end,
            {ok, State}
    end.

handle_call(public, _From, State) -> {reply, public_projection(State), State};
handle_call(owner, _From, State) -> {reply, maps:get(owner, State), State};
handle_call(persisted, _From, State) -> {reply, persisted_projection(State), State};
handle_call({details, Actor}, _From, State) ->
    case can_read(Actor, State) of
        true -> {reply, {ok, details_projection(Actor, State)}, State};
        false -> {reply, {error, forbidden}, State}
    end;
handle_call({stats, Actor}, _From, State) ->
    case is_owner(Actor, State) of
        true -> {reply, {ok, stats_projection(State)}, State};
        false -> {reply, {error, forbidden}, State}
    end;
handle_call({stack_info, Actor}, _From, State) ->
    case can_read(Actor, State) of
        true -> {reply, {ok, payload_verses(maps:get(current, State))}, State};
        false -> {reply, {error, forbidden}, State}
    end;
handle_call({set_option, Actor, Option, Value}, _From, State) ->
    case permitted(Actor, write, State) of
        false -> {reply, {error, forbidden}, State};
        true ->
            case apply_option(Option, Value, State) of
                {ok, Next} ->
                    case persist(Next) of
                        ok -> broadcast(Next), {reply, {ok, public_projection(Next)}, Next};
                        {error, _} -> {reply, {error, persistence_failed}, State}
                    end;
                error -> {reply, {error, invalid_option}, State}
            end
    end;
handle_call({push, Actor, Reference}, _From, State) ->
    case {permitted(Actor, write, State), maps:get(status, State)} of
        {false, _} -> {reply, {error, forbidden}, State};
        {true, stopped} -> {reply, {error, live_stopped}, State};
        {true, running} ->
            case read_payload(Actor, Reference, State) of
                {ok, Payload} ->
                    Stacked = push_payload(Payload, State),
                    Next = State#{current => Stacked, showing => true, paused => false, sequence => maps:get(sequence, State) + 1},
                    case persist(Next) of
                        ok -> broadcast_verse(Next, Stacked), {reply, {ok, Stacked}, Next};
                        {error, _} -> {reply, {error, persistence_failed}, State}
                    end;
                {error, Error} -> {reply, {error, Error}, State}
            end
    end;
handle_call({pop, Actor, Count}, _From, State) ->
    case {permitted(Actor, write, State), maps:get(status, State), maps:get(current, State)} of
        {false, _, _} -> {reply, {error, forbidden}, State};
        {true, stopped, _} -> {reply, {error, live_stopped}, State};
        {true, running, undefined} -> {reply, {error, stack_empty}, State};
        {true, running, Current} ->
            case pop_payload(Current, Count, State) of
                {clear, NextPayload} ->
                    Next = State#{current => NextPayload, showing => false, paused => false, sequence => maps:get(sequence, State) + 1},
                    case persist(Next) of
                        ok -> broadcast_clear(Next), {reply, {ok, live_cleared}, Next};
                        {error, _} -> {reply, {error, persistence_failed}, State}
                    end;
                {ok, Payload} ->
                    Next = State#{current => Payload, showing => true, paused => false, sequence => maps:get(sequence, State) + 1},
                    case persist(Next) of
                        ok -> broadcast_verse(Next, Payload), {reply, {ok, Payload}, Next};
                        {error, _} -> {reply, {error, persistence_failed}, State}
                    end
            end
    end;
handle_call({clear, Actor}, _From, State) ->
    case permitted(Actor, write, State) of
        false -> {reply, {error, forbidden}, State};
        true ->
            Next = State#{current => undefined, showing => false, paused => false, sequence => maps:get(sequence, State) + 1},
            case persist(Next) of
                ok -> broadcast_clear(Next), {reply, ok, Next};
                {error, _} -> {reply, {error, persistence_failed}, State}
            end
    end;
handle_call({resume, Actor}, _From, State) ->
    case {permitted(Actor, write, State), maps:get(status, State), maps:get(current, State)} of
        {false, _, _} -> {reply, {error, forbidden}, State};
        {true, stopped, _} -> {reply, {error, live_stopped}, State};
        {true, running, undefined} -> {reply, {error, nothing_to_resume}, State};
        {true, running, Payload} ->
            Next = State#{showing => true, paused => false, sequence => maps:get(sequence, State) + 1},
            case persist(Next) of
                ok -> broadcast_verse(Next, Payload), {reply, ok, Next};
                {error, _} -> {reply, {error, persistence_failed}, State}
            end
    end;
handle_call({pause, Actor}, _From, State) ->
    case {permitted(Actor, write, State), maps:get(status, State)} of
        {false, _} -> {reply, {error, forbidden}, State};
        {true, stopped} -> {reply, {error, live_stopped}, State};
        {true, running} ->
            Next = State#{showing => false, paused => true, sequence => maps:get(sequence, State) + 1},
            case persist(Next) of
                ok -> broadcast(Next), broadcast_paused(Next), {reply, ok, Next};
                {error, _} -> {reply, {error, persistence_failed}, State}
            end
    end;
handle_call({start, Actor}, _From, State) ->
    case permitted(Actor, manage, State) of
        false -> {reply, {error, forbidden}, State};
        true ->
            Next = case maps:get(status, State) of
                running -> State;
                stopped -> State#{status => running, running_since => now_seconds()}
            end,
            case persist(Next) of
                ok -> broadcast(Next), {reply, {ok, public_projection(Next)}, Next};
                {error, _} -> {reply, {error, persistence_failed}, State}
            end
    end;
handle_call({stop, Actor}, _From, State) ->
    case permitted(Actor, manage, State) of
        false -> {reply, {error, forbidden}, State};
        true ->
            Next = case maps:get(status, State) of
                stopped -> State;
                running -> State#{status => stopped, showing => false, paused => false, running_since => undefined,
                                  running_seconds => running_for_seconds(State)}
            end,
            case persist(Next) of
                ok -> broadcast(Next), {reply, {ok, public_projection(Next)}, Next};
                {error, _} -> {reply, {error, persistence_failed}, State}
            end
    end;
handle_call({set_secret, Actor, Secret}, _From, State) ->
    update_secret(Actor, Secret, State);
handle_call({rotate_secret, Actor}, _From, State) ->
    Secret = binary:encode_hex(crypto:strong_rand_bytes(24), lowercase),
    case update_secret(Actor, Secret, State) of
        {reply, {ok, _}, Next} -> {reply, {ok, #{secret => Secret}}, Next};
        Reply -> Reply
    end;
handle_call({delete_secret, Actor}, _From, State) ->
    case is_owner(Actor, State) of
        false -> {reply, {error, forbidden}, State};
        true ->
            Subscribers = revoke_secret_subscribers(State),
            Next = maps:remove(secret_hash, State#{subscribers => Subscribers}),
            case persist(Next) of
                ok -> {reply, {ok, public_projection(Next)}, Next};
                {error, _} -> {reply, {error, persistence_failed}, State}
            end
    end;
handle_call({authenticate_secret, Secret}, _From, State) ->
    case secret_matches(Secret, State) of
        true -> {reply, ok, State};
        false -> {reply, {error, unauthorized}, State}
    end;
handle_call({remove, Actor}, _From, State) ->
    case is_owner(Actor, State) of
        true -> broadcast_closed(State), {reply, ok, State};
        false -> {reply, {error, forbidden}, State}
    end;
handle_call({subscribe, Subscriber}, _From, State) ->
    case has_secret(State) of
        false -> add_subscriber(Subscriber, undefined, State);
        true -> {reply, {error, forbidden}, State}
    end;
handle_call({subscribe, Actor, Subscriber}, _From, State) ->
    case can_subscribe(Actor, State) of
        true -> add_subscriber(Subscriber, Actor, State);
        false -> {reply, {error, forbidden}, State}
    end;
handle_call({subscribe_with_secret, Secret, Subscriber}, _From, State) ->
    case secret_matches(Secret, State) of
        true -> add_subscriber(Subscriber, secret, State);
        false -> {reply, {error, unauthorized}, State}
    end;
handle_call({unsubscribe, Subscriber}, _From, State) ->
    {reply, ok, State#{subscribers => remove_subscriber(Subscriber, State)}};
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.

add_subscriber(Subscriber, Actor, State) ->
    Subscribers = maps:get(subscribers, State),
    case map_size(Subscribers) >= limit(max_subscribers_per_live, 500) of
        true -> {reply, {error, subscriber_limit_reached}, State};
        false ->
            Ref = erlang:monitor(process, Subscriber),
            send_current(Subscriber, State),
            Entry = #{pid => Subscriber, actor => Actor, connected_at => now_seconds()},
            {reply, {ok, public_projection(State)}, State#{subscribers => Subscribers#{Ref => Entry}}}
    end.

remove_subscriber(Subscriber, State) ->
    maps:fold(fun(Ref, #{pid := Pid} = Entry, Acc) ->
        case Pid =:= Subscriber of
            true -> erlang:demonitor(Ref, [flush]), Acc;
            false -> Acc#{Ref => Entry}
        end
    end, #{}, maps:get(subscribers, State)).
handle_cast(_Message, State) -> {noreply, State}.
handle_info({'DOWN', Ref, process, _Pid, _Reason}, State) ->
    Subscribers = maps:get(subscribers, State),
    {noreply, State#{subscribers => maps:remove(Ref, Subscribers)}};
handle_info(_Info, State) -> {noreply, State}.
terminate(_Reason, _State) -> ok.
code_change(_OldVsn, State, _Extra) -> {ok, State}.

can_read(_Actor, State) when not is_map_key(secret_hash, State) -> true;
can_read(Actor, State) -> is_owner(Actor, State).
can_subscribe(_Actor, State) -> not has_secret(State).
permitted(Actor, _Permission, State) -> is_owner(Actor, State).
is_owner(undefined, _State) -> false;
is_owner(Actor, State) -> Actor =:= maps:get(owner, State).

public_projection(State) ->
    Base = (maps:with([id, name, status], State))#{paused => maps:get(paused, State, false)},
    with_optional(reference, State, with_translations(State, Base)).
details_projection(Actor, State) ->
    case is_owner(Actor, State) of
        true -> (public_projection(State))#{created_at => maps:get(created_at, State)};
        false -> public_projection(State)
    end.
stats_projection(State) ->
    Subscribers = maps:values(maps:get(subscribers, State)),
    Connections = [subscriber_projection(Subscriber) || Subscriber <- Subscribers],
    ActorConnections = length([ok || #{actor := Actor} <- Connections, Actor =/= <<"anonymous">>]),
    #{id => maps:get(id, State),
      running_for_seconds => running_for_seconds(State),
      revision => maps:get(sequence, State),
      stack_entries => length(payload_verses(maps:get(current, State))),
      connections => length(Connections),
      actor_connections => ActorConnections,
      anonymous_connections => length(Connections) - ActorConnections,
      subscribers => lists:sort(fun subscriber_before/2, Connections)}.
subscriber_projection(#{actor := Actor, connected_at := ConnectedAt}) when is_binary(Actor) ->
    #{actor => Actor, access => actor, connected_at => ConnectedAt,
      connected_for_seconds => erlang:max(0, now_seconds() - ConnectedAt)};
subscriber_projection(#{actor := secret, connected_at := ConnectedAt}) ->
    #{actor => <<"anonymous">>, access => secret, connected_at => ConnectedAt,
      connected_for_seconds => erlang:max(0, now_seconds() - ConnectedAt)};
subscriber_projection(#{connected_at := ConnectedAt}) ->
    #{actor => <<"anonymous">>, access => open, connected_at => ConnectedAt,
      connected_for_seconds => erlang:max(0, now_seconds() - ConnectedAt)}.
subscriber_before(Left, Right) ->
    {maps:get(connected_at, Left), maps:get(actor, Left)} =< {maps:get(connected_at, Right), maps:get(actor, Right)}.

with_optional(Key, State, Projection) ->
    case maps:get(Key, State) of
        undefined -> Projection;
        Value -> Projection#{Key => Value}
    end.
with_translations(#{translations := []}, Projection) -> Projection;
with_translations(#{translations := Translations}, Projection) -> Projection#{translations => join_translations(Translations)}.
join_translations(Translations) -> iolist_to_binary(lists:join(<<",">>, Translations)).

broadcast(State) ->
    Event = {live_event, maps:get(id, State), public_projection(State)},
    notify_subscribers(Event, State).
broadcast_verse(State, Payload) ->
    Event = {live_verse, maps:get(id, State), Payload},
    notify_subscribers(Event, State).
broadcast_clear(State) ->
    Event = {live_clear, maps:get(id, State)},
    notify_subscribers(Event, State).
broadcast_paused(State) ->
    Event = {live_paused, maps:get(id, State)},
    notify_subscribers(Event, State).
broadcast_closed(State) ->
    Event = {live_closed, maps:get(id, State)},
    notify_subscribers(Event, State).
notify_subscribers(Event, State) ->
    maps:foreach(fun(_Ref, #{pid := Pid}) -> Pid ! Event end, maps:get(subscribers, State)).
send_current(Subscriber, State) ->
    case {maps:get(status, State), maps:get(showing, State), maps:get(paused, State, false), maps:get(current, State)} of
        {running, true, false, Payload} when Payload =/= undefined -> Subscriber ! {live_verse, maps:get(id, State), Payload};
        _ -> ok
    end.

update_secret(Actor, Secret, State) ->
    case {is_owner(Actor, State), valid_secret(Secret)} of
        {false, _} -> {reply, {error, forbidden}, State};
        {true, false} -> {reply, {error, invalid_secret}, State};
        {true, true} ->
            Subscribers = revoke_secret_subscribers(State),
            Next = State#{secret_hash => secret_hash(Secret), subscribers => Subscribers},
            case persist(Next) of
                ok -> {reply, {ok, public_projection(Next)}, Next};
                {error, _} -> {reply, {error, persistence_failed}, State}
            end
    end.
valid_secret(Secret) when is_binary(Secret) -> byte_size(Secret) >= 8 andalso byte_size(Secret) =< 256;
valid_secret(_) -> false.
secret_hash(Secret) -> crypto:hash(sha256, Secret).
has_secret(State) -> maps:is_key(secret_hash, State).
secret_matches(Secret, State) when is_binary(Secret) ->
    case maps:find(secret_hash, State) of
        {ok, Hash} -> secret_hash(Secret) =:= Hash;
        error -> false
    end;
secret_matches(_, _State) -> false.
revoke_secret_subscribers(State) ->
    maps:fold(fun(Ref, #{pid := Pid, actor := Actor} = Entry, Acc) ->
        case Actor =:= secret of
            true -> erlang:demonitor(Ref, [flush]), Pid ! {live_access_revoked, maps:get(id, State)}, Acc;
            false -> Acc#{Ref => Entry}
        end
    end, #{}, maps:get(subscribers, State)).

persisted_projection(State) -> maps:without([subscribers], State).
limit(Key, Default) ->
    Limits = bibleit_rate_limiter:limits(),
    case maps:get(Key, Limits, Default) of Value when is_integer(Value), Value > 0 -> Value; _ -> Default end.
persist(State) ->
    case whereis(bibleit_live_store) of
        undefined -> ok;
        _ -> bibleit_live_store:save(persisted_projection(State))
    end.
now_seconds() -> erlang:system_time(second).
running_for_seconds(#{status := stopped, running_seconds := Seconds}) -> Seconds;
running_for_seconds(#{running_seconds := Seconds, running_since := Since}) ->
    Seconds + erlang:max(0, now_seconds() - Since).
apply_option(name, Value, State) when is_binary(Value), byte_size(Value) > 0 -> {ok, State#{name => Value}};
apply_option(reference, Value, State) when is_binary(Value), byte_size(Value) > 0 -> {ok, State#{reference => Value}};
apply_option(translations, Values, State) when is_list(Values) -> {ok, State#{translations => Values}};
apply_option(_, _, _) -> error.

read_payload(Actor, #{translation := Translation} = Reference, State) ->
    build_payload(Actor, [Translation], Reference, State);
read_payload(Actor, Reference, State) ->
    case maps:get(translations, State) of
        [] -> {error, translations_not_configured};
        Translations -> build_payload(Actor, Translations, Reference, State)
    end.
build_payload(Actor, Translations, Reference, State) ->
    case canonical_reference(Translations, Reference) of
        {ok, CanonicalReference} ->
            case read_translations(Translations, CanonicalReference, []) of
                {ok, VerseGroups} ->
                    Verses = lists:append(lists:reverse(VerseGroups)),
                    case Verses of
                        [First | _] ->
                            Sequence = maps:get(sequence, State) + 1,
                            {ok, First#{translations => Verses, publisher_id => Actor, sequence => Sequence}};
                        [] -> {error, not_found}
                    end;
                Error -> Error
            end;
        Error -> Error
    end.
push_payload(Payload, #{current := undefined}) -> Payload;
push_payload(Payload, #{current := Current}) ->
    Verses = payload_verses(Current) ++ payload_verses(Payload),
    [First | _] = Verses,
    First#{translations => Verses, publisher_id => maps:get(publisher_id, Payload),
           sequence => maps:get(sequence, Payload)}.
pop_payload(Current, Count, _State) ->
    Verses = payload_verses(Current),
    Keep = case Count > 0 of
        true -> lists:sublist(Verses, erlang:max(0, length(Verses) - Count));
        false -> lists:nthtail(erlang:min(length(Verses), -Count), Verses)
    end,
    case Keep of
        [] -> {clear, undefined};
        [First | _] -> {ok, First#{translations => Keep}}
    end.
payload_verses(undefined) -> [];
payload_verses(#{translations := Verses}) when is_list(Verses), Verses =/= [] -> Verses;
payload_verses(Payload) -> [Payload].
read_translations([], _Reference, Acc) -> {ok, Acc};
read_translations([Translation | Rest], Reference, Acc) ->
    case read_translation(Translation, Reference) of
        {ok, Verses} -> read_translations(Rest, Reference, [Verses | Acc]);
        Error -> Error
    end.
read_translation(Translation, #{book := Book, chapter := Chapter, verse := Verse}) ->
    case resolve_book(Translation, Book) of
        {ok, BookId} ->
            Result = case {Chapter, Verse} of
                {undefined, _} -> bibleit_translation_registry:read(Translation, BookId);
                {_, undefined} -> bibleit_translation_registry:read(Translation, BookId, Chapter);
                _ -> bibleit_translation_registry:read(Translation, BookId, Chapter, Verse)
            end,
            case Result of
                {ok, Text} when is_binary(Text) -> {ok, [verse_payload(Translation, Text)]};
                {ok, Lines} when is_list(Lines) -> {ok, [verse_payload(Translation, Line) || Line <- Lines]};
                {error, _} = Error -> Error
            end;
        Error -> Error
    end.
resolve_book(_Translation, Book) when is_integer(Book) -> {ok, Book};
resolve_book(Translation, Book) -> bibleit_translation_catalog:resolve_book(Translation, Book).
canonical_reference(_Translations, #{book := Book} = Reference) when is_integer(Book) -> {ok, Reference};
canonical_reference(Translations, #{book := Book} = Reference) ->
    find_book_id(Translations, Book, Reference).
find_book_id([], _Book, _Reference) -> {error, book_not_found};
find_book_id([Translation | Rest], Book, Reference) ->
    case bibleit_translation_catalog:resolve_book(Translation, Book) of
        {ok, BookId} -> {ok, Reference#{book => BookId}};
        {error, book_not_found} -> find_book_id(Rest, Book, Reference);
        Error -> Error
    end.
verse_payload(Translation, Line) ->
    case re:run(Line, <<"^(.*) ([0-9]+):([0-9]+) (.*)$">>, [{capture, all_but_first, binary}]) of
        {match, [Book, Chapter, Verse, Text]} ->
            #{translation => Translation, book => Book, chapter => binary_to_integer(Chapter),
              verse => binary_to_integer(Verse), text => Text,
              reference => <<Book/binary, " ", Chapter/binary, ":", Verse/binary>>};
        nomatch -> #{translation => Translation, text => Line}
    end.
