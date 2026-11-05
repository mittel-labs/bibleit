# Set up Bibleit on a new laptop

These steps install the terminal operator, import the NVI, NIV, and LUT files in this repository, and run a local browser viewer. Internet access is needed for the initial clone and installation; the imported translations can then be read offline.

## 1. Install prerequisites

Install Git, Python 3.11 or newer (including `venv`), GNU Make, and a C compiler. On Debian or Ubuntu, for example:

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-dev build-essential
```

On macOS, install the Xcode command-line tools (`xcode-select --install`) and Python 3.11 or newer.

## 2. Clone and install

```bash
git clone --recurse-submodules --branch feat/local-translation-import https://github.com/mittel-labs/bibleit.git
cd bibleit
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install ./python
```

In each new terminal, return to the repository and activate the environment with `. .venv/bin/activate`. If the repository was already cloned without its submodule, run `git submodule update --init --recursive` before installing.

## 3. Import and check the translations

Run these commands from the repository root with the environment activated:

```bash
bibleit --import-translation translations/nvi --slug LOCALNVI --name NVI
bibleit --import-translation translations/niv --slug LOCALNIV --name NIV
bibleit --import-translation translations/lut --slug LOCALLUT --name LUT
bibleit --list-translations
bibleit -t LOCALNVI 'João 3:16'
bibleit -t LOCALNIV 'John 3:16'
bibleit -t LOCALLUT 'Johannes 3:16'
```

Imports copy the files and their indexes into `~/.bibleit`. You only need to import them once per user account. To read in the terminal interface, run `bibleit`, press **Ctrl+T**, and open the translations from **Installed**. The files must contain books in canonical order; the importer does not verify the names or order of those books.

## 4. Run the local live viewer

In one terminal, from the repository root:

```bash
. .venv/bin/activate
bibleit --live 127.0.0.1 8000
```

Open <http://127.0.0.1:8000> on the same laptop. In a second terminal:

```bash
cd /path/to/bibleit
. .venv/bin/activate
BIBLEIT_LIVE_URL=http://127.0.0.1:8000 bibleit
```

Open a translation and press **Ctrl+L** to publish to the viewer. Stop the relay with Ctrl+C in its terminal. For viewers on other devices, bind the relay to an appropriate network interface and open the laptop's reachable network address on port 8000; `127.0.0.1` is accessible only on the laptop itself.
