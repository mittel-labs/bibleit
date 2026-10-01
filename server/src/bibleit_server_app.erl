-module(bibleit_server_app).
-behaviour(application).
-export([start/2, stop/1]).

start(_Type, _Args) ->
    ok = bibleit_server_boot:configure(),
    bibleit_server_sup:start_link().
stop(_State) -> ok.
