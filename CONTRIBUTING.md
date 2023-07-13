# Contributing

## Adding a new Bible translation

Right now we use open bibles from [Bolls Life API](https://bolls.life/api/).
If you want to add one bible from there, you can use the script in the tools folder
by following the steps below:

1. Check which translations are available from the file [tools/bolls/translations.json](tools/bolls/translations.json).
2. Run the script [tools/bolls_org_dw.py](tools/bolls_org_dw.py) with the translation you want to add.
Example: `python tools/bolls_org_dw.py nvi`.
3. The script will generate files in the folder [tools/bolls/bibles/<your_translation>](tools/bolls/bibles/).
4. Run the script `python tools/bolls_fix_skip_verses.py <your_translation>` to fix the verses that are skipped
on your translation.
5. Run the script `concatenate.sh` to remove all empty lines and clean the file, i.e. `cd tools && ./concatenate.sh <path/to/translation/folder>`.
6. Now you need to compare the final file against a valid translation with the diff scripts:
`cd tools && ./gen-diff <your_translation> nvi && python bible_diff.py nvi <your_translation>`.
7. If there are no differences, you are ready to go! Just open the PR with the new translation.
8. If there are differences, you need to check the diff output and fix the chapters that do not match in number of verses.
