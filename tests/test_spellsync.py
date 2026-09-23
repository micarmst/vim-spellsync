"""Exercise the public plugin API in an isolated, real Vim or Neovim process."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO = Path(__file__).resolve().parents[1]
EDITOR = "vim"


def vim_string(value):
    return "'" + str(value).replace("'", "''") + "'"


class SpellSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.editor = shutil.which(EDITOR)
        if not cls.editor:
            raise RuntimeError("Editor not found: " + EDITOR)
        with tempfile.TemporaryDirectory(prefix="spellsync-version-") as directory:
            version = subprocess.run(
                [cls.editor, "--version"], capture_output=True, text=True,
                check=True, timeout=10, cwd=directory,
                env=dict(os.environ, NVIM_LOG_FILE=str(Path(directory) / "nvim.log")),
            ).stdout.splitlines()[0]
        cls.flags = ["--headless"] if version.startswith("NVIM") else ["-N", "-es"]
        print("\nTesting with " + version, flush=True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="spellsync-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.runtime = self.root / "runtime"
        # Even the plugin is copied: runtime discovery must never write to the
        # checkout, another installed plugin, or the editor's system runtime.
        for directory in ("plugin", "autoload"):
            shutil.copytree(REPO / directory, self.runtime / directory)
        self.env = os.environ.copy()
        for name in ("CONFIG", "DATA", "CACHE", "STATE"):
            self.env["XDG_" + name + "_HOME"] = str(self.root / name.lower())
        self.env["NVIM_LOG_FILE"] = str(self.root / "nvim.log")
        self.env.pop("NVIM_APPNAME", None)

    def wordlist(self, name="runtime/spell/ssbase.utf-8.add", words=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(words or ["spellsyncword"]) + "\n", encoding="utf-8")
        return path

    def vim(self, after, before="", startup=0, options=None):
        """Set up before plugin loading; make assertions after real VimEnter."""
        settings = dict(options or {})
        if startup is not None:
            settings["spellsync_run_at_startup"] = startup
        config = "\n".join("let g:%s = %d" % item for item in settings.items())
        script = self.root / "test.vim"
        result = self.root / "result.json"
        log = self.root / "editor.log"
        # A test may use a separate editor invocation to prepare a stale binary.
        for path in (result, log):
            if path.exists():
                path.unlink()
        script.write_text(textwrap.dedent("""
            set nocompatible
            set encoding=utf-8
            set nomore noswapfile nobackup nowritebackup
            set packpath=
            let g:test_root = ROOT
            let &runtimepath = escape(g:test_root . '/runtime', ',')
            let &spellfile = g:test_root . '/unused.utf-8.add'

            function! TestFinish() abort
              call writefile([json_encode(v:errors)], g:test_root . '/result.json')
              if !empty(v:errors)
                cquit
              endif
              qa!
            endfunction

            function! TestSpelling() abort
              " Supply a tiny base dictionary instead of depending on an
              " installed/downloaded English dictionary or system runtime.
              call mkdir(g:test_root . '/runtime/spell', 'p')
              call writefile(['baselineword'], g:test_root . '/base.words')
              execute 'silent mkspell! ' . fnameescape(g:test_root . '/runtime/spell/ssbase.utf-8.spl') . ' ' . fnameescape(g:test_root . '/base.words')
              setlocal spelllang=ssbase spell
              call assert_equal(['', ''], spellbadword('baselineword'))
            endfunction

            function! TestAfterStartup() abort
              try
                call assert_equal(1, v:vim_did_enter, 'Test must run after startup')
                AFTER
              catch
                call assert_report(v:exception . ' at ' . v:throwpoint)
              endtry
              call TestFinish()
            endfunction

            try
              CONFIG
              BEFORE
              runtime plugin/spellsync.vim
              augroup SpellSyncTests
                autocmd VimEnter * call TestAfterStartup()
              augroup END
            catch
              call assert_report(v:exception . ' at ' . v:throwpoint)
              call TestFinish()
            endtry
        """).replace("ROOT", vim_string(self.root.as_posix()))
            .replace("CONFIG", config).replace("BEFORE", before).replace("AFTER", after),
            encoding="utf-8")
        completed = subprocess.run(
            [self.editor, *self.flags, "-n", "-u", "NONE", "-i", "NONE",
             "-V1" + str(log), "-S", str(script)],
            cwd=self.root, env=self.env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
        diagnostics = completed.stdout + completed.stderr
        if log.exists():
            diagnostics += log.read_text(encoding="utf-8", errors="replace")
        self.assertTrue(result.exists(), "Editor did not finish the test:\n" + diagnostics)
        errors = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual([], errors, "\n".join(errors) + "\n" + diagnostics)
        self.assertEqual(0, completed.returncode, diagnostics)

    def compile(self, path):
        self.vim("execute 'silent mkspell! ' . fnameescape(" + vim_string(path.as_posix()) + ")")

    def test_command_and_default_options(self):
        self.vim("""
            call assert_equal(2, exists(':SpellSync'))
            call assert_equal(1, g:spellsync_run_at_startup)
            call assert_equal(1, g:spellsync_enable_git_union_merge)
            call assert_equal(1, g:spellsync_enable_git_ignore)
        """, startup=None)

    def test_explicit_options_are_preserved(self):
        self.wordlist()
        self.vim("""
            call assert_equal(0, g:spellsync_run_at_startup)
            call assert_equal(0, g:spellsync_enable_git_union_merge)
            call assert_equal(0, g:spellsync_enable_git_ignore)
            SpellSync
        """, options={"spellsync_enable_git_union_merge": 0, "spellsync_enable_git_ignore": 0})
        self.assertFalse((self.runtime / "spell/.gitignore").exists())
        self.assertFalse((self.runtime / "spell/.gitattributes").exists())

    def test_startup_builds_missing_binary(self):
        path = self.wordlist()
        self.vim("call assert_true(filereadable(g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'))", startup=None)
        self.assertTrue(Path(str(path) + ".spl").is_file())

    def test_startup_can_be_disabled_without_disabling_command(self):
        self.wordlist()
        self.vim("""
            call assert_false(filereadable(g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'))
            SpellSync
            call assert_true(filereadable(g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'))
        """)

    def test_startup_builds_configured_spellfile(self):
        self.wordlist("custom/words.utf-8.add")
        self.vim("""
            call assert_true(filereadable(g:test_root . '/custom/words.utf-8.add.spl'))
            call TestSpelling()
            call assert_equal(['', ''], spellbadword('spellsyncword'))
        """, before="let &spellfile = g:test_root . '/custom/words.utf-8.add'", startup=None)

    def test_public_autoload_function(self):
        self.wordlist()
        self.vim("""
            call spellsync#Run()
            call assert_true(filereadable(g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'))
        """)

    def test_all_runtime_directories_and_wordlists(self):
        paths = [self.wordlist(name) for name in (
            "runtime/spell/ssbase.utf-8.add", "runtime/spell/other.utf-8.add",
            "second-runtime/spell/ssbase.utf-8.add",
        )]
        self.vim("SpellSync", before="let &runtimepath .= ',' . escape(g:test_root . '/second-runtime', ',')")
        for path in paths:
            self.assertTrue(Path(str(path) + ".spl").is_file(), str(path))

    def test_multiple_custom_spellfiles(self):
        for name in ("one", "two"):
            self.wordlist("custom/" + name + ".utf-8.add", ["spellsync" + name])
        self.vim("""
            SpellSync
            call assert_true(filereadable(g:test_root . '/custom/one.utf-8.add.spl'))
            call assert_true(filereadable(g:test_root . '/custom/two.utf-8.add.spl'))
            call TestSpelling()
            call assert_equal(['', ''], spellbadword('spellsyncone'))
            call assert_equal(['', ''], spellbadword('spellsynctwo'))
        """, before="let &spellfile = g:test_root . '/custom/one.utf-8.add,' . g:test_root . '/custom/two.utf-8.add'")

    def test_custom_path_with_spaces(self):
        self.wordlist("custom words/my words.utf-8.add")
        self.vim("""
            SpellSync
            call TestSpelling()
            call assert_equal(['', ''], spellbadword('spellsyncword'))
        """, before="let &spellfile = g:test_root . '/custom words/my words.utf-8.add'")

    def test_relative_custom_path(self):
        self.wordlist("custom/words.utf-8.add")
        self.vim("""
            SpellSync
            call TestSpelling()
            call assert_equal(['', ''], spellbadword('spellsyncword'))
        """, before="let &spellfile = 'custom/words.utf-8.add'")

    def test_missing_custom_wordlist_is_not_created(self):
        self.vim("SpellSync", before="let &spellfile = g:test_root . '/missing/words.utf-8.add'")
        self.assertFalse((self.root / "missing").exists())

    def test_empty_configuration(self):
        self.vim("SpellSync", before="set spellfile=")
        self.assertFalse((self.runtime / "spell").exists())

    def test_creates_git_rules_in_runtime_and_custom_directories(self):
        self.wordlist()
        self.wordlist("custom/words.utf-8.add")
        self.vim("SpellSync", before="let &spellfile = g:test_root . '/custom/words.utf-8.add'")
        for directory in (self.runtime / "spell", self.root / "custom"):
            self.assertEqual(
                ["# Generated by vim-spellsync", "*.spl", "*.sug"],
                (directory / ".gitignore").read_text().splitlines(),
            )
            self.assertEqual(
                ["# Generated by vim-spellsync", "*.add merge=union"],
                (directory / ".gitattributes").read_text().splitlines(),
            )

    def test_preserves_existing_git_files_including_empty_files(self):
        self.wordlist()
        self.wordlist("second-runtime/spell/ssbase.utf-8.add")
        originals = {}
        for directory, content in ((self.runtime / "spell", b"user content\n"),
                                   (self.root / "second-runtime/spell", b"")):
            for name in (".gitignore", ".gitattributes"):
                path = directory / name
                path.write_bytes(content)
                originals[path] = content
        self.vim("SpellSync", before="let &runtimepath .= ',' . escape(g:test_root . '/second-runtime', ',')")
        for path, content in originals.items():
            self.assertEqual(content, path.read_bytes())

    def test_git_ignore_can_be_disabled_independently(self):
        self.wordlist()
        self.vim("SpellSync", options={"spellsync_enable_git_ignore": 0})
        self.assertFalse((self.runtime / "spell/.gitignore").exists())
        self.assertTrue((self.runtime / "spell/.gitattributes").exists())

    def test_git_union_can_be_disabled_independently(self):
        self.wordlist()
        self.vim("SpellSync", options={"spellsync_enable_git_union_merge": 0})
        self.assertTrue((self.runtime / "spell/.gitignore").exists())
        self.assertFalse((self.runtime / "spell/.gitattributes").exists())

    def test_stale_runtime_binary_is_rebuilt_and_reloaded(self):
        path = self.wordlist(words=["oldspellsyncword"])
        self.compile(path)
        path.write_text("newspellsyncword\n", encoding="utf-8")
        os.utime(str(path) + ".spl", (946684800, 946684800))
        os.utime(path, (946684810, 946684810))
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('newspellsyncword'))
            call assert_equal(['oldspellsyncword', 'bad'], spellbadword('oldspellsyncword'))
        """, before="""
            call TestSpelling()
            call assert_equal(['', ''], spellbadword('oldspellsyncword'))
            call assert_equal(['newspellsyncword', 'bad'], spellbadword('newspellsyncword'))
        """)

    def test_stale_custom_binary_after_first_entry_is_rebuilt(self):
        path = self.wordlist("custom/words.utf-8.add", ["oldspellsyncword"])
        self.compile(path)
        path.write_text("newspellsyncword\n", encoding="utf-8")
        os.utime(str(path) + ".spl", (946684800, 946684800))
        os.utime(path, (946684810, 946684810))
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('newspellsyncword'))
            call assert_equal(['oldspellsyncword', 'bad'], spellbadword('oldspellsyncword'))
        """, before="""
            let &spellfile .= ',' . g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
            call assert_equal(['', ''], spellbadword('oldspellsyncword'))
        """)

    def test_current_runtime_binary_is_not_rewritten(self):
        path = self.wordlist()
        self.compile(path)
        binary = Path(str(path) + ".spl")
        os.utime(path, (946684800, 946684800))
        os.utime(binary, (946684810, 946684810))
        original = binary.read_bytes(), binary.stat().st_mtime_ns
        self.vim("SpellSync")
        self.assertEqual(original, (binary.read_bytes(), binary.stat().st_mtime_ns))

    def test_new_custom_binary_becomes_active_without_restart(self):
        self.wordlist("custom/words.utf-8.add")
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('spellsyncword'))
        """, before="""
            let &spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
            call assert_equal(['spellsyncword', 'bad'], spellbadword('spellsyncword'))
        """)

    def test_wordlist_text_and_spelling_flags_are_preserved(self):
        path = self.wordlist("custom/words.utf-8.add", [
            "# personal words", "spellsyncgood", "spellsyncbad/!", "café",
        ])
        original = path.read_bytes()
        self.vim("""
            SpellSync
            call TestSpelling()
            call assert_equal(['', ''], spellbadword('spellsyncgood'))
            call assert_equal(['spellsyncbad', 'bad'], spellbadword('spellsyncbad'))
            call assert_equal(['', ''], spellbadword('café'))
        """, before="let &spellfile = g:test_root . '/custom/words.utf-8.add'")
        self.assertEqual(original, path.read_bytes())

    def test_in_memory_words_survive_sync(self):
        self.wordlist("custom/words.utf-8.add")
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('ephemeralspellsyncword'))
            call assert_equal(['', ''], spellbadword('spellsyncword'))
        """, before="""
            let &spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
            silent spellgood! ephemeralspellsyncword
        """)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--editor", default="vim", help="vim, nvim, or an executable path")
    arguments, remaining = parser.parse_known_args()
    EDITOR = arguments.editor
    unittest.main(argv=[sys.argv[0], *remaining])
