-module(bibleit_resend_mailer).

-export([configured/0, send_verification/2, send_password_reset/2]).

%% Resend is an outbound adapter. Account state and one-time secrets never
%% leave bibleit_email_account; this module receives only the recipient and
%% an already-generated, short-lived link token.

configured() ->
    case application:get_env(bibleit_server, resend) of
        {ok, #{api_key := ApiKey, from := From, public_url := PublicUrl}}
          when is_binary(ApiKey), is_binary(From), is_binary(PublicUrl) -> true;
        _ -> false
    end.

send_verification(Email, Token) ->
    send(Email, <<"Verify your Bibleit email">>,
         <<"Confirm your email address to finish creating your Bibleit account.">>,
         <<"/auth/email/verify/", Token/binary>>).

send_password_reset(Email, Token) ->
    send(Email, <<"Reset your Bibleit password">>,
         <<"Choose a new password for your Bibleit account.">>,
         <<"/auth/password/reset/", Token/binary>>).

send(Email, Subject, Intro, Path) ->
    case application:get_env(bibleit_server, resend) of
        {ok, #{api_key := ApiKey, from := From, public_url := PublicUrl}} ->
            Url = <<PublicUrl/binary, Path/binary>>,
            Html = <<"<!doctype html><html><body><p>", Intro/binary,
                     "</p><p><a href=\"", Url/binary, "\">Continue</a></p>",
                     "<p>If you did not request this, you can safely ignore this email.</p></body></html>">>,
            Payload = json:encode(#{<<"from">> => From, <<"to">> => [Email], <<"subject">> => Subject, <<"html">> => Html}),
            Headers = [{"authorization", "Bearer " ++ binary_to_list(ApiKey)}, {"accept", "application/json"}],
            case httpc:request(post, {"https://api.resend.com/emails", Headers, "application/json", Payload}, [{timeout, 15000}], [{body_format, binary}]) of
                {ok, {{_, Status, _}, _, _}} when Status >= 200, Status < 300 -> ok;
                {ok, {{_, Status, _}, _, ResponseBody}} ->
                    logger:warning("Resend rejected Bibleit email (status ~p): ~ts", [Status, ResponseBody]),
                    {error, email_delivery_failed};
                {error, Reason} ->
                    logger:warning("Resend delivery request failed: ~p", [Reason]),
                    {error, email_delivery_failed}
            end;
        _ -> {error, email_not_configured}
    end.
