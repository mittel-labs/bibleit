-module(bibleit_protocol).
-export([handle/2, decode/1, encode/1, version/0, request_cost/1]).

%% One space-separated command per TCP line. Names and Bible references consume
%% the remainder of their command line, so they naturally support spaces.

decode(Line) when is_binary(Line) -> parse(words(binary_to_list(Line), [], [])).

encode({ok, Fields}) when is_list(Fields) -> ["OK", fields(Fields), "\n"];
encode({ok, {lives, Lives}}) ->
    ["OK count=", integer_to_list(length(Lives)), "\n",
     [["LIVE", fields(maps:to_list(Live)), "\n"] || Live <- Lives], "END\n"];
encode({ok, {books, Slug, Books}}) ->
    [["OK", fields([{translation, Slug}, {books, length(Books)}]), "\n"],
     [book_lines(Book) || Book <- Books], "END\n"];
encode({ok, {help, _Topic, Authenticated, Commands}}) ->
    [["OK", fields([{auth, Authenticated}, {commands, length(Commands)}]), "\n"],
     [help_line(Command) || Command <- Commands], "END\n"];
encode({ok, {auth_permissions, Permissions}}) ->
    ["OK count=", integer_to_list(length(Permissions)), "\n",
     [["PERMISSION", fields([{resource, list_to_binary(atom_to_list(Resource))}, {verb, list_to_binary(atom_to_list(Verb))}]), "\n"] || {Resource, Verb} <- Permissions], "END\n"];
encode({ok, {auth_resources, Resources}}) ->
    ["OK count=", integer_to_list(length(Resources)), "\n",
     [["RESOURCE", fields([{name, list_to_binary(atom_to_list(Resource))}]), "\n"] || Resource <- Resources], "END\n"];
encode({ok, {auth_roles, Roles}}) ->
    ["OK count=", integer_to_list(length(Roles)), "\n",
     [["ROLE", fields([{name, list_to_binary(atom_to_list(Role))}, {permissions, join_permissions(Permissions)}]), "\n"] || {Role, Permissions} <- Roles], "END\n"];
encode({ok, {auth_quotas, Actor, Quotas}}) ->
    [["OK", fields([{actor, Actor}, {count, length(Quotas)}]), "\n"],
     [["QUOTA", fields([{permission, permission_name(Permission)}, {limit, Limit}]), "\n"] || {Permission, Limit} <- Quotas], "END\n"];
encode({ok, {account_quotas, Quotas}}) ->
    [["OK", fields([{count, length(Quotas)}]), "\n"],
     [["QUOTA", fields([{permission, permission_name(Permission)}, {limit, Limit}, {used, Used}]), "\n"] || {Permission, Limit, Used} <- Quotas], "END\n"];
encode({ok, {actors, Actors}}) ->
    ["OK count=", integer_to_list(length(Actors)), "\n",
     [actor_line(Actor) || Actor <- Actors], "END\n"];
encode({ok, {actors, Actors, Next}}) ->
    [["OK", fields([{count, length(Actors)}] ++ case Next of undefined -> []; _ -> [{next, Next}] end), "\n"],
     [actor_line(Actor) || Actor <- Actors], "END\n"];
encode({ok, {tokens, Actor, Tokens}}) ->
    [["OK", fields([{actor, Actor}, {count, length(Tokens)}]), "\n"],
     [["TOKEN", fields(maps:to_list(Token)), "\n"] || Token <- Tokens], "END\n"];
encode({ok, {keys, Actor, Keys}}) ->
    [["OK", fields([{actor, Actor}, {count, length(Keys)}]), "\n"],
     [["KEY", fields(maps:to_list(Key)), "\n"] || Key <- Keys], "END\n"];
encode({ok, {verses, Fields, Lines}}) ->
    [["OK", fields(Fields), "\n"], [["VERSE text=", format(Line), "\n"] || Line <- Lines], "END\n"];
encode({ok, {live_verse, Payload}}) ->
    Verses = maps:get(translations, Payload),
    [["OK event=verse", fields([{translations, length(Verses)}]), "\n"],
     [live_verse_line(Verse) || Verse <- Verses], "END\n"];
encode({ok, {live_stack, Id, Verses}}) ->
    [["OK", fields([{id, Id}, {count, length(Verses)}]), "\n"],
     [live_stack_line(Position, Verse) || {Position, Verse} <- lists:zip(lists:seq(1, length(Verses)), Verses)], "END\n"];
encode({ok, {live_stats, Stats}}) ->
    Connections = maps:get(subscribers, Stats),
    [["OK", fields([{connections, length(Connections)} | maps:to_list(maps:remove(subscribers, Stats))]), "\n"],
     [["CONNECTION", fields(maps:to_list(Connection)), "\n"] || Connection <- Connections], "END\n"];
encode({ok, live_cleared}) -> "OK event=clear\n";
encode({ok, live_removed}) -> "OK event=deleted\n";
encode({event, live, Id, Live}) -> ["EVENT live=", format(Id), fields(maps:to_list(Live)), "\n"];
encode({event, verse, Payload}) -> ["EVENT verse ", event_payload(Payload), "\n"];
encode({event, clear}) -> "EVENT clear\n";
encode({event, paused}) -> "EVENT paused\n";
encode({event, closed}) -> "EVENT closed\n";
encode({event, revoked}) -> "EVENT revoked\n";
encode({error, rate_limited, RetryAfter}) -> ["ERR rate_limited retry_after_ms=", integer_to_list(RetryAfter), "\n"];
encode({error, Code}) -> ["ERR ", atom_to_list(Code), "\n"].

request_cost({search, _, _}) -> 5;
request_cost({translation_catalog, _}) -> 5;
request_cost({read, _, _}) -> 3;
request_cost({read, _, _, _}) -> 3;
request_cost({read_named, _, _, _, _}) -> 3;
request_cost(_) -> 1.

%% A connected socket is never a public command surface. The two key-login
%% requests are the only bootstrap exception for the TLS/TCP protocol; SSH
%% performs the equivalent proof before it opens a channel.
handle(Request, State) when is_map(State) ->
    case is_authenticated(State) orelse authentication_bootstrap(Request) of
        true -> dispatch(Request, State);
        false -> {reply, {error, unauthorized}, State}
    end.

authentication_bootstrap({auth_login_key, _}) -> true;
authentication_bootstrap({auth_login_prove, _, _}) -> true;
authentication_bootstrap(quit) -> true;
authentication_bootstrap(_) -> false.

dispatch(server_info, State) ->
    case has_permission({server, get}, State) of
        false -> {reply, {error, forbidden}, State};
        true ->
            Fields = [{protocol_version, 1}, {version, version()}] ++
                     case is_authenticated(State) of
                         true -> [{capabilities, <<"help,auth,translation,read,search,live">>}];
                         false -> []
                     end,
            {reply, {ok, Fields}, State}
    end;
