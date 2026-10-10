package bibleit

import (
	"context"
	"fmt"
)

type TranslationInfo struct {
	ShortName, FullName                             string
	Edition, Updated                                string
	RightsStatus, RightsLabel, RightsURL, SourceURL string
	Attribution, TrademarkNotice                    string
	Raw                                             Response
}
type CatalogChapter struct {
	Number, Verses int64
	Fields         map[string]string
}
type CatalogBook struct {
	ID       int64 // Server source book identifier; not the book's position in Books.
	Name     string
	Chapters []CatalogChapter
	Fields   map[string]string
}
type TranslationCatalog struct {
	Translation string
	Books       []CatalogBook
	Raw         Response
}

func (c *Client) GetTranslationInfo(ctx context.Context, slug string) (TranslationInfo, error) {
	cmd, err := TranslationInfoCommand(slug)
	if err != nil {
		return TranslationInfo{}, err
	}
	result, err := c.Execute(ctx, cmd)
	if err != nil {
		return TranslationInfo{}, err
	}
	fields, err := single(result)
	if err != nil {
		return TranslationInfo{}, err
	}
	value := TranslationInfo{Raw: result, Edition: fields["edition"], Updated: fields["updated"], RightsStatus: fields["rights_status"], RightsLabel: fields["rights_label"], RightsURL: fields["rights_url"], SourceURL: fields["source_url"], Attribution: fields["attribution"], TrademarkNotice: fields["trademark_notice"]}
	value.ShortName, err = required(fields, "short_name")
	if err != nil {
		return TranslationInfo{}, err
	}
	value.FullName, err = required(fields, "full_name")
	if err != nil {
		return TranslationInfo{}, err
	}
	return value, nil
}
func positive(fields map[string]string, key string) (int64, error) {
	value, err := number(fields, key)
	if err != nil {
		return 0, err
	}
	if value == 0 {
		return 0, fmt.Errorf("invalid response field %q: expected a positive integer", key)
	}
	return value, nil
}
func (c *Client) GetTranslationCatalog(ctx context.Context, slug string) (TranslationCatalog, error) {
	cmd, err := TranslationCatalogCommand(slug)
	if err != nil {
		return TranslationCatalog{}, err
	}
	result, err := c.Execute(ctx, cmd)
	if err != nil {
		return TranslationCatalog{}, err
	}
	return translationCatalog(result)
}
func translationCatalog(result Response) (TranslationCatalog, error) {
	if len(result.Records) == 0 || result.Records[0].Type != "ok" {
		return TranslationCatalog{}, fmt.Errorf("expected a catalogue OK header")
	}
	header := result.Records[0].Fields
	slug, err := required(header, "translation")
	if err != nil {
		return TranslationCatalog{}, err
	}
	bookCount, err := number(header, "books")
	if err != nil {
		return TranslationCatalog{}, err
	}
	value := TranslationCatalog{Translation: slug, Books: []CatalogBook{}, Raw: result}
	seenBooks := map[int64]bool{}
	seenChapters := map[int64]bool{}
	var expectedChapters int64
	finishBook := func() error {
		if len(value.Books) > 0 && int64(len(value.Books[len(value.Books)-1].Chapters)) != expectedChapters {
			return fmt.Errorf("catalogue chapter count does not match book records")
		}
		return nil
	}
	for _, record := range result.Records[1:] {
		id, err := positive(record.Fields, "book")
		if err != nil {
			return TranslationCatalog{}, err
		}
		switch record.Type {
		case "book":
			if err := finishBook(); err != nil {
				return TranslationCatalog{}, err
			}
			if seenBooks[id] {
				return TranslationCatalog{}, fmt.Errorf("duplicate catalogue book %d", id)
			}
			seenBooks[id] = true
			name, err := required(record.Fields, "name")
			if err != nil {
				return TranslationCatalog{}, err
			}
			expectedChapters, err = number(record.Fields, "chapters")
			if err != nil {
				return TranslationCatalog{}, err
			}
			value.Books = append(value.Books, CatalogBook{ID: id, Name: name, Chapters: []CatalogChapter{}, Fields: record.Fields})
			seenChapters = map[int64]bool{}
		case "chapter":
			if len(value.Books) == 0 || value.Books[len(value.Books)-1].ID != id {
				return TranslationCatalog{}, fmt.Errorf("catalogue chapter does not belong to current book")
			}
			chapter, err := positive(record.Fields, "chapter")
			if err != nil {
				return TranslationCatalog{}, err
			}
			verses, err := positive(record.Fields, "verses")
			if err != nil {
				return TranslationCatalog{}, err
			}
			if seenChapters[chapter] {
				return TranslationCatalog{}, fmt.Errorf("duplicate catalogue chapter %d", chapter)
			}
			seenChapters[chapter] = true
			book := &value.Books[len(value.Books)-1]
			book.Chapters = append(book.Chapters, CatalogChapter{Number: chapter, Verses: verses, Fields: record.Fields})
		default:
			return TranslationCatalog{}, fmt.Errorf("unexpected catalogue record %s", record.Type)
		}
	}
	if err := finishBook(); err != nil {
		return TranslationCatalog{}, err
	}
	if int64(len(value.Books)) != bookCount {
		return TranslationCatalog{}, fmt.Errorf("catalogue book count does not match records")
	}
	return value, nil
}
