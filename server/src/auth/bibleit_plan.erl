-module(bibleit_plan).

%% Plans are product definitions. An account stores only its subscription
%% state; the plan supplies the stable limits and feature catalogue.

-export([free/0, plan/1, limits/1, new_subscription/1, normalize_subscription/2]).

free() -> plan(free).

plan(free) ->
    #{id => free,
      name => <<"Free">>,
      price => #{amount => 0, currency => <<"USD">>},
      limits => #{{live, create} => 3, {token, create} => 5, {key, create} => 5},
      features => [<<"SSH access">>, <<"Live presentations">>, <<"Translation search">>]};
plan(_) -> free().

limits(Plan) -> maps:get(limits, plan(Plan)).

new_subscription(StartedAt) when is_integer(StartedAt) ->
    #{plan => free, status => active, started_at => StartedAt,
      trial_ends_at => undefined, billing_cycle => none}.

normalize_subscription(Subscription, CreatedAt) when is_map(Subscription), is_integer(CreatedAt) ->
    Plan = maps:get(plan, Subscription, free),
    #{plan => maps:get(id, plan(Plan)),
      status => maps:get(status, Subscription, active),
      started_at => maps:get(started_at, Subscription, CreatedAt),
      trial_ends_at => maps:get(trial_ends_at, Subscription, undefined),
      billing_cycle => maps:get(billing_cycle, Subscription, none)};
normalize_subscription(_, CreatedAt) -> new_subscription(CreatedAt).
