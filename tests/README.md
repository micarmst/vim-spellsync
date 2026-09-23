# Regression tests

The suite protects the public behaviour of `:SpellSync`, `spellsync#Run()`, and
the three `g:spellsync_*` options before changing the released implementation.
It uses Vim's built-in assertions and Python's standard-library `unittest`
runner. No test framework, plugin manager, Python package, or downloaded
dictionary is required.

These are mostly integration tests: they execute the real plugin, filesystem
operations, and spell compiler in Vim or Neovim. That boundary contains the
behaviour users depend on. They do not call private `s:` functions, mock
`:mkspell`, or depend on the internal organisation of the plugin. If pure
parsing or decision-making helpers are introduced later, smaller unit tests
can supplement these tests.

## Running

From the repository root, using Python 3.8 or newer:

```sh
python3 tests/test_spellsync.py --editor vim -v
python3 tests/test_spellsync.py --editor nvim -v
```

On Windows, use `python` or `py -3` in place of `python3`. An absolute editor
executable path is also accepted. The runner detects Vim versus Neovim from
the executable's version output. A missing editor is an error, not a skipped
test run.

To run one test:

```sh
python3 tests/test_spellsync.py --editor nvim -v \
  SpellSyncTests.test_new_custom_binary_becomes_active_without_restart
```

Assertion failures and unexpected Vimscript exceptions produce a nonzero exit
status, with the editor's output and verbose log included in the failure report.
Each editor invocation has a 20-second timeout. Temporary files are removed
after each test, including failed tests.

## Coverage

The 53 tests cover:

- Command registration, default options, and preservation of explicit options.
- Automatic syncing through the actual `VimEnter` event, startup opt-out, and
  invocation through both public entry points.
- Multiple runtime spell directories, multiple custom word lists, relative
  paths, spaces and escaped commas in paths, and missing/empty configurations.
- Discovery independent of `'wildignore'`, including broken source symlinks,
  and leaving runtime spell directories without word lists alone.
- Missing binaries and stale binaries, including additions and removals that
  become visible to spell checking during the same editor session.
- Already-current runtime and first custom dictionaries remaining unchanged
  on disk, including after repeated syncing.
- Generated Git rules in runtime and custom directories, preservation of
  existing files (including empty and unreadable ones), symlinks and their
  targets (including dangling links), directories at Git configuration paths,
  and independent Git option opt-outs.
- Preservation of word-list text, banned-word flags, Unicode words, and
  temporary words added with `:spellgood!`.
- Refreshing new dictionaries with an empty `'spellfile'` or a missing first
  custom entry, while preserving the old reload marker as a real word.
- Runtime additions across multiple directories, language regions, and ASCII
  fallback, without preloading unrelated languages.
- Preservation of local/global spell options and disabled spell checking,
  without artificial `OptionSet` events during refresh.
- Rebuilt dictionaries remaining active in other windows that already use them.
- Read-only sources, unreadable sources, unwritable binaries and directories,
  and updating an existing writable binary in a read-only directory.
- Path-specific warnings in `:messages`, compiler and write-time errors,
  and continuing with other dictionaries after failures, including at startup.
- Preserving source/binary symlinks and rejecting directories and named pipes
  as dictionary inputs or outputs without opening them, including during
  refresh while spell checking is enabled.

The stale-custom-file test deliberately uses an entry after the first one in
`'spellfile'` to ensure syncing processes more than just the first entry.
The test runner allows nested events during assertions so option-event checks
exercise the same hooks that can run during a manual `:SpellSync` invocation.
The write-time-error test uses Vim's sandbox to deny writes after permission
checks pass, exercising actual error handling without mocking file operations.

## Isolation and repeatability

Every test gets a fresh temporary directory and a copy of `plugin/` and
`autoload/`. Each editor invocation starts with `-u NONE`, no viminfo/ShaDa,
no swap files, an empty package path, and a runtime path containing only test
fixtures. Neovim's XDG directories and log file also point into the temporary
directory. The working directory and the default test `'spellfile'` are there
too. The developer's home directory is not changed.

Tests that need spell recognition compile a tiny synthetic base dictionary.
They never load the system spelling plugin or depend on English spell files
being installed. Tests compare spell recognition and source-file content;
they do not snapshot the editor-specific binary format.

Timestamp tests use explicit, widely separated modification times set by
Python's `os.utime()`. No sleeps or filesystem timing races are needed. Editor
processes are separate so loaded dictionaries and script-local state do not
leak between tests.

Permission tests require POSIX permissions and are skipped when the current
user bypasses the requested restrictions (for example, as root).
Symlink tests are skipped when the system does not support or permit creating
them. Named-pipe tests require POSIX support. These skips are reported by the
test runner.

## Existing defects and future tests

A passing baseline does not mean every known defect has been fixed. The
following cases should get a failing regression test as part of their fix;
the suite intentionally does not assert that these undesirable behaviours
must continue:

| Case | Desired regression assertion |
| --- | --- |
| Repeated/late loading | Registration is idempotent and late loading follows the agreed automatic/manual policy. |
| Timestamp equality/restores | A force-rebuild command or stronger detection handles content changes missed by modification times. |

For each fix: add a test that fails on the existing implementation, make the
smallest change needed, and run the whole suite in both editors. Keep the new
test as a normal passing test. Assertions for permissions should account for
Windows permission semantics and privileged Unix users.

Changes to which buffers are scanned, the Git merge policy, automatic event
selection, or public defaults need an explicit behaviour decision before
writing their expected results. The current suite does not promise a particular
private implementation or broaden the plugin's scope.

## CI and compatibility

The GitHub Actions workflow runs both editors on Linux, macOS, and Windows.
It requests `stable` from `rhysd/action-setup-vim`; that action uses a current
Windows Vim build because it does not provide a stable Windows Vim channel.
Each job prints the actual editor version.

The matrix also tests the compatibility baselines, Vim 8.2.1926 and Neovim
0.5.0, on Linux. Running against an older executable locally uses the same
`--editor` argument. Vim before 9.1.0783 and Neovim before 0.11 need 'isfname' to include backslash
when assigning escaped commas to 'spellfile'; the custom-path fixture applies
that editor workaround, while the runtime-path test verifies that the plugin
handles it and restores 'isfname'. Windows warning assertions normalize path
separators, and preservation tests compare the original bytes (including the
fixture's native line endings). The test tooling's Python requirement does
not add a runtime dependency to the plugin.

## Framework choices

[Vim's native assertions](https://vimhelp.org/testing.txt.html#assert-functions-details)
are sufficient for this suite. [Vader](https://github.com/junegunn/vader.vim)
provides a convenient format for buffer contents and keystroke-driven tests;
[Themis](https://github.com/thinca/vim-themis) provides a fuller Vimscript test
framework. Either would be reasonable if the testing needs grow. The current
choice keeps the tests runnable with an editor and standard Python tooling.
