-module(bibleit_ssh_key_cb).
-behaviour(ssh_server_key_api).
-export([host_key/2, is_auth_key/3]).

%% The supplied OpenSSH key is mapped directly to its owning Bibleit account;
%% the SSH username is transport metadata and never grants identity. OTP calls
%% this callback in the connection handler, which is also supplied to the
%% channel callback, so the supervised identity registry carries the verified
%% result in-process.

host_key(Algorithm, Options) -> ssh_file:host_key(Algorithm, Options).

is_auth_key({{'ECPoint', Encoded}, {namedCurve, {1, 3, 101, 112}}}, _User, _Options)
  when is_binary(Encoded), byte_size(Encoded) =:= 32 ->
    Fingerprint = fingerprint(Encoded),
    case bibleit_authorization:key(Fingerprint) of
        {ok, Actor, Encoded} ->
            _ = bibleit_authorization:touch_key(Fingerprint),
            ok = bibleit_ssh_identity:remember(self(), Actor, Fingerprint),
            true;
        _ -> false
    end;
is_auth_key(_, _, _) -> false.

fingerprint(Encoded) ->
    Blob = <<11:32/big, "ssh-ed25519", 32:32/big, Encoded/binary>>,
    EncodedHash = binary:replace(base64:encode(crypto:hash(sha256, Blob)), <<"=">>, <<>>, [global]),
    <<"SHA256:", EncodedHash/binary>>.
