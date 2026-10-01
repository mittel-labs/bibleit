-module(bibleit_proxy_protocol).
-export([parse_v1/1]).

%% Accept only a complete HAProxy PROXY protocol v1 header.  This parser is
%% enabled explicitly for a trusted proxy; never enable it on a public direct
%% listener because the source address is supplied by the peer.
parse_v1(Line) when is_binary(Line) ->
    case string:tokens(binary_to_list(Line), " \r\n") of
        ["PROXY", Family, Source | _] when Family =:= "TCP4"; Family =:= "TCP6" ->
            case inet:parse_address(Source) of {ok, Ip} -> {ok, Ip}; _ -> {error, invalid_proxy_header} end;
        _ -> {error, invalid_proxy_header}
    end.
