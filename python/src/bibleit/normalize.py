import re

_ACCENTS = {
    "À": "A",
    "Á": "A",
    "Â": "A",
    "Ã": "A",
    "Ä": "A",
    "à": "a",
    "á": "a",
    "â": "a",
    "ã": "a",
    "ä": "a",
    "ª": "A",
    "È": "E",
    "É": "E",
    "Ê": "E",
    "Ë": "E",
    "è": "e",
    "é": "e",
    "ê": "e",
    "ë": "e",
    "Í": "I",
    "Ì": "I",
    "Î": "I",
    "Ï": "I",
    "í": "i",
    "ì": "i",
    "î": "i",
    "ï": "i",
    "Ò": "O",
    "Ó": "O",
    "Ô": "O",
    "Õ": "O",
    "Ö": "O",
    "ò": "o",
    "ó": "o",
    "ô": "o",
    "õ": "o",
    "ö": "o",
    "º": "O",
    "Ù": "U",
    "Ú": "U",
    "Û": "U",
    "Ü": "U",
    "ù": "u",
    "ú": "u",
    "û": "u",
    "ü": "u",
    "Ñ": "N",
    "ñ": "n",
    "Ç": "C",
    "ç": "c",
    "§": "S",
    "³": "3",
    "²": "2",
    "¹": "1",
}
_NORMALIZE = str.maketrans(_ACCENTS)
_REF_REGEX = re.compile(r"[^a-zA-Z0-9:\s\+\-\^]")


def normalize(text):
    return text.lower().translate(_NORMALIZE).strip() if text else None


def normalize_ref(ref):
    return _REF_REGEX.sub("", ref)
