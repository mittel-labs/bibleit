-module(bibleit_protocol_tests).
-include_lib("eunit/include/eunit.hrl").

protocol_test_() ->
    {setup, fun setup/0, fun cleanup/1, fun(_Pid) -> [fun server_info_advertises_capabilities/0,
                                                        fun live_list_requires_authentication/0,
                                                        fun auth_and_live_lifecycle/0,
                                                        fun public_key_login_is_challenge_bound/0,
                                                        fun bootstrap_actor_can_receive_quota/0,
                                                        fun token_and_custom_role_lifecycle/0,
                                                        fun wildcard_permissions_and_server_admin_binding/0,
                                                        fun quota_lifecycle_and_enforcement/0,
                                                        fun actor_management_is_limited_to_direct_children/0,
                                                        fun owned_live_listing/0,
                                                        fun remove_live_notifies_subscribers/0,
                                                        fun remove_all_lives_only_removes_lives_managed_by_the_actor/0,
                                                        fun secret_protected_live_subscription_requires_secret/0] end}.

tcp_connection_supervision_test() ->
    {ok, Supervisor} = bibleit_tcp_connection_sup:start_link(),
    try
        {ok, Connection} = bibleit_tcp_connection_sup:start_child(),
        ?assert(lists:any(fun({_Id, Pid, worker, [bibleit_tcp_connection]}) -> Pid =:= Connection; (_) -> false end,
                          supervisor:which_children(Supervisor)))
    after
        unlink(Supervisor),
        exit(Supervisor, shutdown)
    end.

