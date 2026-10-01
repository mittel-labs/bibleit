-module(bibleit_live_session_sup).
-behaviour(supervisor).
-export([start_link/0, start_child/3, init/1]).

start_link() -> supervisor:start_link({local, ?MODULE}, ?MODULE, []).
start_child(Id, Owner, Options) -> supervisor:start_child(?MODULE, [Id, Owner, Options]).

init([]) ->
    Child = #{id => bibleit_live_session,
              start => {bibleit_live_session, start_link, []},
              restart => temporary, shutdown => 5000,
              type => worker, modules => [bibleit_live_session]},
    {ok, {{simple_one_for_one, 10, 10}, [Child]}}.
