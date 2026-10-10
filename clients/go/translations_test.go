package bibleit

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func TestTranslationMetadata(t *testing.T) {
	client := discoveryClient(t, map[string]string{
		"TRANSLATION INFO web": "OK short_name=WEB full_name=\"World English Bible\" rights_status=public_domain rights_url=\"https://example.test/rights\" attribution=\"Publisher credit\" future=kept\n",
	})
	info, err := client.GetTranslationInfo(context.Background(), "web")
	if err != nil || info.ShortName != "WEB" || info.FullName != "World English Bible" || info.RightsStatus != "public_domain" || info.Attribution != "Publisher credit" || info.Raw.Records[0].Fields["future"] != "kept" {
		t.Fatalf("%+v %v", info, err)
	}
	if info.Edition != "" || info.TrademarkNotice != "" {
		t.Fatal("invented optional metadata")
	}
	for _, wire := range []string{"OK short_name=WEB\n", "OK full_name=Name\n"} {
		client := discoveryClient(t, map[string]string{"TRANSLATION INFO web": wire})
		if _, err := client.GetTranslationInfo(context.Background(), "web"); err == nil {
			t.Fatal("accepted missing metadata identity")
		}
	}
}

func TestCatalogPreservesSourceIDsAndSparseChapters(t *testing.T) {
	wire := "OK translation=KJV books=2 future=kept\nBOOK book=88 name=Azariah chapters=1 future=book\nCHAPTER book=88 chapter=1 verses=68 future=chapter\nBOOK book=19 name=\"Salmos – Psalms\" chapters=2\nCHAPTER book=19 chapter=1 verses=1\nCHAPTER book=19 chapter=23 verses=2\nEND\n"
	client := discoveryClient(t, map[string]string{"TRANSLATION CATALOG KJV": wire})
	catalog, err := client.GetTranslationCatalog(context.Background(), "KJV")
	if err != nil {
		t.Fatal(err)
	}
	if catalog.Translation != "KJV" || len(catalog.Books) != 2 || catalog.Books[0].ID != 88 || catalog.Books[0].Chapters[0].Verses != 68 || catalog.Books[1].Chapters[1].Number != 23 {
		t.Fatalf("%+v", catalog)
	}
	if catalog.Raw.Records[0].Fields["future"] != "kept" || catalog.Books[0].Fields["future"] != "book" || catalog.Books[0].Chapters[0].Fields["future"] != "chapter" {
		t.Fatal("lost unknown fields")
	}
	client = discoveryClient(t, map[string]string{"TRANSLATION CATALOG web": "OK translation=web books=0\nEND\n"})
	empty, err := client.GetTranslationCatalog(context.Background(), "web")
	if err != nil || len(empty.Books) != 0 {
		t.Fatalf("%+v %v", empty, err)
	}
}

func TestInvalidCatalogHierarchy(t *testing.T) {
	for name, wire := range map[string]string{
		"book count":         "OK translation=web books=2\nBOOK book=19 name=Psalms chapters=0\nEND\n",
		"chapter count":      "OK translation=web books=1\nBOOK book=19 name=Psalms chapters=2\nCHAPTER book=19 chapter=23 verses=2\nEND\n",
		"wrong parent":       "OK translation=web books=1\nBOOK book=19 name=Psalms chapters=1\nCHAPTER book=20 chapter=23 verses=2\nEND\n",
		"orphan chapter":     "OK translation=web books=0\nCHAPTER book=19 chapter=23 verses=2\nEND\n",
		"duplicate book":     "OK translation=web books=2\nBOOK book=19 name=Psalms chapters=0\nBOOK book=19 name=Psalms chapters=0\nEND\n",
		"duplicate chapter":  "OK translation=web books=1\nBOOK book=19 name=Psalms chapters=2\nCHAPTER book=19 chapter=23 verses=2\nCHAPTER book=19 chapter=23 verses=2\nEND\n",
		"zero verse count":   "OK translation=web books=1\nBOOK book=19 name=Psalms chapters=1\nCHAPTER book=19 chapter=23 verses=0\nEND\n",
		"invalid id":         "OK translation=web books=1\nBOOK book=-1 name=Psalms chapters=0\nEND\n",
		"overflow":           "OK translation=web books=1\nBOOK book=9223372036854775808 name=Psalms chapters=0\nEND\n",
		"missing terminator": "OK translation=web books=0\n",
	} {
		t.Run(name, func(t *testing.T) {
			client := discoveryClient(t, map[string]string{"TRANSLATION CATALOG web": wire})
			if _, err := client.GetTranslationCatalog(context.Background(), "web"); err == nil {
				t.Fatal("accepted invalid catalogue")
			}
		})
	}
}
func TestTranslationDiscoveryErrorsAndArguments(t *testing.T) {
	for _, build := range []func(string) (Command, error){TranslationInfoCommand, TranslationCatalogCommand} {
		for _, slug := range []string{"", "web\nPING", "bad\"quote", "web\x00"} {
			if _, err := build(slug); err == nil {
				t.Fatalf("accepted %q", slug)
			}
		}
	}
	client := discoveryClient(t, map[string]string{"TRANSLATION CATALOG web": "ERR forbidden reason=scope\n"})
	_, err := client.GetTranslationCatalog(context.Background(), "web")
	var serverErr *ServerError
	if !errors.As(err, &serverErr) || serverErr.Code != "forbidden" || serverErr.Fields["reason"] != "scope" {
		t.Fatalf("%v", err)
	}
	client = discoveryClient(t, map[string]string{"TRANSLATION INFO web": "ERR translation_not_found\n"})
	if _, err := client.GetTranslationInfo(context.Background(), "web"); err == nil || !strings.Contains(err.Error(), "translation_not_found") {
		t.Fatalf("%v", err)
	}
}
