# bibleit

Interactive Bible reading.

## How to run

```
$ python -m bibleit

usage: bibleit [-h] [--version] [--repl] [--linesep value] [--bible value] [--debug] [--screen] [--textwrap] [--bold] [--label] [args ...]

positional arguments:
  args             Arguments to be evaluated

options:
  -h, --help       show this help message and exit
  --version        show program's version number and exit
  --repl           Opens bibleit REPL
  --linesep value  Configure line separator
  --bible value    Use one or more Bible translations
  --debug          Enable debug flag
  --screen         Enable screen flag
  --textwrap       Enable textwrap flag
  --bold           Enable bold flag
  --label          Enable label flag
```

## REPL

Bibleit has an interactive interpreter in order to interact with the Bible.

You can use `--repl` argument:

```sh
python -m bibleit --repl
```

Or run directly from `bibleit.repl` module:

```sh
python -m bibleit.repl
```

After that you're going to see a console, so that you can start typing commands:

![](repl.gif)

## Contributing

Contributions are very welcome! Check our [Contributing](CONTRIBUTING.md) guide.
