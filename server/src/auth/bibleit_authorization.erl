-module(bibleit_authorization).
-behaviour(gen_server).
-export([start_link/0, login/1, actor_permissions/1, actor_display_name/1, set_actor_display_name/2, actor_handle/1, set_actor_handle/2, token_id/1, token_roles/2, create_actor/2, ensure_member_actor/2, delete_actor/1, actor_info/1, create_token/2, create_token/3, revoke_tokens/1, revoke_token/2, tokens/1, token_count/1, create_key/3, revoke_key/2, keys/1, key/1, key_count/1, touch_key/1, can_manage_actor/2, children/1, actors/0, actor_page/2, child_page/3, grant_permissions/2, grant_role/2, revoke_permissions/2, revoke_role/2, set_quota/3, revoke_quota/2, quotas/1, quota_limit/2, check_quota/3, create_role/2, update_role/2, delete_role/1, role/1, role_name/1, roles/0, permissions/0, default_permissions/0, expand_permissions/1]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

-define(TABLE, bibleit_authorization_table).
start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
login(Token) -> gen_server:call(?MODULE, {login, Token}).
actor_permissions(Actor) -> gen_server:call(?MODULE, {actor_permissions, Actor}).
actor_display_name(Actor) -> gen_server:call(?MODULE, {actor_display_name, Actor}).
set_actor_display_name(Actor, Name) -> gen_server:call(?MODULE, {set_actor_display_name, Actor, Name}).
actor_handle(Actor) -> gen_server:call(?MODULE, {actor_handle, Actor}).
set_actor_handle(Actor, Handle) -> gen_server:call(?MODULE, {set_actor_handle, Actor, Handle}).
create_actor(Issuer, Actor) -> gen_server:call(?MODULE, {create_actor, Issuer, Actor}).
ensure_member_actor(Source, Actor) -> gen_server:call(?MODULE, {ensure_member_actor, Source, Actor}).
delete_actor(Actor) -> gen_server:call(?MODULE, {delete_actor, Actor}).
actor_info(Actor) -> gen_server:call(?MODULE, {actor_info, Actor}).
token_id(Token) -> gen_server:call(?MODULE, {token_id, Token}).
token_roles(Token, Actor) -> gen_server:call(?MODULE, {token_roles, Token, Actor}).
create_token(Issuer, Actor) -> create_token(Issuer, Actor, undefined).
create_token(Issuer, Actor, Label) -> gen_server:call(?MODULE, {create_token, Issuer, Actor, Label}).
revoke_tokens(Actor) -> gen_server:call(?MODULE, {revoke_tokens, Actor}).
revoke_token(Actor, Id) -> gen_server:call(?MODULE, {revoke_token, Actor, Id}).
tokens(Actor) -> gen_server:call(?MODULE, {tokens, Actor}).
token_count(Actor) -> case whereis(?MODULE) of undefined -> 0; _ -> gen_server:call(?MODULE, {token_count, Actor}) end.
create_key(Issuer, Actor, PublicKey) -> gen_server:call(?MODULE, {create_key, Issuer, Actor, PublicKey}).
revoke_key(Actor, Fingerprint) -> gen_server:call(?MODULE, {revoke_key, Actor, Fingerprint}).
keys(Actor) -> gen_server:call(?MODULE, {keys, Actor}).
key(Fingerprint) -> gen_server:call(?MODULE, {key, Fingerprint}).
key_count(Actor) -> gen_server:call(?MODULE, {key_count, Actor}).
touch_key(Fingerprint) -> gen_server:call(?MODULE, {touch_key, Fingerprint}).
can_manage_actor(Principal, Actor) -> gen_server:call(?MODULE, {can_manage_actor, Principal, Actor}).
children(Actor) -> case whereis(?MODULE) of undefined -> []; _ -> gen_server:call(?MODULE, {children, Actor}) end.
actors() -> case whereis(?MODULE) of undefined -> []; _ -> gen_server:call(?MODULE, actors) end.
actor_page(Limit, Cursor) -> gen_server:call(?MODULE, {actor_page, Limit, Cursor}).
child_page(Actor, Limit, Cursor) -> gen_server:call(?MODULE, {child_page, Actor, Limit, Cursor}).
grant_permissions(Actor, Permissions) -> gen_server:call(?MODULE, {grant_permissions, Actor, Permissions}).
grant_role(Actor, Role) -> gen_server:call(?MODULE, {grant_role, Actor, Role}).
revoke_permissions(Actor, Permissions) -> gen_server:call(?MODULE, {revoke_permissions, Actor, Permissions}).
revoke_role(Actor, Role) -> gen_server:call(?MODULE, {revoke_role, Actor, Role}).
set_quota(Actor, Permission, Limit) -> gen_server:call(?MODULE, {set_quota, Actor, Permission, Limit}).
revoke_quota(Actor, Permission) -> gen_server:call(?MODULE, {revoke_quota, Actor, Permission}).
quotas(Actor) -> gen_server:call(?MODULE, {quotas, Actor}).
quota_limit(Actor, Permission) -> gen_server:call(?MODULE, {quota_limit, Actor, Permission}).
check_quota(Actor, Permission, Used) -> gen_server:call(?MODULE, {check_quota, Actor, Permission, Used}).
create_role(Name, Permissions) -> gen_server:call(?MODULE, {create_role, Name, Permissions}).
update_role(Name, Permissions) -> gen_server:call(?MODULE, {update_role, Name, Permissions}).
delete_role(Name) -> gen_server:call(?MODULE, {delete_role, Name}).
role(Name) -> gen_server:call(?MODULE, {role, Name}).
role_name(Name) -> gen_server:call(?MODULE, {role_name, Name}).
roles() -> case whereis(?MODULE) of undefined -> configured_roles(); _ -> gen_server:call(?MODULE, roles) end.

init([]) ->
    Path = path(),
    case filelib:ensure_dir(Path) of
        ok ->
            case dets:open_file(?TABLE, [{file, Path}, {type, set}]) of
                {ok, ?TABLE} ->
                    case seed_bootstrap_keys() of
                        ok ->
                            case migrate_subscriptions() of
                                ok -> {ok, #{}};
                                {error, MigrationReason} -> dets:close(?TABLE), {stop, {subscription_migration_failed, MigrationReason}}
                            end;
                        {error, BootstrapReason} -> dets:close(?TABLE), {stop, {invalid_bootstrap_key, BootstrapReason}}
                    end;
                {error, Reason} -> {stop, {authorization_open_failed, Reason}}
            end;
        {error, Reason} -> {stop, {authorization_directory_unavailable, Path, Reason}}
    end.
handle_call({login, Token}, _From, State) ->
    case authenticate_token(Token) of
        {ok, Actor} when is_binary(Actor) -> {reply, {ok, Actor, actor_permissions(Actor, [])}, State};
        {ok, #{actor := Actor} = Claims} ->
            Bootstrap = maps:get(permissions, Claims, maps:get(scopes, Claims, [])),
            BootstrapRoles = maps:get(roles, Claims, []),
            {reply, {ok, Actor, actor_permissions(Actor, Bootstrap, BootstrapRoles)}, State};
        error -> authenticate_issued(Token, State)
    end;
handle_call({actor_permissions, Actor}, _From, State) ->
    case dets:lookup(?TABLE, Actor) of
        [{Actor, _}] -> {reply, {ok, actor_permissions(Actor, [])}, State};
        [] -> {reply, {error, actor_not_found}, State}
    end;
handle_call({actor_display_name, Actor}, _From, State) ->
    case dets:lookup(?TABLE, Actor) of
        [{Actor, Value}] -> {reply, {ok, maps:get(display_name, Value, Actor)}, State};
        [] -> {reply, {error, actor_not_found}, State}
    end;
handle_call({set_actor_display_name, Actor, Name}, _From, State) ->
    case valid_display_name(Name) of
        true -> {reply, update_actor(Actor, fun(Current) -> Current#{display_name => Name} end), State};
        false -> {reply, {error, invalid_display_name}, State}
    end;
handle_call({actor_handle, Actor}, _From, State) ->
    case dets:lookup(?TABLE, Actor) of
        [{Actor, Value}] -> {reply, maps:find(handle, Value), State};
        [] -> {reply, {error, actor_not_found}, State}
    end;
handle_call({set_actor_handle, Actor, Handle}, _From, State) ->
    case valid_handle(Handle) of
        true -> {reply, update_actor(Actor, fun(Current) -> Current#{handle => Handle} end), State};
        false -> {reply, {error, invalid_handle}, State}
    end;
handle_call({create_actor, Issuer, Actor}, _From, State) ->
    case quota_available(Issuer, {actor, create}, created_actor_count(Issuer)) of
        ok -> case dets:lookup(?TABLE, Actor) of
            [] ->
                CreatedAt = erlang:system_time(second),
                {reply, save(Actor, #{permissions => [], roles => [], quotas => #{},
                                      subscription => bibleit_plan:new_subscription(CreatedAt),
                                      created_by => Issuer, created_at => CreatedAt}), State};
            _ -> {reply, {error, actor_exists}, State}
        end;
        Error -> {reply, Error, State}
    end;
handle_call({ensure_member_actor, Source, Actor}, _From, State) ->
    Reply = case dets:lookup(?TABLE, Actor) of
        [] ->
            CreatedAt = erlang:system_time(second),
            save(Actor, #{permissions => [], roles => [member], quotas => member_quotas(),
                          subscription => bibleit_plan:new_subscription(CreatedAt),
                          created_by => Source, created_at => CreatedAt});
        _ -> update_actor(Actor, fun(Current) ->
            Current#{roles => lists:usort([member | maps:get(roles, Current)]),
                     quotas => maps:merge(member_quotas(), maps:get(quotas, Current, #{})),
                     subscription => maps:get(subscription, Current)}
        end)
    end,
    {reply, Reply, State};
handle_call({delete_actor, Actor}, _From, State) ->
    case dets:lookup(?TABLE, Actor) of
        [] -> {reply, {error, actor_not_found}, State};
        _ ->
            Tokens = token_keys(Actor),
            Keys = key_keys(Actor),
            lists:foreach(fun(Key) -> dets:delete(?TABLE, Key) end, Tokens ++ Keys),
            case dets:delete(?TABLE, Actor) of
                ok -> {reply, case dets:sync(?TABLE) of ok -> {ok, length(Tokens) + length(Keys)}; Error -> Error end, State};
                Error -> {reply, Error, State}
            end
    end;
handle_call({actor_info, Actor}, _From, State) ->
    case dets:lookup(?TABLE, Actor) of
        [] -> {reply, {error, actor_not_found}, State};
        _ ->
            Stored = actor(Actor),
            {reply, {ok, Stored#{actor => Actor, permissions => actor_permissions(Actor, []), tokens => length(token_keys(Actor))}}, State}
    end;
handle_call({create_token, Issuer, Actor, Label}, _From, State) ->
    case {valid_label(Label), quota_available(Issuer, {token, create}, issued_token_count(Issuer))} of
        {false, _} -> {reply, {error, invalid_token_label}, State};
        {true, ok} -> case dets:lookup(?TABLE, Actor) of
            [] -> {reply, {error, actor_not_found}, State};
            _ ->
                Token = <<"bt_", (base62_token())/binary>>,
                Hash = token_hash(Token),
            Id = binary:encode_hex(crypto:strong_rand_bytes(8)),
            case dets:insert(?TABLE, {{token, Hash}, token_entry(Id, Actor, Issuer, manual, Label)}) of
                ok -> {reply, case dets:sync(?TABLE) of ok -> {ok, Id, Token}; Error -> Error end, State};
                    Error -> {reply, Error, State}
                end
        end;
        {true, Error} -> {reply, Error, State}
    end;
handle_call({revoke_tokens, Actor}, _From, State) ->
    Tokens = token_keys(Actor),
    lists:foreach(fun(Key) -> dets:delete(?TABLE, Key) end, Tokens),
    {reply, case dets:sync(?TABLE) of ok -> {ok, length(Tokens)}; Error -> Error end, State};
handle_call({revoke_token, Actor, Id}, _From, State) ->
    case [Key || {Key, Value} <- token_entries(Actor), token_id(Key, Value) =:= Id] of
        [Key] -> dets:delete(?TABLE, Key), {reply, case dets:sync(?TABLE) of ok -> ok; Error -> Error end, State};
        [] -> {reply, {error, token_not_found}, State}
    end;
handle_call({tokens, Actor}, _From, State) -> {reply, {ok, [token_public(Key, Value) || {Key, Value} <- token_entries(Actor)]}, State};
handle_call({token_count, Actor}, _From, State) -> {reply, length(token_keys(Actor)), State};
handle_call({create_key, Issuer, Actor, PublicKey}, _From, State) ->
    case {parse_public_key(PublicKey), dets:lookup(?TABLE, Actor), quota_available(Issuer, {key, create}, issued_key_count(Issuer))} of
        {{ok, Fingerprint, Encoded}, [_], ok} ->
            case dets:lookup(?TABLE, {key, Fingerprint}) of
                [] ->
                    Entry = #{actor => Actor, issued_by => Issuer, issued_at => erlang:system_time(second), public_key => Encoded},
                    {reply, case dets:insert(?TABLE, {{key, Fingerprint}, Entry}) of
                                ok -> case dets:sync(?TABLE) of ok -> {ok, Fingerprint}; Error -> Error end;
                                Error -> Error
                            end, State};
                _ -> {reply, {error, key_exists}, State}
            end;
        {{error, Reason}, _, _} -> {reply, {error, Reason}, State};
        {_, [], _} -> {reply, {error, actor_not_found}, State};
        {_, _, Error} -> {reply, Error, State}
    end;
handle_call({revoke_key, Actor, Fingerprint}, _From, State) ->
    case dets:lookup(?TABLE, {key, Fingerprint}) of
        [{{key, Fingerprint}, #{actor := Actor}}] ->
            {reply, case dets:delete(?TABLE, {key, Fingerprint}) of ok -> dets:sync(?TABLE); Error -> Error end, State};
        _ -> {reply, {error, key_not_found}, State}
    end;
handle_call({keys, Actor}, _From, State) ->
    {reply, {ok, [key_public(Fingerprint, Entry) || {Fingerprint, Entry} <- key_entries(Actor)]}, State};
handle_call({key_count, Actor}, _From, State) ->
    {reply, length(key_keys(Actor)), State};
handle_call({key, Fingerprint}, _From, State) ->
    case dets:lookup(?TABLE, {key, Fingerprint}) of
        [{{key, Fingerprint}, #{actor := Actor, public_key := PublicKey}}] -> {reply, {ok, Actor, PublicKey}, State};
        [] -> {reply, {error, key_not_found}, State}
    end;
handle_call({touch_key, Fingerprint}, _From, State) ->
    case dets:lookup(?TABLE, {key, Fingerprint}) of
        [{Key, Entry}] -> {reply, touch_key(Key, Entry), State};
        [] -> {reply, {error, key_not_found}, State}
    end;
handle_call({token_id, Token}, _From, State) ->
    Hash = token_hash(Token),
    case dets:lookup(?TABLE, {token, Hash}) of
        [{{token, Hash}, Value}] -> {reply, token_id({token, Hash}, Value), State};
        [] -> {reply, undefined, State}
    end;
handle_call({token_roles, Token, Actor}, _From, State) ->
    BootstrapRoles = case authenticate_token(Token) of {ok, Claims} when is_map(Claims) -> maps:get(roles, Claims, []); _ -> [] end,
    {reply, lists:usort(BootstrapRoles ++ maps:get(roles, actor(Actor), [])), State};
handle_call({can_manage_actor, Principal, Actor}, _From, State) ->
    {reply, Principal =:= Actor orelse maps:get(created_by, actor(Actor), undefined) =:= Principal, State};
handle_call({children, Parent}, _From, State) ->
    {reply, child_actors(Parent), State};
handle_call(actors, _From, State) ->
    {reply, all_actors(), State};
handle_call({actor_page, Limit, Cursor}, _From, State) -> {reply, page_actors(undefined, Limit, Cursor), State};
handle_call({child_page, Parent, Limit, Cursor}, _From, State) -> {reply, page_actors(Parent, Limit, Cursor), State};
handle_call({grant_permissions, Actor, Permissions}, _From, State) -> {reply, update_actor(Actor, fun(Current) -> Current#{permissions => lists:usort(maps:get(permissions, Current) ++ Permissions)} end), State};
handle_call({revoke_permissions, Actor, Permissions}, _From, State) -> {reply, update_actor(Actor, fun(Current) -> Current#{permissions => maps:get(permissions, Current) -- Permissions} end), State};
handle_call({grant_role, Actor, Role}, _From, State) ->
    case role_value(Role) of {ok, _} -> {reply, update_actor(Actor, fun(Current) -> Current#{roles => lists:usort([Role | maps:get(roles, Current)])} end), State}; Error -> {reply, Error, State} end;
handle_call({revoke_role, Actor, Role}, _From, State) -> {reply, update_actor(Actor, fun(Current) -> Current#{roles => lists:delete(Role, maps:get(roles, Current))} end), State};
handle_call({set_quota, Actor, Permission, Limit}, _From, State) ->
    {reply, update_actor(Actor, fun(Current) ->
        Current#{quotas => (maps:get(quotas, Current, #{}))#{Permission => Limit}}
    end), State};
handle_call({revoke_quota, Actor, Permission}, _From, State) ->
    {reply, update_actor(Actor, fun(Current) ->
        Current#{quotas => maps:remove(Permission, maps:get(quotas, Current, #{}))}
    end), State};
handle_call({quotas, Actor}, _From, State) ->
    case dets:lookup(?TABLE, Actor) of
        [] -> {reply, {error, actor_not_found}, State};
        _ -> {reply, {ok, maps:to_list(maps:get(quotas, actor(Actor), #{}))}, State}
    end;
handle_call({quota_limit, Actor, Permission}, _From, State) ->
    {reply, maps:get(Permission, maps:get(quotas, actor(Actor), #{}), unlimited), State};
handle_call({check_quota, Actor, Permission, Used}, _From, State) ->
    {reply, quota_available(Actor, Permission, Used), State};
handle_call({create_role, Name, Permissions}, _From, State) ->
    case maps:is_key(Name, all_roles()) of
        true -> {reply, {error, role_exists}, State};
        false -> {reply, save_role(Name, Permissions), State}
    end;
handle_call({update_role, Name, Permissions}, _From, State) ->
    case dets:lookup(?TABLE, {role, Name}) of
        [] -> {reply, {error, role_not_found}, State};
        _ -> {reply, save_role(Name, Permissions), State}
    end;
handle_call({delete_role, Name}, _From, State) ->
    case dets:lookup(?TABLE, {role, Name}) of
        [] -> {reply, {error, role_not_found}, State};
        _ -> {reply, case dets:delete(?TABLE, {role, Name}) of ok -> dets:sync(?TABLE); Error -> Error end, State}
    end;
handle_call({role, Name}, _From, State) -> {reply, role_value(Name), State};
handle_call({role_name, Name}, _From, State) ->
    Matches = [Role || Role <- maps:keys(all_roles()), string:uppercase(role_name_string(Role)) =:= string:uppercase(Name)],
    case Matches of [Role] -> {reply, {ok, Role}, State}; _ -> {reply, {error, role_not_found}, State} end;
handle_call(roles, _From, State) -> {reply, all_roles(), State};
handle_call(_, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_, State) -> {noreply, State}.
handle_info(_, State) -> {noreply, State}.
terminate(_, _) -> dets:close(?TABLE).
code_change(_, State, _) -> {ok, State}.

actor_permissions(Actor, TokenPermissions) ->
    actor_permissions(Actor, TokenPermissions, []).
actor_permissions(Actor, TokenPermissions, BootstrapRoles) ->
    #{permissions := Granted, roles := Roles} = actor(Actor),
    RolePermissions = lists:append([Permissions || Role <- lists:usort(Roles ++ BootstrapRoles), {ok, Permissions} <- [role_value(Role)]]),
    expand_permissions(default_permissions() ++ normalize_permissions(TokenPermissions) ++ Granted ++ RolePermissions).
actor(Actor) ->
    case dets:lookup(?TABLE, Actor) of
        [{Actor, Value}] ->
            CreatedAt = maps:get(created_at, Value, erlang:system_time(second)),
            maps:merge(#{permissions => normalize_permissions(maps:get(permissions, Value, maps:get(scopes, Value, []))),
                         roles => maps:get(roles, Value, []), quotas => maps:get(quotas, Value, #{}),
                         subscription => bibleit_plan:normalize_subscription(maps:get(subscription, Value, undefined), CreatedAt)},
                       maps:with([created_by, created_at, display_name, handle], Value));
        [] -> #{permissions => [], roles => [], quotas => #{}, subscription => bibleit_plan:new_subscription(erlang:system_time(second))}
    end.
update_actor(Actor, Fun) ->
    case dets:lookup(?TABLE, Actor) of
        [] ->
            case is_bootstrap_actor(Actor) of
                true ->
                    CreatedAt = erlang:system_time(second),
                    save(Actor, Fun(#{permissions => [], roles => [], quotas => #{},
                                      subscription => bibleit_plan:new_subscription(CreatedAt), created_at => CreatedAt}));
                false -> {error, actor_not_found}
            end;
        _ -> save(Actor, Fun(actor(Actor)))
    end.
save(Actor, Value) -> case dets:insert(?TABLE, {Actor, Value}) of ok -> dets:sync(?TABLE); Error -> Error end.
save_role(Name, Permissions) -> case dets:insert(?TABLE, {{role, Name}, normalize_permissions(Permissions)}) of ok -> dets:sync(?TABLE); Error -> Error end.
role_value(Name) -> case maps:find(Name, all_roles()) of {ok, Values} -> {ok, Values}; error -> {error, role_not_found} end.
all_roles() -> maps:merge(configured_roles(), dynamic_roles()).
dynamic_roles() -> dets:foldl(fun({{role, Name}, Permissions}, Acc) -> Acc#{Name => normalize_permissions(Permissions)}; (_, Acc) -> Acc end, #{}, ?TABLE).
configured_roles() ->
    Base = default_permissions(),
    Defaults = #{default => Base,
                 member => Base ++ [{translation, search}, {live, get}, {live, list}, {live, subscribe}, {live, create}, {live, update}, {live, delete}, {token, create}, {token, delete}, {key, get}, {key, create}, {key, delete}],
                 presenter => Base ++ [{live, get}, {live, list}, {live, subscribe}, {live, update}],
                 live_operator => Base ++ [{live, get}, {live, list}, {live, subscribe}, {live, create}, {live, update}, {live, delete}],
                 translation_manager => Base ++ [{translation, get}, {translation, list}, {translation, create}, {translation, delete}],
                 identity_manager => Base ++ [{actor, create}, {actor, get}, {actor, list}, {actor, update}, {token, create}, {token, delete}, {key, create}, {key, delete}],
                 authorization_manager => Base ++ [{authorization, get}, {authorization, list}, {authorization, create}, {authorization, delete}, {actor, create}, {actor, get}, {actor, list}, {actor, update}, {actor, delete}, {token, create}, {token, delete}, {key, create}, {key, delete}, {quota, get}, {quota, update}]},
    Configured = (application:get_env(bibleit_server, roles, Defaults))#{default => Base},
    WithAdmin = Configured#{server_admin => lists:usort(permissions() ++ lists:append(maps:values(Configured)))},
    maps:map(fun(_Role, Values) -> normalize_permissions(Values) end, WithAdmin).
permissions() -> [{server, get}, {help, get},
                  {live, get}, {live, list}, {live, subscribe}, {live, create}, {live, update}, {live, delete},
                  {translation, get}, {translation, list}, {translation, read}, {translation, search}, {translation, create}, {translation, delete},
                  {authorization, get}, {authorization, list}, {authorization, create}, {authorization, delete},
                  {actor, create}, {actor, get}, {actor, list}, {actor, update}, {actor, delete},
                  {role, get}, {role, list}, {role, create}, {role, update}, {role, delete}, {role, bind},
                  {token, get}, {token, create}, {token, delete},
                  {key, get}, {key, create}, {key, delete},
                  {quota, get}, {quota, update}].
%% Every account begins with this baseline. It is applied only after the
%% transport has authenticated an actor; anonymous protocol states receive no
%% permissions.
default_permissions() -> [{server, get}, {help, get}, {token, get},
                          {translation, get}, {translation, list}, {translation, read}].
normalize_permissions(Permissions) -> lists:usort(lists:append([normalize_permission(Value) || Value <- Permissions])).
normalize_permission({Resource, Verb}) when is_atom(Resource), is_atom(Verb) ->
    case {Verb, lists:member({Resource, Verb}, permissions()), resource_exists(Resource)} of
        {all, _, true} -> [{Resource, all}];
        {_, true, _} -> [{Resource, Verb}];
        _ -> []
    end;
normalize_permission(live_create) -> [{live, create}];
normalize_permission(translations_manage) -> [{translation, create}, {translation, delete}];
normalize_permission(authorization_manage) -> [{authorization, create}, {authorization, delete}];
normalize_permission(_) -> [].
expand_permissions(Permissions) ->
    lists:usort(lists:append([expand_permission(Permission) || Permission <- Permissions])).
expand_permission({Resource, all}) -> [Permission || Permission = {ResourceName, _Verb} <- permissions(), ResourceName =:= Resource];
expand_permission(Permission) -> [Permission].
resource_exists(Resource) -> lists:any(fun({Name, _Verb}) -> Name =:= Resource end, permissions()).
all_actors() ->
    lists:sort(dets:foldl(fun({Actor, Value}, Acc) when is_binary(Actor), is_map(Value) ->
        [maps:merge(#{actor => Actor, created_by => maps:get(created_by, Value, undefined)}, maps:with([created_at, display_name, handle], Value)) | Acc]; (_, Acc) -> Acc end, [], ?TABLE)).
child_actors(Parent) -> [Info || Info = #{created_by := ParentName} <- all_actors(), ParentName =:= Parent].
page_actors(Parent, Limit, Cursor) ->
    Start = case Cursor of undefined -> dets:first(?TABLE); _ -> dets:next(?TABLE, Cursor) end,
    page_actors(Start, Parent, Limit, []).
page_actors('$end_of_table', _Parent, _Limit, Acc) -> {lists:reverse(Acc), undefined};
page_actors(Key, Parent, Limit, Acc) ->
    Next = dets:next(?TABLE, Key),
    case dets:lookup(?TABLE, Key) of
        [{Actor, Value}] when is_binary(Actor), is_map(Value) ->
            case Parent =:= undefined orelse maps:get(created_by, Value, undefined) =:= Parent of
                true -> Info = maps:merge(#{actor => Actor, created_by => maps:get(created_by, Value, undefined)}, maps:with([created_at, display_name, handle], Value)), case length(Acc) + 1 >= Limit of true -> {lists:reverse([Info | Acc]), next_actor(Next, Parent)}; false -> page_actors(Next, Parent, Limit, [Info | Acc]) end;
                false -> page_actors(Next, Parent, Limit, Acc)
            end;
        _ -> page_actors(Next, Parent, Limit, Acc)
    end.
next_actor('$end_of_table', _Parent) -> undefined;
next_actor(Key, Parent) ->
    case dets:lookup(?TABLE, Key) of
        [{Actor, Value}] when is_binary(Actor), is_map(Value) -> case Parent =:= undefined orelse maps:get(created_by, Value, undefined) =:= Parent of true -> Actor; false -> next_actor(dets:next(?TABLE, Key), Parent) end;
        _ -> next_actor(dets:next(?TABLE, Key), Parent)
    end.
authenticate_token(Token) -> maps:find(Token, bootstrap_tokens()).
authenticate_issued(Token, State) ->
    Hash = token_hash(Token),
    case dets:lookup(?TABLE, {token, Hash}) of
        [{Key, #{actor := Actor} = Entry}] ->
            case touch_token(Key, Entry) of
                ok -> {reply, {ok, Actor, actor_permissions(Actor, [])}, State};
                Error -> {reply, Error, State}
            end;
        [] -> {reply, {error, unauthorized}, State}
    end.
token_hash(Token) -> crypto:hash(sha256, Token).
base62_token() -> base62_pad(base62_digits(binary:decode_unsigned(crypto:strong_rand_bytes(32)), [])).
base62_digits(0, []) -> <<"0">>;
base62_digits(0, Digits) -> list_to_binary(Digits);
base62_digits(Number, Digits) ->
    Alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    Digit = lists:nth((Number rem 62) + 1, Alphabet),
    base62_digits(Number div 62, [Digit | Digits]).
base62_pad(Digits) ->
    Padding = 43 - byte_size(Digits),
    case Padding > 0 of true -> <<(binary:copy(<<"0">>, Padding))/binary, Digits/binary>>; false -> Digits end.
token_keys(Actor) ->
    dets:foldl(fun({{token, _Hash} = Key, #{actor := TokenActor}}, Acc) when TokenActor =:= Actor -> [Key | Acc]; (_, Acc) -> Acc end, [], ?TABLE).
token_entries(Actor) -> dets:foldl(fun({{token, _Hash} = Key, #{actor := TokenActor} = Value}, Acc) when TokenActor =:= Actor -> [{Key, Value} | Acc]; (_, Acc) -> Acc end, [], ?TABLE).
token_id({token, Hash}, Value) -> maps:get(id, Value, binary:part(binary:encode_hex(Hash), 0, 16)).
token_public(Key, Value) ->
    (maps:with([issued_at, issued_by, label, source, last_used_at], Value))#{id => token_id(Key, Value)}.
token_entry(Id, Actor, IssuedBy, Source, Label) ->
    Base = #{id => Id, actor => Actor, issued_at => erlang:system_time(second), issued_by => IssuedBy, source => Source},
    case Label of undefined -> Base; <<>> -> Base; _ -> Base#{label => Label} end.
valid_label(undefined) -> true;
valid_label(Label) when is_binary(Label) -> byte_size(Label) > 0 andalso byte_size(Label) =< 128;
valid_label(_) -> false.
valid_display_name(Name) when is_binary(Name) -> byte_size(Name) > 0 andalso byte_size(Name) =< 160;
valid_display_name(_) -> false.
valid_handle(Handle) when is_binary(Handle) -> byte_size(Handle) > 0 andalso byte_size(Handle) =< 128;
valid_handle(_) -> false.
touch_token(Key, Entry) ->
    case dets:insert(?TABLE, {Key, Entry#{last_used_at => erlang:system_time(second)}}) of
        ok -> dets:sync(?TABLE);
        Error -> Error
    end.
key_keys(Actor) -> [Key || {Key, _} <- key_entries(Actor)].
key_entries(Actor) ->
    dets:foldl(fun({{key, Fingerprint}, #{actor := KeyActor} = Entry}, Acc) when KeyActor =:= Actor ->
                       [{Fingerprint, Entry} | Acc];
                  (_, Acc) -> Acc
               end, [], ?TABLE).
key_public(Fingerprint, Entry) -> (maps:with([issued_at, issued_by, last_used_at], Entry))#{fingerprint => Fingerprint, algorithm => <<"ssh-ed25519">>}.
touch_key(Key, Entry) ->
    case dets:insert(?TABLE, {Key, Entry#{last_used_at => erlang:system_time(second)}}) of
        ok -> dets:sync(?TABLE);
        Error -> Error
    end.
parse_public_key(PublicKey) when is_binary(PublicKey) ->
    try ssh_file:decode(PublicKey, public_key) of
        [{{{'ECPoint', Encoded}, {namedCurve, {1, 3, 101, 112}}}, _}] when byte_size(Encoded) =:= 32 ->
            {ok, key_fingerprint(Encoded), Encoded};
        _ -> {error, invalid_public_key}
    catch
        _:_ -> {error, invalid_public_key}
    end;
parse_public_key(_) -> {error, invalid_public_key}.
%% OpenSSH fingerprints hash the SSH wire-format public-key blob, not only
%% the curve point. This intentionally matches `ssh-keygen -lf -E sha256`.
key_fingerprint(Encoded) ->
    Blob = <<11:32/big, "ssh-ed25519", 32:32/big, Encoded/binary>>,
    <<"SHA256:", (strip_base64_padding(base64:encode(crypto:hash(sha256, Blob))))/binary>>.
strip_base64_padding(Value) -> binary:replace(Value, <<"=">>, <<>>, [global]).
created_actor_count(Issuer) ->
    dets:foldl(fun({Actor, #{created_by := Creator}}, Count) when is_binary(Actor), Creator =:= Issuer -> Count + 1; (_, Count) -> Count end, 0, ?TABLE).
issued_token_count(Issuer) ->
    dets:foldl(fun({{token, _Hash}, #{issued_by := Creator}}, Count) when Creator =:= Issuer -> Count + 1; (_, Count) -> Count end, 0, ?TABLE).
issued_key_count(Issuer) ->
    dets:foldl(fun({{key, _Fingerprint}, #{issued_by := Creator}}, Count) when Creator =:= Issuer -> Count + 1; (_, Count) -> Count end, 0, ?TABLE).
member_quotas() -> bibleit_plan:limits(free).
quota_available(Actor, Permission, Used) ->
    case maps:find(Permission, maps:get(quotas, actor(Actor), #{})) of
        error -> ok;
        {ok, Limit} when Used < Limit -> ok;
        {ok, _Limit} -> {error, quota_exceeded}
    end.
bootstrap_tokens() -> application:get_env(bibleit_server, tokens, #{}).
bootstrap_keys() -> application:get_env(bibleit_server, bootstrap_keys, #{}).
seed_bootstrap_keys() ->
    case lists:foldl(fun({PublicKey, Claims}, ok) -> seed_bootstrap_key(PublicKey, Claims); (_Entry, Error) -> Error end,
                     ok, maps:to_list(bootstrap_keys())) of
        ok -> dets:sync(?TABLE);
        Error -> Error
    end.
seed_bootstrap_key(PublicKey, Claims) ->
    case {parse_public_key(iolist_to_binary(PublicKey)), bootstrap_claim_actor(Claims)} of
        {{ok, Fingerprint, Encoded}, Actor} when is_binary(Actor) ->
            seed_bootstrap_actor(Actor, Claims),
            case dets:lookup(?TABLE, {key, Fingerprint}) of
                [] -> dets:insert(?TABLE, {{key, Fingerprint}, #{actor => Actor, issued_by => bootstrap, issued_at => erlang:system_time(second), public_key => Encoded}});
                _ -> ok
            end;
        {{error, Reason}, _} -> {error, Reason};
        _ -> {error, invalid_bootstrap_claim}
    end.
seed_bootstrap_actor(Actor, Claims) ->
    case dets:lookup(?TABLE, Actor) of
        [] ->
            CreatedAt = erlang:system_time(second),
            save(Actor, #{permissions => maps:get(permissions, Claims, []), roles => maps:get(roles, Claims, []), quotas => #{},
                          subscription => bibleit_plan:new_subscription(CreatedAt),
                          created_by => bootstrap, created_at => CreatedAt});
        _ -> ok
    end.
migrate_subscriptions() ->
    Result = dets:foldl(
      fun({Actor, Value}, ok) when is_binary(Actor), is_map(Value) ->
              case maps:is_key(subscription, Value) of
                  true -> ok;
                  false ->
                      CreatedAt = maps:get(created_at, Value, erlang:system_time(second)),
                      dets:insert(?TABLE, {Actor, Value#{subscription => bibleit_plan:new_subscription(CreatedAt)}})
              end;
         (_, ok) -> ok;
         (_, Error) -> Error
      end, ok, ?TABLE),
    case Result of
        ok -> dets:sync(?TABLE);
        Error -> {error, Error}
    end.
is_bootstrap_actor(Actor) ->
    lists:any(fun({_Token, Claim}) -> bootstrap_claim_actor(Claim) =:= Actor end,
              maps:to_list(bootstrap_tokens())) orelse
    lists:any(fun({_Key, Claim}) -> bootstrap_claim_actor(Claim) =:= Actor end,
              maps:to_list(bootstrap_keys())).
bootstrap_claim_actor(Actor) when is_binary(Actor) -> Actor;
bootstrap_claim_actor(#{actor := Actor}) -> Actor;
bootstrap_claim_actor(_) -> undefined.
role_name_string(Role) when is_atom(Role) -> atom_to_list(Role);
role_name_string(Role) when is_binary(Role) -> binary_to_list(Role).
path() -> case application:get_env(bibleit_server, authorization_path) of {ok, Value} when is_list(Value) -> Value; {ok, Value} when is_binary(Value) -> binary_to_list(Value); undefined -> filename:join(os:getenv("HOME"), ".bibleit/authorization.dets") end.
