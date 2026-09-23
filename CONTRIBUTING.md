# Contributing

Contributions are welcome. Keep changes focused and preserve compatibility
with existing commands, configuration options, and defaults.

## Running the tests

The regression suite needs Python 3.8 or newer and the selected editor, with
no additional Python packages or test plugins. From the repository root, run
it against both Vim and Neovim:

```sh
python3 tests/test_spellsync.py --editor vim -v
python3 tests/test_spellsync.py --editor nvim -v
```

On Windows, use `python` or `py -3` in place of `python3`.

For a bug fix, first add a regression test that demonstrates the failure,
then make the change and run the full suite in both editors. Update the
user-facing README and Vim help when documented behaviour changes.

See [tests/README.md](tests/README.md) for coverage, test isolation, CI,
individual test execution, and known defects awaiting regression tests.
