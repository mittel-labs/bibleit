import os
import requests
import json
import argparse


class BibleDownloader:
    def __init__(self, base_dir, translation):
        self.base_dir = base_dir
        self.translation = translation
        self.output_dir = f"{base_dir}/{translation}"
        self.books_data = self.load_books_data()
        self.base_url = "https://bolls.life"
        self.url_whole_bible = f"/static/translations/{translation}.json"

    @staticmethod
    def load_books_data():
        with open("bolls/books.json") as f:
            return json.load(f)

    def create_output_dir(self):
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

    def write_book_file(self, bid, name, lines):
        name_normalized = name.replace(" ", "_").replace("/", "_")
        file_name = f"{self.output_dir}/{bid}_{name_normalized}.txt"
        with open(file_name, "w") as file:
            file.writelines(lines)

    def download_bible(self):
        url = f"{self.base_url}{self.url_whole_bible}"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()

    def process_bible(self, bible_translation):
        book_lines = []
        cur_book = 1
        book_name = self.books_data[self.translation][cur_book - 1]["name"]

        for verse in bible_translation:
            book_id = verse["book"]

            if book_id != cur_book:
                book_name = self.books_data[self.translation][cur_book - 1]["name"]
                print(f"Finished processing {book_name}")
                self.write_book_file(cur_book, book_name, book_lines)
                book_lines = []
                book_name = self.books_data[self.translation][book_id - 1]["name"]

            book_chapter = verse["chapter"]
            book_lines.append(
                f"{book_name} {book_chapter}:{verse['verse']} {verse['text']}\n"
            )
            cur_book = book_id

        book_name = self.books_data[self.translation][cur_book - 1]["name"]
        print(f"Finished processing {book_name}")
        self.write_book_file(cur_book, book_name, book_lines)

    def download_and_process_bible(self):
        self.create_output_dir()
        bible_translation = self.download_bible()
        self.process_bible(bible_translation)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download and process bible")
    parser.add_argument(
        "translation",
        type=str,
        help="Translation to download and process. Must be one of the translations from the file "
        "bolls/translations.json",
    )
    args = parser.parse_args()

    if not args.translation:
        parser.print_help()
        exit()

    base_dir = "bolls/bibles"
    translation = args.translation
    downloader = BibleDownloader(base_dir, translation)
    downloader.download_and_process_bible()
