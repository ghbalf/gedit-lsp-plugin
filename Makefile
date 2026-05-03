PLUGIN_NAME := gedit_lsp
PLUGIN_DIR  := $(HOME)/.local/share/gedit/plugins
VERSION     := $(shell python3 -c "import tomllib; print(tomllib.loads(open('pyproject.toml').read())['project']['version'])")

.PHONY: help install uninstall test test-integration lint typecheck pot mo dist clean

help:
	@echo "Targets:"
	@echo "  install            Copy plugin into $(PLUGIN_DIR)"
	@echo "  uninstall          Remove plugin and logs"
	@echo "  test               Run unit tests"
	@echo "  test-integration   Run integration tests (requires pylsp)"
	@echo "  lint               Run ruff"
	@echo "  typecheck          Run mypy"
	@echo "  pot                Regenerate po/gedit-lsp.pot"
	@echo "  mo                 Compile po/*.po → installed .mo"
	@echo "  dist               Build dist/gedit-lsp-plugin-$(VERSION).tar.gz"
	@echo "  clean              Remove build artefacts"

install:
	mkdir -p $(PLUGIN_DIR)
	cp -r src/$(PLUGIN_NAME) $(PLUGIN_DIR)/
	cp data/gedit-lsp.plugin $(PLUGIN_DIR)/
	@echo "Installed to $(PLUGIN_DIR). Restart gedit and enable in Preferences → Plugins."

uninstall:
	rm -rf $(PLUGIN_DIR)/$(PLUGIN_NAME)
	rm -f $(PLUGIN_DIR)/gedit-lsp.plugin
	rm -rf $(HOME)/.local/state/gedit-lsp
	@echo "Uninstalled. User config at ~/.config/gedit/lsp-plugin.json was NOT removed."

# Strip PYTHONPATH: a system-wide $PYTHONPATH (a pattern some shells set
# to /usr/lib/python3/dist-packages) prepends apt-installed packages to
# the venv's sys.path and shadows the venv's pinned versions, which
# breaks pytest 9.x against system pluggy 1.4.0.
test:
	env -u PYTHONPATH python -m pytest tests/unit

test-integration:
	@command -v pylsp >/dev/null 2>&1 || { echo "pylsp not on PATH; install with apt install python3-pylsp or pip install python-lsp-server" >&2; exit 1; }
	env -u PYTHONPATH python -m pytest tests/integration

lint:
	python -m ruff check src tests

typecheck:
	python -m mypy src

pot:
	xgettext --from-code=UTF-8 --keyword=_ --output=po/gedit-lsp.pot \
	    --files-from=po/POTFILES.in --add-comments=TRANSLATORS --package-name=gedit-lsp

mo:
	@for po in po/*.po; do \
	    [ -e "$$po" ] || continue; \
	    locale=$$(basename "$$po" .po); \
	    mkdir -p "$(PLUGIN_DIR)/locale/$$locale/LC_MESSAGES"; \
	    msgfmt "$$po" -o "$(PLUGIN_DIR)/locale/$$locale/LC_MESSAGES/gedit-lsp.mo"; \
	done

dist:
	mkdir -p dist
	tar --transform 's,^,gedit-lsp-plugin-$(VERSION)/,' \
	    -czf dist/gedit-lsp-plugin-$(VERSION).tar.gz \
	    src/$(PLUGIN_NAME) data/gedit-lsp.plugin Makefile install.sh \
	    README.md LICENSE CHANGELOG.md docs po
	cd dist && sha256sum gedit-lsp-plugin-$(VERSION).tar.gz > gedit-lsp-plugin-$(VERSION).tar.gz.sha256
	@echo "Built dist/gedit-lsp-plugin-$(VERSION).tar.gz"

clean:
	rm -rf dist build *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
