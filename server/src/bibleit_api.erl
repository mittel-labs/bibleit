-module(bibleit_api).

%% Application-facing API.  Transports call this module instead of calling
%% registry/session processes directly.  The TCP protocol is consequently an
%% adapter: it parses a line, invokes this API, and renders a response.

-export([translations/0, all_translations/0, translation_info/1, translation_catalog/1,
         read/2, read/3, read/4, resolve_book/2, search/3, fetch_translation/1, delete_translation/1,
         live/1, live_exists/1, live_public/1, authorize_live_secret/2,
         subscribe_live/4, unsubscribe_live/2]).

translations() -> bibleit_translation_registry:list().
all_translations() ->
    case {translations(), bibleit_translation_available:list()} of
        {{ok, Installed}, {ok, Available}} -> {ok, lists:usort(Installed ++ Available)};
        {{error, _} = Error, _} -> Error;
        {_, {error, _} = Error} -> Error
    end.
translation_info(Slug) -> bibleit_translation_available:info(Slug).
translation_catalog(Slug) ->
    case bibleit_translation_registry:catalog(Slug) of
        {ok, IndexedBooks} -> bibleit_translation_catalog:describe_books(Slug, IndexedBooks);
        {error, _} = Error -> Error
    end.
read(Slug, Book, Chapter, Verse) -> bibleit_translation_registry:read(Slug, Book, Chapter, Verse).
read(Slug, Book, Chapter) -> bibleit_translation_registry:read(Slug, Book, Chapter).
read(Slug, Book) -> bibleit_translation_registry:read(Slug, Book).
resolve_book(Slug, Name) -> bibleit_translation_catalog:resolve_book(Slug, Name).
search(Slug, Query, Limit) -> bibleit_translation_registry:search(Slug, Query, Limit).
fetch_translation(Slug) -> bibleit_translation_fetcher:fetch(Slug).
delete_translation(all) -> bibleit_translation_registry:delete_all();
delete_translation(Slug) -> bibleit_translation_registry:delete(Slug).

live(Id) -> bibleit_live_registry:lookup(Id).
live_exists(Id) -> case live(Id) of {ok, _} -> true; error -> false end.
live_public(Pid) -> bibleit_live_session:public(Pid).
authorize_live_secret(Id, Secret) ->
    case live(Id) of
        {ok, Pid} -> bibleit_live_session:authenticate_secret(Pid, Secret);
        error -> {error, not_found}
    end.
subscribe_live(Id, Actor, Secret, Subscriber) ->
    case live(Id) of
        error -> {error, not_found};
        {ok, Pid} ->
            case bibleit_live_session:subscribe(Pid, Actor, Subscriber) of
                {error, forbidden} ->
                    case bibleit_live_session:subscribe_with_secret(Pid, Secret, Subscriber) of
                        {ok, Live} -> {ok, Pid, Live};
                        {error, _} = Error -> Error
                    end;
                {ok, Live} -> {ok, Pid, Live};
                {error, _} = Error -> Error
            end
    end.
unsubscribe_live(Pid, Subscriber) -> bibleit_live_session:unsubscribe(Pid, Subscriber).
