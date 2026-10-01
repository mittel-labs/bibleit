-module(bibleit_server).
-export([start/0, stop/0]).

start() ->
    application:load(bibleit_server),
    application:ensure_all_started(bibleit_server).

stop() -> application:stop(bibleit_server).