setup() ->
    Path = filename:join("/tmp", "bibleit-auth-" ++ integer_to_list(erlang:unique_integer([positive])) ++ ".dets"),
    file:delete(Path),
    application:set_env(bibleit_server, authorization_path, Path),
    application:set_env(bibleit_server, tokens, #{<<"owner-token">> => #{actor => <<"owner">>, permissions => [{live, create}, {live, get}, {translation, create}, {actor, create}, {actor, update}]}}),
    {ok, Authorization} = bibleit_authorization:start_link(),
    {ok, Sessions} = bibleit_live_session_sup:start_link(),
    {ok, Registry} = bibleit_live_registry:start_link(), {Authorization, Sessions, Registry, Path}.
cleanup({Authorization, Sessions, Registry, Path}) ->
    unlink(Registry), exit(Registry, shutdown),
    unlink(Sessions), exit(Sessions, shutdown),
    unlink(Authorization), exit(Authorization, shutdown),
    file:delete(Path),
    application:unset_env(bibleit_server, authorization_path),
    application:unset_env(bibleit_server, tokens).

server_info_advertises_capabilities() ->
    {ok, server_info} = bibleit_protocol:decode(<<"SERVER INFO">>),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle(server_info, #{actor => undefined}),
    {reply, {ok, AuthenticatedResponse}, _} = bibleit_protocol:handle(server_info, #{actor => <<"reader">>, permissions => []}),
    ?assertEqual(<<"help,auth,translation,read,search,live">>, proplists:get_value(capabilities, AuthenticatedResponse)),
    ?assertMatch(["OK" | _], bibleit_protocol:encode({ok, AuthenticatedResponse})).

rate_limit_errors_include_a_retry_hint_test() ->
    ?assertEqual(<<"ERR rate_limited retry_after_ms=250\n">>, iolist_to_binary(bibleit_protocol:encode({error, rate_limited, 250}))).

live_list_requires_authentication() ->
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle(list_lives, #{actor => undefined}),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle({get_live, <<"id">>}, #{actor => undefined}),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle({subscribe_live, <<"id">>}, #{actor => undefined}).

auth_and_live_lifecycle() ->
    State0 = #{actor => undefined},
    {reply, {error, unknown_key}, _} = bibleit_protocol:handle({auth_login_key, <<"SHA256:missing">>}, State0),
    {reply, {error, unauthorized}, State1} = bibleit_protocol:handle({create_live, <<"Sunday">>}, State0),
    State2 = State1#{actor => <<"owner">>, permissions => [{live, create}, {live, get}, {translation, create}, {actor, create}, {actor, update}]},
    {ok, CreateActor} = bibleit_protocol:decode(<<"auth actor create bob">>),
    {reply, {ok, _}, State2} = bibleit_protocol:handle(CreateActor, State2),
    {ok, Grant} = bibleit_protocol:decode(<<"auth actor grant bob permission translation create">>),
    {reply, {ok, []}, State2} = bibleit_protocol:handle(Grant, State2),
    {ok, Create} = bibleit_protocol:decode(<<"live create Sunday Service">>),
    {reply, {ok, Created}, State3} = bibleit_protocol:handle(Create, State2),
    Id = proplists:get_value(id, Created),
    ?assertEqual(undefined, proplists:get_value(secret, Created)),
    {ok, Set} = bibleit_protocol:decode(<<"live ", Id/binary, " set reference John 3:16">>),
    {reply, {ok, Updated}, _} = bibleit_protocol:handle(Set, State3),
    ?assertEqual(<<"John 3:16">>, proplists:get_value(reference, Updated)),
    {reply, {ok, Info}, _} = bibleit_protocol:handle({get_live, Id}, State3),
    ?assertEqual(<<"owner">>, proplists:get_value(created_by, Info)),
    {ok, Translations} = bibleit_protocol:decode(<<"live ", Id/binary, " set translations KJV NVIPT">>),
    {reply, {ok, WithTranslations}, _} = bibleit_protocol:handle(Translations, State3),
    ?assertEqual(<<"KJV,NVIPT">>, proplists:get_value(translations, WithTranslations)).

public_key_login_is_challenge_bound() ->
    ok = bibleit_authorization:create_actor(<<"owner">>, <<"key-user">>),
    {PublicKey, PrivateKey} = crypto:generate_key(eddsa, ed25519),
    {ok, Fingerprint} = bibleit_authorization:create_key(<<"owner">>, <<"key-user">>, ssh_public_key(PublicKey)),
    {reply, {ok, Challenge}, State1} = bibleit_protocol:handle({auth_login_key, Fingerprint}, #{actor => undefined}),
    Id = proplists:get_value(challenge, Challenge),
    Nonce = base64:decode(proplists:get_value(nonce, Challenge)),
    Message = <<"bibleit-auth-key-v1", 0, Id/binary, 0, Nonce/binary>>,
    Signature = base64:encode(ssh_signature(Message, PublicKey, PrivateKey)),
    {reply, {ok, Fields}, State2} = bibleit_protocol:handle({auth_login_prove, Id, Signature}, State1),
    ?assertEqual(<<"key-user">>, proplists:get_value(actor, Fields)),
    ?assertEqual(<<"key-user">>, maps:get(actor, State2)),
    {reply, {error, invalid_challenge}, _} = bibleit_protocol:handle({auth_login_prove, Id, Signature}, State2).

bootstrap_actor_can_receive_quota() ->
    ok = bibleit_authorization:set_quota(<<"owner">>, {token, create}, 1000),
    {ok, Owner} = bibleit_authorization:actor_info(<<"owner">>),
    ?assertEqual(1000, maps:get({token, create}, maps:get(quotas, Owner))).

token_and_custom_role_lifecycle() ->
    Admin = #{actor => <<"owner">>, permissions => [{actor, create}, {actor, update}, {actor, delete}, {role, create}, {role, update}, {role, delete}, {token, create}, {token, get}, {token, delete}, {live, get}, {live, subscribe}]},
    {ok, CreateRole} = bibleit_protocol:decode(<<"auth role create reader permission live get subscribe">>),
    {reply, {ok, _}, _} = bibleit_protocol:handle(CreateRole, Admin),
    {ok, CreateActor} = bibleit_protocol:decode(<<"auth actor create role-reader">>),
    {reply, {ok, _}, _} = bibleit_protocol:handle(CreateActor, Admin),
    {ok, GrantRole} = bibleit_protocol:decode(<<"auth actor grant role-reader role reader">>),
    {reply, {ok, []}, _} = bibleit_protocol:handle(GrantRole, Admin),
    {ok, CreateToken} = bibleit_protocol:decode(<<"auth token create role-reader Workstation">>),
    {reply, {ok, Issued}, _} = bibleit_protocol:handle(CreateToken, Admin),
    TokenId = proplists:get_value(id, Issued),
    Token = proplists:get_value(token, Issued),
    ?assertMatch(<<"bt_", _:43/binary>>, Token),
    {ok, RoleReaderPermissions} = bibleit_authorization:actor_permissions(<<"role-reader">>),
    Authenticated = #{actor => <<"role-reader">>, permissions => RoleReaderPermissions},
    ?assertEqual(<<"role-reader">>, maps:get(actor, Authenticated)),
    ?assert(lists:member({live, get}, maps:get(permissions, Authenticated))),
    {ok, ListTokens} = bibleit_protocol:decode(<<"auth token list role-reader">>),
    {reply, {ok, {tokens, <<"role-reader">>, [ListedToken]}}, _} = bibleit_protocol:handle(ListTokens, Admin),
    ?assertEqual(TokenId, maps:get(id, ListedToken)),
    ?assertEqual(<<"Workstation">>, maps:get(label, ListedToken)),
    ?assertEqual(manual, maps:get(source, ListedToken)),
    RevokeLine = <<"auth token revoke role-reader ", TokenId/binary>>,
    {ok, RevokeToken} = bibleit_protocol:decode(RevokeLine),
    {reply, {ok, Revoked}, _} = bibleit_protocol:handle(RevokeToken, Admin),
    ?assertEqual(TokenId, proplists:get_value(id, Revoked)),
    {reply, {ok, _}, _} = bibleit_protocol:handle(CreateToken, Admin),
    {ok, RevokeAll} = bibleit_protocol:decode(<<"auth token revoke role-reader all">>),
    {reply, {ok, RevokedAll}, _} = bibleit_protocol:handle(RevokeAll, Admin),
    ?assertEqual(1, proplists:get_value(revoked, RevokedAll)).

wildcard_permissions_and_server_admin_binding() ->
    ?assertEqual({ok, {global_grant, <<"bob">>, permission, [{live, all}]}},
                 bibleit_protocol:decode(<<"auth actor grant bob permission live.*">>)),
    {reply, {ok, {help, <<"live">>, true, LiveCommands}}, _} = bibleit_protocol:handle({help, <<"live">>}, #{actor => <<"operator">>, permissions => [{live, all}]}),
    ?assert(lists:member(<<"live <id> delete">>, [maps:get(usage, Command) || Command <- LiveCommands])),
    ok = bibleit_authorization:create_actor(<<"owner">>, <<"admin-target">>),
    Manager = #{actor => <<"manager">>, permissions => [{actor, update}]},
    {reply, {error, forbidden}, _} = bibleit_protocol:handle({global_grant, <<"admin-target">>, role, [server_admin]}, Manager),
    OwnerManager = #{actor => <<"owner">>, permissions => [{actor, update}]},
    {reply, {error, role_not_assignable}, _} = bibleit_protocol:handle({global_grant, <<"admin-target">>, role, [default]}, OwnerManager),
    ServerAdmin = #{actor => <<"root">>, permissions => [{actor, update}, {role, bind}]},
    {reply, {ok, []}, _} = bibleit_protocol:handle({global_grant, <<"admin-target">>, role, [server_admin]}, ServerAdmin).

quota_lifecycle_and_enforcement() ->
    ok = bibleit_authorization:create_actor(<<"owner">>, <<"limited">>),
    Admin = #{actor => <<"owner">>, permissions => [{quota, get}, {quota, update}]},
    {ok, ActorQuota} = bibleit_protocol:decode(<<"auth actor grant limited quota actor.create 1">>),
    {reply, {ok, []}, _} = bibleit_protocol:handle(ActorQuota, Admin),
    {reply, {ok, {auth_quotas, <<"limited">>, ActorQuotas}}, _} = bibleit_protocol:handle({auth_quotas, <<"limited">>}, Admin),
    ?assertEqual([{{actor, create}, 1}], ActorQuotas),
    LimitedActor = #{actor => <<"limited">>, permissions => [{actor, create}]},
    {reply, {ok, _}, _} = bibleit_protocol:handle({create_actor, <<"first-child">>}, LimitedActor),
    {reply, {error, quota_exceeded}, _} = bibleit_protocol:handle({create_actor, <<"second-child">>}, LimitedActor),
    {ok, TokenQuota} = bibleit_protocol:decode(<<"auth actor grant limited quota token.create 1">>),
    {reply, {ok, []}, _} = bibleit_protocol:handle(TokenQuota, Admin),
    LimitedToken = #{actor => <<"limited">>, permissions => [{actor, update}, {token, create}]},
    {reply, {ok, _}, _} = bibleit_protocol:handle({create_token, <<"first-child">>}, LimitedToken),
    {reply, {error, quota_exceeded}, _} = bibleit_protocol:handle({create_token, <<"first-child">>}, LimitedToken),
    {ok, LiveQuota} = bibleit_protocol:decode(<<"auth actor grant limited quota live.create 1">>),
    {reply, {ok, []}, _} = bibleit_protocol:handle(LiveQuota, Admin),
    LimitedLive = #{actor => <<"limited">>, permissions => [{live, create}]},
    {reply, {ok, _}, _} = bibleit_protocol:handle({create_live, <<"first live">>}, LimitedLive),
    {reply, {error, quota_exceeded}, _} = bibleit_protocol:handle({create_live, <<"second live">>}, LimitedLive),
    {ok, RevokeQuota} = bibleit_protocol:decode(<<"auth actor revoke limited quota actor.create">>),
    {reply, {ok, []}, _} = bibleit_protocol:handle(RevokeQuota, Admin),
    ?assertEqual(<<"OK\n">>, iolist_to_binary(bibleit_protocol:encode({ok, []}))).

actor_management_is_limited_to_direct_children() ->
    ok = bibleit_authorization:create_actor(<<"owner">>, <<"managed-child">>),
    ok = bibleit_authorization:create_actor(<<"other-parent">>, <<"unmanaged-child">>),
    Owner = #{actor => <<"owner">>, permissions => [{actor, get}, {actor, list}, {actor, update}, {token, create}, {live, get}]},
    {reply, {ok, {actors, Children, _}}, _} = bibleit_protocol:handle({list_actors, 10, undefined}, Owner),
    [ManagedChild] = [Info || Info = #{actor := <<"managed-child">>} <- Children],
    ?assert(is_integer(maps:get(created_at, ManagedChild))),
    ?assertNot(lists:any(fun(#{actor := Actor}) -> Actor =:= <<"unmanaged-child">> end, Children)),
    {reply, {ok, ManagedInfo}, _} = bibleit_protocol:handle({actor_info, <<"managed-child">>}, Owner),
    ?assert(is_integer(proplists:get_value(created_at, ManagedInfo))),
    ?assertEqual(0, proplists:get_value(tokens, ManagedInfo)),
    {reply, {ok, []}, _} = bibleit_protocol:handle({global_grant, <<"managed-child">>, permission, [{live, get}]}, Owner),
    {reply, {error, forbidden}, _} = bibleit_protocol:handle({global_grant, <<"unmanaged-child">>, permission, [{live, get}]}, Owner),
    {reply, {ok, _}, _} = bibleit_protocol:handle({create_token, <<"managed-child">>}, Owner),
    {reply, {error, forbidden}, _} = bibleit_protocol:handle({create_token, <<"unmanaged-child">>}, Owner).

owned_live_listing() ->
    {ok, _OwnerId, _} = bibleit_live_registry:create(<<"owner">>, #{name => <<"owner">>}),
    ok = bibleit_authorization:create_actor(<<"owner">>, <<"child">>),
    {ok, _TokenId, _Token} = bibleit_authorization:create_token(<<"owner">>, <<"child">>),
    {ok, _ChildId, _} = bibleit_live_registry:create(<<"child">>, #{name => <<"child">>}),
    ok = bibleit_authorization:create_actor(<<"other-parent">>, <<"other">>),
    {ok, _OtherTokenId, _OtherToken} = bibleit_authorization:create_token(<<"other-parent">>, <<"other">>),
    {ok, _OtherId, _} = bibleit_live_registry:create(<<"other">>, #{name => <<"other">>}),
    {ok, Lives} = bibleit_live_registry:list(<<"owner">>),
    Names = [maps:get(name, Live) || Live <- Lives],
    ?assert(lists:all(fun(Live) -> maps:is_key(created_by, Live) end, Lives)),
    ?assert(lists:member(<<"owner">>, Names)),
    ?assert(lists:member(<<"child">>, Names)),
    ?assertNot(lists:member(<<"other">>, Names)).

single_word_live_name_is_valid_test() ->
    ?assertEqual({ok, {create_live, <<"mittel">>}},
                 bibleit_protocol:decode(<<"live create mittel">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"live create+ mittel">>)).

read_uses_translation_and_numeric_reference_test() ->
    ?assertEqual({ok, {read, <<"KJV">>, 43, 3, 16}},
                 bibleit_protocol:decode(<<"read KJV 43 3 16">>)),
    ?assertEqual({ok, {read, <<"KJV">>, 43, 3, 16}},
                 bibleit_protocol:decode(<<"read KJV 43 3:16">>)).

named_book_catalog_uses_latin_ester_test() ->
    ?assertEqual({ok, 17},
                 bibleit_translation_catalog:resolve_book(<<"nvipt">>, <<"ester">>)),
    ?assertEqual({ok, 43},
                 bibleit_translation_catalog:resolve_book(<<"nvipt">>, <<"o evangelho de joao">>)).

invalid_translation_commands_are_specific_test() ->
    ?assertEqual({error, invalid_reference}, bibleit_protocol:decode(<<"read KJV 0 3">>)),
    ?assertEqual({error, empty_query}, bibleit_protocol:decode(<<"search KJV">>)),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle({search, <<"KJV">>, <<"love">>}, #{actor => undefined}).

help_is_permission_aware_test() ->
    ?assertEqual({ok, {help, <<"translation">>}}, bibleit_protocol:decode(<<"help translation">>)),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle({help, <<"translation">>}, #{actor => undefined}),
    {reply, {ok, {help, <<"translation">>, true, Managed}}, _} = bibleit_protocol:handle({help, <<"translation">>}, #{actor => <<"admin">>, permissions => [{translation, create}]}),
    ?assert(lists:any(fun(#{usage := Usage}) -> binary:match(Usage, <<"fetch">>) =/= nomatch end, Managed)),
    {reply, {ok, {help, <<"translation">>, true, Reader}}, _} = bibleit_protocol:handle({help, <<"translation">>}, #{actor => <<"reader">>, permissions => [{translation, get}]}),
    Encoded = iolist_to_binary(bibleit_protocol:encode({ok, {help, <<"translation">>, true, Reader}})),
    ?assertNotEqual(nomatch, binary:match(Encoded, <<"COMMAND usage=\"translation catalog <slug>\" auth=permission summary=">>)),
    ?assertNotEqual(nomatch, binary:match(Encoded, <<"auth=true">>)),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle({help, <<"root">>}, #{actor => undefined}),
    {reply, {ok, {help, <<"root">>, true, AuthenticatedRoot}}, _} = bibleit_protocol:handle({help, <<"root">>}, #{actor => <<"reader">>, permissions => []}),
    ?assertEqual(false, lists:any(fun(#{usage := Usage}) -> binary:match(Usage, <<"search ">>) =/= nomatch end, AuthenticatedRoot)),
    ?assertEqual(false, lists:any(fun(#{usage := Usage}) -> Usage =:= <<"live ...">> end, AuthenticatedRoot)),
    ?assert(lists:member(<<"help [server|account|auth|translation|live]">>, [maps:get(usage, Command) || Command <- AuthenticatedRoot])),
    {reply, {ok, {help, <<"live">>, true, []}}, _} = bibleit_protocol:handle({help, <<"live">>}, #{actor => <<"reader">>, permissions => []}),
    {reply, {ok, {help, <<"live">>, true, ReadOnlyLive}}, _} = bibleit_protocol:handle({help, <<"live">>}, #{actor => <<"reader">>, permissions => [{live, get}]}),
    ?assertEqual([<<"live <id> info">>, <<"live <id> stack info">>, <<"live <id> stats">>], [maps:get(usage, Command) || Command <- ReadOnlyLive]),
    {reply, {ok, {help, <<"auth">>, true, BasicAuth}}, _} = bibleit_protocol:handle({help, <<"auth">>}, #{actor => <<"reader">>, permissions => []}),
    BasicAuthUsages = [maps:get(usage, Command) || Command <- BasicAuth],
    ?assertNot(lists:member(<<"auth list resource">>, BasicAuthUsages)),
    ?assertNot(lists:member(<<"auth list permission">>, BasicAuthUsages)),
    ?assertNot(lists:member(<<"auth list role">>, BasicAuthUsages)),
    {reply, {ok, {help, <<"auth">>, true, AuthorizationReader}}, _} = bibleit_protocol:handle({help, <<"auth">>}, #{actor => <<"manager">>, permissions => [{authorization, list}, {role, list}]}),
    AuthorizationReaderUsages = [maps:get(usage, Command) || Command <- AuthorizationReader],
    ?assert(lists:member(<<"auth list resource">>, AuthorizationReaderUsages)),
    ?assert(lists:member(<<"auth list permission">>, AuthorizationReaderUsages)),
    ?assert(lists:member(<<"auth list role">>, AuthorizationReaderUsages)),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle({help, <<"live">>}, #{actor => undefined}),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle({help, <<"fd">>}, #{actor => undefined}).

auth_subcommands_test() ->
    ?assertEqual({ok, {auth_login_key, <<"SHA256:key">>}}, bibleit_protocol:decode(<<"auth login SHA256:key">>)),
    ?assertEqual({ok, {auth_login_prove, <<"challenge">>, <<"signature">>}}, bibleit_protocol:decode(<<"auth login prove challenge signature">>)),
    ?assertEqual({ok, {list_keys, <<"felipe">>}}, bibleit_protocol:decode(<<"auth key list felipe">>)),
    ?assertEqual({ok, {revoke_key, <<"felipe">>, <<"SHA256:key">>}}, bibleit_protocol:decode(<<"auth key revoke felipe SHA256:key">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"auth f">>)),
    ?assertEqual({ok, auth_logout}, bibleit_protocol:decode(<<"auth logout">>)),
    ?assertEqual({ok, auth_info}, bibleit_protocol:decode(<<"auth info">>)),
    ?assertEqual({ok, auth_info}, bibleit_protocol:decode(<<"whoami">>)),
    ?assertEqual({ok, quit}, bibleit_protocol:decode(<<"quit">>)),
    ?assertEqual({ok, quit}, bibleit_protocol:decode(<<"exit">>)),
    ?assertEqual({ok, auth_permissions}, bibleit_protocol:decode(<<"auth list permission">>)),
    ?assertEqual({ok, auth_resources}, bibleit_protocol:decode(<<"auth list resource">>)),
    ?assertEqual({ok, auth_roles}, bibleit_protocol:decode(<<"auth list role">>)),
    ?assertEqual({ok, {create_actor, <<"bob">>}}, bibleit_protocol:decode(<<"auth actor create bob">>)),
    ?assertEqual({ok, {global_grant, <<"bob">>, permission, [{live, create}]}},
                 bibleit_protocol:decode(<<"auth actor grant bob permission live create">>)),
    ?assertEqual({ok, {global_grant, <<"bob">>, permission, [{translation, create}, {translation, delete}]}},
                 bibleit_protocol:decode(<<"auth actor grant bob permission translation create delete">>)),
    ?assertEqual({ok, {global_grant, <<"bob">>, permission, [{actor, create}, {translation, read}]}},
                 bibleit_protocol:decode(<<"auth actor grant bob permission actor.create translation.read">>)),
    ?assertEqual({ok, {global_revoke, <<"bob">>, permission, [{actor, create}]}},
                 bibleit_protocol:decode(<<"auth actor revoke bob permission actor.create">>)),
    ?assertEqual({ok, {global_grant, <<"bob">>, permission, [{live, all}]}},
                 bibleit_protocol:decode(<<"auth actor grant bob permission live.*">>)),
    ?assertEqual({ok, {global_grant, <<"bob">>, quota, {{actor, create}, 3}}},
                 bibleit_protocol:decode(<<"auth actor grant bob quota actor.create 3">>)),
    ?assertEqual({ok, {global_revoke, <<"bob">>, quota, {actor, create}}},
                 bibleit_protocol:decode(<<"auth actor revoke bob quota actor.create">>)),
    ?assertEqual({ok, {auth_quotas, <<"bob">>}}, bibleit_protocol:decode(<<"auth actor quota list bob">>)),
    ?assertEqual({ok, {list_actors, 10, undefined}}, bibleit_protocol:decode(<<"auth actor list">>)),
    ?assertEqual({ok, {actor_info, <<"bob">>}}, bibleit_protocol:decode(<<"auth actor info bob">>)),
    ?assertEqual({error, missing_token_id}, bibleit_protocol:decode(<<"auth token revoke bob">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"auth token">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"auth grant bob permission live create">>)),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle(auth_info, #{actor => undefined}),
    {reply, {ok, AuthInfo}, _} = bibleit_protocol:handle(auth_info, #{actor => <<"reader">>, permissions => [{live, create}]}),
    ?assertEqual(true, proplists:get_value(auth, AuthInfo)),
    ?assertEqual(<<"reader">>, proplists:get_value(actor, AuthInfo)),
    ?assertEqual(<<"help.get,live.create,server.get,token.get,translation.get,translation.list,translation.read">>, proplists:get_value(permissions, AuthInfo)),
    ?assertMatch(<<"OK actor=\"reader\" display_name=\"reader\" auth=true", _/binary>>, iolist_to_binary(bibleit_protocol:encode({ok, AuthInfo}))),
    {reply, {ok, [{closing, true}]}, ClosingState} = bibleit_protocol:handle(quit, #{actor => undefined}),
    ?assertEqual(true, maps:get(close_after_reply, ClosingState)),
    {reply, {ok, LoggedOff}, LoggedOffState} = bibleit_protocol:handle(auth_logout, #{actor => <<"reader">>, permissions => [{live, create}]}),
    ?assertEqual(false, proplists:get_value(auth, LoggedOff)),
    ?assertEqual(undefined, maps:get(actor, LoggedOffState)),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle(auth_permissions, #{actor => undefined}),
    {reply, {ok, {auth_permissions, Permissions}}, _} = bibleit_protocol:handle(auth_permissions, #{actor => <<"reader">>, permissions => [{authorization, list}]}),
    ?assert(lists:member({live, create}, Permissions)),
    {reply, {ok, {auth_resources, Resources}}, _} = bibleit_protocol:handle(auth_resources, #{actor => <<"reader">>, permissions => [{authorization, list}]}),
    ?assert(lists:member(actor, Resources)),
    {reply, {ok, {auth_roles, Roles}}, _} = bibleit_protocol:handle(auth_roles, #{actor => <<"reader">>, permissions => [{role, list}]}),
    ?assert(lists:keymember(live_operator, 1, Roles)),
    {presenter, PresenterPermissions} = lists:keyfind(presenter, 1, Roles),
    ?assert(lists:member({translation, read}, PresenterPermissions)),
    {identity_manager, IdentityPermissions} = lists:keyfind(identity_manager, 1, Roles),
    ?assert(lists:member({actor, create}, IdentityPermissions)),
    ?assert(lists:member({token, create}, IdentityPermissions)).

member_account_entitlement_test_() ->
    {setup, fun setup/0, fun cleanup/1, fun(_Context) -> fun() ->
        ok = bibleit_authorization:ensure_member_actor(<<"google">>, <<"member">>),
        {ok, Permissions} = bibleit_authorization:actor_permissions(<<"member">>),
        ?assert(lists:member({translation, search}, Permissions)),
        ?assert(lists:member({live, create}, Permissions)),
        ?assert(lists:member({token, create}, Permissions)),
        ?assert(lists:member({key, create}, Permissions)),
        ?assertEqual(3, bibleit_authorization:quota_limit(<<"member">>, {live, create})),
        ?assertEqual(5, bibleit_authorization:quota_limit(<<"member">>, {token, create})),
        ?assertEqual(5, bibleit_authorization:quota_limit(<<"member">>, {key, create})),
        ?assertEqual({error, quota_exceeded}, bibleit_authorization:check_quota(<<"member">>, {live, create}, 3)),
        MemberState = #{actor => <<"member">>, permissions => Permissions, roles => [member]},
        {ok, account_info} = bibleit_protocol:decode(<<"account info">>),
        {reply, {ok, Account}, _} = bibleit_protocol:handle(account_info, MemberState),
        ?assertEqual(<<"member">>, proplists:get_value(actor, Account)),
        {ok, ContractAccount} = bibleit_account:summary(<<"member">>),
        ?assertEqual(maps:get(lives, ContractAccount), proplists:get_value(lives, Account)),
        ?assertEqual(maps:get(tokens, ContractAccount), proplists:get_value(tokens, Account)),
        ?assertEqual(maps:get(keys, ContractAccount), proplists:get_value(keys, Account)),
        ?assertEqual(free, proplists:get_value(plan, Account)),
        ?assertEqual(active, proplists:get_value(subscription_status, Account)),
        ?assertEqual(none, proplists:get_value(subscription_billing_cycle, Account)),
        {ok, {account_create_token, <<"Terminal">>}} = bibleit_protocol:decode(<<"account token create Terminal">>),
        {reply, {ok, Token}, _} = bibleit_protocol:handle({account_create_token, <<"Terminal">>}, MemberState),
        TokenId = proplists:get_value(id, Token),
        {reply, {ok, {tokens, <<"member">>, [_]}}, _} = bibleit_protocol:handle(account_list_tokens, MemberState),
        {reply, {ok, [{id, TokenId}]}, _} = bibleit_protocol:handle({account_revoke_tokens, TokenId}, MemberState),
        {reply, {ok, {account_quotas, Quotas}}, _} = bibleit_protocol:handle(account_quotas, MemberState),
        ?assert(lists:member({{live, create}, 3, 0}, Quotas)),
        {reply, {ok, {help, _, _, Help}}, _} = bibleit_protocol:handle({help, <<"account">>}, MemberState),
        ?assert(lists:any(fun(Entry) -> maps:get(usage, Entry) =:= <<"account token create [label]">> end, Help)),
        {reply, {ok, {help, _, _, AuthHelp}}, _} = bibleit_protocol:handle({help, <<"auth">>}, MemberState),
        ?assertNot(lists:any(fun(Entry) -> maps:get(usage, Entry) =:= <<"auth token create <actor> [label]">> end, AuthHelp)),
        {reply, {error, forbidden}, _} = bibleit_protocol:handle({create_token, <<"member">>}, MemberState)
    end end}.

live_secret_commands_are_case_insensitive_test() ->
    ?assertEqual({ok, ping}, bibleit_protocol:decode(<<"PING">>)),
    ?assertEqual({ok, {get_live, <<"id">>}}, bibleit_protocol:decode(<<"live id info">>)),
    ?assertEqual({ok, {live_stats, <<"id">>}}, bibleit_protocol:decode(<<"live id stats">>)),
    ?assertEqual({ok, {authenticate_live_secret, <<"id">>, <<"my-secret">>}}, bibleit_protocol:decode(<<"live id secret my-secret">>)),
    ?assertEqual({ok, {set_live_secret, <<"id">>, <<"my-secret">>}}, bibleit_protocol:decode(<<"LIVE id SECRET SET my-secret">>)),
    ?assertEqual({ok, {rotate_live_secret, <<"id">>}}, bibleit_protocol:decode(<<"live id secret rotate">>)),
    ?assertEqual({ok, {delete_live_secret, <<"id">>}}, bibleit_protocol:decode(<<"live id secret delete">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"live id set type private">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"live id show">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"live id hide">>)),
    ?assertEqual({ok, {resume_live, <<"id">>}}, bibleit_protocol:decode(<<"live id resume">>)),
    ?assertEqual({ok, {pause_live, <<"id">>}}, bibleit_protocol:decode(<<"live id pause">>)),
    ?assertEqual({ok, list_lives}, bibleit_protocol:decode(<<"live list">>)),
    ?assertEqual({ok, remove_all_lives}, bibleit_protocol:decode(<<"live delete all">>)),
    ?assertEqual({ok, {subscribe_live, <<"id">>}},
                 bibleit_protocol:decode(<<"LIVE id SUBSCRIBE">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"LIVE id READ nvipt salmos 23">>)),
    ?assertEqual({ok, {push_live, <<"id">>, #{translation => <<"nvipt">>, book => <<"salmos">>, chapter => 23, verse => undefined}}},
                 bibleit_protocol:decode(<<"LIVE id STACK PUSH nvipt salmos 23">>)),
    ?assertEqual({ok, {push_live, <<"id">>, #{book => <<"salmos">>, chapter => 23, verse => undefined}}},
                 bibleit_protocol:decode(<<"LIVE id STACK PUSH salmos 23">>)),
    ?assertEqual({ok, {push_live, <<"id">>, #{book => <<"salmos">>, chapter => 23, verse => 1}}},
                 bibleit_protocol:decode(<<"LIVE id STACK PUSH salmos 23 1">>)),
    ?assertEqual({ok, {push_live, <<"id">>, #{book => <<"salmos">>, chapter => 23, verse => 1}}},
                 bibleit_protocol:decode(<<"LIVE id STACK PUSH salmos 23:1">>)),
    ?assertEqual({ok, {pop_live, <<"id">>, 1}}, bibleit_protocol:decode(<<"LIVE id STACK POP">>)),
    ?assertEqual({ok, {pop_live, <<"id">>, 2}}, bibleit_protocol:decode(<<"LIVE id STACK POP 2">>)),
    ?assertEqual({ok, {pop_live, <<"id">>, -2}}, bibleit_protocol:decode(<<"LIVE id STACK POP -2">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"LIVE id STACK POP 0">>)),
    ?assertEqual({ok, {live_stack_info, <<"id">>}}, bibleit_protocol:decode(<<"LIVE id STACK INFO">>)),
    ?assertEqual({ok, {clear_live, <<"id">>}},
                 bibleit_protocol:decode(<<"LIVE id CLEAR">>)),
    ?assertEqual({ok, {clear_live, <<"id">>}}, bibleit_protocol:decode(<<"LIVE id STACK CLEAR">>)),
    ?assertEqual({ok, {start_live, <<"id">>}}, bibleit_protocol:decode(<<"LIVE id START">>)),
    ?assertEqual({ok, {stop_live, <<"id">>}}, bibleit_protocol:decode(<<"LIVE id STOP">>)),
    ?assertEqual({ok, {remove_live, <<"id">>}}, bibleit_protocol:decode(<<"LIVE id DELETE">>)).

remove_live_notifies_subscribers() ->
    {ok, Id, _} = bibleit_live_registry:create(<<"owner">>, #{}),
    {ok, Pid} = bibleit_live_registry:lookup(Id),
    {ok, _} = bibleit_live_session:subscribe(Pid, <<"owner">>, self()),
    {reply, {ok, live_removed}, _} = bibleit_protocol:handle({remove_live, Id}, #{actor => <<"owner">>}),
    receive {live_closed, Id} -> ok after 1000 -> ?assert(false) end,
    ?assertEqual(error, bibleit_live_registry:lookup(Id)).

remove_all_lives_only_removes_lives_managed_by_the_actor() ->
    {ok, OwnedId, _} = bibleit_live_registry:create(<<"owner">>, #{}),
    {ok, OtherId, _} = bibleit_live_registry:create(<<"other">>, #{}),
    {reply, {ok, [{deleted, Count}]}, _} = bibleit_protocol:handle(remove_all_lives, #{actor => <<"owner">>}),
    ?assert(Count >= 1),
    ?assertEqual(error, bibleit_live_registry:lookup(OwnedId)),
    ?assertMatch({ok, _}, bibleit_live_registry:lookup(OtherId)).

secret_protected_live_subscription_requires_secret() ->
    {ok, Id, _} = bibleit_live_registry:create(<<"owner">>, #{}),
    {ok, Pid} = bibleit_live_registry:lookup(Id),
    Secret = <<"shared-secret">>,
    {ok, _} = bibleit_live_session:set_secret(Pid, <<"owner">>, Secret),
    Viewer = #{actor => <<"viewer">>, permissions => [{live, subscribe}]},
    {reply, {error, forbidden}, _} = bibleit_protocol:handle({subscribe_live, Id}, Viewer),
    {reply, {ok, []}, Authorized} = bibleit_protocol:handle({authenticate_live_secret, Id, Secret}, #{actor => <<"viewer">>, permissions => [{live, subscribe}]}),
    {reply, {ok, _}, _} = bibleit_protocol:handle({subscribe_live, Id}, Authorized),
    {reply, {error, unauthorized}, _} = bibleit_protocol:handle({authenticate_live_secret, Id, <<"wrong-secret">>}, #{actor => <<"viewer">>, permissions => [{live, subscribe}]}).

fetch_translation_uses_translation_subcommand_test() ->
    ?assertEqual({ok, {fetch_translation, <<"nvipt">>}},
                 bibleit_protocol:decode(<<"translation fetch nvipt">>)).

translation_subcommands_test() ->
    ?assertEqual({ok, translation_list}, bibleit_protocol:decode(<<"translation list">>)),
    ?assertEqual({ok, available_translation_list}, bibleit_protocol:decode(<<"translation list all">>)),
    ?assertEqual({ok, {translation_info, <<"kja">>}}, bibleit_protocol:decode(<<"translation info kja">>)),
    ?assertEqual({ok, {translation_catalog, <<"nvipt">>}}, bibleit_protocol:decode(<<"translation catalog nvipt">>)),
    ?assertEqual({ok, {delete_translation, <<"kja">>}}, bibleit_protocol:decode(<<"translation delete kja">>)),
    ?assertEqual({ok, {delete_translation, all}}, bibleit_protocol:decode(<<"translation delete all">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"translation remove kja">>)),
    ?assertEqual({error, bad_command}, bibleit_protocol:decode(<<"translations list">>)).

live_verse_event_encodes_json_payload_test() ->
    Payload = #{translation => <<"nvipt">>, reference => <<"Salmos 23:1">>,
                text => <<"O pastor.">>, translations => []},
    Encoded = iolist_to_binary(bibleit_protocol:encode({event, verse, Payload})),
    Line = binary:part(Encoded, 0, byte_size(Encoded) - 1),
    [Prefix, Kind, Base64] = binary:split(Line, <<" ">>, [global]),
    ?assertEqual(<<"EVENT">>, Prefix),
    ?assertEqual(<<"verse">>, Kind),
    ?assertMatch(#{<<"reference">> := <<"Salmos 23:1">>}, json:decode(base64:decode(Base64))).

ssh_public_key(PublicKey) ->
    Blob = <<11:32/big, "ssh-ed25519", 32:32/big, PublicKey/binary>>,
    <<"ssh-ed25519 ", (base64:encode(Blob))/binary, " test@bibleit">>.
ssh_signature(Message, PublicKey, PrivateKey) ->
    PublicBlob = <<11:32/big, "ssh-ed25519", 32:32/big, PublicKey/binary>>,
    Namespace = <<"bibleit@bibleit.app">>,
    HashAlgorithm = <<"sha512">>,
    Digest = crypto:hash(sha512, Message),
    Signed = <<"SSHSIG", 1:32/big, (ssh_string(PublicBlob))/binary, (ssh_string(Namespace))/binary, 0:32/big, (ssh_string(HashAlgorithm))/binary, (ssh_string(Digest))/binary>>,
    RawSignature = crypto:sign(eddsa, none, Signed, [PrivateKey, ed25519]),
    SignatureBlob = <<(ssh_string(<<"ssh-ed25519">>))/binary, (ssh_string(RawSignature))/binary>>,
    <<"SSHSIG", 1:32/big, (ssh_string(PublicBlob))/binary, (ssh_string(Namespace))/binary, 0:32/big, (ssh_string(HashAlgorithm))/binary, (ssh_string(SignatureBlob))/binary>>.
ssh_string(Value) -> <<(byte_size(Value)):32/big, Value/binary>>.
