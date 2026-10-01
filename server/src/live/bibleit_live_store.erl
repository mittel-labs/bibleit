-module(bibleit_live_store).
-behaviour(gen_server).
-export([start_link/0, list/0, get/1, save/1, delete/1]).
-export([init/1, handle_call/3, handle_cast/2, handle_info/2, terminate/2, code_change/3]).

-define(TABLE, bibleit_live_store_table).

start_link() -> gen_server:start_link({local, ?MODULE}, ?MODULE, [], []).
list() -> gen_server:call(?MODULE, list).
get(Id) -> gen_server:call(?MODULE, {get, Id}).
save(#{id := Id} = Live) -> gen_server:call(?MODULE, {save, Id, Live}).
delete(Id) -> gen_server:call(?MODULE, {delete, Id}).

init([]) ->
    Path = store_path(),
    case filelib:ensure_dir(Path) of
        ok ->
            case dets:open_file(?TABLE, [{file, Path}, {type, set}]) of
                {ok, ?TABLE} -> {ok, #{path => Path}};
                {error, Reason} -> {stop, {store_open_failed, Reason}}
            end;
        {error, Reason} -> {stop, {store_directory_unavailable, Path, Reason}}
    end.
handle_call(list, _From, State) ->
    Lives = dets:foldl(fun({_Id, Live}, Acc) -> [Live | Acc] end, [], ?TABLE),
    {reply, {ok, Lives}, State};
handle_call({get, Id}, _From, State) ->
    case dets:lookup(?TABLE, Id) of [{Id, Live}] -> {reply, {ok, Live}, State}; [] -> {reply, not_found, State} end;
handle_call({save, Id, Live}, _From, State) ->
    case dets:insert(?TABLE, {Id, Live}) of
        ok -> {reply, dets:sync(?TABLE), State};
        {error, Reason} -> {reply, {error, Reason}, State}
    end;
handle_call({delete, Id}, _From, State) ->
    case dets:delete(?TABLE, Id) of
        ok -> {reply, dets:sync(?TABLE), State};
        {error, Reason} -> {reply, {error, Reason}, State}
    end;
handle_call(_, _From, State) -> {reply, {error, bad_request}, State}.
handle_cast(_, State) -> {noreply, State}.
handle_info(_, State) -> {noreply, State}.
terminate(_, _) -> dets:close(?TABLE).
code_change(_, State, _) -> {ok, State}.

store_path() ->
    case application:get_env(bibleit_server, lives_path) of
        {ok, Path} when is_binary(Path) -> binary_to_list(Path);
        {ok, Path} when is_list(Path) -> Path;
        undefined ->
            case os:getenv("HOME") of
                false -> "bibleit-lives.dets";
                Home -> filename:join([Home, ".bibleit", "lives.dets"])
            end
    end.