dispatch(ping, State) -> {reply, {ok, [{pong, true}]}, State};
dispatch(quit, State) -> {reply, {ok, [{closing, true}]}, State#{close_after_reply => true}};
dispatch({help, Topic}, State) ->
    case has_permission({help, get}, State) of
        false -> {reply, {error, forbidden}, State};
        true -> case help_commands(Topic, State) of
            {ok, Commands} -> {reply, {ok, {help, Topic, is_authenticated(State), Commands}}, State};
            error -> {reply, {error, help_topic_not_found}, State}
        end
    end;
dispatch(translation_list, State) ->
    guarded({translation, list}, State, fun() ->
    case bibleit_api:translations() of
        {ok, Slugs} -> {reply, {ok, [{translations, join_binaries(Slugs)}]}, State};
        {error, Error} -> {reply, {error, Error}, State}
    end end);
dispatch(available_translation_list, State) ->
    guarded({translation, list}, State, fun() ->
    case bibleit_api:all_translations() of
        {ok, Slugs} -> {reply, {ok, [{translations, join_binaries(Slugs)}]}, State};
        {error, Error} -> {reply, {error, Error}, State}
    end end);
dispatch({translation_info, Slug}, State) ->
    guarded({translation, get}, State, fun() ->
    case bibleit_api:translation_info(Slug) of
        {ok, Info} ->
            Fields = [{short_name, maps:get(<<"short_name">>, Info)}, {full_name, maps:get(<<"full_name">>, Info)}] ++
                     case maps:find(<<"updated">>, Info) of {ok, Updated} -> [{updated, Updated}]; error -> [] end,
            {reply, {ok, Fields}, State};
        {error, Error} -> {reply, {error, Error}, State}
    end end);
dispatch({translation_catalog, Slug}, State) ->
    guarded({translation, get}, State, fun() ->
    case bibleit_api:translation_catalog(Slug) of
        {ok, Books} -> {reply, {ok, {books, Slug, Books}}, State};
        {error, Error} -> {reply, {error, Error}, State}
    end end);
dispatch({search, Slug, Query}, State) ->
    guarded({translation, search}, State, fun() ->
    Limit = search_limit(),
    case bibleit_api:search(Slug, Query, Limit) of
        {ok, Lines} -> {reply, {ok, {verses, [{translation, Slug}, {results, length(Lines)}], Lines}}, State};
        {error, Error} -> {reply, {error, Error}, State}
    end end);
dispatch({read, Slug, Book, Chapter, Verse}, State) ->
    guarded({translation, read}, State, fun() ->
    case bibleit_api:read(Slug, Book, Chapter, Verse) of
        {ok, Text} -> {reply, {ok, [{translation, Slug}, {book, Book}, {chapter, Chapter},
                                    {verse, Verse}, {text, trim_line_ending(Text)}]}, State};
        {error, Error} -> {reply, {error, Error}, State}
    end end);
dispatch({read, Slug, Book, Chapter}, State) -> read_many(bibleit_api:read(Slug, Book, Chapter), Slug, Book, Chapter, State);
dispatch({read, Slug, Book}, State) -> read_many(bibleit_api:read(Slug, Book), Slug, Book, undefined, State);
dispatch({read_named, Slug, Name, Chapter, Verse}, State) ->
    case bibleit_api:resolve_book(Slug, Name) of
        {ok, Book} when Chapter =:= undefined -> handle({read, Slug, Book}, State);
        {ok, Book} when Verse =:= undefined -> handle({read, Slug, Book, Chapter}, State);
        {ok, Book} -> handle({read, Slug, Book, Chapter, Verse}, State);
        {error, Error} -> {reply, {error, Error}, State}
    end;
dispatch({auth_login_key, Fingerprint}, State) ->
    case bibleit_authorization:key(Fingerprint) of
        {ok, _Actor, _PublicKey} ->
            Challenge = binary:encode_hex(crypto:strong_rand_bytes(16)),
            Nonce = crypto:strong_rand_bytes(32),
            ExpiresAt = erlang:system_time(second) + 60,
            Fields = [{challenge, Challenge}, {nonce, base64:encode(Nonce)}, {algorithm, <<"ssh-ed25519">>}, {expires_at, ExpiresAt}],
            {reply, {ok, Fields}, State#{key_challenge => #{id => Challenge, nonce => Nonce, fingerprint => Fingerprint, expires_at => ExpiresAt}}};
        {error, key_not_found} -> {reply, {error, unknown_key}, State}
    end;
dispatch({auth_login_prove, Challenge, Signature}, State) ->
    case maps:get(key_challenge, State, undefined) of
        #{id := Challenge, nonce := Nonce, fingerprint := Fingerprint, expires_at := ExpiresAt} ->
            case ExpiresAt >= erlang:system_time(second) of
                false -> {reply, {error, expired_challenge}, State#{key_challenge => undefined}};
                true ->
            case bibleit_authorization:key(Fingerprint) of
                {ok, Actor, PublicKey} ->
                    case verify_key_signature(Challenge, Nonce, Signature, PublicKey) of
                        true ->
                            {ok, Permissions} = bibleit_authorization:actor_permissions(Actor),
                            ok = bibleit_authorization:touch_key(Fingerprint),
                            {ok, ActorInfo} = bibleit_authorization:actor_info(Actor),
                            Roles = maps:get(roles, ActorInfo, []),
                            {reply, {ok, [{actor, Actor}, {key_fingerprint, Fingerprint}]}, State#{actor => Actor, permissions => Permissions, roles => Roles, key_fingerprint => Fingerprint, key_challenge => undefined}};
                        false -> {reply, {error, invalid_signature}, State#{key_challenge => undefined}}
                    end;
                {error, key_not_found} -> {reply, {error, unknown_key}, State#{key_challenge => undefined}}
            end
            end;
        _ -> {reply, {error, invalid_challenge}, State#{key_challenge => undefined}}
    end;
dispatch(auth_info, #{actor := Actor} = State) ->
    KeyField = case maps:get(key_fingerprint, State, undefined) of undefined -> []; Fingerprint -> [{key_fingerprint, Fingerprint}] end,
    {reply, {ok, [{actor, Actor}, {display_name, actor_display_name(Actor)}, {auth, true} | KeyField] ++ [{roles, join_roles(maps:get(roles, State, []))}, {permissions, join_permissions(effective_permissions(State))}]}, State};
dispatch(account_info, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch(account_info, #{actor := Actor} = State) ->
    case bibleit_account:summary(Actor) of
        {ok, Summary} -> {reply, {ok, account_summary_fields(Summary)}, State};
        Error -> {reply, Error, State}
    end;
dispatch(account_quotas, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch(account_quotas, #{actor := Actor} = State) ->
    case bibleit_account:quotas(Actor) of
        {ok, Quotas} -> {reply, {ok, {account_quotas, Quotas}}, State};
        Error -> {reply, Error, State}
    end;
dispatch({account_create_token, _Label}, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch({account_create_token, Label}, #{actor := Actor} = State) ->
    permitted_change({token, create}, State, fun() ->
        case bibleit_account:create_token(Actor, Label) of
            {ok, Id, Token} -> {ok, [{id, Id}, {token, Token}]};
            Error -> Error
        end
    end);
dispatch(account_list_tokens, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch(account_list_tokens, #{actor := Actor} = State) ->
    guarded({token, get}, State, fun() ->
        case bibleit_account:tokens(Actor) of
            {ok, Tokens} -> {reply, {ok, {tokens, Actor, Tokens}}, State};
            Error -> {reply, Error, State}
        end
    end);
dispatch({account_revoke_tokens, _Id}, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch({account_revoke_tokens, Id}, #{actor := Actor} = State) ->
    permitted_change({token, delete}, State, fun() ->
        case Id of
            all -> case bibleit_account:revoke_tokens(Actor, all) of {ok, Count} -> {ok, [{revoked, Count}]}; Error -> Error end;
            _ -> case bibleit_account:revoke_tokens(Actor, Id) of ok -> {ok, [{id, Id}]}; Error -> Error end
        end
    end);
dispatch({account_create_key, _PublicKey}, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch({account_create_key, PublicKey}, #{actor := Actor} = State) ->
    permitted_change({key, create}, State, fun() ->
        case bibleit_account:add_key(Actor, PublicKey) of
            {ok, Fingerprint} -> {ok, [{fingerprint, Fingerprint}]};
            Error -> Error
        end
    end);
dispatch(account_list_keys, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch(account_list_keys, #{actor := Actor} = State) ->
    guarded({key, get}, State, fun() ->
        case bibleit_account:keys(Actor) of
            {ok, Keys} -> {reply, {ok, {keys, Actor, Keys}}, State};
            Error -> {reply, Error, State}
        end
    end);
dispatch({account_revoke_key, _Fingerprint}, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch({account_revoke_key, Fingerprint}, #{actor := Actor} = State) ->
    permitted_change({key, delete}, State, fun() ->
        case bibleit_account:revoke_key(Actor, Fingerprint) of
            ok -> {ok, [{fingerprint, Fingerprint}]};
            Error -> Error
        end
    end);
dispatch(auth_logout, State) ->
    case is_authenticated(State) of
        false -> {reply, {error, unauthorized}, State};
        true ->
        unsubscribe_lives(maps:get(subscriptions, State, #{})),
        Next = State#{actor => undefined, permissions => [], roles => [], key_fingerprint => undefined, key_challenge => undefined, subscriptions => #{}},
        {reply, {ok, [{auth, false}]}, Next}
    end;
dispatch(auth_permissions, State) -> guarded({authorization, list}, State, fun() -> {reply, {ok, {auth_permissions, bibleit_authorization:permissions()}}, State} end);
dispatch(auth_resources, State) -> guarded({authorization, list}, State, fun() -> {reply, {ok, {auth_resources, lists:usort([Resource || {Resource, _Verb} <- bibleit_authorization:permissions()])}}, State} end);
dispatch(auth_roles, State) -> guarded({role, list}, State, fun() -> {reply, {ok, {auth_roles, maps:to_list(bibleit_authorization:roles())}}, State} end);
dispatch({auth_quotas, Actor}, State) ->
    guarded({quota, get}, State, fun() ->
        case can_manage_target(Actor, State) of
            true -> case bibleit_authorization:quotas(Actor) of
                {ok, Quotas} -> {reply, {ok, {auth_quotas, Actor, Quotas}}, State};
                {error, Error} -> {reply, {error, Error}, State}
            end;
            false -> {reply, {error, forbidden}, State}
        end
    end);
dispatch({list_actors, Limit, Cursor}, State) ->
    guarded({actor, list}, State, fun() ->
        {Actors, Next} = case is_server_admin(State) of true -> bibleit_authorization:actor_page(Limit, Cursor); false -> bibleit_authorization:child_page(maps:get(actor, State), Limit, Cursor) end,
        {reply, {ok, {actors, Actors, Next}}, State}
    end);
dispatch({actor_info, Actor}, State) ->
    guarded({actor, get}, State, fun() ->
        case can_manage_target(Actor, State) of
            true -> case bibleit_authorization:actor_info(Actor) of
                {ok, Info} -> {reply, {ok, actor_info_fields(Info)}, State};
                {error, Error} -> {reply, {error, Error}, State}
            end;
            false -> {reply, {error, forbidden}, State}
        end
    end);
dispatch({create_actor, Actor}, State) ->
    permitted_change({actor, create}, State, fun() ->
        case bibleit_authorization:create_actor(maps:get(actor, State), Actor) of ok -> {ok, [{actor, Actor}]}; Error -> Error end
    end);
dispatch({delete_actor, Actor}, State) ->
    permitted_change({actor, delete}, State, fun() ->
        case can_manage_target(Actor, State) of
            true -> case bibleit_authorization:delete_actor(Actor) of {ok, Revoked} -> {ok, [{actor, Actor}, {revoked, Revoked}]}; Error -> Error end;
            false -> {error, forbidden}
        end
    end);
dispatch({create_token, Actor}, State) ->
    operator_permitted_change({token, create}, State, fun() ->
        case can_manage_target(Actor, State) of
            true -> case bibleit_authorization:create_token(maps:get(actor, State), Actor) of {ok, Id, Token} -> {ok, [{actor, Actor}, {id, Id}, {token, Token}]}; Error -> Error end;
            false -> {error, forbidden}
        end
    end);
dispatch({create_token, Actor, Label}, State) ->
    operator_permitted_change({token, create}, State, fun() ->
        case can_manage_target(Actor, State) of
            true -> case bibleit_authorization:create_token(maps:get(actor, State), Actor, Label) of {ok, Id, Token} -> {ok, [{actor, Actor}, {id, Id}, {token, Token}]}; Error -> Error end;
            false -> {error, forbidden}
        end
    end);
dispatch({revoke_tokens, Actor, all}, State) ->
    operator_permitted_change({token, delete}, State, fun() ->
        case can_manage_target(Actor, State) of
            true -> case bibleit_authorization:revoke_tokens(Actor) of {ok, Count} -> {ok, [{actor, Actor}, {revoked, Count}]}; Error -> Error end;
            false -> {error, forbidden}
        end
    end);
dispatch({revoke_tokens, Actor, Id}, State) ->
    operator_permitted_change({token, delete}, State, fun() ->
        case can_manage_target(Actor, State) of true -> case bibleit_authorization:revoke_token(Actor, Id) of ok -> {ok, [{actor, Actor}, {id, Id}]}; Error -> Error end; false -> {error, forbidden} end
    end);
dispatch({list_tokens, Actor}, State) ->
    operator_guarded({token, get}, State, fun() ->
        case can_manage_target(Actor, State) of true -> case bibleit_authorization:tokens(Actor) of {ok, Tokens} -> {reply, {ok, {tokens, Actor, Tokens}}, State}; Error -> {reply, Error, State} end; false -> {reply, {error, forbidden}, State} end
    end);
dispatch({create_key, Actor, PublicKey}, State) ->
    operator_permitted_change({key, create}, State, fun() ->
        case can_manage_target(Actor, State) of
            true -> case bibleit_authorization:create_key(maps:get(actor, State), Actor, PublicKey) of {ok, Fingerprint} -> {ok, [{actor, Actor}, {fingerprint, Fingerprint}]}; Error -> Error end;
            false -> {error, forbidden}
        end
    end);
dispatch({list_keys, Actor}, State) ->
    operator_guarded({key, get}, State, fun() ->
        case can_manage_target(Actor, State) of
            true -> case bibleit_authorization:keys(Actor) of {ok, Keys} -> {reply, {ok, {keys, Actor, Keys}}, State}; Error -> {reply, Error, State} end;
            false -> {reply, {error, forbidden}, State}
        end
    end);
dispatch({revoke_key, Actor, Fingerprint}, State) ->
    operator_permitted_change({key, delete}, State, fun() ->
        case can_manage_target(Actor, State) of
            true -> case bibleit_authorization:revoke_key(Actor, Fingerprint) of ok -> {ok, [{actor, Actor}, {fingerprint, Fingerprint}]}; Error -> Error end;
            false -> {error, forbidden}
        end
    end);
dispatch({create_role, Name, Permissions}, State) ->
    permitted_change({role, create}, State, fun() ->
        case can_delegate_permissions(Permissions, State) of
            true -> case bibleit_authorization:create_role(Name, Permissions) of ok -> {ok, [{role, Name}, {permissions, join_permissions(Permissions)}]}; Error -> Error end;
            false -> {error, forbidden}
        end
    end);
dispatch({update_role, Name, Permissions}, State) ->
    permitted_change({role, update}, State, fun() ->
        case can_delegate_permissions(Permissions, State) of
            true -> case bibleit_authorization:update_role(Name, Permissions) of ok -> {ok, [{role, Name}, {permissions, join_permissions(Permissions)}]}; Error -> Error end;
            false -> {error, forbidden}
        end
    end);
dispatch({delete_role, Name}, State) ->
    permitted_change({role, delete}, State, fun() ->
        case bibleit_authorization:delete_role(Name) of ok -> {ok, [{role, Name}]}; Error -> Error end
    end);
dispatch({create_live, _Name}, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch({create_live, Name}, #{actor := Actor} = State) ->
    permitted_change({live, create}, State, fun() ->
        case bibleit_live_registry:create(Actor, #{name => Name}, bibleit_authorization:quota_limit(Actor, {live, create})) of
            {ok, _Id, Live} -> {ok, maps:to_list(Live)};
            {error, Error} -> {error, Error}
        end
    end);
dispatch({set_live_secret, Id, Secret}, State) ->
    guarded({live, update}, State, fun() -> with_live(Id, fun(Pid) ->
        case bibleit_live_session:set_secret(Pid, maps:get(actor, State), Secret) of
            {ok, _} -> {reply, {ok, [{id, Id}, {secret, Secret}]}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State) end);
dispatch({rotate_live_secret, Id}, State) ->
    guarded({live, update}, State, fun() -> with_live(Id, fun(Pid) ->
        case bibleit_live_session:rotate_secret(Pid, maps:get(actor, State)) of
            {ok, #{secret := Secret}} -> {reply, {ok, [{id, Id}, {secret, Secret}]}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State) end);
dispatch({delete_live_secret, Id}, State) ->
    guarded({live, update}, State, fun() -> with_live(Id, fun(Pid) ->
        case bibleit_live_session:delete_secret(Pid, maps:get(actor, State)) of
            {ok, _} -> {reply, {ok, [{id, Id}]}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State) end);
dispatch({authenticate_live_secret, Id, Secret}, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:authenticate_secret(Pid, Secret) of
            ok -> {reply, {ok, []}, State#{live_secret => {Id, Secret}}};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State);
dispatch({global_grant, Actor, permission, Permissions}, State) -> actor_change(State, Actor, fun() ->
    case can_delegate_permissions(Permissions, State) of true -> bibleit_authorization:grant_permissions(Actor, Permissions); false -> {error, forbidden} end
end);
dispatch({global_grant, Actor, role, [Role]}, State) -> actor_change(State, Actor, fun() ->
    case role_binding_allowed(Role, State) of ok -> bibleit_authorization:grant_role(Actor, Role); Error -> Error end
end);
dispatch({global_grant, Actor, quota, {Permission, Limit}}, State) ->
    quota_change(State, Actor, fun() -> bibleit_authorization:set_quota(Actor, Permission, Limit) end);
dispatch({global_revoke, Actor, permission, Permissions}, State) -> actor_change(State, Actor, fun() ->
    case can_delegate_permissions(Permissions, State) of true -> bibleit_authorization:revoke_permissions(Actor, Permissions); false -> {error, forbidden} end
end);
dispatch({global_revoke, Actor, role, [Role]}, State) -> actor_change(State, Actor, fun() ->
    case role_binding_allowed(Role, State) of ok -> bibleit_authorization:revoke_role(Actor, Role); Error -> Error end
end);
dispatch({global_revoke, Actor, quota, Permission}, State) ->
    quota_change(State, Actor, fun() -> bibleit_authorization:revoke_quota(Actor, Permission) end);
dispatch({get_live, Id}, State) ->
    guarded({live, get}, State, fun() -> with_live(Id, fun(Pid) ->
        case bibleit_live_session:details(Pid, maps:get(actor, State)) of
            {ok, Live} ->
                Owner = bibleit_live_session:owner(Pid),
                {reply, {ok, maps:to_list(maybe_add_created_by(Live, Owner, State))}, State};
            {error, forbidden} -> {reply, {error, forbidden}, State}
        end
    end, State) end);
dispatch(list_lives, State) ->
    guarded({live, list}, State, fun() ->
        {ok, Lives} = bibleit_live_registry:list(maps:get(actor, State)),
        {reply, {ok, {lives, Lives}}, State}
    end);
dispatch({set_live, Id, Option, Value}, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:set_option(Pid, maps:get(actor, State), Option, Value) of
            {ok, Live} -> {reply, {ok, maps:to_list(Live)}, State};
            {error, forbidden} -> {reply, {error, forbidden}, State}
        end
    end, State);
dispatch({push_live, Id, Reference}, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:push(Pid, maps:get(actor, State), Reference) of
            {ok, Payload} -> {reply, {ok, {live_verse, Payload}}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State);
dispatch({pop_live, Id, Count}, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:pop(Pid, maps:get(actor, State), Count) of
            {ok, live_cleared} -> {reply, {ok, live_cleared}, State};
            {ok, Payload} -> {reply, {ok, {live_verse, Payload}}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State);
dispatch({live_stack_info, Id}, State) ->
    guarded({live, get}, State, fun() -> with_live(Id, fun(Pid) ->
        case bibleit_live_session:stack_info(Pid, maps:get(actor, State)) of
            {ok, Verses} -> {reply, {ok, {live_stack, Id, Verses}}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State) end);
dispatch({live_stats, Id}, State) ->
    guarded({live, get}, State, fun() -> with_live(Id, fun(Pid) ->
        case bibleit_live_session:stats(Pid, maps:get(actor, State)) of
            {ok, Stats} -> {reply, {ok, {live_stats, Stats}}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State) end);
dispatch({clear_live, Id}, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:clear(Pid, maps:get(actor, State)) of
            ok -> {reply, {ok, live_cleared}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State);
dispatch({resume_live, Id}, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:resume(Pid, maps:get(actor, State)) of
            ok -> {reply, {ok, [{paused, false}]}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State);
dispatch({pause_live, Id}, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:pause(Pid, maps:get(actor, State)) of
            ok -> {reply, {ok, [{paused, true}]}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State);
dispatch({start_live, Id}, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:start(Pid, maps:get(actor, State)) of
            {ok, Live} -> {reply, {ok, maps:to_list(Live)}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State);
dispatch({stop_live, Id}, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:stop(Pid, maps:get(actor, State)) of
            {ok, Live} -> {reply, {ok, maps:to_list(Live)}, State};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State);
dispatch({remove_live, Id}, State) ->
    case bibleit_live_registry:remove(Id, maps:get(actor, State)) of
        ok -> {reply, {ok, live_removed}, State};
        {error, Error} -> {reply, {error, Error}, State}
    end;
dispatch(remove_all_lives, #{actor := undefined} = State) ->
    {reply, {error, unauthorized}, State};
dispatch(remove_all_lives, State) ->
    case bibleit_live_registry:remove_all(maps:get(actor, State)) of
        {ok, Count} -> {reply, {ok, [{deleted, Count}]}, State}
    end;
dispatch({subscribe_live, Id}, State) ->
    case maps:get(live_secret, State, undefined) of
        {Id, Secret} -> subscribe_with_secret(Id, Secret, State);
        _ -> guarded({live, subscribe}, State, fun() -> subscribe_to_live(Id, State) end)
    end;
dispatch({fetch_translation, _Slug}, #{actor := undefined} = State) -> {reply, {error, unauthorized}, State};
dispatch({fetch_translation, Slug}, State) ->
    permitted_change({translation, create}, State, fun() ->
        case bibleit_api:fetch_translation(Slug) of
            {ok, Installed} -> {ok, [{translation, Installed}]};
            {error, Error} -> {error, Error}
        end
    end);
dispatch({delete_translation, _Slug}, #{actor := undefined} = State) -> {reply, {error, unauthorized}, State};
dispatch({delete_translation, all}, State) ->
    permitted_change({translation, delete}, State, fun() ->
        case bibleit_api:delete_translation(all) of {ok, Count} -> {ok, [{deleted, Count}]}; {error, Error} -> {error, Error} end
    end);
dispatch({delete_translation, Slug}, State) ->
    permitted_change({translation, delete}, State, fun() ->
        case bibleit_api:delete_translation(Slug) of {ok, Deleted} -> {ok, [{deleted, Deleted}]}; {error, Error} -> {error, Error} end
    end);
dispatch(_Request, State) -> {reply, {error, bad_request}, State}.

subscribe_to_live(Id, State) -> with_live(Id, fun(Pid) -> subscribe_live(Pid, Id, State) end, State).

parse([Command | Arguments]) ->
    case string:uppercase(Command) of
        "SERVER" -> parse_server(Arguments);
        "HELP" -> help(Arguments);
        "TRANSLATION" -> parse_translation(Arguments);
        "READ" -> read(Arguments);
        "SEARCH" -> search(Arguments);
        "PING" -> exact(Arguments, ping);
        "WHOAMI" -> exact(Arguments, auth_info);
        "QUIT" -> exact(Arguments, quit);
        "EXIT" -> exact(Arguments, quit);
        "AUTH" -> parse_auth(Arguments);
        "ACCOUNT" -> parse_account(Arguments);
        "LIVE" -> parse_live(Arguments);
        _ -> {error, bad_command}
    end;
parse([]) -> {error, bad_command}.

parse_server([Subcommand | Arguments]) ->
    case string:uppercase(Subcommand) of
        "INFO" -> exact(Arguments, server_info);
        _ -> {error, bad_command}
    end;
parse_server([]) -> {error, bad_command}.

exact([], Result) -> {ok, Result};
exact(_, _Result) -> {error, bad_command}.
help([]) -> {ok, {help, <<"root">>}};
help(Parts) -> {ok, {help, join(Parts)}}.
parse_auth([Subcommand | Arguments]) ->
    case string:uppercase(Subcommand) of
        "LOGIN" -> parse_auth_login(Arguments);
        "LOGOUT" -> exact(Arguments, auth_logout);
        "ACTOR" -> parse_auth_actor(Arguments);
        "KEY" -> parse_auth_key(Arguments);
        "TOKEN" -> parse_auth_token(Arguments);
        "ROLE" -> parse_auth_role(Arguments);
        "INFO" -> exact(Arguments, auth_info);
        "LIST" -> parse_auth_list(Arguments);
        _ -> {error, bad_command}
    end;
parse_auth(_) -> {error, bad_command}.
parse_auth_login(["PROVE", Challenge, Signature]) -> {ok, {auth_login_prove, list_to_binary(Challenge), list_to_binary(Signature)}};
parse_auth_login([Action, Challenge, Signature]) ->
    case string:uppercase(Action) of "PROVE" -> {ok, {auth_login_prove, list_to_binary(Challenge), list_to_binary(Signature)}}; _ -> {error, bad_command} end;
parse_auth_login([Fingerprint]) -> {ok, {auth_login_key, list_to_binary(Fingerprint)}};
parse_auth_login(_) -> {error, bad_command}.
parse_auth_key([Action, Actor, Fingerprint]) ->
    case string:uppercase(Action) of
        "REVOKE" -> {ok, {revoke_key, list_to_binary(Actor), list_to_binary(Fingerprint)}};
        "ADD" -> {ok, {create_key, list_to_binary(Actor), list_to_binary(Fingerprint)}};
        _ -> {error, bad_command}
    end;
parse_auth_key([Action, Actor | PublicKey]) ->
    case string:uppercase(Action) of
        "ADD" when PublicKey =/= [] -> {ok, {create_key, list_to_binary(Actor), join(PublicKey)}};
        "LIST" when PublicKey =:= [] -> {ok, {list_keys, list_to_binary(Actor)}};
        "REVOKE" -> {error, missing_key_fingerprint};
        _ -> {error, bad_command}
    end;
parse_auth_key(_) -> {error, bad_command}.
parse_auth_actor([Action, Actor]) ->
    case string:uppercase(Action) of
        "CREATE" -> {ok, {create_actor, list_to_binary(Actor)}};
        "DELETE" -> {ok, {delete_actor, list_to_binary(Actor)}};
        "INFO" -> {ok, {actor_info, list_to_binary(Actor)}};
        "LIST" -> parse_actor_list(Actor, undefined);
        _ -> {error, bad_command}
    end;
parse_auth_actor([Action]) ->
    case string:uppercase(Action) of "LIST" -> {ok, {list_actors, 10, undefined}}; _ -> {error, bad_command} end;
parse_auth_actor([Action, List, Actor]) ->
    case {string:uppercase(Action), string:uppercase(List)} of
        {"QUOTA", "LIST"} -> {ok, {auth_quotas, list_to_binary(Actor)}};
        {"LIST", _} -> parse_actor_list(List, Actor);
        _ -> {error, bad_command}
    end;
parse_auth_actor([Action, Actor | Binding]) ->
    case string:uppercase(Action) of
        "GRANT" -> parse_global_grant([Actor | Binding], global_grant);
        "REVOKE" -> parse_global_grant([Actor | Binding], global_revoke);
        _ -> {error, bad_command}
    end;
parse_auth_actor(_) -> {error, bad_command}.
parse_actor_list(LimitText, Cursor) ->
    case integer(LimitText) of {ok, Limit} when Limit > 0, Limit =< 100 -> {ok, {list_actors, Limit, case Cursor of undefined -> undefined; _ -> list_to_binary(Cursor) end}}; _ -> {error, invalid_limit} end.
parse_auth_token([Action, Actor]) ->
    case string:uppercase(Action) of
        "CREATE" -> {ok, {create_token, list_to_binary(Actor)}};
        "REVOKE" -> {error, missing_token_id};
        "LIST" -> {ok, {list_tokens, list_to_binary(Actor)}};
        _ -> {error, bad_command}
    end;
parse_auth_token([Action, Actor, Id]) ->
    case string:uppercase(Action) of
        "REVOKE" -> {ok, {revoke_tokens, list_to_binary(Actor), case string:uppercase(Id) of "ALL" -> all; _ -> list_to_binary(Id) end}};
        "CREATE" -> {ok, {create_token, list_to_binary(Actor), list_to_binary(Id)}};
        _ -> {error, bad_command}
    end;
parse_auth_token([Action, Actor | Label]) ->
    case string:uppercase(Action) of
        "CREATE" -> {ok, {create_token, list_to_binary(Actor), join(Label)}};
        _ -> {error, bad_command}
    end;
parse_auth_token(_) -> {error, bad_command}.
parse_account([Action | Arguments]) ->
    case string:uppercase(Action) of
        "INFO" -> exact(Arguments, account_info);
        "QUOTA" -> case Arguments of [Command] when is_list(Command) -> case string:uppercase(Command) of "LIST" -> {ok, account_quotas}; _ -> {error, bad_command} end; _ -> {error, bad_command} end;
        "TOKEN" -> parse_account_token(Arguments);
        "KEY" -> parse_account_key(Arguments);
        _ -> {error, bad_command}
    end;
parse_account(_) -> {error, bad_command}.
parse_account_token([Command | Label]) ->
    case string:uppercase(Command) of
        "CREATE" -> {ok, {account_create_token, case Label of [] -> undefined; _ -> join(Label) end}};
        "LIST" when Label =:= [] -> {ok, account_list_tokens};
        "REVOKE" -> case Label of [Id] -> {ok, {account_revoke_tokens, case string:uppercase(Id) of "ALL" -> all; _ -> list_to_binary(Id) end}}; _ -> {error, bad_command} end;
        _ -> {error, bad_command}
    end;
parse_account_token(_) -> {error, bad_command}.
parse_account_key([Command | Arguments]) ->
    case string:uppercase(Command) of
        "ADD" when Arguments =/= [] -> {ok, {account_create_key, join(Arguments)}};
        "LIST" when Arguments =:= [] -> {ok, account_list_keys};
        "REVOKE" -> case Arguments of [Fingerprint] -> {ok, {account_revoke_key, list_to_binary(Fingerprint)}}; _ -> {error, bad_command} end;
        _ -> {error, bad_command}
    end;
parse_account_key(_) -> {error, bad_command}.
parse_auth_role([Action, Name, "permission", Resource | Verbs]) -> parse_auth_role_action(Action, Name, Resource, Verbs);
parse_auth_role([Action, Name, PermissionKeyword, Resource | Verbs]) ->
    case string:uppercase(PermissionKeyword) of "PERMISSION" -> parse_auth_role_action(Action, Name, Resource, Verbs); _ -> {error, bad_command} end;
parse_auth_role([Action, Name]) ->
    case string:uppercase(Action) of "DELETE" -> {ok, {delete_role, list_to_binary(Name)}}; _ -> {error, bad_command} end;
parse_auth_role(_) -> {error, bad_command}.
parse_auth_role_action(Action, Name, Resource, Verbs) ->
    case {string:uppercase(Action), permission_bindings([Resource | Verbs])} of
        {"CREATE", {ok, Permissions}} -> {ok, {create_role, list_to_binary(Name), Permissions}};
        {"UPDATE", {ok, Permissions}} -> {ok, {update_role, list_to_binary(Name), Permissions}};
        {_Other, {error, Error}} -> {error, Error};
        _ -> {error, bad_command}
    end.
parse_auth_list([Kind]) ->
    case string:uppercase(Kind) of
        "PERMISSION" -> {ok, auth_permissions};
        "RESOURCE" -> {ok, auth_resources};
        "ROLE" -> {ok, auth_roles};
        _ -> {error, bad_command}
    end;
parse_auth_list(_) -> {error, bad_command}.
parse_translation([Subcommand]) ->
    case string:uppercase(Subcommand) of
        "LIST" -> {ok, translation_list};
        _ -> {error, bad_command}
    end;
parse_translation([Subcommand, Scope]) ->
    case string:uppercase(Subcommand) of
        "LIST" -> case string:uppercase(Scope) of "ALL" -> {ok, available_translation_list}; _ -> {error, bad_command} end;
        "FETCH" -> {ok, {fetch_translation, list_to_binary(Scope)}};
        "INFO" -> {ok, {translation_info, list_to_binary(Scope)}};
        "CATALOG" -> {ok, {translation_catalog, list_to_binary(Scope)}};
        "DELETE" -> {ok, {delete_translation, delete_target(Scope)}};
        _ -> {error, bad_command}
    end;
parse_translation(_) -> {error, bad_command}.
delete_target(Slug) -> case string:uppercase(Slug) of "ALL" -> all; _ -> list_to_binary(Slug) end.
read([Slug, Book]) ->
    case reference_integer(Book) of
        {ok, B} -> {ok, {read, list_to_binary(Slug), B}};
        not_integer -> {ok, {read_named, list_to_binary(Slug), list_to_binary(Book), undefined, undefined}};
        invalid -> {error, invalid_reference}
    end;
read([Slug, BookOrName, Chapter]) ->
    case chapter_verse(Chapter) of
        {ok, C, V} -> read_with_reference(Slug, BookOrName, C, V);
        error ->
            case {reference_integer(BookOrName), reference_integer(Chapter)} of
                {{ok, B}, {ok, C}} -> {ok, {read, list_to_binary(Slug), B, C}};
                {not_integer, {ok, C}} -> {ok, {read_named, list_to_binary(Slug), list_to_binary(BookOrName), C, undefined}};
                _ -> {error, invalid_reference}
            end
    end;
read([Slug, BookOrName, Chapter, Verse]) ->
    case {reference_integer(BookOrName), reference_integer(Chapter), reference_integer(Verse)} of
        {{ok, B}, {ok, C}, {ok, V}} -> {ok, {read, list_to_binary(Slug), B, C, V}};
        {not_integer, {ok, C}, {ok, V}} -> {ok, {read_named, list_to_binary(Slug), list_to_binary(BookOrName), C, V}};
        _ -> {error, invalid_reference}
    end;
read(_) -> {error, bad_command}.
read_with_reference(Slug, BookOrName, Chapter, Verse) ->
    case reference_integer(BookOrName) of
        {ok, Book} -> {ok, {read, list_to_binary(Slug), Book, Chapter, Verse}};
        not_integer -> {ok, {read_named, list_to_binary(Slug), list_to_binary(BookOrName), Chapter, Verse}};
        invalid -> {error, invalid_reference}
    end.
search([_Slug]) -> {error, empty_query};
search([Slug | Query]) -> {ok, {search, list_to_binary(Slug), join(Query)}};
search(_) -> {error, empty_query}.
integer(Value) -> try {ok, list_to_integer(Value)} catch error:badarg -> error end.
reference_integer(Value) ->
    case integer(Value) of
        {ok, Number} when Number > 0, Number =< 255 -> {ok, Number};
        {ok, _} -> invalid;
        error -> not_integer
    end.
parse_live([First | Arguments]) ->
    case string:uppercase(First) of
        "CREATE" -> create_live(Arguments);
        "LIST" -> case Arguments of [] -> {ok, list_lives}; _ -> {error, bad_command} end;
        "DELETE" -> live_remove_all(Arguments);
        _ -> parse_live_instance(First, Arguments)
    end;
parse_live([]) -> {error, bad_command}.
parse_live_instance(Id, [Subcommand | Arguments]) ->
    case string:uppercase(Subcommand) of
        "INFO" -> live_info(Id, Arguments);
        "STATS" -> live_stats(Id, Arguments);
        "SET" -> live_set(Id, Arguments);
        "SECRET" -> live_secret(Id, Arguments);
        "START" -> live_start(Id, Arguments);
        "STOP" -> live_stop(Id, Arguments);
        "CLEAR" -> live_clear(Id, Arguments);
        "RESUME" -> live_resume(Id, Arguments);
        "PAUSE" -> live_pause(Id, Arguments);
        "DELETE" -> live_remove(Id, Arguments);
        "STACK" -> live_stack(Id, Arguments);
        "SUBSCRIBE" -> live_subscribe(Id, Arguments);
        _ -> {error, bad_command}
    end;
parse_live_instance(_, _) -> {error, bad_command}.
parse_global_grant([Actor, Kind | Values], Request) when Values =/= [] ->
    case string:uppercase(Kind) of
        "PERMISSION" -> case permission_bindings(Values) of {ok, Parsed} -> {ok, {Request, list_to_binary(Actor), permission, Parsed}}; Error -> Error end;
        "ROLE" -> case Values of [RoleName] -> case bibleit_authorization:role_name(RoleName) of {ok, Role} -> {ok, {Request, list_to_binary(Actor), role, [Role]}}; Error -> Error end; _ -> {error, bad_command} end;
        "QUOTA" -> parse_quota_binding(Actor, Values, Request);
        _ -> {error, bad_command}
    end;
parse_global_grant(_, _) -> {error, bad_command}.
parse_quota_binding(Actor, [PermissionName, LimitText], global_grant) ->
    case {quota_permission(PermissionName), quota_limit(LimitText)} of
        {{ok, Permission}, {ok, Limit}} -> {ok, {global_grant, list_to_binary(Actor), quota, {Permission, Limit}}};
        {{error, Error}, _} -> {error, Error};
        {_, {error, Error}} -> {error, Error}
    end;
parse_quota_binding(Actor, [PermissionName], global_revoke) ->
    case quota_permission(PermissionName) of
        {ok, Permission} -> {ok, {global_revoke, list_to_binary(Actor), quota, Permission}};
        Error -> Error
    end;
parse_quota_binding(_, _, _) -> {error, bad_command}.
permission_bindings(Values) ->
    case lists:any(fun(Value) -> lists:member($., Value) end, Values) of
        false -> global_permissions(Values);
        true ->
            Parsed = [parse_permission_name(Value) || Value <- Values],
            case [Permission || {ok, Permission} <- Parsed] of
                Permissions when length(Permissions) =:= length(Parsed) -> {ok, lists:usort(Permissions)};
                _ -> {error, permission_not_found}
            end
    end.
quota_permission(Name) ->
    case parse_permission_name(Name) of
        {ok, {Resource, create} = Permission} when Resource =:= actor; Resource =:= token; Resource =:= key; Resource =:= live -> {ok, Permission};
        {ok, _} -> {error, quota_not_supported};
        Error -> Error
    end.
parse_permission_name(Name) ->
    case string:split(Name, ".", all) of
        [Resource, Verb] -> case global_permissions([Resource, Verb]) of {ok, [Permission]} -> {ok, Permission}; Error -> Error end;
        _ -> {error, permission_not_found}
    end.
quota_limit(Value) ->
    case integer(Value) of
        {ok, Limit} when Limit > 0 -> {ok, Limit};
        _ -> {error, invalid_quota}
    end.
global_permissions([Resource | Verbs]) when Verbs =/= [] ->
    ResourceAtom = permission_resource(Resource),
    Parsed = [permission_verb(ResourceAtom, Verb) || Verb <- Verbs],
    case {ResourceAtom, lists:member(error, Parsed)} of
        {error, _} -> {error, permission_not_found};
        {_, true} -> {error, permission_not_found};
        _ -> {ok, lists:usort(Parsed)}
    end;
global_permissions(_) -> {error, bad_command}.
permission_resource(Name) ->
    case string:uppercase(Name) of "LIVE" -> live; "TRANSLATION" -> translation; "AUTHORIZATION" -> authorization; "ACTOR" -> actor; "ROLE" -> role; "TOKEN" -> token; "KEY" -> key; "QUOTA" -> quota; _ -> error end.
permission_verb(error, _Name) -> error;
permission_verb(Resource, "*") ->
    case lists:any(fun({ResourceName, _Verb}) -> ResourceName =:= Resource end, bibleit_authorization:permissions()) of true -> {Resource, all}; false -> error end;
permission_verb(Resource, Name) ->
    try Verb = list_to_existing_atom(string:lowercase(Name)),
        case lists:member({Resource, Verb}, bibleit_authorization:permissions()) of true -> {Resource, Verb}; false -> error end
    catch error:badarg -> error end.
effective_permissions(State) ->
    case is_authenticated(State) of
        true -> bibleit_authorization:expand_permissions(bibleit_authorization:default_permissions() ++ maps:get(permissions, State, []));
        false -> []
    end.
has_permission(Permission, State) -> lists:member(Permission, effective_permissions(State)).
can_delegate_permissions(Permissions, State) -> lists:all(fun(Permission) -> has_permission(Permission, State) end, bibleit_authorization:expand_permissions(Permissions)).
role_binding_allowed(default, _State) -> {error, role_not_assignable};
role_binding_allowed(Role, State) -> case can_delegate_role(Role, State) of true -> ok; false -> {error, forbidden} end.
can_delegate_role(server_admin, State) -> has_permission({role, bind}, State);
can_delegate_role(Role, State) ->
    case bibleit_authorization:role(Role) of
        {ok, Permissions} -> can_delegate_permissions(Permissions, State);
        {error, _} -> false
    end.
guarded(Permission, State, Fun) ->
    case has_permission(Permission, State) of true -> Fun(); false -> {reply, {error, forbidden}, State} end.
operator_guarded(Permission, State, Fun) ->
    case is_operator(State) of true -> guarded(Permission, State, Fun); false -> {reply, {error, forbidden}, State} end.
actor_change(State, Target, Change) ->
    case has_permission({actor, update}, State) of
        true -> managed_change(State, Target, Change);
        false -> {reply, {error, forbidden}, State}
    end.
quota_change(State, Target, Change) ->
    case has_permission({quota, update}, State) of
        true -> managed_change(State, Target, Change);
        false -> {reply, {error, forbidden}, State}
    end.
managed_change(State, Target, Change) ->
    case can_manage_target(Target, State) of
        true -> case Change() of ok -> {reply, {ok, []}, State}; {error, Error} -> {reply, {error, Error}, State} end;
        false -> {reply, {error, forbidden}, State}
    end.
can_manage_target(Target, State) -> is_server_admin(State) orelse bibleit_authorization:can_manage_actor(maps:get(actor, State), Target).
is_server_admin(State) -> has_permission({role, bind}, State).
maybe_add_created_by(Live, Owner, State) ->
    case can_manage_target(Owner, State) of true -> Live#{created_by => Owner}; false -> Live end.
permitted_change(Permission, State, Change) ->
    case has_permission(Permission, State) of
        true -> case Change() of {ok, Fields} -> {reply, {ok, Fields}, State}; {error, Error} -> {reply, {error, Error}, State} end;
        false -> {reply, {error, forbidden}, State}
    end.
operator_permitted_change(Permission, State, Change) ->
    case is_operator(State) of true -> permitted_change(Permission, State, Change); false -> {reply, {error, forbidden}, State} end.
is_operator(State) -> has_permission({actor, update}, State) orelse is_server_admin(State).
live_info(Id, []) -> {ok, {get_live, list_to_binary(Id)}};
live_info(_, _) -> {error, bad_command}.
live_stats(Id, []) -> {ok, {live_stats, list_to_binary(Id)}};
live_stats(_, _) -> {error, bad_command}.
live_set(Id, [Option | Values]) ->
    case live_option(Option, Values) of
        {ok, Value} -> {ok, {set_live, list_to_binary(Id), option_atom(Option), Value}};
        Error -> Error
    end;
live_set(_, _) -> {error, bad_command}.
live_secret(Id, [Command | Arguments]) ->
    case string:uppercase(Command) of
        "SET" -> case Arguments of [Secret] -> {ok, {set_live_secret, list_to_binary(Id), list_to_binary(Secret)}}; _ -> {error, bad_command} end;
        "ROTATE" -> case Arguments of [] -> {ok, {rotate_live_secret, list_to_binary(Id)}}; _ -> {error, bad_command} end;
        "DELETE" -> case Arguments of [] -> {ok, {delete_live_secret, list_to_binary(Id)}}; _ -> {error, bad_command} end;
        _ -> case Arguments of [] -> {ok, {authenticate_live_secret, list_to_binary(Id), list_to_binary(Command)}}; _ -> {error, bad_command} end
    end;
live_secret(_, _) -> {error, bad_command}.
live_start(Id, []) -> {ok, {start_live, list_to_binary(Id)}};
live_start(_, _) -> {error, bad_command}.
live_stop(Id, []) -> {ok, {stop_live, list_to_binary(Id)}};
live_stop(_, _) -> {error, bad_command}.
live_clear(Id, []) -> {ok, {clear_live, list_to_binary(Id)}};
live_clear(_, _) -> {error, bad_command}.
live_resume(Id, []) -> {ok, {resume_live, list_to_binary(Id)}};
live_resume(_, _) -> {error, bad_command}.
live_pause(Id, []) -> {ok, {pause_live, list_to_binary(Id)}};
live_pause(_, _) -> {error, bad_command}.
live_remove(Id, []) -> {ok, {remove_live, list_to_binary(Id)}};
live_remove(_, _) -> {error, bad_command}.
live_remove_all([Target]) -> case string:uppercase(Target) of "ALL" -> {ok, remove_all_lives}; _ -> {error, bad_command} end;
live_remove_all(_) -> {error, bad_command}.
live_push(Id, [Book, ChapterVerse]) ->
    build_live_push(Id, undefined, Book, [ChapterVerse]);
live_push(Id, [Book | Reference]) when length(Reference) =< 1 ->
    build_live_push(Id, undefined, Book, Reference);
live_push(Id, [First, Second, Third]) ->
    case {reference_integer(Second), bibleit_translation_catalog:canonical_slug(list_to_binary(First))} of
        {{ok, _}, {error, _}} -> build_live_push(Id, undefined, First, [Second, Third]);
        _ -> build_live_push(Id, list_to_binary(First), Second, [Third])
    end;
live_push(Id, [Translation, Book | Reference]) ->
    build_live_push(Id, list_to_binary(Translation), Book, Reference);
live_push(_, _) -> {error, bad_command}.
live_stack(Id, [Command | Arguments]) ->
    case string:uppercase(Command) of
        "PUSH" -> live_push(Id, Arguments);
        "POP" -> live_pop(Id, Arguments);
        "INFO" -> case Arguments of [] -> {ok, {live_stack_info, list_to_binary(Id)}}; _ -> {error, bad_command} end;
        "CLEAR" -> case Arguments of [] -> {ok, {clear_live, list_to_binary(Id)}}; _ -> {error, bad_command} end;
        _ -> {error, bad_command}
    end;
live_stack(_, _) -> {error, bad_command}.
live_pop(Id, []) -> {ok, {pop_live, list_to_binary(Id), 1}};
live_pop(Id, [CountText]) ->
    case integer(CountText) of
        {ok, Count} when Count =/= 0 -> {ok, {pop_live, list_to_binary(Id), Count}};
        _ -> {error, bad_command}
    end;
live_pop(_, _) -> {error, bad_command}.
build_live_push(Id, Translation, Book, Reference) ->
    case parse_reference(Book, Reference) of
        {ok, Parsed} ->
            Request = case Translation of undefined -> Parsed; _ -> Parsed#{translation => Translation} end,
            {ok, {push_live, list_to_binary(Id), Request}};
        Error -> Error
    end.
parse_reference(Book, []) -> reference(Book, undefined, undefined);
parse_reference(Book, [Chapter]) ->
    case chapter_verse(Chapter) of
        {ok, ParsedChapter, Verse} -> reference(Book, ParsedChapter, Verse);
        error -> reference(Book, Chapter, undefined)
    end;
parse_reference(Book, [Chapter, Verse]) -> reference(Book, Chapter, Verse);
parse_reference(_, _) -> {error, bad_command}.
reference(Book, Chapter, Verse) ->
    case {reference_book(Book), reference_part(Chapter), reference_part(Verse)} of
        {{ok, ParsedBook}, {ok, ParsedChapter}, {ok, ParsedVerse}} ->
            {ok, #{book => ParsedBook, chapter => ParsedChapter, verse => ParsedVerse}};
        _ -> {error, invalid_reference}
    end.
reference_book(Book) ->
    case reference_integer(Book) of
        {ok, Number} -> {ok, Number};
        not_integer -> {ok, list_to_binary(Book)};
        invalid -> error
    end.
reference_part(undefined) -> {ok, undefined};
reference_part(Value) when is_integer(Value), Value > 0, Value =< 255 -> {ok, Value};
reference_part(Value) -> case reference_integer(Value) of {ok, Number} -> {ok, Number}; _ -> error end.
chapter_verse(Value) ->
    case string:split(Value, ":", all) of
        [Chapter, Verse] ->
            case {reference_integer(Chapter), reference_integer(Verse)} of
                {{ok, ParsedChapter}, {ok, ParsedVerse}} -> {ok, ParsedChapter, ParsedVerse};
                _ -> error
            end;
        _ -> error
    end.
live_subscribe(Id, []) -> {ok, {subscribe_live, list_to_binary(Id)}};
live_subscribe(_, _) -> {error, bad_command}.
create_live(Name) when Name =/= [] -> {ok, {create_live, join(Name)}};
create_live([]) -> {ok, {create_live, <<>>}}.
live_option(Option, Values) ->
    case string:uppercase(Option) of
        "NAME" -> nonempty_join(Values);
        "REFERENCE" -> nonempty_join(Values);
        "TRANSLATIONS" when Values =/= [] -> {ok, [list_to_binary(Value) || Value <- Values]};
        _ -> {error, bad_command}
    end.
nonempty_join([]) -> {error, bad_command};
nonempty_join(Values) -> {ok, join(Values)}.
option_atom(Option) ->
    case string:uppercase(Option) of
        "NAME" -> name;
        "REFERENCE" -> reference;
        "TRANSLATIONS" -> translations
    end.
join(Parts) -> list_to_binary(string:join(Parts, " ")).

with_live(Id, Fun, State) ->
    case bibleit_live_registry:lookup(Id) of
        {ok, Pid} -> Fun(Pid);
        error -> {reply, {error, not_found}, State}
    end.
subscribe_live(Pid, Id, State) ->
    case bibleit_live_session:subscribe(Pid, maps:get(actor, State), self()) of
        {ok, Live} ->
            Subscriptions = maps:get(subscriptions, State, #{}),
            {reply, {ok, maps:to_list(Live)}, State#{subscriptions => Subscriptions#{Id => Pid}}};
        {error, Error} -> {reply, {error, Error}, State}
    end.
subscribe_with_secret(Id, Secret, State) ->
    with_live(Id, fun(Pid) ->
        case bibleit_live_session:subscribe_with_secret(Pid, Secret, self()) of
            {ok, Live} ->
                Subscriptions = maps:get(subscriptions, State, #{}),
                {reply, {ok, maps:to_list(Live)}, State#{subscriptions => Subscriptions#{Id => Pid}}};
            {error, Error} -> {reply, {error, Error}, State}
        end
    end, State).

verify_key_signature(Challenge, Nonce, Signature, PublicKey) when is_binary(Signature), is_binary(PublicKey) ->
    try
        verify_ssh_signature(base64:decode(Signature), key_challenge_message(Challenge, Nonce), PublicKey)
    catch
        _:_ -> false
    end.
key_challenge_message(Challenge, Nonce) -> <<"bibleit-auth-key-v1", 0, Challenge/binary, 0, Nonce/binary>>.
verify_ssh_signature(Signature, Message, PublicKey) ->
    case parse_sshsig(Signature) of
        {ok, PublicBlob, Namespace, Reserved, HashAlgorithm, SignatureAlgorithm, RawSignature} ->
            ExpectedPublicBlob = iolist_to_binary([ssh_string(<<"ssh-ed25519">>), ssh_string(PublicKey)]),
            case {PublicBlob, Namespace, Reserved, HashAlgorithm, SignatureAlgorithm} of
                {ExpectedPublicBlob, <<"bibleit@bibleit.app">>, <<>>, Algorithm, <<"ssh-ed25519">>}
                  when Algorithm =:= <<"sha256">>; Algorithm =:= <<"sha512">> ->
                    Digest = crypto:hash(hash_algorithm(Algorithm), Message),
                    Signed = iolist_to_binary([<<"SSHSIG", 1:32/big>>, ssh_string(PublicBlob), ssh_string(Namespace), ssh_string(Reserved), ssh_string(HashAlgorithm), ssh_string(Digest)]),
                    crypto:verify(eddsa, none, Signed, RawSignature, [PublicKey, ed25519]);
                _ -> false
            end;
        error -> false
    end.
parse_sshsig(<<"SSHSIG", 1:32/big, Rest/binary>>) ->
    case with_ssh_strings(Rest, 5, fun(Values) -> Values end) of
        {ok, [PublicBlob, Namespace, Reserved, HashAlgorithm, SignatureBlob]} ->
            case with_ssh_strings(SignatureBlob, 2, fun(Values) -> Values end) of
                {ok, [Algorithm, Signature]} -> {ok, PublicBlob, Namespace, Reserved, HashAlgorithm, Algorithm, Signature};
                error -> error
            end;
        error -> error
    end;
parse_sshsig(_) -> error.
with_ssh_strings(Bin, Count, Fun) -> with_ssh_strings(Bin, Count, [], Fun).
with_ssh_strings(<<>>, 0, Acc, Fun) -> {ok, Fun(lists:reverse(Acc))};
with_ssh_strings(<<Length:32/big, Value:Length/binary, Rest/binary>>, Count, Acc, Fun) when Count > 0 -> with_ssh_strings(Rest, Count - 1, [Value | Acc], Fun);
with_ssh_strings(_, _, _, _) -> error.
ssh_string(Value) when is_binary(Value) -> [<<(byte_size(Value)):32/big>>, Value].
hash_algorithm(<<"sha256">>) -> sha256;
hash_algorithm(<<"sha512">>) -> sha512.

help_commands(Topic, State) ->
    case string:uppercase(binary_to_list(Topic)) of
        "ROOT" -> {ok, root_help(State)};
        "SERVER" -> {ok, server_help()};
        "AUTH" -> {ok, auth_help(State)};
        "ACCOUNT" -> {ok, account_help(State)};
        "TRANSLATION" -> {ok, translation_help(State)};
        "LIVE" -> {ok, live_help(State)};
        _ -> error
    end.

root_help(State) ->
    Topics = <<"help [server|account|auth|translation|live]">>,
    Public = [help_command(Topics, none, <<"List commands visible to this connection.">>),
              help_command(<<"server info">>, none, <<"Show protocol version and capabilities.">>),
              help_command(<<"ping">>, none, <<"Check whether this connection is responsive.">>),
              help_command(<<"whoami">>, none, <<"Show this connection's authentication state and actor.">>),
              help_command(<<"quit|exit">>, none, <<"Close this TCP connection cleanly.">>),
              help_command(<<"auth login <key-fingerprint>">>, none, <<"Start an SSH-style public-key login challenge.">>),
              help_command(<<"auth login prove <challenge> <signature>">>, none, <<"Complete a public-key login challenge.">>),
              help_command(<<"auth info">>, none, <<"Show this connection's authentication state.">>),
              help_command(<<"live <id> secret <secret>">>, none, <<"Authorize this connection for a secret-protected Live.">>),
              help_command(<<"read <translation> <book> [chapter] [verse]">>, none, <<"Read a verse, chapter, or book.">>)],
    WithTranslations = add_when(has_translation_permission(State), help_command(<<"translation ...">>, permission, <<"Run translation discovery commands; use help translation.">>), Public),
    WithSearch = add_when(has_permission({translation, search}, State),
                          help_command(<<"search <translation> <query>">>, permission, <<"Search verse text.">>), WithTranslations),
    WithLiveCreate = add_when(has_permission({live, create}, State),
                               help_command(<<"live create [name]">>, permission, <<"Create an open Live.">>), WithSearch),
    WithLive = add_when(has_live_permission(State), help_command(<<"live ...">>, authenticated, <<"Access lives permitted to the actor; use help live.">>), WithLiveCreate),
    WithAccount = add_when(is_authenticated(State), help_command(<<"account ...">>, authenticated, <<"Manage your own account, tokens, and SSH keys; use help account.">>), WithLive),
    add_when(is_authenticated(State), help_command(<<"auth ...">>, authenticated, <<"Operator authorization controls; use help auth.">>), WithAccount).

server_help() ->
    [help_command(<<"server info">>, none, <<"Show protocol version and capabilities.">>),
     help_command(<<"ping">>, none, <<"Check whether this connection is responsive.">>)].

auth_help(State) ->
    Public = [help_command(<<"auth login <key-fingerprint>">>, none, <<"Start an SSH-style public-key login challenge.">>),
              help_command(<<"auth login prove <challenge> <signature>">>, none, <<"Complete a public-key login challenge.">>),
              help_command(<<"auth info">>, none, <<"Show this connection's authentication state.">>)],
    Authenticated = add_when(is_authenticated(State),
                             help_command(<<"auth logout">>, authenticated, <<"Clear this connection's authentication and live subscriptions.">>), Public),
    WithAuthorizationList = add_when(has_permission({authorization, list}, State),
                                     [help_command(<<"auth list resource">>, permission, <<"List recognized RBAC resources.">>),
                                      help_command(<<"auth list permission">>, permission, <<"List recognized resource-verb permissions.">>)], Authenticated),
    WithRoleList = add_when(has_permission({role, list}, State),
                            help_command(<<"auth list role">>, permission, <<"List available roles and their permissions.">>), WithAuthorizationList),
    WithActorCreate = add_when(has_permission({actor, create}, State),
                               help_command(<<"auth actor create <actor>">>, permission, <<"Create an actor with no permissions.">>), WithRoleList),
    WithActorInfo = add_when(has_permission({actor, get}, State),
                             help_command(<<"auth actor info <actor>">>, permission, <<"Show a managed actor's authentication details.">>), WithActorCreate),
    WithActorList = add_when(has_permission({actor, list}, State),
                             help_command(<<"auth actor list">>, permission, <<"List direct child actors.">>), WithActorInfo),
    WithActorDelete = add_when(has_permission({actor, delete}, State),
                               help_command(<<"auth actor delete <actor>">>, permission, <<"Delete an actor and revoke its tokens.">>), WithActorList),
    WithBindings = add_when(has_permission({actor, update}, State),
                            [help_command(<<"auth actor grant <actor> permission <resource.verb...>">>, permission, <<"Grant server-wide permissions.">>),
                             help_command(<<"auth actor grant <actor> role <role>">>, permission, <<"Grant a server-wide role.">>),
                             help_command(<<"auth actor revoke <actor> permission <resource.verb...>">>, permission, <<"Revoke server-wide permissions.">>),
                             help_command(<<"auth actor revoke <actor> role <role>">>, permission, <<"Revoke a server-wide role.">>)], WithActorDelete),
    WithQuotas = add_when(has_permission({quota, get}, State),
                          help_command(<<"auth actor quota list <actor>">>, permission, <<"List an actor's assigned quotas.">>), WithBindings),
    WithQuotaUpdates = add_when(has_permission({quota, update}, State),
                                [help_command(<<"auth actor grant <actor> quota <resource.verb> <limit>">>, permission, <<"Set an actor's creation quota.">>),
                                 help_command(<<"auth actor revoke <actor> quota <resource.verb>">>, permission, <<"Remove an actor's quota.">>)], WithQuotas),
    CanManageActors = has_permission({actor, update}, State) orelse is_server_admin(State),
    WithTokens = add_when(CanManageActors andalso has_permission({token, create}, State),
                          help_command(<<"auth token create <actor> [label]">>, permission, <<"Issue a labeled token for an existing actor; shown once.">>), WithQuotaUpdates),
    WithTokenList = add_when(CanManageActors andalso has_permission({token, get}, State),
                             help_command(<<"auth token list <actor>">>, permission, <<"List an actor's token identifiers and metadata.">>), WithTokens),
    WithTokenRevocation = add_when(CanManageActors andalso has_permission({token, delete}, State),
                                   help_command(<<"auth token revoke <actor> <id|all>">>, permission, <<"Revoke one token by ID, or every token with all.">>), WithTokenList),
    WithKeys = add_when(CanManageActors andalso has_permission({key, create}, State),
                        help_command(<<"auth key add <actor> <ssh-ed25519-public-key>">>, permission, <<"Add an SSH-style public key to an actor.">>), WithTokenRevocation),
    WithKeyList = add_when(CanManageActors andalso has_permission({key, get}, State),
                           help_command(<<"auth key list <actor>">>, permission, <<"List an actor's public-key metadata.">>), WithKeys),
    WithKeyRevocation = add_when(CanManageActors andalso has_permission({key, delete}, State),
                                 help_command(<<"auth key revoke <actor> <fingerprint>">>, permission, <<"Revoke one public key by fingerprint.">>), WithKeyList),
    WithRoleCreate = add_when(has_permission({role, create}, State),
                              help_command(<<"auth role create <name> permission <resource.verb...>">>, permission, <<"Create a custom role.">>), WithKeyRevocation),
    WithRoleUpdate = add_when(has_permission({role, update}, State),
                              help_command(<<"auth role update <name> permission <resource.verb...>">>, permission, <<"Replace a custom role's permissions.">>), WithRoleCreate),
    add_when(has_permission({role, delete}, State),
             help_command(<<"auth role delete <name>">>, permission, <<"Delete a custom role.">>), WithRoleUpdate).

account_help(#{actor := undefined}) -> [];
account_help(State) ->
    Info = [help_command(<<"account info">>, authenticated, <<"Show your account identity and current resource counts.">>),
            help_command(<<"account quota list">>, authenticated, <<"Show your plan quotas and current usage.">>)],
    WithTokens = add_when(has_permission({token, create}, State),
                          help_command(<<"account token create [label]">>, permission, <<"Create a personal access token; shown once.">>), Info),
    WithTokenList = add_when(has_permission({token, get}, State),
                             help_command(<<"account token list">>, permission, <<"List your token metadata without secrets.">>), WithTokens),
    WithTokenDelete = add_when(has_permission({token, delete}, State),
                               help_command(<<"account token revoke <id|all>">>, permission, <<"Revoke one of your tokens, or all of them explicitly.">>), WithTokenList),
    WithKeys = add_when(has_permission({key, create}, State),
                        help_command(<<"account key add <ssh-ed25519-public-key>">>, permission, <<"Add an SSH public key to your account.">>), WithTokenDelete),
    WithKeyList = add_when(has_permission({key, get}, State),
                           help_command(<<"account key list">>, permission, <<"List your SSH key metadata.">>), WithKeys),
    sort_help(add_when(has_permission({key, delete}, State),
                       help_command(<<"account key revoke <fingerprint>">>, permission, <<"Revoke one of your SSH keys.">>), WithKeyList)).

translation_help(State) ->
    WithRead = add_when(has_permission({translation, read}, State),
                        help_command(<<"read <translation> <book> [chapter] [verse]">>, none, <<"Read a verse, chapter, or book.">>), []),
    WithSearch = add_when(has_permission({translation, search}, State),
                          help_command(<<"search <translation> <query>">>, permission, <<"Search verse text.">>), WithRead),
    WithGet = add_when(has_permission({translation, get}, State),
                       [help_command(<<"translation info <slug>">>, permission, <<"Show translation metadata.">>),
                        help_command(<<"translation catalog <slug>">>, permission, <<"Stream books, chapters, and verse counts for an installed translation.">>)], WithSearch),
    WithList = add_when(has_permission({translation, list}, State),
                        [help_command(<<"translation list">>, permission, <<"List installed translations.">>),
                         help_command(<<"translation list all">>, permission, <<"List installed and available translations.">>)], WithGet),
    WithFetch = add_when(has_permission({translation, create}, State),
                         help_command(<<"translation fetch <slug>">>, permission, <<"Download and install a translation.">>), WithList),
    add_when(has_permission({translation, delete}, State),
             help_command(<<"translation delete <slug|all>">>, permission, <<"Delete one or all installed translations.">>), WithFetch).

live_help(State) ->
    case is_authenticated(State) of
        false -> [help_command(<<"live <id> secret <secret>">>, none, <<"Authorize this connection to subscribe to a secret-protected Live.">>)];
        true ->
            Created = add_when(has_permission({live, create}, State), help_command(<<"live create [name]">>, permission, <<"Create an open Live.">>), []),
            Get = add_when(has_permission({live, get}, State), help_command(<<"live <id> info">>, permission, <<"Show a permitted live.">>), Created),
            Listed = add_when(has_permission({live, list}, State), help_command(<<"live list">>, permission, <<"List lives owned by the actor or its child actors.">>), Get),
            Subscribed = add_when(has_permission({live, subscribe}, State), help_command(<<"live <id> subscribe">>, permission, <<"Subscribe to an open Live.">>), Listed),
            WithStackInfo = add_when(has_permission({live, get}, State), help_command(<<"live <id> stack info">>, permission, <<"Show the current Live stack.">>), Subscribed),
            WithStats = add_when(has_permission({live, get}, State), help_command(<<"live <id> stats">>, permission, <<"Show owner-only Live connection and stack statistics.">>), WithStackInfo),
            Updated = add_when(has_permission({live, update}, State), [help_command(<<"live <id> stack push [translation] <book> [chapter] [verse]">>, permission, <<"Push verses onto the Live stack.">>), help_command(<<"live <id> stack pop [count]">>, permission, <<"Pop newest entries; use a negative count to remove oldest entries.">>), help_command(<<"live <id> stack clear">>, permission, <<"Clear the Live stack.">>), help_command(<<"live <id> pause|resume">>, permission, <<"Pause or resume the retained Live stack.">>), help_command(<<"live <id> set name|reference|translations <value...>">>, permission, <<"Change a live option.">>), help_command(<<"live <id> start|stop">>, permission, <<"Control a live.">>)], WithStats),
            WithSecrets = add_when(has_permission({live, update}, State), [help_command(<<"live <id> secret delete">>, permission, <<"Delete the Live secret and open audience access.">>), help_command(<<"live <id> secret set <secret>">>, permission, <<"Set a Live secret and restrict audience access.">>), help_command(<<"live <id> secret rotate">>, permission, <<"Generate a replacement Live secret.">>)], Updated),
            WithDelete = add_when(has_permission({live, delete}, State), [help_command(<<"live <id> delete">>, permission, <<"Delete a permitted live.">>), help_command(<<"live delete all">>, permission, <<"Delete every live managed by the actor.">>)], WithSecrets),
            sort_help(WithDelete)
    end.

help_command(Usage, Auth, Summary) -> #{usage => Usage, auth => Auth, summary => Summary}.
sort_help(Commands) -> lists:sort(fun(Left, Right) -> maps:get(usage, Left) < maps:get(usage, Right) end, Commands).
add_when(true, Entries, Existing) when is_list(Entries) -> Existing ++ Entries;
add_when(true, Entry, Existing) -> Existing ++ [Entry];
add_when(false, _Entries, Existing) -> Existing.
is_authenticated(State) -> maps:get(actor, State, undefined) =/= undefined.
account_summary_fields(Summary) ->
    Subscription = maps:get(subscription, Summary),
    Plan = maps:get(plan, Summary),
    maps:to_list(maps:without([subscription, plan], Summary)) ++
    [{plan, maps:get(id, Plan)},
     {plan_name, maps:get(name, Plan)},
     {subscription_status, maps:get(status, Subscription)},
     {subscription_started_at, maps:get(started_at, Subscription)},
     {subscription_trial_ends_at, maps:get(trial_ends_at, Subscription)},
     {subscription_billing_cycle, maps:get(billing_cycle, Subscription)}].
actor_display_name(Actor) ->
    try bibleit_authorization:actor_display_name(Actor) of
        {ok, Name} when is_binary(Name), Name =/= <<>> -> Name;
        _ -> Actor
    catch
        exit:_ -> Actor
    end.
has_translation_permission(State) -> lists:any(fun(Permission) -> has_permission(Permission, State) end, [{translation, get}, {translation, list}, {translation, create}, {translation, delete}]).
has_live_permission(State) -> lists:any(fun(Permission) -> has_permission(Permission, State) end, [{live, create}, {live, get}, {live, list}, {live, subscribe}, {live, update}, {live, delete}]).
unsubscribe_lives(Subscriptions) ->
    maps:foreach(fun(_Id, Pid) ->
        try bibleit_live_session:unsubscribe(Pid, self()) of _ -> ok catch exit:_ -> ok end
    end, Subscriptions).

fields(Values) -> [[" ", atom_to_list(Key), "=", format(Value)] || {Key, Value} <- Values].
format(Value) when is_atom(Value) -> atom_to_list(Value);
format(Value) when is_integer(Value) -> integer_to_list(Value);
format(Value) when is_binary(Value) -> ["\"", escape(binary_to_list(Value)), "\""];
format(Value) when is_list(Value) -> ["\"", escape(Value), "\""];
format(Value) -> io_lib:format("~p", [Value]).
escape([]) -> [];
escape([$\\ | Rest]) -> [$\\, $\\ | escape(Rest)];
escape([$\" | Rest]) -> [$\\, $\" | escape(Rest)];
escape([Character | Rest]) -> [Character | escape(Rest)].

join_binaries(Values) -> list_to_binary(string:join([binary_to_list(Value) || Value <- Values], ",")).
join_permissions(Values) ->
    list_to_binary(string:join([atom_to_list(Resource) ++ "." ++ atom_to_list(Verb) || {Resource, Verb} <- Values], ",")).
permission_name(Permission) -> join_permissions([Permission]).
trim_line_ending(<<>>) -> <<>>;
trim_line_ending(Value) ->
    Last = binary:at(Value, byte_size(Value) - 1),
    case Last =:= $\n orelse Last =:= $\r of
        true -> trim_line_ending(binary:part(Value, 0, byte_size(Value) - 1));
        false -> Value
    end.
event_payload(Payload) -> base64:encode(iolist_to_binary(json:encode(Payload))).
live_verse_line(Verse) ->
    ["VERSE", fields([{translation, maps:get(translation, Verse)},
                       {reference, maps:get(reference, Verse, <<>>)},
                       {text, maps:get(text, Verse)}]), "\n"].
live_stack_line(Position, Verse) ->
    ["STACK", fields([{position, Position}, {translation, maps:get(translation, Verse, <<>>)},
                       {reference, maps:get(reference, Verse, <<>>)}, {text, maps:get(text, Verse, <<>>)}]), "\n"].
book_lines(#{book := Book, name := Name, chapters := Chapters}) ->
    [["BOOK", fields([{book, Book}, {name, Name}, {chapters, length(Chapters)}]), "\n"],
     [["CHAPTER", fields([{book, Book}, {chapter, maps:get(chapter, Chapter)},
                            {verses, maps:get(verses, Chapter)}]), "\n"] || Chapter <- Chapters]].
actor_line(Actor) -> ["ACTOR", fields(actor_identity_fields(Actor)), "\n"].
actor_info_fields(Info) ->
    actor_identity_fields(Info) ++
    [{roles, join_roles(maps:get(roles, Info))},
     {permissions, join_permissions(maps:get(permissions, Info))},
     {tokens, maps:get(tokens, Info)},
     {quota_count, map_size(maps:get(quotas, Info))}].
actor_identity_fields(Info) ->
    Base = [{actor, maps:get(actor, Info)}],
    WithName = case maps:find(display_name, Info) of {ok, Name} -> Base ++ [{name, Name}]; error -> Base end,
    WithHandle = case maps:find(handle, Info) of {ok, Handle} -> WithName ++ [{handle, Handle}]; error -> WithName end,
    WithParent = case maps:get(created_by, Info, undefined) of undefined -> WithHandle; Parent -> WithHandle ++ [{created_by, Parent}] end,
    case maps:find(created_at, Info) of {ok, CreatedAt} -> WithParent ++ [{created_at, CreatedAt}]; error -> WithParent end.
join_roles(Roles) -> list_to_binary(string:join([role_display_name(Role) || Role <- Roles], ",")).
role_display_name(Role) when is_atom(Role) -> atom_to_list(Role);
role_display_name(Role) when is_binary(Role) -> binary_to_list(Role).
help_line(#{usage := Usage, auth := none, summary := Summary}) ->
    ["COMMAND", fields([{usage, Usage}, {summary, Summary}]), "\n"];
help_line(#{usage := Usage, auth := Auth, summary := Summary}) ->
    ["COMMAND", fields([{usage, Usage}, {auth, Auth}, {summary, Summary}]), "\n"].
words([], Current, Acc) -> lists:reverse(finish_word(Current, Acc));
words([$\" | Rest], Current, Acc) -> quoted(Rest, Current, Acc);
words([C | Rest], Current, Acc) when C =:= $\s; C =:= $\t -> words(Rest, [], finish_word(Current, Acc));
words([C | Rest], Current, Acc) -> words(Rest, [C | Current], Acc).
quoted([], _Current, _Acc) -> [];
quoted([$\" | Rest], Current, Acc) -> words(Rest, Current, Acc);
quoted([C | Rest], Current, Acc) -> quoted(Rest, [C | Current], Acc).
finish_word([], Acc) -> Acc;
finish_word(Current, Acc) -> [lists:reverse(Current) | Acc].
read_many({ok, Lines}, Slug, Book, Chapter, State) ->
    Fields = [{translation, Slug}, {book, Book}] ++ case Chapter of undefined -> []; _ -> [{chapter, Chapter}] end,
    {reply, {ok, {verses, Fields ++ [{verses, length(Lines)}], Lines}}, State};
read_many({error, Error}, _Slug, _Book, _Chapter, State) -> {reply, {error, Error}, State};
read_many(not_found, _Slug, _Book, _Chapter, State) -> {reply, {error, not_found}, State}.
search_limit() ->
    case application:get_env(bibleit_server, search_max_results, 100) of
        Limit when is_integer(Limit), Limit > 0, Limit =< 1000 -> Limit;
        _ -> 100
    end.
version() ->
    case application:get_key(bibleit_server, vsn) of
        {ok, Value} when is_binary(Value) -> Value;
        {ok, Value} when is_list(Value) -> list_to_binary(Value);
        _ -> <<"0.0.1">>
    end.
