#!/usr/bin/env python3
"""Compare verse references and optionally create aligned translation copies.

Book identity is determined by canonical position, not translated book names.
This tool cannot detect differences in versification or verify verse content.
"""
import argparse
from collections import defaultdict
from pathlib import Path
import re

LINE = re.compile(r'^(.+?) (\d+):(\d+) (.+)$')
PLACEHOLDER = '[Verse not present in source translation]'


def read(path):
    books, seen, verses = [], set(), {}
    previous = (0, 0)
    with path.open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            match = LINE.fullmatch(line.rstrip('\r\n'))
            if not match:
                raise ValueError(f'{path}:{number}: invalid verse line')
            book, chapter, verse, text = match.groups()
            chapter, verse = int(chapter), int(verse)
            if not books or books[-1] != book:
                if book in seen or (chapter, verse) != (1, 1):
                    raise ValueError(f'{path}:{number}: invalid book boundary')
                books.append(book)
                seen.add(book)
                previous = (0, 0)
            if (chapter, verse) <= previous or not chapter or not verse:
                raise ValueError(f'{path}:{number}: duplicate or out-of-order reference')
            previous = chapter, verse
            verses[(len(books), chapter, verse)] = text
    if len(books) != 66:
        raise ValueError(f'{path}: expected 66 books, found {len(books)}')
    return books, verses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path, help='Reference translation in canonical order')
    parser.add_argument('translations', type=Path, nargs='+', help='Translations to compare')
    parser.add_argument('--output-dir', type=Path, help='Write aligned copies to a new directory')
    args = parser.parse_args()
    paths = [args.reference, *args.translations]
    if len({p.name for p in paths}) != len(paths):
        parser.error('input filenames must be distinct')
    try:
        data = [(path, *read(path)) for path in paths]
        all_refs = set().union(*(set(verses) for _, _, verses in data))
        chapters = defaultdict(int)
        for book, chapter, verse in all_refs:
            chapters[book, chapter] = max(chapters[book, chapter], verse)
        # The native index assumes contiguous verse numbers in each chapter.
        aligned = {(book, chapter, verse) for (book, chapter), last in chapters.items()
                   for verse in range(1, last + 1)}
        ref = set(data[0][2])
        for path, _, verses in data:
            refs = set(verses)
            print(f'{path}: {len(refs)} verses; {len(ref - refs)} missing from reference; '
                  f'{len(refs - ref)} extra; {len(aligned - refs)} placeholders needed')
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=False)
            for path, books, verses in data:
                with (args.output_dir / path.name).open('x', encoding='utf-8', newline='\n') as out:
                    for book, chapter, verse in sorted(aligned):
                        text = verses.get((book, chapter, verse), PLACEHOLDER)
                        out.write(f'{books[book - 1]} {chapter}:{verse} {text}\n')
            print(f'Aligned copies written to {args.output_dir}')
        print('Book order and verse meaning must be verified separately.')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'error: {exc}\n')


if __name__ == '__main__':
    main()
