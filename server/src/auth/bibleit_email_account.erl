-module(bibleit_email_account).
-behaviour(gen_server).

-export([start_link/0, register/3, verify/1, authenticate/2, begin_password_reset/1, reset_password/2]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

-define(TABLE, bibleit_email_account_table).
-define(ACTION_TTL_SECONDS, 1800).

%% Email accounts are private identity records. Actors retain only a generated
%% ID and display name, so an actor list never exposes email addresses or
%% password material.

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
register(Email, Password, DisplayName) -> gen_server:call(?MODULE, {register, Email, Password, DisplayName}, 30000).
verify(Token) -> gen_server:call(?MODULE, {verify, Token}, 30000).
authenticate(Email, Password) -> gen_server:call(?MODULE, {authenticate, Email, Password}, 30000).
begin_password_reset(Email) -> gen_server:call(?MODULE, {begin_password_reset, Email}, 30000).
reset_password(Token, Password) -> gen_server:call(?MODULE, {reset_password, Token, Password}, 30000).

init([]) ->
    Path = application:get_env(bibleit_server, account_path, filename:absname("accounts.dets")),
    case filelib:ensure_dir(Path) of
        ok ->
            case dets:open_file(?TABLE, [{file, Path}, {type, set}]) of
                {ok, ?TABLE} ->
                    purge_expired_actions(),
                    case password_hash(<<"bibleit-dummy-password">>) of
                        {ok, DummyPasswordHash} -> {ok, #{dummy_password_hash => DummyPasswordHash}};
                        {error, Reason} -> {stop, {password_hasher_unavailable, Reason}}
                    end;
                {error, Reason} -> {stop, {account_open_failed, Reason}}
            end;
        {error, Reason} -> {stop, {account_directory_unavailable, Path, Reason}}
    end.

handle_call({register, Email0, Password, DisplayName}, _From, State) ->
    purge_expired_actions(),
    case {bibleit_resend_mailer:configured(), normalize_email(Email0), valid_password(Password), valid_display_name(DisplayName)} of
        {false, _, _, _} -> {reply, {error, email_not_configured}, State};
        {true, {error, _}, _, _} -> {reply, {error, invalid_email}, State};
        {true, _, false, _} -> {reply, {error, invalid_password}, State};
        {true, _, _, false} -> {reply, {error, invalid_display_name}, State};
        {true, {ok, Email}, true, true} ->
            case dets:lookup(?TABLE, {account, Email}) of
                [{{account, Email}, #{status := active}}] -> {reply, ok, State};
                _ ->
                    case password_hash(Password) of
                        {ok, PasswordHash} ->
                            Account = #{status => pending, email => Email, password_hash => PasswordHash,
                                        display_name => DisplayName, created_at => erlang:system_time(second)},
                            {Token, Action} = action(verify_email, Email),
                            case save({account, Email}, Account) of
                                ok -> case replace_action(verify_email, Email, Token, Action) of
                                    ok -> {reply, bibleit_resend_mailer:send_verification(Email, Token), State};
                                    Error -> {reply, Error, State}
                                end;
                                Error -> {reply, Error, State}
                            end;
                        Error -> {reply, Error, State}
                    end
            end
    end;
handle_call({verify, Token}, _From, State) ->
    purge_expired_actions(),
    {reply, verify_email(Token), State};
handle_call({authenticate, Email0, Password}, _From, #{dummy_password_hash := DummyPasswordHash} = State) ->
    purge_expired_actions(),
    Reply = case normalize_email(Email0) of
        {ok, Email} -> case dets:lookup(?TABLE, {account, Email}) of
            [{{account, Email}, #{status := active, password_hash := PasswordHash, actor := Actor}}] ->
                case password_matches(Password, PasswordHash) of true -> {ok, Actor}; false -> {error, invalid_credentials} end;
            _ -> password_matches(Password, DummyPasswordHash), {error, invalid_credentials}
        end;
        _ -> password_matches(Password, DummyPasswordHash), {error, invalid_credentials}
    end,
    {reply, Reply, State};
handle_call({begin_password_reset, Email0}, _From, State) ->
    purge_expired_actions(),
    Reply = case {bibleit_resend_mailer:configured(), normalize_email(Email0)} of
        {false, _} -> {error, email_not_configured};
        {true, {ok, Email}} -> case dets:lookup(?TABLE, {account, Email}) of
            [{{account, Email}, #{status := active}}] ->
                {Token, Action} = action(reset_password, Email),
                case replace_action(reset_password, Email, Token, Action) of
                    ok -> bibleit_resend_mailer:send_password_reset(Email, Token);
                    Error -> Error
                end;
            _ -> ok
        end;
        _ -> ok
    end,
    {reply, Reply, State};
handle_call({reset_password, Token, Password}, _From, State) ->
    purge_expired_actions(),
    Reply = case valid_password(Password) of
        false -> {error, invalid_password};
        true -> reset_account_password(Token, Password)
    end,
    {reply, Reply, State};
handle_call(_Request, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_Message, State) -> {noreply, State}.
handle_info(_Message, State) -> {noreply, State}.
terminate(_, _) -> dets:close(?TABLE).
code_change(_, State, _) -> {ok, State}.

verify_email(Token) ->
    with_action(Token, verify_email, fun(Email) ->
        case dets:lookup(?TABLE, {account, Email}) of
            [{{account, Email}, #{status := pending, display_name := DisplayName} = Account}] ->
                Actor = maps:get(actor, Account, new_actor_id()),
                case bibleit_authorization:ensure_member_actor(<<"email">>, Actor) of
                    ok -> activate_account(Email, Account, Actor, DisplayName, Token);
                    {error, actor_exists} -> activate_account(Email, Account, Actor, DisplayName, Token);
                    Error -> Error
                end;
            _ -> {error, invalid_or_expired_verification}
        end
    end).

activate_account(Email, Account, Actor, DisplayName, Token) ->
    case bibleit_authorization:set_actor_display_name(Actor, DisplayName) of
        ok ->
            Active = Account#{status => active, actor => Actor, verified_at => erlang:system_time(second)},
            case save({account, Email}, Active) of
                ok -> delete_action(Token), {ok, Actor};
                Error -> Error
            end;
        Error -> Error
    end.

reset_account_password(Token, Password) ->
    with_action(Token, reset_password, fun(Email) ->
        case {dets:lookup(?TABLE, {account, Email}), password_hash(Password)} of
            {[{{account, Email}, #{status := active} = Account}], {ok, PasswordHash}} ->
                case save({account, Email}, Account#{password_hash => PasswordHash, password_updated_at => erlang:system_time(second)}) of
                    ok ->
                        bibleit_http_session:logout_actor(maps:get(actor, Account)),
                        delete_action(Token),
                        ok;
                    Error -> Error
                end;
            {[], _} -> {error, invalid_or_expired_reset};
            {_, Error} -> Error
        end
    end).

with_action(Token, Type, Fun) when is_binary(Token), byte_size(Token) >= 32 ->
    case dets:lookup(?TABLE, {action, token_hash(Token)}) of
        [{{action, _}, #{type := Type, email := Email, expires_at := ExpiresAt}}] ->
            case ExpiresAt > erlang:system_time(second) of true -> Fun(Email); false -> {error, invalid_or_expired_action} end;
        _ -> {error, invalid_or_expired_action}
    end;
with_action(_, _, _) -> {error, invalid_or_expired_action}.

action(Type, Email) ->
    Token = binary:encode_hex(crypto:strong_rand_bytes(32)),
    {Token, #{type => Type, email => Email, expires_at => erlang:system_time(second) + ?ACTION_TTL_SECONDS}}.
replace_action(Type, Email, Token, Action) ->
    Keys = dets:foldl(fun({{action, _} = Key, #{type := EntryType, email := EntryEmail}}, Acc) when EntryType =:= Type, EntryEmail =:= Email -> [Key | Acc]; (_, Acc) -> Acc end, [], ?TABLE),
    lists:foreach(fun(Key) -> dets:delete(?TABLE, Key) end, Keys),
    save({action, token_hash(Token)}, Action).
purge_expired_actions() ->
    Now = erlang:system_time(second),
    Keys = dets:foldl(fun({{action, _} = Key, #{expires_at := ExpiresAt}}, Acc) when ExpiresAt =< Now -> [Key | Acc]; (_, Acc) -> Acc end, [], ?TABLE),
    lists:foreach(fun(Key) -> dets:delete(?TABLE, Key) end, Keys),
    case Keys of [] -> ok; _ -> dets:sync(?TABLE) end.
delete_action(Token) ->
    case dets:delete(?TABLE, {action, token_hash(Token)}) of ok -> dets:sync(?TABLE); Error -> Error end.
save(Key, Value) -> save_many([{Key, Value}]).
save_many(Entries) -> case dets:insert(?TABLE, Entries) of ok -> dets:sync(?TABLE); Error -> Error end.
token_hash(Token) -> crypto:hash(sha256, Token).

password_hash(Password) ->
    Salt = crypto:strong_rand_bytes(16),
    case jargon:hash(Password, Salt, argon2id, 2, 19456, 1, 32) of
        {ok, _RawHash, EncodedHash} -> {ok, EncodedHash};
        {error, _} = Error -> Error
    end.
password_matches(Password, EncodedHash) ->
    case jargon:verify(EncodedHash, Password) of {ok, true} -> true; _ -> false end.

normalize_email(Email) when is_binary(Email), byte_size(Email) =< 254 ->
    Lower = unicode:characters_to_binary(string:lowercase(binary_to_list(Email))),
    case binary:split(Lower, <<"@">>, [global]) of
        [Local, Domain] when byte_size(Local) > 0, byte_size(Domain) > 2 ->
            case {binary:match(Local, <<" ">>), binary:match(Domain, <<".">>), binary:match(Domain, <<" ">>)} of
                {nomatch, {_, _}, nomatch} -> {ok, Lower};
                _ -> {error, invalid_email}
            end;
        _ -> {error, invalid_email}
    end;
normalize_email(_) -> {error, invalid_email}.
valid_password(Password) when is_binary(Password) -> byte_size(Password) >= 12 andalso byte_size(Password) =< 1024;
valid_password(_) -> false.
valid_display_name(Name) when is_binary(Name) -> byte_size(Name) > 0 andalso byte_size(Name) =< 160;
valid_display_name(_) -> false.
new_actor_id() -> <<"email-", (binary:encode_hex(crypto:strong_rand_bytes(16)))/binary>>.
