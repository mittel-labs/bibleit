from __future__ import annotations
import os
import platform
from importlib.resources import files

from ctypes import (
    CDLL,
    c_char_p,
    c_char,
    c_uint8,
    c_uint32,
    c_size_t,
    c_int,
    POINTER,
    Structure,
)
import ctypes


def _lib_name() -> str:
    plat = platform.system()
    if plat == "Darwin":
        return "libbibleit.dylib"
    return "libbibleit.so"


def _load_lib():
    libpath = files(__package__).joinpath("_native").joinpath(_lib_name())
    override = os.getenv("BIBLEIT_LIB")
    path = override or os.fspath(libpath)
    if not os.path.exists(path):
        raise OSError(f"libbibleit not found at {path}")
    return CDLL(path)


libbibleit = _load_lib()


class BidxFile(Structure):
    pass


class BidxRef(Structure):
    _fields_ = [
        ("book", c_uint8),
        ("chapter", c_uint8),
        ("verse", c_uint8),
    ]


class BidxRecordView(Structure):
    _fields_ = [
        ("ptr", POINTER(c_char)),
    ]


class BidxIter(Structure):
    _fields_ = [
        ("f", POINTER(BidxFile)),
        ("start", POINTER(c_char)),
        ("end", POINTER(c_char)),
        ("ptr", POINTER(c_char)),
    ]


libbibleit.bidx_open.argtypes = [c_char_p]
libbibleit.bidx_open.restype = POINTER(BidxFile)

libbibleit.bidx_close.argtypes = [POINTER(BidxFile)]
libbibleit.bidx_close.restype = None

libbibleit.bidx_version.argtypes = [POINTER(BidxFile)]
libbibleit.bidx_version.restype = c_int

libbibleit.bidx_count.argtypes = [POINTER(BidxFile)]
libbibleit.bidx_count.restype = c_size_t

libbibleit.bidx_read.argtypes = [POINTER(BidxFile), BidxRef, POINTER(c_uint32)]
libbibleit.bidx_read.restype = c_int

libbibleit.bidx_create.argtypes = [c_char_p, c_char_p]
libbibleit.bidx_create.restype = c_int


libbibleit.bidx_iter_init.argtypes = [
    POINTER(BidxIter),
    POINTER(BidxFile),
    BidxRef,
]
libbibleit.bidx_iter_init.restype = c_int


libbibleit.bidx_iter_init_chapter.argtypes = [
    POINTER(BidxIter),
    POINTER(BidxFile),
    c_uint8,
    c_uint8,
]
libbibleit.bidx_iter_init_chapter.restype = c_int


libbibleit.bidx_iter_init_book.argtypes = [
    POINTER(BidxIter),
    POINTER(BidxFile),
    c_uint8,
]
libbibleit.bidx_iter_init_book.restype = c_int


libbibleit.bidx_iter_next.argtypes = [
    POINTER(BidxIter),
    POINTER(BidxRecordView),
]
libbibleit.bidx_iter_next.restype = c_int


libbibleit.bidx_iter_previous.argtypes = [
    POINTER(BidxIter),
    POINTER(BidxRecordView),
]
libbibleit.bidx_iter_previous.restype = c_int

libbibleit.bidx_view_book.argtypes = [BidxRecordView]
libbibleit.bidx_view_book.restype = c_uint8

libbibleit.bidx_view_chapter.argtypes = [BidxRecordView]
libbibleit.bidx_view_chapter.restype = c_uint8

libbibleit.bidx_view_verse.argtypes = [BidxRecordView]
libbibleit.bidx_view_verse.restype = c_uint8

libbibleit.bidx_view_offset.argtypes = [BidxRecordView]
libbibleit.bidx_view_offset.restype = c_uint32


class BtFile(Structure):
    pass


class BtRecordView(Structure):
    _fields_ = [
        ("ptr", POINTER(c_char)),
        ("len", c_size_t),
    ]


libbibleit.bt_open.argtypes = [c_char_p]
libbibleit.bt_open.restype = POINTER(BtFile)

libbibleit.bt_close.argtypes = [POINTER(BtFile)]
libbibleit.bt_close.restype = None

libbibleit.bt_read_view.argtypes = [
    POINTER(BtFile),
    c_uint32,
    POINTER(BtRecordView),
]
libbibleit.bt_read_view.restype = c_int


# optional legacy API
libbibleit.bt_read.argtypes = [
    POINTER(BtFile),
    c_uint32,
    c_char_p,
    c_size_t,
]
libbibleit.bt_read.restype = c_int


def bt_view_to_str(v: BtRecordView) -> str:
    return bytes(v.ptr[: v.len]).decode("utf-8")


def bidx_ref(book: int, chapter: int, verse: int) -> BidxRef:
    return BidxRef(book=book, chapter=chapter, verse=verse)


class BtView:
    __slots__ = ("ptr", "len")

    def __init__(self, ptr, length):
        self.ptr = ptr
        self.len = length

    def memoryview(self):
        addr = ctypes.cast(self.ptr, ctypes.c_void_p).value
        return memoryview((ctypes.c_char * self.len).from_address(addr))

    def bytes(self):
        return self.memoryview().tobytes()

    def __bytes__(self):
        return self.bytes()

    def decode(self, encoding="utf-8", errors="replace"):
        return self.memoryview().tobytes().decode(encoding, errors)

    def __repr__(self):
        return f"BtView(len={self.len})"
