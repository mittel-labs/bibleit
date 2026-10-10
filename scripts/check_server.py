#!/usr/bin/env python3
"""Verify the current server source without modifying its checkout or loading .env."""
import argparse, datetime, hashlib, json, os, pathlib, shutil, subprocess, tempfile, time, uuid
root = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--server', type=pathlib.Path, default=root.parent/'bibleit-server')
parser.add_argument('--integration', action='store_true', help='run server authentication/security tests with a unique disposable Docker database')
parser.add_argument('--baseline', type=pathlib.Path, help='save verified snapshot fingerprints after all requested checks pass')
args = parser.parse_args()
server = args.server.resolve()
def run(command, **kw):
    return subprocess.run(command, check=True, text=True, **kw)
with tempfile.TemporaryDirectory(prefix='bibleit-contract-') as directory:
    temporary = pathlib.Path(directory)
    app = temporary/'bibleit_server'; ebin = app/'ebin'; ebin.mkdir(parents=True)
    # Freeze source and runtime assets; exclude local credentials and data.
    original = server
    server = temporary/'snapshot'
    for relative in ('src', 'test', 'priv/config', 'priv/sql', 'priv/i18n', 'priv/templates', 'priv/static'):
        shutil.copytree(original/relative, server/relative,
                        ignore=lambda folder, names: [name for name in names if (pathlib.Path(folder)/name).is_symlink()])
    shutil.copytree(original/'_build/default/lib', server/'_build/default/lib',
                    ignore=shutil.ignore_patterns('bibleit_server', 'src', 'include', 'priv'))
    for native in (original/'_build/default/lib').glob('*/priv/*.so'):
        if native.parent.parent.name == 'bibleit_server':
            continue
        destination = server/native.relative_to(original)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(native, destination)
    app_source = original/'_build/default/lib/bibleit_server/ebin/bibleit_server.app'
    app_target = server/'_build/default/lib/bibleit_server/ebin/bibleit_server.app'
    app_target.parent.mkdir(parents=True)
    shutil.copy(app_source, app_target)
    shutil.copy(original/'priv/bibleit_translation_nif.so', server/'priv')
    # Detect concurrent source edits during the copy rather than mixing revisions.
    for folder in ('src', 'test'):
        source_files = sorted(p.relative_to(original) for p in (original/folder).rglob('*.erl'))
        copied_files = sorted(p.relative_to(server) for p in (server/folder).rglob('*.erl'))
        if source_files != copied_files or any((original/p).read_bytes() != (server/p).read_bytes() for p in source_files):
            raise RuntimeError('server source changed during snapshot; rerun the check')
    shutil.copytree(server/'priv', app/'priv')
    baseline = {
        'reviewed_at': datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        'head': run(['git','-C',str(original),'rev-parse','HEAD'],capture_output=True).stdout.strip(),
        'working_tree_changes': bool(run(['git','-C',str(original),'status','--porcelain'],capture_output=True).stdout.strip()),
        'files_sha256': {str(p.relative_to(server)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted((server/'src').rglob('*.erl'))},
        'verification': {'integration': args.integration}
    }
    print('Server source snapshot created (local credentials/data excluded)', flush=True)
    deps = [p for p in (server/'_build/default/lib').glob('*/ebin') if p.parent.name != 'bibleit_server']
    paths = [part for p in deps for part in ('-pa', str(p))]
    sources = list((server/'src').rglob('*.erl')) if args.integration else [server/'src/protocol/bibleit_protocol.erl']
    run(['erlc', *paths, '-o', str(ebin), *map(str,sources)], cwd=temporary)
    fixture = root/'contract/fixtures/requests-v1.json'
    env = dict(os.environ, BIBLEIT_REQUEST_FIXTURES=str(fixture), BIBLEIT_RESPONSE_FIXTURES=str(root/"contract/fixtures/responses-v1.json"))
    check = '''
      {ok, Body} = file:read_file(os:getenv("BIBLEIT_REQUEST_FIXTURES")),
      Cases = json:decode(Body),
      lists:foreach(fun(Case) ->
        {ok, Tokens, _} = erl_scan:string(binary_to_list(maps:get(<<"server_term">>, Case)) ++ "."),
        {ok, Expected} = erl_parse:parse_term(Tokens),
        Actual = bibleit_protocol:decode(maps:get(<<"wire">>, Case)),
        case Actual =:= Expected of true -> ok; false -> error({fixture_mismatch, maps:get(<<"name">>, Case), Expected, Actual}) end
      end, Cases),
      io:format("Server decoder fixtures: ~p passed~n", [length(Cases)]),
      {ok, ResponsesBody}=file:read_file(os:getenv("BIBLEIT_RESPONSE_FIXTURES")),
      Responses=[R || R<-json:decode(ResponsesBody),maps:is_key(<<"server_response_term">>,R)],
      lists:foreach(fun(R)->
        {ok,T,_}=erl_scan:string(binary_to_list(maps:get(<<"server_response_term">>,R))++"."),
        {ok,Term}=erl_parse:parse_term(T),
        Wire=iolist_to_binary(bibleit_protocol:encode(Term)),
        case Wire=:=maps:get(<<"wire">>,R) of true->ok;false->error({encoder_mismatch,maps:get(<<"name">>,R),Wire}) end
      end,Responses),
      io:format("Server encoder fixtures: ~p passed~n",[length(Responses)]), halt().
    '''
    run(['erl','-noshell','-pa',str(ebin),'-eval',check],env=env,cwd=temporary)
    if args.integration:
        go_env = dict(os.environ, GOCACHE='/tmp/bibleit-go127-cache', GOTOOLCHAIN='local')
        binary=temporary/'client-integration.test'
        run(['go','test','-c','-o',str(binary),'./clients/go'],cwd=root,env=go_env)
        env['BIBLEIT_GO_TEST_BIN']=str(binary)
        cli_binary=temporary/'cli-integration.test'
        run(['go','test','-c','-o',str(cli_binary),'.'],cwd=root,env=go_env)
        env['BIBLEIT_CLI_TEST_BIN']=str(cli_binary)
        shutil.copy(server/'_build/default/lib/bibleit_server/ebin/bibleit_server.app', ebin)
        suites = [server/'test/bibleit_test_database.erl', server/'test/bibleit_security_SUITE.erl', server/'test/http/bibleit_cli_auth_tests.erl', server/'test/ssh/bibleit_ssh_key_cb_tests.erl']
        run(['erlc', *paths,'-o',str(ebin),*map(str,suites)],cwd=temporary)
        name = 'bibleit-client-test-'+uuid.uuid4().hex[:12]
        started = False
        try:
            run(['docker','run','--pull=never','--detach','--name',name,'--publish','127.0.0.1::5432','--tmpfs','/var/lib/postgresql/data',
                 '--env','POSTGRES_USER=bibleit_test','--env','POSTGRES_PASSWORD=bibleit-test-only','--env','POSTGRES_DB=bibleit_test','postgres:17-alpine'],stdout=subprocess.DEVNULL)
            started = True
            for _ in range(80):
                ready = subprocess.run(['docker','exec',name,'pg_isready','-h','127.0.0.1','-U','bibleit_test','-d','bibleit_test'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                if ready.returncode == 0: break
                time.sleep(.25)
            else: raise RuntimeError('test database did not become ready')
            port = run(['docker','port',name,'5432/tcp'],capture_output=True).stdout.strip().rsplit(':',1)[1]
            env['BIBLEIT_TEST_DATABASE_URL']=f'postgresql://bibleit_test:bibleit-test-only@127.0.0.1:{port}/bibleit_test?sslmode=disable'
            private=temporary/'test-data';private.mkdir();env['BIBLEIT_TEST_PRIV']=str(private)
            integration='''
              {ok,_}=application:ensure_all_started(cowboy),
              Config=bibleit_security_SUITE:init_per_suite([{priv_dir,os:getenv("BIBLEIT_TEST_PRIV")}]),
              Results=try lists:foreach(fun(Case)->
                C=bibleit_security_SUITE:init_per_testcase(Case,Config),
                try apply(bibleit_security_SUITE,Case,[C]), io:format("Server integration: ~p passed~n",[Case])
                after bibleit_security_SUITE:end_per_testcase(Case,C) end
              end,[cli_rate_limit,scoped_token_cannot_escalate,revoked_credentials,concurrent_code_exchange,oversized_cli_input,search_shares_budget,ssh_revocation]),
              _=bibleit_security_SUITE:init_per_testcase(go_client,Config),
              gen_server:stop(bibleit_rate_limit),
              application:set_env(bibleit_server,rate_limits,#{ssh_command=>#{limit=>100},ssh_search=>#{limit=>100}}),
              {ok,L}=bibleit_rate_limit:start_link(),unlink(L),
              {ok,ManualId,Token}=bibleit_authorization:create_token(<<"security-owner">>,<<"security-owner">>,<<"Go integration">>,[]),
              {error,quota_exceeded}=bibleit_authorization:create_token(<<"security-owner">>,<<"security-owner">>,<<"Over quota">>,[]),
              {ok,ExpiredId,ExpiredToken}=bibleit_authorization:create_token(<<"security-other">>,<<"security-other">>,<<"Expired fixture">>,[],manual,erlang:system_time(second)+60),
              {ok,_}=bibleit_database:query(<<"UPDATE access_tokens SET expires_at=now()-interval '1 second' WHERE id=$1">>,[ExpiredId]),
              {ok,ScopedId,ScopedToken}=bibleit_authorization:create_token(<<"security-owner">>,<<"security-owner">>,<<"Scoped fixture\nlabel">>,[{token,get}],cli,erlang:system_time(second)+3600),
              {ok,_,DeniedToken}=bibleit_authorization:create_token(<<"security-owner">>,<<"security-owner">>,<<"Restricted fixture">>,[{live,list}],cli,undefined),
              {ok,OwnerExpiredId,_}=bibleit_authorization:create_token(<<"security-owner">>,<<"security-owner">>,<<"Owner expired fixture">>,[],cli,erlang:system_time(second)+60),
              {ok,_}=bibleit_database:query(<<"UPDATE access_tokens SET expires_at=now()-interval '1 second' WHERE id=$1">>,[OwnerExpiredId]),
              {ok,RevokedId,_}=bibleit_authorization:create_token(<<"security-owner">>,<<"security-owner">>,<<"Owner revoked fixture">>,[],cli,undefined),
              ok=bibleit_authorization:revoke_token(<<"security-owner">>,RevokedId),
              AuthVerifier = <<"bibleit-go-integration-verifier-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ">>,
              Base64URL=fun(Value)->binary:replace(binary:replace(binary:replace(base64:encode(Value),<<"=">>,<<>>, [global]),<<"+">>,<<"-">>,[global]),<<"/">>,<<"_">>,[global]) end,
              AuthChallenge=Base64URL(crypto:hash(sha256,AuthVerifier)),
              AuthCodeFor=fun()->
                {ok,AuthFlow}=bibleit_cli_auth:begin_flow(<<"http://127.0.0.1:43123/callback">>,Base64URL(crypto:strong_rand_bytes(32)),AuthChallenge),
                {ok,AuthLocation}=bibleit_cli_auth:approve(AuthFlow,<<"security-owner">>),
                maps:get(<<"code">>,maps:from_list(uri_string:dissect_query(maps:get(query,uri_string:parse(AuthLocation)))))
              end,
              AuthCode=AuthCodeFor(),BadAuthCode=AuthCodeFor(),
              Directory=os:getenv("BIBLEIT_TEST_PRIV"),
              BT=filename:join(Directory,"web.bt"), Index=filename:join(Directory,"web.bidx"),
              Prefix=[io_lib:format("Book ~B 1:1 filler~n",[B]) || B<-lists:seq(1,18)],
              ok=file:write_file(BT,iolist_to_binary([Prefix,"Psalms 1:1 Fixture book opening.\nPsalms 23:1 The shepherd guides me.\nPsalms 23:2 The shepherd gives rest.\n"])),
              ok=bibleit_translation_nif:create_index(list_to_binary(BT),list_to_binary(Index)),
              Endpoint="http://127.0.0.1:"++integer_to_list(proplists:get_value(port,Config)),
              P=open_port({spawn_executable,os:getenv("BIBLEIT_GO_TEST_BIN")},[exit_status,use_stdio,stderr_to_stdout,
                {args,["-test.run=^TestServerHTTPIntegration$","-test.v"]},
                {env,[{"BIBLEIT_CLIENT_TEST_DISPOSABLE","1"},{"BIBLEIT_INTEGRATION_ENDPOINT",Endpoint},{"BIBLEIT_INTEGRATION_TOKEN",binary_to_list(Token)},{"BIBLEIT_EXPIRED_TOKEN",binary_to_list(ExpiredToken)},{"BIBLEIT_MANUAL_TOKEN_ID",binary_to_list(ManualId)},{"BIBLEIT_SCOPED_TOKEN_ID",binary_to_list(ScopedId)},{"BIBLEIT_SCOPED_TOKEN",binary_to_list(ScopedToken)},{"BIBLEIT_DENIED_TOKEN",binary_to_list(DeniedToken)},{"BIBLEIT_AUTH_CODE",binary_to_list(AuthCode)},{"BIBLEIT_AUTH_BAD_CODE",binary_to_list(BadAuthCode)},{"BIBLEIT_AUTH_VERIFIER",binary_to_list(AuthVerifier)}]}]),
              Wait=fun F()->receive {P,{data,Data}}->io:put_chars(Data),F();{P,{exit_status,0}}->ok;{P,{exit_status,Status}}->{error,{go_client_failed,Status}} after 30000->error(go_client_timeout) end end,
              GoResult=Wait(),
              SSHDirectory=filename:join(Directory,"client-ssh"),
              ok=file:make_dir(SSHDirectory),
              Private=public_key:generate_key({rsa,2048,65537}),
              Public={'RSAPublicKey',element(3,Private),element(4,Private)},
              Pem=public_key:pem_encode([public_key:pem_entry_encode('RSAPrivateKey',Private)]),
              Identity=filename:join(SSHDirectory,"id_rsa"),
              Host=filename:join(SSHDirectory,"ssh_host_rsa_key"),
              [begin ok=file:write_file(F,Pem),ok=file:change_mode(F,8#600) end || F<-[Identity,Host]],
              PublicLine=ssh_file:encode([{Public,[]}],openssh_key),
              ok=file:write_file(Identity++".pub",PublicLine),
              {ok,_}=bibleit_account:add_key(<<"security-owner">>,PublicLine),
              {ok,SSHListener=#{daemon:=Daemon}}=bibleit_ssh_listener:init(#{port=>0,system_dir=>SSHDirectory}),
              try
                {ok,SSHInfo}=ssh:daemon_info(Daemon),
                SSHAddress="127.0.0.1:"++integer_to_list(proplists:get_value(port,SSHInfo)),
                CLI=open_port({spawn_executable,os:getenv("BIBLEIT_CLI_TEST_BIN")},[exit_status,use_stdio,stderr_to_stdout,
                  {args,["-test.run=^TestServerSSHSubscription$","-test.v"]},
                  {env,[{"BIBLEIT_CLIENT_TEST_DISPOSABLE","1"},{"BIBLEIT_INTEGRATION_ENDPOINT",Endpoint},
                        {"BIBLEIT_INTEGRATION_TOKEN",binary_to_list(Token)},{"BIBLEIT_INTEGRATION_SSH",SSHAddress},
                        {"BIBLEIT_INTEGRATION_IDENTITY",Identity}]}]),
                CLIWait=fun F()->receive {CLI,{data,Data}}->io:put_chars(Data),F();{CLI,{exit_status,0}}->ok;
                  {CLI,{exit_status,Status}}->{error,{cli_subscription_failed,Status}} after 30000->error(cli_subscription_timeout) end end,
                {GoResult,CLIWait()}
              after bibleit_ssh_listener:terminate(normal,SSHListener) end
              after bibleit_security_SUITE:end_per_suite(Config) end,
              application:unset_env(bibleit_server,rate_limits),
              DB=bibleit_test_database:start(),
              UnitResult=try eunit:test([bibleit_cli_auth_tests,bibleit_ssh_key_cb_tests],[verbose])
              after bibleit_test_database:stop(DB) end,
              case {Results,UnitResult} of
                {{ok,ok},ok}->halt();
                Failures->io:format("Integration failure summary: ~p~n",[Failures]),halt(1)
              end.
            '''
            run(['erl','-noshell',*paths,'-pa',str(ebin),'-eval',integration],env=env,cwd=temporary,timeout=120)
        finally:
            if started: run(['docker','rm','--force',name],stdout=subprocess.DEVNULL)
    if args.baseline:
        baseline['verification'].update({
            'request_decoder_cases': len(json.loads(fixture.read_text())),
            'response_encoder_cases': sum('server_response_term' in case for case in json.loads((root/'contract/fixtures/responses-v1.json').read_text())),
        })
        args.baseline.write_text(json.dumps(baseline, indent=2)+'\n')
