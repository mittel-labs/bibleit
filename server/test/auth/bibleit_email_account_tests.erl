-module(bibleit_email_account_tests).
-include_lib("eunit/include/eunit.hrl").

email_verification_creates_an_actor_and_allows_password_login_test_() ->
    {setup, fun setup/0, fun cleanup/1, fun verified_account_can_authenticate/1}.

password_reset_is_single_use_test_() ->
    {setup, fun setup/0, fun cleanup/1, fun password_reset_is_single_use/1}.

setup() ->
    Base = "/tmp/bibleit-email-account-" ++ integer_to_list(erlang:unique_integer([positive])),
    AuthorizationPath = Base ++ "-authorization.dets",
    AccountPath = Base ++ "-accounts.dets",
    application:set_env(bibleit_server, authorization_path, AuthorizationPath),
    application:set_env(bibleit_server, account_path, AccountPath),
    {ok, Authorization} = bibleit_authorization:start_link(),
    {ok, Accounts} = bibleit_email_account:start_link(),
    #{authorization_path => AuthorizationPath, account_path => AccountPath, authorization => Authorization, accounts => Accounts}.

cleanup(#{authorization_path := AuthorizationPath, account_path := AccountPath, authorization := Authorization, accounts := Accounts}) ->
    unlink(Accounts), exit(Accounts, shutdown),
    unlink(Authorization), exit(Authorization, shutdown),
    file:delete(AuthorizationPath),
    file:delete(AccountPath),
    application:unset_env(bibleit_server, authorization_path),
    application:unset_env(bibleit_server, account_path).

verified_account_can_authenticate(_Context) -> fun() ->
    Email = <<"felipe@example.test">>,
    Password = <<"a secure test password">>,
    Token = binary:encode_hex(crypto:strong_rand_bytes(32)),
    insert_pending_account(Email, Password, <<"Felipe">>, Token),
    {ok, Actor} = bibleit_email_account:verify(Token),
    ?assertMatch(<<"email-", _/binary>>, Actor),
    ?assertEqual({ok, Actor}, bibleit_email_account:authenticate(Email, Password)),
    ?assertEqual({error, invalid_credentials}, bibleit_email_account:authenticate(Email, <<"wrong password value">>)),
    ?assertEqual({ok, <<"Felipe">>}, bibleit_authorization:actor_display_name(Actor)),
    ?assertMatch({error, _}, bibleit_email_account:verify(Token))
end.

password_reset_is_single_use(_Context) -> fun() ->
    Email = <<"felipe@example.test">>,
    Password = <<"a secure test password">>,
    NewPassword = <<"another secure password">>,
    VerifyToken = binary:encode_hex(crypto:strong_rand_bytes(32)),
    insert_pending_account(Email, Password, <<"Felipe">>, VerifyToken),
    {ok, Actor} = bibleit_email_account:verify(VerifyToken),
    ResetToken = binary:encode_hex(crypto:strong_rand_bytes(32)),
    ok = dets:insert(bibleit_email_account_table, {{action, crypto:hash(sha256, ResetToken)}, #{type => reset_password, email => Email, expires_at => erlang:system_time(second) + 60}}),
    ok = dets:sync(bibleit_email_account_table),
    ok = bibleit_email_account:reset_password(ResetToken, NewPassword),
    ?assertEqual({error, invalid_credentials}, bibleit_email_account:authenticate(Email, Password)),
    ?assertEqual({ok, Actor}, bibleit_email_account:authenticate(Email, NewPassword)),
    ?assertMatch({error, _}, bibleit_email_account:reset_password(ResetToken, <<"a third secure password">>))
end.

insert_pending_account(Email, Password, DisplayName, Token) ->
    {ok, _Raw, PasswordHash} = jargon:hash(Password, crypto:strong_rand_bytes(16), argon2id, 2, 19456, 1, 32),
    Account = #{status => pending, email => Email, password_hash => PasswordHash, display_name => DisplayName, created_at => erlang:system_time(second)},
    Action = #{type => verify_email, email => Email, expires_at => erlang:system_time(second) + 60},
    ok = dets:insert(bibleit_email_account_table, [{{account, Email}, Account}, {{action, crypto:hash(sha256, Token)}, Action}]),
    ok = dets:sync(bibleit_email_account_table).
