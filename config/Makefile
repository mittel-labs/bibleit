TRANSLATION_DIR := $(HOME)/.bibleit

CONFIG_FILES_BASE_URI := https://bolls.life/static/bolls/app/views
CONFIG_FILES := dictionaries.json languages.json translations_books.json

TRANSLATIONS := KJV NVIPT
TRANSLATIONS_BASE_URI := https://bolls.life/static/translations

TRANSLATION_FILES := $(addsuffix .bt,$(TRANSLATIONS))

all: $(CONFIG_FILES) $(TRANSLATION_FILES)

$(CONFIG_FILES):
	wget -O $@ $(CONFIG_FILES_BASE_URI)/$@

%.bt:
	wget -O $@ $(TRANSLATIONS_BASE_URI)/$*.json

install: all
	mkdir -p $(TRANSLATION_DIR)
	cp $(CONFIG_FILES) $(TRANSLATION_FILES) $(TRANSLATION_DIR)

clean:
	rm -f $(CONFIG_FILES) $(TRANSLATION_FILES)