-module(bibleit_account).

%% Account-facing application API shared by the browser dashboard and protocol
%% adapters. It deliberately models resources owned by one account, never an
%% arbitrary actor selected by a client.

-export([summary/1, quotas/1, tokens/1, create_token/2, revoke_tokens/2,
         keys/1, add_key/2, revoke_key/2]).

summary(Actor) ->
    case {bibleit_authorization:actor_display_name(Actor), bibleit_authorization:actor_info(Actor)} of
        {{ok, DisplayName}, {ok, ActorInfo}} ->
            Subscription = maps:get(subscription, ActorInfo),
            Plan = bibleit_plan:plan(maps:get(plan, Subscription)),
            {ok, #{actor => Actor, display_name => DisplayName,
                   lives => bibleit_live_registry:count_owned(Actor),
                   tokens => bibleit_authorization:token_count(Actor),
                   keys => bibleit_authorization:key_count(Actor),
                   subscription => Subscription, plan => Plan}};
        {{error, _} = Error, _} -> Error;
        {_, {error, _} = Error} -> Error
    end.

quotas(Actor) ->
    case bibleit_authorization:quotas(Actor) of
        {ok, Limits} -> {ok, [{Permission, Limit, usage(Actor, Permission)} || {Permission, Limit} <- Limits]};
        {error, _} = Error -> Error
    end.

tokens(Actor) -> bibleit_authorization:tokens(Actor).
create_token(Actor, Label) -> bibleit_authorization:create_token(Actor, Actor, Label).
revoke_tokens(Actor, all) -> bibleit_authorization:revoke_tokens(Actor);
revoke_tokens(Actor, Id) -> bibleit_authorization:revoke_token(Actor, Id).

keys(Actor) -> bibleit_authorization:keys(Actor).
add_key(Actor, PublicKey) -> bibleit_authorization:create_key(Actor, Actor, PublicKey).
revoke_key(Actor, Fingerprint) -> bibleit_authorization:revoke_key(Actor, Fingerprint).

usage(Actor, {live, create}) -> bibleit_live_registry:count_owned(Actor);
usage(Actor, {token, create}) -> bibleit_authorization:token_count(Actor);
usage(Actor, {key, create}) -> bibleit_authorization:key_count(Actor);
usage(_Actor, _Permission) -> 0.
