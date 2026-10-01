-module(bibleit_account_tests).
-include_lib("eunit/include/eunit.hrl").

%% This is the account ownership contract consumed by both the Cowboy
%% dashboard and protocol adapters (including the SSH TUI). Keeping it here
%% prevents either adapter from accidentally growing a different definition of
%% a member's resources or quota usage.

account_contract_test_() ->
    {setup, fun setup/0, fun cleanup/1, fun(_Context) -> fun() ->
        Actor = <<"member">>,
        ok = bibleit_authorization:ensure_member_actor(<<"email">>, Actor),
        ok = bibleit_authorization:set_actor_display_name(Actor, <<"Member name">>),

        {ok, Summary0} = bibleit_account:summary(Actor),
        ?assertEqual(<<"Member name">>, maps:get(display_name, Summary0)),
        ?assertEqual(0, maps:get(lives, Summary0)),
        ?assertEqual(0, maps:get(tokens, Summary0)),
        ?assertEqual(0, maps:get(keys, Summary0)),
        Subscription = maps:get(subscription, Summary0),
        ?assertEqual(free, maps:get(plan, Subscription)),
        ?assertEqual(active, maps:get(status, Subscription)),
        ?assertEqual(none, maps:get(billing_cycle, Subscription)),
        Plan = maps:get(plan, Summary0),
        ?assertEqual(<<"Free">>, maps:get(name, Plan)),
        ?assertEqual(0, maps:get(amount, maps:get(price, Plan))),
        ?assert(lists:member(<<"SSH access">>, maps:get(features, Plan))),

        {ok, TokenId, _Secret} = bibleit_account:create_token(Actor, <<"Terminal">>),
        {ok, [Token]} = bibleit_account:tokens(Actor),
        ?assertEqual(TokenId, maps:get(id, Token)),
        ok = bibleit_account:revoke_tokens(Actor, TokenId),

        {Public, _Private} = crypto:generate_key(eddsa, ed25519),
        {ok, Fingerprint} = bibleit_account:add_key(Actor, ssh_public_key(Public)),
        {ok, [Key]} = bibleit_account:keys(Actor),
        ?assertEqual(Fingerprint, maps:get(fingerprint, Key)),
        ok = bibleit_account:revoke_key(Actor, Fingerprint),

        {ok, Quotas} = bibleit_account:quotas(Actor),
        ?assert(lists:member({{live, create}, 3, 0}, Quotas)),
        ?assert(lists:member({{token, create}, 5, 0}, Quotas)),
        ?assert(lists:member({{key, create}, 5, 0}, Quotas)),
        {ok, Summary1} = bibleit_account:summary(Actor),
        ?assertEqual(0, maps:get(tokens, Summary1)),
        ?assertEqual(0, maps:get(keys, Summary1))
    end end}.

setup() ->
    Path = filename:join("/tmp", "bibleit-account-" ++ integer_to_list(erlang:unique_integer([positive])) ++ ".dets"),
    file:delete(Path),
    application:set_env(bibleit_server, authorization_path, Path),
    application:set_env(bibleit_server, tokens, #{}),
    {ok, Authorization} = bibleit_authorization:start_link(),
    {ok, Sessions} = bibleit_live_session_sup:start_link(),
    {ok, Registry} = bibleit_live_registry:start_link(),
    {Authorization, Sessions, Registry, Path}.

cleanup({Authorization, Sessions, Registry, Path}) ->
    unlink(Registry), exit(Registry, shutdown),
    unlink(Sessions), exit(Sessions, shutdown),
    unlink(Authorization), exit(Authorization, shutdown),
    file:delete(Path),
    application:unset_env(bibleit_server, authorization_path),
    application:unset_env(bibleit_server, tokens).

ssh_public_key(PublicKey) ->
    Blob = <<11:32/big, "ssh-ed25519", 32:32/big, PublicKey/binary>>,
    <<"ssh-ed25519 ", (base64:encode(Blob))/binary, " account-test@bibleit">>.
