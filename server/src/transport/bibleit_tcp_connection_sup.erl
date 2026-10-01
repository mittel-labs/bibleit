-module(bibleit_tcp_connection_sup).
-behaviour(supervisor).
-export([start_link/0, start_child/0, init/1]).

start_link() -> supervisor:start_link({local, ?MODULE}, ?MODULE, []).

start_child() ->
    Child = #{id => make_ref(),
              start => {bibleit_tcp_connection, start_link, []},
              restart => temporary,
              shutdown => 5000,
              type => worker,
              modules => [bibleit_tcp_connection]},
    supervisor:start_child(?MODULE, Child).

init([]) -> {ok, {{one_for_one, 5, 10}, []}}.
