-module(bibleit_http_handler).
-export([init/2]).

init(Req0, health) ->
    reply(200, <<"application/json">>, json:encode(#{<<"ok">> => true}), Req0);
init(Req0, index) -> docs(Req0);
init(Req0, page) ->
    Id = cowboy_req:binding(id, Req0),
    case valid_live_id(Id) of
        false -> reply(404, <<"text/plain">>, <<"not found\n">>, Req0);
        true -> case bibleit_api:live_exists(Id) of true -> live_page(Req0); false -> reply(404, <<"text/plain">>, <<"not found\n">>, Req0) end
    end;
init(Req0, short_live) ->
    Id = cowboy_req:binding(id, Req0),
    case valid_live_id(Id) of
        true -> {ok, cowboy_req:reply(307, #{<<"location">> => <<"/lives/", Id/binary>>}, Req0), undefined};
        false -> reply(404, <<"text/plain">>, <<"not found\n">>, Req0)
    end;
init(Req0, access) -> access(Req0);
init(Req0, login) -> login(Req0);
init(Req0, signup) -> signup(Req0);
init(Req0, google_login) -> google_login(Req0);
init(Req0, google_callback) -> google_callback(Req0);
init(Req0, github_login) -> github_login(Req0);
init(Req0, github_callback) -> github_callback(Req0);
init(Req0, email_verify) -> email_verify(Req0);
init(Req0, password_reset_request) -> password_reset_request(Req0);
init(Req0, password_reset) -> password_reset(Req0);
init(Req0, logout) -> logout(Req0);
init(Req0, dashboard_keys) -> dashboard_keys(Req0);
init(Req0, dashboard) -> dashboard(Req0).

docs(Req0) ->
    case file:read_file(docs_index_path()) of
        {ok, Html} -> reply(200, <<"text/html; charset=utf-8">>, Html, Req0);
        _ -> reply(500, <<"text/plain">>, <<"documentation unavailable\n">>, Req0)
    end.

live_page(Req0) ->
    case file:read_file(live_index_path()) of
        {ok, Html} -> reply(200, <<"text/html; charset=utf-8">>, Html, Req0);
        _ -> reply(500, <<"text/plain">>, <<"live page unavailable\n">>, Req0)
    end.

access(Req0) ->
    Id = cowboy_req:binding(id, Req0),
    case {valid_live_id(Id), cowboy_req:method(Req0)} of
        {true, <<"POST">>} ->
            {ok, Fields, Req1} = cowboy_req:read_urlencoded_body(Req0),
            Secret = proplists:get_value(<<"secret">>, Fields, <<>>),
            case bibleit_api:authorize_live_secret(Id, Secret) of
                    ok ->
                        Options = #{path => <<"/">>, http_only => true, same_site => lax, secure => secure_cookies()},
                        Req2 = cowboy_req:set_resp_cookie(cookie_name(Id), Secret, Req1, Options),
                        {ok, cowboy_req:reply(204, Req2), undefined};
                    {error, not_found} -> reply(404, <<"text/plain">>, <<"not found\n">>, Req1);
                    _ -> reply(401, <<"text/plain">>, <<"invalid secret\n">>, Req1)
            end;
        _ -> reply(404, <<"text/plain">>, <<"not found\n">>, Req0)
    end.

login(Req0) ->
    case cowboy_req:method(Req0) of
        <<"GET">> -> login_page(undefined, Req0);
        <<"POST">> ->
            {ok, Fields, Req1} = cowboy_req:read_urlencoded_body(Req0),
            email_login(Fields, Req1);
        _ -> reply(405, <<"text/plain">>, <<"method not allowed\n">>, Req0)
    end.

logout(Req0) ->
    case cowboy_req:method(Req0) of
        <<"POST">> ->
            Req1 = bibleit_http_auth:logout(Req0),
            {ok, cowboy_req:reply(303, #{<<"location">> => <<"/auth/login">>, <<"cache-control">> => <<"no-store">>}, Req1), undefined};
        _ -> reply(405, <<"text/plain">>, <<"method not allowed\n">>, Req0)
    end.

login_page(Error, Req0) ->
    Body = auth_page(<<"Welcome back">>, <<"Sign in to manage your Bibleit server and lives.">>, Error,
                     <<"<div class=\"oauth-options\"><a class=\"oauth\" href=\"/auth/github\"><img class=\"provider-logo\" src=\"/assets/github-mark.svg\" alt=\"\"> Continue with GitHub</a><a class=\"oauth\" href=\"/auth/google\"><img class=\"provider-logo\" src=\"/assets/google-mark.svg\" alt=\"\"> Continue with Google</a></div><div class=\"divider\"><span>or</span></div><form method=\"post\"><label for=\"email\">Email</label><input id=\"email\" name=\"email\" type=\"email\" autocomplete=\"email\" required autofocus><label for=\"password\">Password</label><input id=\"password\" name=\"password\" type=\"password\" autocomplete=\"current-password\" required><p class=\"help\"><a href=\"/auth/password/reset\">Forgot password?</a></p><button type=\"submit\">Sign in</button></form><p class=\"switch\">New to Bibleit? <a href=\"/auth/signup\">Create an account</a></p>">>),
    reply(case Error of undefined -> 200; _ -> 401 end, <<"text/html; charset=utf-8">>, Body, Req0).

email_login(Fields, Req0) ->
    Email = proplists:get_value(<<"email">>, Fields, <<>>),
    Password = proplists:get_value(<<"password">>, Fields, <<>>),
    case bibleit_email_account:authenticate(Email, Password) of
        {ok, Actor} -> case bibleit_http_auth:login_actor(Actor, Req0) of
            {ok, _LoginActor, Req1} -> redirect(<<"/dashboard">>, Req1);
            _ -> reply(500, <<"text/plain">>, <<"unable to create browser session\n">>, Req0)
        end;
        _ -> login_page(<<"Email or password is incorrect.">>, Req0)
    end.

signup(Req0) ->
    case cowboy_req:method(Req0) of
        <<"GET">> -> signup_page(undefined, #{}, Req0);
        <<"POST">> ->
            {ok, Fields, Req1} = cowboy_req:read_urlencoded_body(Req0),
            Values = #{name => proplists:get_value(<<"name">>, Fields, <<>>), email => proplists:get_value(<<"email">>, Fields, <<>>)},
            case bibleit_email_account:register(maps:get(email, Values), proplists:get_value(<<"password">>, Fields, <<>>), maps:get(name, Values)) of
                ok -> reply(200, <<"text/html; charset=utf-8">>, auth_page(<<"Check your email">>, <<"We sent a verification link if this address can be registered. It expires in 30 minutes.">>, undefined, <<"<p class=\"switch\"><a href=\"/auth/login\">Back to sign in</a></p>">>), Req1);
                {error, email_not_configured} -> oauth_not_configured(<<"Email sign-up">>, <<"BIBLEIT_RESEND_API_KEY and BIBLEIT_EMAIL_FROM">>, Req1);
                {error, invalid_display_name} -> signup_page(<<"Enter the name you want people to see in Bibleit.">>, Values, Req1);
                {error, invalid_email} -> signup_page(<<"Enter a valid email address.">>, Values, Req1);
                {error, invalid_password} -> signup_page(<<"Use a password with at least 12 characters.">>, Values, Req1);
                {error, email_delivery_failed} -> signup_page(<<"We could not send the verification email. Confirm BIBLEIT_EMAIL_FROM is verified in Resend, then try again.">>, Values, Req1);
                _ -> signup_page(<<"We could not create the account. Please try again.">>, Values, Req1)
            end;
        _ -> reply(405, <<"text/plain">>, <<"method not allowed\n">>, Req0)
    end.

signup_page(Error, Values, Req0) ->
    Name = html_escape(maps:get(name, Values, <<>>)),
    Email = html_escape(maps:get(email, Values, <<>>)),
    reply(case Error of undefined -> 200; _ -> 400 end, <<"text/html; charset=utf-8">>, auth_page(<<"Create your account">>, <<"Start a personal space for your Bibleit lives.">>, Error,
        <<"<div class=\"oauth-options\"><a class=\"oauth\" href=\"/auth/github\"><img class=\"provider-logo\" src=\"/assets/github-mark.svg\" alt=\"\"> Continue with GitHub</a><a class=\"oauth primary\" href=\"/auth/google\"><img class=\"provider-logo\" src=\"/assets/google-mark.svg\" alt=\"\"> Continue with Google</a></div><div class=\"divider\"><span>or</span></div><form method=\"post\"><label for=\"name\">Name</label><input id=\"name\" name=\"name\" type=\"text\" autocomplete=\"name\" value=\"", Name/binary, "\" required autofocus><label for=\"email\">Email</label><input id=\"email\" name=\"email\" type=\"email\" autocomplete=\"email\" value=\"", Email/binary, "\" required><label for=\"password\">Password</label><input id=\"password\" name=\"password\" type=\"password\" autocomplete=\"new-password\" minlength=\"12\" required><p class=\"help\">At least 12 characters. We will email a verification link before creating your account.</p><button type=\"submit\">Create account</button></form><p class=\"switch\">Already have an account? <a href=\"/auth/login\">Sign in</a></p>">>), Req0).

email_verify(Req0) ->
    case cowboy_req:method(Req0) of
        <<"GET">> -> case bibleit_email_account:verify(cowboy_req:binding(token, Req0)) of
            {ok, Actor} -> case bibleit_http_auth:login_actor(Actor, Req0) of
                {ok, _LoginActor, Req1} -> redirect(<<"/dashboard">>, Req1);
                _ -> reply(500, <<"text/plain">>, <<"unable to create browser session\n">>, Req0)
            end;
            _ -> reply(400, <<"text/html; charset=utf-8">>, auth_page(<<"This link has expired">>, <<"Request a new verification email to finish creating your account.">>, undefined, <<"<p class=\"switch\"><a href=\"/auth/signup\">Create an account</a></p>">>), Req0)
        end;
        _ -> reply(405, <<"text/plain">>, <<"method not allowed\n">>, Req0)
    end.

password_reset_request(Req0) ->
    case cowboy_req:method(Req0) of
        <<"GET">> -> password_reset_request_page(undefined, Req0);
        <<"POST">> ->
            {ok, Fields, Req1} = cowboy_req:read_urlencoded_body(Req0),
            case bibleit_email_account:begin_password_reset(proplists:get_value(<<"email">>, Fields, <<>>)) of
                {error, email_not_configured} -> oauth_not_configured(<<"Password reset">>, <<"BIBLEIT_RESEND_API_KEY and BIBLEIT_EMAIL_FROM">>, Req1);
                _ -> reply(200, <<"text/html; charset=utf-8">>, auth_page(<<"Check your email">>, <<"If an account exists for this address, we sent a password-reset link.">>, undefined, <<"<p class=\"switch\"><a href=\"/auth/login\">Back to sign in</a></p>">>), Req1)
            end;
        _ -> reply(405, <<"text/plain">>, <<"method not allowed\n">>, Req0)
    end.

password_reset_request_page(Error, Req0) ->
    reply(200, <<"text/html; charset=utf-8">>, auth_page(<<"Reset your password">>, <<"Enter your email and we will send a one-time reset link.">>, Error,
        <<"<form method=\"post\"><label for=\"email\">Email</label><input id=\"email\" name=\"email\" type=\"email\" autocomplete=\"email\" required autofocus><button type=\"submit\">Send reset link</button></form><p class=\"switch\"><a href=\"/auth/login\">Back to sign in</a></p>">>), Req0).

password_reset(Req0) ->
    Token = cowboy_req:binding(token, Req0),
    case cowboy_req:method(Req0) of
        <<"GET">> -> password_reset_page(Token, undefined, Req0);
        <<"POST">> ->
            {ok, Fields, Req1} = cowboy_req:read_urlencoded_body(Req0),
            case bibleit_email_account:reset_password(Token, proplists:get_value(<<"password">>, Fields, <<>>)) of
                ok -> reply(200, <<"text/html; charset=utf-8">>, auth_page(<<"Password updated">>, <<"Your password has been changed. You can now sign in.">>, undefined, <<"<p class=\"switch\"><a href=\"/auth/login\">Sign in</a></p>">>), Req1);
                {error, invalid_password} -> password_reset_page(Token, <<"Use a password with at least 12 characters.">>, Req1);
                _ -> reply(400, <<"text/html; charset=utf-8">>, auth_page(<<"This link has expired">>, <<"Request a new password-reset link.">>, undefined, <<"<p class=\"switch\"><a href=\"/auth/password/reset\">Reset password</a></p>">>), Req1)
            end;
        _ -> reply(405, <<"text/plain">>, <<"method not allowed\n">>, Req0)
    end.

password_reset_page(Token, Error, Req0) ->
    reply(case Error of undefined -> 200; _ -> 400 end, <<"text/html; charset=utf-8">>, auth_page(<<"Choose a new password">>, <<"Use at least 12 characters.">>, Error,
        <<"<form method=\"post\" action=\"/auth/password/reset/", Token/binary, "\"><label for=\"password\">New password</label><input id=\"password\" name=\"password\" type=\"password\" autocomplete=\"new-password\" minlength=\"12\" required autofocus><button type=\"submit\">Update password</button></form>">>), Req0).

google_login(Req0) ->
    case bibleit_http_oauth:google_url() of
        {ok, Url} -> redirect(Url, Req0);
        {error, oauth_not_configured} -> oauth_not_configured(<<"Google">>, <<"BIBLEIT_GOOGLE_CLIENT_ID and BIBLEIT_GOOGLE_CLIENT_SECRET">>, Req0)
    end.

google_callback(Req0) ->
    Query = cowboy_req:parse_qs(Req0),
    State = proplists:get_value(<<"state">>, Query, <<>>),
    Code = proplists:get_value(<<"code">>, Query, <<>>),
    case bibleit_http_oauth:complete_google(State, Code) of
        {ok, Actor} -> case bibleit_http_auth:login_actor(Actor, Req0) of {ok, _LoginActor, Req1} -> redirect(<<"/dashboard">>, Req1); _ -> reply(500, <<"text/plain">>, <<"unable to create browser session\n">>, Req0) end;
        _ -> reply(401, <<"text/html; charset=utf-8">>, auth_page(<<"Google sign-in did not complete">>, <<"Please return to sign in and try again.">>, undefined, <<"<p class=\"switch\"><a href=\"/auth/login\">Back to sign in</a></p>">>), Req0)
    end.

github_login(Req0) ->
    case bibleit_http_oauth:github_url() of
        {ok, Url} -> redirect(Url, Req0);
        {error, oauth_not_configured} -> oauth_not_configured(<<"GitHub">>, <<"BIBLEIT_GITHUB_CLIENT_ID and BIBLEIT_GITHUB_CLIENT_SECRET">>, Req0)
    end.

github_callback(Req0) ->
    Query = cowboy_req:parse_qs(Req0),
    State = proplists:get_value(<<"state">>, Query, <<>>),
    Code = proplists:get_value(<<"code">>, Query, <<>>),
    case bibleit_http_oauth:complete_github(State, Code) of
        {ok, Actor} -> case bibleit_http_auth:login_actor(Actor, Req0) of {ok, _LoginActor, Req1} -> redirect(<<"/dashboard">>, Req1); _ -> reply(500, <<"text/plain">>, <<"unable to create browser session\n">>, Req0) end;
        _ -> reply(401, <<"text/html; charset=utf-8">>, auth_page(<<"GitHub sign-in did not complete">>, <<"Please return to sign in and try again.">>, undefined, <<"<p class=\"switch\"><a href=\"/auth/login\">Back to sign in</a></p>">>), Req0)
    end.

oauth_not_configured(Provider, Variables, Req0) ->
    reply(503, <<"text/html; charset=utf-8">>, auth_page(<<Provider/binary, " sign-in is not configured">>, <<"Set ", Variables/binary, " and BIBLEIT_PUBLIC_URL before enabling ", Provider/binary, " sign-in.">>, undefined, <<"<p class=\"switch\"><a href=\"/auth/login\">Back to sign in</a></p>">>), Req0).

dashboard(Req0) ->
    case bibleit_http_auth:current(Req0) of
        {ok, Actor, Permissions} -> dashboard_response(Actor, Permissions, undefined, Req0);
        {error, unauthenticated} -> redirect(<<"/auth/login">>, Req0)
    end.

dashboard_keys(Req0) ->
    case {cowboy_req:method(Req0), bibleit_http_auth:current(Req0)} of
        {<<"POST">>, {ok, Actor, Permissions}} ->
            {ok, Fields, Req1} = cowboy_req:read_urlencoded_body(Req0),
            dashboard_key_action(Actor, Permissions, Fields, Req1);
        {<<"POST">>, {error, unauthenticated}} -> redirect(<<"/auth/login">>, Req0);
        _ -> reply(405, <<"text/plain">>, <<"method not allowed\n">>, Req0)
    end.

dashboard_key_action(Actor, Permissions, Fields, Req0) ->
    case proplists:get_value(<<"action">>, Fields) of
        <<"add">> ->
            PublicKey = proplists:get_value(<<"public_key">>, Fields, <<>>),
            Notice = case bibleit_account:add_key(Actor, PublicKey) of
                {ok, _Fingerprint} -> {ok, <<"SSH key added. It can now sign in to Bibleit.">>};
                %% A public-key line alone is not proof of private-key control,
                %% so a key can never be silently moved between accounts.
                {error, key_exists} -> {error, <<"That SSH key is linked to a different account. Sign in to that account to revoke it, or add a different key.">>};
                {error, invalid_public_key} -> {error, <<"Paste a complete ssh-ed25519 public-key line.">>};
                _ -> {error, <<"We could not add that SSH key.">>}
            end,
            dashboard_response(Actor, Permissions, Notice, Req0);
        <<"revoke">> ->
            Fingerprint = proplists:get_value(<<"fingerprint">>, Fields, <<>>),
            Notice = case bibleit_account:revoke_key(Actor, Fingerprint) of
                ok -> {ok, <<"SSH key revoked.">>};
                {error, key_not_found} -> {error, <<"That SSH key is no longer linked to your account.">>};
                _ -> {error, <<"We could not revoke that SSH key.">>}
            end,
            dashboard_response(Actor, Permissions, Notice, Req0);
        _ -> dashboard_response(Actor, Permissions, {error, <<"Choose an SSH key action.">>}, Req0)
    end.

dashboard_response(Actor, Permissions, Notice, Req0) ->
    %% OAuth and email accounts created before the member role existed are
    %% upgraded lazily when their owner next opens the dashboard. This is
    %% idempotent and preserves any explicitly configured quota overrides.
    _ = bibleit_authorization:ensure_member_actor(<<"account">>, Actor),
    EffectivePermissions = case bibleit_authorization:actor_permissions(Actor) of
        {ok, PermissionValues} -> PermissionValues;
        _ -> Permissions
    end,
    Summary = case bibleit_account:summary(Actor) of
        {ok, AccountSummary} -> AccountSummary;
        _ -> #{actor => Actor, display_name => Actor, lives => 0, tokens => 0, keys => 0,
               subscription => bibleit_plan:new_subscription(erlang:system_time(second)),
               plan => bibleit_plan:free()}
    end,
    DisplayName = maps:get(display_name, Summary),
    Keys = case bibleit_account:keys(Actor) of {ok, AccountKeys} -> AccountKeys; _ -> [] end,
    Body = dashboard_page(DisplayName, EffectivePermissions, Summary, Keys, Notice),
    reply(200, <<"text/html; charset=utf-8">>, Body, Req0).

reply(Status, ContentType, Body, Req0) ->
    {ok, cowboy_req:reply(Status, #{<<"content-type">> => ContentType, <<"cache-control">> => <<"no-store">>}, Body, Req0), undefined}.
redirect(Location, Req0) ->
    {ok, cowboy_req:reply(303, #{<<"location">> => Location, <<"cache-control">> => <<"no-store">>}, Req0), undefined}.
live_index_path() -> filename:join(static_dir(), "index.html").
docs_index_path() -> filename:join(docs_dir(), "index.html").
auth_page(Title, Subtitle, Error, Content) ->
    Notice = case Error of undefined -> <<>>; _ -> <<"<p class=\"notice\" role=\"alert\">", Error/binary, "</p>">> end,
    <<"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>", Title/binary, " · Bibleit</title><link rel=\"stylesheet\" href=\"/assets/auth.css\"></head><body><main class=\"auth-shell\"><a class=\"brand\" href=\"/\"><span>✦</span> bibleit</a><section class=\"auth-card\"><p class=\"eyebrow\">BIBLEIT CLOUD</p><h1>", Title/binary, "</h1><p class=\"subtitle\">", Subtitle/binary, "</p>", Notice/binary, Content/binary, "</section><p class=\"footnote\">Scripture, shared in the moment.</p></main></body></html>">>.
dashboard_page(Actor, Permissions, Summary, Keys, Notice) ->
    PermissionsText = join_permissions(Permissions),
    NoticeHtml = dashboard_notice(Notice),
    ResourceSummary = dashboard_resource_summary(Summary),
    SubscriptionSummary = dashboard_subscription_summary(Summary),
    <<"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Dashboard · Bibleit</title><link rel=\"stylesheet\" href=\"/assets/auth.css\"></head><body><main class=\"dashboard\"><nav><a class=\"brand\" href=\"/\"><span>✦</span> bibleit</a><form action=\"/auth/logout\" method=\"post\"><button class=\"quiet\" type=\"submit\">Sign out</button></form></nav><section><p class=\"eyebrow\">DASHBOARD</p><h1>Welcome, ", (html_escape(Actor))/binary, ".</h1><p class=\"subtitle\">Your account is connected and ready to present.</p>", NoticeHtml/binary, SubscriptionSummary/binary, ResourceSummary/binary, "<div class=\"dashboard-card\"><span>Effective permissions</span><code>", (html_escape(PermissionsText))/binary, "</code></div><section class=\"dashboard-card ssh-keys\"><div><span>SSH keys</span><p class=\"help\">Add an Ed25519 public key to sign in through SSH.</p></div>", (dashboard_keys_html(Keys))/binary, "<form class=\"key-form\" action=\"/dashboard/keys\" method=\"post\"><input type=\"hidden\" name=\"action\" value=\"add\"><label for=\"public-key\">Public key</label><input id=\"public-key\" name=\"public_key\" type=\"text\" autocomplete=\"off\" placeholder=\"ssh-ed25519 AAAA… your-device\" required><button type=\"submit\">Add SSH key</button></form></section></section></main></body></html>">>.

dashboard_resource_summary(Summary) ->
    Lives = integer_to_binary(maps:get(lives, Summary, 0)),
    Tokens = integer_to_binary(maps:get(tokens, Summary, 0)),
    Keys = integer_to_binary(maps:get(keys, Summary, 0)),
    <<"<div class=\"dashboard-card\"><span>Account resources</span><p class=\"help\">", Lives/binary,
      " lives &middot; ", Tokens/binary, " tokens &middot; ", Keys/binary, " SSH keys</p></div>">>.

dashboard_subscription_summary(Summary) ->
    Subscription = maps:get(subscription, Summary),
    Plan = maps:get(plan, Summary),
    PlanName = html_escape(maps:get(name, Plan)),
    Status = atom_to_binary(maps:get(status, Subscription)),
    BillingCycle = atom_to_binary(maps:get(billing_cycle, Subscription)),
    <<"<div class=\"dashboard-card\"><span>Subscription</span><p class=\"help\"><strong>", PlanName/binary,
      "</strong> &middot; ", Status/binary, " &middot; ", BillingCycle/binary, " billing</p></div>">>.

dashboard_notice(undefined) -> <<>>;
dashboard_notice({ok, Text}) -> <<"<p class=\"notice success\" role=\"status\">", (html_escape(Text))/binary, "</p>">>;
dashboard_notice({error, Text}) -> <<"<p class=\"notice\" role=\"alert\">", (html_escape(Text))/binary, "</p>">>.
dashboard_keys_html([]) -> <<"<p class=\"help\">No SSH keys are linked yet.</p>">>;
dashboard_keys_html(Keys) -> iolist_to_binary([dashboard_key_html(Key) || Key <- Keys]).
dashboard_key_html(Key) ->
    Fingerprint = maps:get(fingerprint, Key),
    <<"<div class=\"key-row\"><code>", (html_escape(Fingerprint))/binary, "</code><form action=\"/dashboard/keys\" method=\"post\"><input type=\"hidden\" name=\"action\" value=\"revoke\"><input type=\"hidden\" name=\"fingerprint\" value=\"", (html_escape(Fingerprint))/binary, "\"><button class=\"quiet danger\" type=\"submit\">Revoke</button></form></div>">>.
static_dir() ->
    case application:get_env(bibleit_server, static_dir) of
        {ok, Directory} -> Directory;
        undefined ->
            case code:priv_dir(bibleit_server) of
                {error, bad_name} -> filename:absname("priv/static");
                Priv -> filename:join(Priv, "static")
            end
    end.
docs_dir() ->
    case application:get_env(bibleit_server, docs_dir) of
        {ok, Directory} -> Directory;
        undefined -> filename:absname("docs")
    end.
secure_cookies() -> application:get_env(bibleit_server, http_secure_cookies, false).
cookie_name(Id) -> <<"bibleit_live_", Id/binary>>.
valid_live_id(Id) when is_binary(Id), byte_size(Id) > 0, byte_size(Id) =< 64 ->
    lists:all(fun(Character) -> (Character >= $0 andalso Character =< $9) orelse (Character >= $A andalso Character =< $Z) orelse (Character >= $a andalso Character =< $z) end, binary_to_list(Id));
valid_live_id(_) -> false.
html_escape(Value) ->
    EscapedAmpersand = binary:replace(Value, <<"&">>, <<"&amp;">>, [global]),
    EscapedLessThan = binary:replace(EscapedAmpersand, <<"<">>, <<"&lt;">>, [global]),
    EscapedGreaterThan = binary:replace(EscapedLessThan, <<">">>, <<"&gt;">>, [global]),
    binary:replace(EscapedGreaterThan, <<$">>, <<"&quot;">>, [global]).
join_permissions(Permissions) -> list_to_binary(string:join([atom_to_list(Resource) ++ "." ++ atom_to_list(Verb) || {Resource, Verb} <- Permissions], ", ")).
