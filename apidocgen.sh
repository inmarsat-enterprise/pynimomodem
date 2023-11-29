#!/bin/bash
pdoc --html pynimomodem --output-dir docs --force
mv ./docs/pynimomodem/* ./docs
rm -r ./docs/pynimomodem
