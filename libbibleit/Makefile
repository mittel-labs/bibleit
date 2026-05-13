UNAME_S := $(shell uname -s)

CC      ?= cc
AR      ?= ar
CFLAGS  ?= -O2 -g -std=c99 -Wall -Wextra -pedantic
CPPFLAGS:= -Iinclude
LDFLAGS ?=

CFLAGS  += $(ARCHFLAGS)
LDFLAGS += $(ARCHFLAGS)

SRCS := src/bidx.c src/translation.c
OBJS := $(SRCS:src/%.c=build/%.o)

ifeq ($(UNAME_S),Darwin)
  SHLIB := libbibleit.dylib
  SHLIB_BUILD = $(CC) $(CPPFLAGS) $(CFLAGS) -dynamiclib $(LDFLAGS) -install_name @rpath/$(SHLIB) -o $(SHLIB) $(OBJS)
else
  SHLIB := libbibleit.so
  SOV   ?= 1
  VER   ?= 1.0.0
  SHLIB_FULL   := $(SHLIB).$(SOV).$(VER)
  SHLIB_SONAME := $(SHLIB).$(SOV)
  SHLIB_BUILD  = $(CC) -shared -Wl,-soname,$(SHLIB_SONAME) -o $(SHLIB_FULL) $(OBJS) $(LDFLAGS) && \
                 ln -sf $(SHLIB_FULL) $(SHLIB_SONAME) && ln -sf $(SHLIB_SONAME) $(SHLIB)
endif

.PHONY: all build clean
all: build
build: libbibleit.a $(SHLIB)

build/%.o: src/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -fPIC -c $< -o $@

libbibleit.a: $(OBJS)
	$(AR) rcs $@ $(OBJS)

$(SHLIB): $(OBJS)
	$(SHLIB_BUILD)

clean:
	rm -rf build libbibleit.a libbibleit.so* libbibleit.dylib

.PHONY: example
example: build/example
build/example: src/example.c libbibleit.a
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ $< ./libbibleit.a