"""Exercise the public plugin API in an isolated, real Vim or Neovim process."""

import argparse
import errno
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

    def restrict_permissions(self, path, mode, denied_access):
        if os.name != "posix":
            self.skipTest("Requires POSIX file permissions")
        original = path.stat().st_mode & 0o777
        self.addCleanup(path.chmod, original)
        path.chmod(mode)
        if os.access(path, denied_access):
            self.skipTest("Current user bypasses the requested permission restriction")

    def symlink(self, path, target):
        try:
            path.symlink_to(target)
        except NotImplementedError:
            self.skipTest("Symbolic links are unavailable")
        except OSError as error:
            if error.errno not in (errno.EPERM, errno.EACCES, errno.ENOTSUP):
                raise
            self.skipTest("Cannot create symbolic links: " + str(error))

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

            function! TestWarning(path, reason) abort
              let warnings = split(execute('messages'), "\\n")
              call filter(warnings, 'stridx(v:val, "SpellSync: ") == 0')
              " globpath() uses native separators on Windows.
              if has('win32')
                call map(warnings, 'tr(v:val, nr2char(92), "/")')
              endif
              call filter(warnings, 'stridx(v:val, a:path) >= 0 && stridx(v:val, a:reason) >= 0')
              call assert_false(empty(warnings), 'Missing warning for ' . a:path . ': ' . a:reason)
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
                " Allow editor events as with an interactive :SpellSync call.
                autocmd VimEnter * nested call TestAfterStartup()
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

    def test_repeated_loading_registers_one_startup_hook(self):
        self.wordlist()
        self.vim(r"""
            runtime plugin/spellsync.vim
            let hooks = filter(split(execute('autocmd VimEnter'), "\n"), 'v:val =~# ''\%(call spellsync#Run()\|SpellSync\)\s*$''' )
            call assert_equal(1, len(hooks))
            call assert_equal(1, g:unrelated_startup)
            call assert_true(filereadable(g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'))
        """, before="""
            let g:unrelated_startup = 0
            augroup TestUnrelatedStartup
              autocmd VimEnter * let g:unrelated_startup += 1
            augroup END
            runtime plugin/spellsync.vim
        """, startup=1)

    def test_late_loading_syncs_once(self):
        self.wordlist()
        (self.runtime / 'plugin/spellsync.vim').rename(self.root / 'held-plugin.vim')
        self.vim("""
            execute 'source ' . fnameescape(g:test_root . '/held-plugin.vim')
            let binary = g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'
            call assert_true(filereadable(binary))
            call delete(binary)
            execute 'source ' . fnameescape(g:test_root . '/held-plugin.vim')
            call assert_false(filereadable(binary), 'Repeated loading must not sync again')
        """, startup=1)

    def test_late_loading_respects_startup_opt_out(self):
        self.wordlist()
        (self.runtime / 'plugin/spellsync.vim').rename(self.root / 'held-plugin.vim')
        self.vim("""
            execute 'source ' . fnameescape(g:test_root . '/held-plugin.vim')
            call assert_false(filereadable(g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'))
            SpellSync
            call assert_true(filereadable(g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'))
        """)

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

    def test_custom_path_with_escaped_comma(self):
        path = self.wordlist("custom, words/words.utf-8.add")
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_notmatch('SpellSync:', execute('messages'))
        """, before="""
            " Older Vim rejects the comma escape unless it is in 'isfname'.
            if (has('nvim') ? !has('nvim-0.11') : !has('patch-9.1.783'))
              set isfname+=92
            endif
            let &spellfile = escape(g:test_root . '/custom, words/words.utf-8.add', ',')
            call TestSpelling()
        """)
        self.assertTrue(Path(str(path) + ".spl").is_file())

    def test_runtime_path_with_escaped_comma(self):
        path = self.wordlist("extra, runtime/spell/ssbase.utf-8.add")
        self.vim("""
            let original_isfname = &isfname
            SpellSync
            call assert_equal(original_isfname, &isfname)
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_notmatch('SpellSync:', execute('messages'))
        """, before="""
            let &runtimepath .= ',' . escape(g:test_root . '/extra, runtime', ',')
            call TestSpelling()
        """)
        self.assertTrue(Path(str(path) + ".spl").is_file())

    def test_runtime_directories_with_literal_glob_characters(self):
        for directory in ('extra[one]', 'extra{one,two}'):
            with self.subTest(directory=directory):
                path = self.wordlist(directory + '/spell/ssbase.utf-8.add')
                self.vim(r"""
                    let original_isfname = &isfname
                    SpellSync
                    call assert_true(filereadable(g:test_root . '/DIRECTORY/spell/ssbase.utf-8.add.spl'))
                    call assert_equal(['', ''], spellbadword('spellsyncword'))
                    call assert_equal(original_isfname, &isfname)
                    call assert_notmatch('SpellSync:', execute('messages'))
                """.replace('DIRECTORY', directory), before=r"""
                    " :help wildcard: Windows uses [[] for a literal bracket.
                    let directory = g:test_root . '/DIRECTORY'
                    let directory = has('win32') ? substitute(directory, '\[', '[[]', 'g') : escape(directory, '[]{}')
                    let &runtimepath .= ',' . escape(directory, ',')
                    call assert_false(empty(globpath(&runtimepath, 'spell', 1, 1)))
                    call TestSpelling()
                    call assert_equal(['spellsyncword', 'bad'], spellbadword('spellsyncword'))
                """.replace('DIRECTORY', directory))
                self.assertTrue(Path(str(path) + '.spl').is_file())

    def test_discovery_ignores_wildignore(self):
        path = self.wordlist()
        self.vim("""
            set wildignore=spell,*.add,*.spl
            SpellSync
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_equal('spell,*.add,*.spl', &wildignore)
            call assert_notmatch('SpellSync:', execute('messages'))
        """, before="call TestSpelling()")
        self.assertTrue(Path(str(path) + ".spl").is_file())

    def test_missing_custom_wordlist_is_not_created(self):
        self.vim("""
            SpellSync
            call assert_notmatch('SpellSync:', execute('messages'))
        """, before="let &spellfile = g:test_root . '/missing/words.utf-8.add'")
        self.assertFalse((self.root / "missing").exists())

    def test_empty_configuration(self):
        self.vim("SpellSync", before="set spellfile=")
        self.assertFalse((self.runtime / "spell").exists())

    def test_empty_runtime_spell_directory_is_left_alone(self):
        directory = self.runtime / "spell"
        directory.mkdir()
        self.vim("""
            SpellSync
            call assert_notmatch('SpellSync:', execute('messages'))
        """, before="set spellfile=")
        self.assertEqual([], list(directory.iterdir()))

    def test_hidden_runtime_wordlists_remain_outside_discovery(self):
        path = self.wordlist('runtime/spell/.hidden.add')
        self.vim('SpellSync')
        self.assertFalse(Path(str(path) + '.spl').exists())
        self.assertFalse((path.parent / '.gitignore').exists())

    def test_unreadable_runtime_directory_does_not_block_others(self):
        source = self.wordlist()
        good = self.wordlist('second-runtime/spell/ssbase.utf-8.add')
        self.restrict_permissions(source.parent, 0o000, os.R_OK)
        self.vim("""
            SpellSync
            " Neovim may reject this directory during the initial glob;
            " Vim reaches readdir(). Either failure must leave others usable.
            call assert_true(filereadable(g:test_root . '/second-runtime/spell/ssbase.utf-8.add.spl'))
        """, before="let &runtimepath .= ',' . escape(g:test_root . '/second-runtime', ',')")
        self.assertTrue(Path(str(good) + '.spl').is_file())

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

    @unittest.skipUnless(os.name == "posix", "Requires POSIX file permissions")
    def test_preserves_unreadable_writable_git_files(self):
        self.wordlist()
        self.wordlist("custom/words.utf-8.add")
        originals = {}
        try:
            for directory in (self.runtime / "spell", self.root / "custom"):
                for name in (".gitignore", ".gitattributes"):
                    path = directory / name
                    content = ("user rules for " + name + "\n").encode("utf-8")
                    path.write_bytes(content)
                    originals[path] = content
                    path.chmod(0o200)
                    if os.access(path, os.R_OK):
                        self.skipTest("Current user can read files despite missing read permission")
            self.vim("""
                for directory in ['runtime/spell', 'custom']
                  for name in ['.gitignore', '.gitattributes']
                    let path = g:test_root . '/' . directory . '/' . name
                    call assert_equal(0, filereadable(path), path)
                    call assert_equal(1, filewritable(path), path)
                  endfor
                endfor
                SpellSync
            """, before="let &spellfile = g:test_root . '/custom/words.utf-8.add'")
        finally:
            # Restore access before checking contents and removing fixtures.
            for path in originals:
                path.chmod(0o600)
        for path, content in originals.items():
            with self.subTest(path=path.relative_to(self.root)):
                self.assertEqual(content, path.read_bytes())

    def test_preserves_git_symlinks_and_their_targets(self):
        self.wordlist()
        self.wordlist("custom/words.utf-8.add")
        originals = {}
        for directory, content in ((self.runtime / "spell", b"user rules\n"),
                                   (self.root / "custom", None)):
            for name in (".gitignore", ".gitattributes"):
                path = directory / name
                target = directory / ("saved" + name)
                if content is not None:
                    target.write_bytes(content)
                self.symlink(path, target.name)
                originals[path] = target, content
        self.vim("SpellSync", before="let &spellfile = g:test_root . '/custom/words.utf-8.add'")
        for path, (target, content) in originals.items():
            with self.subTest(path=path.relative_to(self.root)):
                self.assertTrue(path.is_symlink())
                self.assertEqual(target.name, os.readlink(path))
                if content is None:
                    self.assertFalse(target.exists(), "A dangling link must not create its target")
                else:
                    self.assertEqual(content, target.read_bytes())

    def test_preserves_directories_at_git_config_paths(self):
        wordlists = [self.wordlist(), self.wordlist("custom/words.utf-8.add")]
        sentinels = []
        for wordlist in wordlists:
            for name in (".gitignore", ".gitattributes"):
                path = wordlist.parent / name
                path.mkdir()
                sentinel = path / "keep.txt"
                sentinel.write_bytes(b"user content\n")
                sentinels.append(sentinel)
        self.vim("SpellSync", before="let &spellfile = g:test_root . '/custom/words.utf-8.add'")
        for sentinel in sentinels:
            self.assertEqual(b"user content\n", sentinel.read_bytes())
        for wordlist in wordlists:
            self.assertTrue(Path(str(wordlist) + ".spl").is_file())

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

    def test_readonly_sources_build_missing_and_stale_binaries(self):
        runtime = self.wordlist()
        custom = self.wordlist("custom/words.utf-8.add", ["oldspellsyncword"])
        self.compile(custom)
        custom.write_text("newspellsyncword\n", encoding="utf-8")
        os.utime(str(custom) + ".spl", (946684800, 946684800))
        os.utime(custom, (946684810, 946684810))
        for path in (runtime, custom):
            self.restrict_permissions(path, 0o400, os.W_OK)
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_equal(['', ''], spellbadword('newspellsyncword'))
            call assert_equal(['oldspellsyncword', 'bad'], spellbadword('oldspellsyncword'))
            call assert_notmatch('SpellSync:', execute('messages'))
        """, before="""
            let &spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
        """)

    def test_unreadable_source_is_reported_and_other_dictionaries_continue(self):
        path = self.wordlist("runtime/spell/aa.utf-8.add")
        good = self.wordlist("runtime/spell/zz.utf-8.add")
        self.restrict_permissions(path, 0o000, os.R_OK)
        self.vim("""
            SpellSync
            call TestWarning(g:test_root . '/runtime/spell/aa.utf-8.add', 'not readable')
        """)
        self.assertFalse(Path(str(path) + ".spl").exists())
        self.assertTrue(Path(str(good) + ".spl").is_file())

    def test_missing_binary_in_unwritable_directory_is_reported(self):
        path = self.wordlist("custom/words.utf-8.add")
        good = self.wordlist("later/words.utf-8.add")
        self.restrict_permissions(path.parent, 0o500, os.W_OK)
        self.vim("""
            SpellSync
            call TestWarning(g:test_root . '/custom/words.utf-8.add.spl', 'not writable')
        """, before="let &spellfile = g:test_root . '/custom/words.utf-8.add,' . g:test_root . '/later/words.utf-8.add'")
        self.assertFalse(Path(str(path) + ".spl").exists())
        self.assertTrue(Path(str(good) + ".spl").is_file())

    def test_unwritable_existing_binary_is_reported_and_preserved(self):
        path = self.wordlist("custom/words.utf-8.add", ["oldspellsyncword"])
        self.compile(path)
        binary = Path(str(path) + ".spl")
        path.write_text("newspellsyncword\n", encoding="utf-8")
        os.utime(binary, (946684800, 946684800))
        os.utime(path, (946684810, 946684810))
        original = binary.read_bytes(), binary.stat().st_mtime_ns
        self.restrict_permissions(binary, 0o400, os.W_OK)
        good = self.wordlist("later/words.utf-8.add")
        self.vim("""
            SpellSync
            call TestWarning(g:test_root . '/custom/words.utf-8.add.spl', 'not writable')
        """, before="let &spellfile = g:test_root . '/custom/words.utf-8.add,' . g:test_root . '/later/words.utf-8.add'")
        self.assertEqual(original, (binary.read_bytes(), binary.stat().st_mtime_ns))
        self.assertTrue(Path(str(good) + ".spl").is_file())

    def test_git_write_failures_do_not_block_writable_binary_in_readonly_directory(self):
        path = self.wordlist("custom/words.utf-8.add", ["oldspellsyncword"])
        self.compile(path)
        path.write_text("newspellsyncword\n", encoding="utf-8")
        os.utime(str(path) + ".spl", (946684800, 946684800))
        os.utime(path, (946684810, 946684810))
        self.restrict_permissions(path, 0o400, os.W_OK)
        self.restrict_permissions(path.parent, 0o500, os.W_OK)
        self.vim("""
            SpellSync
            call TestWarning(g:test_root . '/custom/.gitignore', 'not writable')
            call TestWarning(g:test_root . '/custom/.gitattributes', 'not writable')
            call assert_equal(['', ''], spellbadword('newspellsyncword'))
            call assert_equal(['oldspellsyncword', 'bad'], spellbadword('oldspellsyncword'))
        """, before="""
            let &spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
        """)
        self.assertFalse((path.parent / ".gitignore").exists())
        self.assertFalse((path.parent / ".gitattributes").exists())

    def test_current_readonly_binary_does_not_report_a_write_failure(self):
        path = self.wordlist()
        self.compile(path)
        binary = Path(str(path) + ".spl")
        os.utime(path, (946684800, 946684800))
        os.utime(binary, (946684810, 946684810))
        original = binary.read_bytes(), binary.stat().st_mtime_ns
        self.restrict_permissions(binary, 0o400, os.W_OK)
        self.vim("""
            SpellSync
            call assert_notmatch('SpellSync:', execute('messages'))
        """)
        self.assertEqual(original, (binary.read_bytes(), binary.stat().st_mtime_ns))

    def test_non_file_sources_and_destinations_are_reported(self):
        source = self.root / "runtime/spell/aa.utf-8.add"
        source.mkdir(parents=True)
        path = self.wordlist("runtime/spell/bb.utf-8.add")
        binary = Path(str(path) + ".spl")
        binary.mkdir()
        sentinel = binary / "keep.txt"
        sentinel.write_bytes(b"user content\n")
        good = self.wordlist("runtime/spell/zz.utf-8.add")
        self.vim("""
            SpellSync
            call TestWarning(g:test_root . '/runtime/spell/aa.utf-8.add', 'not a regular file')
            call TestWarning(g:test_root . '/runtime/spell/bb.utf-8.add.spl', 'not a regular file')
        """)
        self.assertTrue(source.is_dir())
        self.assertEqual(b"user content\n", sentinel.read_bytes())
        self.assertTrue(Path(str(good) + ".spl").is_file())

    def test_compiler_errors_are_reported_and_later_dictionaries_continue(self):
        bad = self.wordlist("runtime/spell/aa_bad.utf-8.add")
        good = self.wordlist("runtime/spell/zz.utf-8.add")
        custom = self.wordlist("custom/words.utf-8.add")
        self.vim("""
            call TestWarning(g:test_root . '/runtime/spell/aa_bad.utf-8.add', 'E751:')
        """, before="let &spellfile = g:test_root . '/custom/words.utf-8.add'", startup=1)
        self.assertFalse(Path(str(bad) + ".spl").exists())
        for path in (good, custom):
            self.assertTrue(Path(str(path) + ".spl").is_file())

    def test_write_time_errors_are_caught_and_reported(self):
        path = self.wordlist()
        self.vim("""
            " The sandbox denies writes even though permission checks pass.
            runtime autoload/spellsync.vim
            sandbox call spellsync#Run()
            call TestWarning(g:test_root . '/runtime/spell/.gitignore', 'E48:')
            call TestWarning(g:test_root . '/runtime/spell/.gitattributes', 'E48:')
            call TestWarning(g:test_root . '/runtime/spell/ssbase.utf-8.add', 'E48:')
            call assert_false(filereadable(g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'))
            " A subsequent ordinary invocation can still complete normally.
            SpellSync
        """, before="let &spellfile = g:test_root . '/runtime/spell/ssbase.utf-8.add'")
        self.assertTrue(Path(str(path) + ".spl").is_file())

    def test_wordlist_and_binary_symlinks_are_preserved(self):
        source = self.wordlist("stored/words.utf-8.add", ["oldspellsyncword"])
        self.compile(source)
        binary = Path(str(source) + ".spl")
        source.write_text("newspellsyncword\n", encoding="utf-8")
        original = source.read_bytes()
        os.utime(binary, (946684800, 946684800))
        os.utime(source, (946684810, 946684810))
        link = self.root / "custom/words.utf-8.add"
        link.parent.mkdir()
        output = Path(str(link) + ".spl")
        self.symlink(link, os.path.relpath(source, link.parent))
        self.symlink(output, os.path.relpath(binary, output.parent))
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('newspellsyncword'))
            call assert_equal(['oldspellsyncword', 'bad'], spellbadword('oldspellsyncword'))
            call assert_notmatch('SpellSync:', execute('messages'))
        """, before="""
            let &spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
        """)
        self.assertTrue(link.is_symlink())
        self.assertTrue(output.is_symlink())
        self.assertEqual(original, source.read_bytes())

    def test_dangling_wordlist_symlinks_are_reported(self):
        link = self.root / "runtime/spell/aa.utf-8.add"
        good = self.wordlist("runtime/spell/zz.utf-8.add")
        self.symlink(link, "missing.words")
        self.vim("""
            SpellSync
            " Windows Vim reports dangling links as unreadable files.
            let reason = has('win32') && !has('nvim') ? 'not readable' : 'not a regular file'
            call TestWarning(g:test_root . '/runtime/spell/aa.utf-8.add', reason)
        """)
        self.assertTrue(link.is_symlink())
        self.assertFalse((link.parent / "missing.words").exists())
        self.assertTrue(Path(str(good) + ".spl").is_file())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Requires POSIX named pipes")
    def test_named_pipes_are_rejected_without_blocking(self):
        source = self.root / "custom/aa.utf-8.add"
        regular = self.wordlist("custom/bb.utf-8.add")
        output = Path(str(regular) + ".spl")
        os.mkfifo(source)
        os.mkfifo(output)
        good = self.wordlist("custom/zz.utf-8.add")
        self.vim("""
            SpellSync
            call TestWarning(g:test_root . '/custom/aa.utf-8.add', 'not a regular file')
            call TestWarning(g:test_root . '/custom/bb.utf-8.add.spl', 'not a regular file')
        """, before="let &spellfile = join(map(['aa', 'bb', 'zz'], \"g:test_root . '/custom/' . v:val . '.utf-8.add'\"), ',')")
        self.assertTrue(source.is_fifo())
        self.assertTrue(output.is_fifo())
        self.assertTrue(Path(str(good) + ".spl").is_file())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Requires POSIX named pipes")
    def test_refresh_does_not_open_named_pipe_outputs(self):
        for name, spellfile in (
            ("custom/words.utf-8.add", "g:test_root . '/custom/words.utf-8.add'"),
            ("runtime/spell/ssbase.utf-8.add", "''"),
        ):
            with self.subTest(wordlist=name):
                path = self.wordlist(name)
                binary = Path(str(path) + ".spl")
                pending = self.root / "pending-fifo"
                os.mkfifo(pending)
                good = self.wordlist("later/words.utf-8.add")
                output = vim_string(binary.as_posix())
                self.vim("""
                    " Introduce a bad output after spell checking is active.
                    call assert_equal(0, rename(g:test_root . '/pending-fifo', OUTPUT))
                    SpellSync
                    call TestWarning(OUTPUT, 'not a regular file')
                    call assert_equal('fifo', getftype(OUTPUT))
                    call assert_true(filereadable(g:test_root . '/later/words.utf-8.add.spl'))
                    call assert_equal(0, delete(OUTPUT))
                    SpellSync
                    call assert_equal(['', ''], spellbadword('spellsyncword'))
                """.replace("OUTPUT", output), before="""
                    let &spellfile = SPELLFILE
                    let &spellfile .= (empty(&spellfile) ? '' : ',') . g:test_root . '/later/words.utf-8.add'
                    call TestSpelling()
                """.replace("SPELLFILE", spellfile))
                for created in (path, binary, good, Path(str(good) + ".spl")):
                    created.unlink()

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

    def test_force_rebuild_recovers_equal_and_older_timestamps(self):
        for command in ('SpellSync!', 'call spellsync#Run(1)'):
            for source_time in (946684800, 946684790):
                with self.subTest(command=command, source_time=source_time):
                    paths = [self.wordlist(name, ['oldspellsyncword']) for name in (
                        'runtime/spell/ssbase.utf-8.add', 'custom/words.utf-8.add',
                    )]
                    for path in paths:
                        self.compile(path)
                        path.write_text('newspellsyncword\n', encoding='utf-8')
                        os.utime(path, (source_time, source_time))
                        os.utime(str(path) + '.spl', (946684800, 946684800))
                    originals = [path.read_bytes() for path in paths]
                    self.vim("""
                        SpellSync
                        call assert_equal(['newspellsyncword', 'bad'], spellbadword('newspellsyncword'))
                        call assert_equal(946684800, getftime(g:test_root . '/runtime/spell/ssbase.utf-8.add.spl'))
                        FORCE
                        call assert_equal(['', ''], spellbadword('newspellsyncword'))
                        call assert_equal(['oldspellsyncword', 'bad'], spellbadword('oldspellsyncword'))
                        call assert_equal(['', ''], spellbadword('ephemeralspellsyncword'))
                        call assert_notmatch('SpellSync:', execute('messages'))
                    """.replace('FORCE', command), before="""
                        let &spellfile = g:test_root . '/custom/words.utf-8.add'
                        call TestSpelling()
                        silent spellgood! ephemeralspellsyncword
                    """)
                    for path, original in zip(paths, originals):
                        self.assertEqual(original, path.read_bytes())
                        self.assertGreater(Path(str(path) + '.spl').stat().st_mtime, 946684800)

    def test_force_rebuild_recovers_corrupt_binary(self):
        path = self.wordlist()
        binary = Path(str(path) + '.spl')
        binary.write_bytes(b'not a spell binary')
        for file in (path, binary):
            os.utime(file, (946684800, 946684800))
        self.vim("""
            SpellSync!
            call TestSpelling()
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_notmatch('SpellSync:', execute('messages'))
        """)

    def test_force_rebuild_reports_unwritable_binary_and_continues(self):
        path = self.wordlist('runtime/spell/aa.utf-8.add')
        self.compile(path)
        binary = Path(str(path) + '.spl')
        original = binary.read_bytes()
        for file in (path, binary):
            os.utime(file, (946684800, 946684800))
        self.restrict_permissions(binary, 0o444, os.W_OK)
        good = self.wordlist('runtime/spell/zz.utf-8.add')
        self.vim("""
            SpellSync!
            call TestWarning(g:test_root . '/runtime/spell/aa.utf-8.add.spl', 'not writable')
            call assert_equal(946684800, getftime(g:test_root . '/runtime/spell/aa.utf-8.add.spl'))
        """)
        self.assertEqual(original, binary.read_bytes())
        self.assertTrue(Path(str(good) + '.spl').is_file())

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

    def test_current_first_custom_binary_is_not_rewritten(self):
        path = self.wordlist("custom/words.utf-8.add")
        self.compile(path)
        binary = Path(str(path) + ".spl")
        os.utime(path, (946684800, 946684800))
        os.utime(binary, (946684810, 946684810))
        original = binary.read_bytes(), binary.stat().st_mtime_ns
        self.vim("""
            SpellSync
            SpellSync
            call assert_equal(['', ''], spellbadword('spellsyncword'))
        """, before="""
            let &spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
        """)
        self.assertEqual(original, (binary.read_bytes(), binary.stat().st_mtime_ns))

    def test_old_reload_marker_is_preserved_in_wordlist(self):
        path = self.wordlist("custom/words.utf-8.add", ["U1BFTExTWU5D", "spellsyncword"])
        original = path.read_bytes()
        self.vim("""
            SpellSync
            SpellSync
            call assert_equal(['', ''], spellbadword('spellsyncword'))
        """, before="""
            let &spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
        """)
        self.assertEqual(original, path.read_bytes())

    def test_new_runtime_binary_refresh_preserves_empty_spellfile(self):
        self.wordlist()
        self.vim("""
            SpellSync
            call assert_equal('', &l:spellfile)
            call assert_equal(['', ''], spellbadword('spellsyncword'))
        """, before="""
            setlocal spellfile=
            call TestSpelling()
            call assert_equal(['spellsyncword', 'bad'], spellbadword('spellsyncword'))
        """)

    def test_new_runtime_additions_in_multiple_directories_become_active(self):
        self.wordlist(words=["firstruntimeword"])
        self.wordlist("second-runtime/spell/ssbase.utf-8.add", ["secondruntimeword"])
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('firstruntimeword'))
            call assert_equal(['', ''], spellbadword('secondruntimeword'))
            call assert_equal(['', ''], spellbadword('baselineword'))
        """, before="""
            let &runtimepath .= ',' . escape(g:test_root . '/second-runtime', ',')
            setlocal spellfile=
            call TestSpelling()
            call assert_equal(['firstruntimeword', 'bad'], spellbadword('firstruntimeword'))
            call assert_equal(['secondruntimeword', 'bad'], spellbadword('secondruntimeword'))
        """)

    def test_new_runtime_additions_respect_language_regions(self):
        self.wordlist(words=["/regions=usgb", "usspellsyncword/1", "gbspellsyncword/2"])
        self.wordlist("regional.words", ["/regions=usgb", "baselineword"])
        self.vim("""
            SpellSync
            call assert_equal('ssbase_us', &l:spelllang)
            call assert_equal(['', ''], spellbadword('usspellsyncword'))
            call assert_equal(['gbspellsyncword', 'local'], spellbadword('gbspellsyncword'))
            setlocal spelllang=ssbase_gb
            call assert_equal(['', ''], spellbadword('gbspellsyncword'))
            call assert_equal(['usspellsyncword', 'local'], spellbadword('usspellsyncword'))
        """, before="""
            execute 'silent mkspell! ' . fnameescape(g:test_root . '/runtime/spell/ssbase.utf-8.spl') . ' ' . fnameescape(g:test_root . '/regional.words')
            setlocal spellfile= spelllang=ssbase_us spell
            call assert_equal(['', ''], spellbadword('baselineword'))
            call assert_equal(['usspellsyncword', 'bad'], spellbadword('usspellsyncword'))
        """)

    def test_new_runtime_additions_match_base_dictionary_encoding(self):
        self.wordlist("base.words", ["baselineword"])
        self.wordlist(words=["utfspellsyncword"])
        self.wordlist("runtime/spell/ssbase.ascii.add", ["asciispellsyncword"])
        for encoding, flag, accepted, rejected in (
            ("utf-8", "", "utfspellsyncword", "asciispellsyncword"),
            ("ascii", "-ascii ", "asciispellsyncword", "utfspellsyncword"),
        ):
            with self.subTest(encoding=encoding):
                # Each invocation starts a fresh editor with only this base.
                for binary in (self.runtime / "spell").glob("*.spl"):
                    binary.unlink()
                self.vim("""
                    SpellSync
                    call assert_equal(['', ''], spellbadword('ACCEPTED'))
                    call assert_equal(['REJECTED', 'bad'], spellbadword('REJECTED'))
                    call assert_equal(['', ''], spellbadword('baselineword'))
                """.replace("ACCEPTED", accepted).replace("REJECTED", rejected), before="""
                    execute 'silent mkspell! FLAG' . fnameescape(g:test_root . '/runtime/spell/ssbase.ENCODING.spl') . ' ' . fnameescape(g:test_root . '/base.words')
                    setlocal spellfile= spelllang=ssbase spell
                    call assert_equal(['ACCEPTED', 'bad'], spellbadword('ACCEPTED'))
                """.replace("FLAG", flag).replace("ENCODING", encoding).replace("ACCEPTED", accepted))

    def test_refresh_does_not_preload_an_unrelated_language(self):
        self.wordlist()
        self.wordlist("runtime/spell/otherbase.utf-8.add", ["otheradditionword"])
        self.wordlist("other.words", ["otherbaselineword"])
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_equal(['otheradditionword', 'bad'], spellbadword('otheradditionword'))
            setlocal spelllang=otherbase
            call assert_equal(['', ''], spellbadword('otherbaselineword'))
            call assert_equal(['', ''], spellbadword('otheradditionword'))
        """, before="""
            execute 'silent mkspell! ' . fnameescape(g:test_root . '/runtime/spell/otherbase.utf-8.spl') . ' ' . fnameescape(g:test_root . '/other.words')
            setlocal spellfile=
            call TestSpelling()
        """)

    def test_new_custom_binary_after_missing_first_entry_becomes_active(self):
        self.wordlist("custom/words.utf-8.add")
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('spellsyncword'))
        """, before="""
            let &spellfile .= ',' . g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
            call assert_equal(['spellsyncword', 'bad'], spellbadword('spellsyncword'))
        """)

    def test_refresh_preserves_options_without_firing_optionset(self):
        self.wordlist("custom/words.utf-8.add")
        self.wordlist(words=["runtimespellsyncword"])
        self.vim("""
            let options = [&l:spellfile, &g:spellfile, &l:spelllang, &g:spelllang, &l:spell]
            let g:option_events = 0
            augroup TestOptionEvents
              autocmd OptionSet * let g:option_events += 1
            augroup END
            " Verify that the harness allows OptionSet to run before checking
            " that the refresh itself emits no artificial option changes.
            let &l:readonly = &l:readonly
            call assert_equal(1, g:option_events)
            let g:option_events = 0
            SpellSync
            call assert_equal(0, g:option_events)
            call assert_equal(options, [&l:spellfile, &g:spellfile, &l:spelllang, &g:spelllang, &l:spell])
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_equal(['', ''], spellbadword('runtimespellsyncword'))
        """, before="""
            let &l:spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
        """)

    def test_new_runtime_dictionary_refreshes_windows_and_tabs(self):
        self.wordlist()
        self.vim("""
            let current = win_getid()
            let view = winsaveview()
            let directories = map(getwininfo(), '[v:val.winid, getcwd(v:val.winnr, v:val.tabnr), haslocaldir(v:val.winnr, v:val.tabnr)]')
            let options = [&l:spell, &l:spellfile, &l:spelllang]
            let g:refresh_events = 0
            augroup TestRefreshEvents
              autocmd OptionSet,WinEnter,WinLeave,BufEnter,BufLeave,TabEnter,TabLeave,DirChanged * let g:refresh_events += 1
            augroup END
            SpellSync
            call assert_equal(current, win_getid())
            call assert_equal(view, winsaveview())
            call assert_equal(directories, map(getwininfo(), '[v:val.winid, getcwd(v:val.winnr, v:val.tabnr), haslocaldir(v:val.winnr, v:val.tabnr)]'))
            call assert_equal(options, [&l:spell, &l:spellfile, &l:spelllang])
            call assert_equal(0, g:refresh_events)
            for window in [g:first_window, g:second_window]
              call win_execute(window, "call assert_equal(['', ''], spellbadword('spellsyncword'))")
              call win_execute(window, "call assert_equal(['', ''], spellbadword('ephemeralspellsyncword'))")
            endfor
            call assert_notmatch('SpellSync:', execute('messages'))
        """, before="""
            call TestSpelling()
            setlocal spellfile=
            silent spellgood! ephemeralspellsyncword
            execute 'lcd ' . fnameescape(g:test_root . '/runtime')
            let g:first_window = win_getid()
            tabnew
            execute 'tcd ' . fnameescape(g:test_root)
            setlocal spelllang=ssbase spell spellfile=
            let g:second_window = win_getid()
            new
            setlocal nospell spellfile=
        """)

    def test_new_runtime_dictionaries_refresh_each_open_language(self):
        self.wordlist()
        self.wordlist('runtime/spell/otherbase.utf-8.add', ['otheradditionword'])
        self.wordlist('other.words', ['otherbaselineword'])
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('otheradditionword'))
            call assert_equal(['spellsyncword', 'bad'], spellbadword('spellsyncword'))
            wincmd p
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_equal(['otheradditionword', 'bad'], spellbadword('otheradditionword'))
        """, before="""
            call TestSpelling()
            execute 'silent mkspell! ' . fnameescape(g:test_root . '/runtime/spell/otherbase.utf-8.spl') . ' ' . fnameescape(g:test_root . '/other.words')
            new
            setlocal spelllang=otherbase spell spellfile=
        """)

    def test_new_runtime_dictionary_is_active_when_hidden_buffer_returns(self):
        self.wordlist()
        self.vim("""
            SpellSync
            execute 'buffer ' . g:hidden_buffer
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_equal('preserved text', getline(1))
        """, before="""
            set hidden
            call TestSpelling()
            call setline(1, 'preserved text')
            let g:hidden_buffer = bufnr('')
            enew
            setlocal spelllang=ssbase spell spellfile=
        """)

    def test_refresh_does_not_compile_other_buffers_custom_sources(self):
        path = self.wordlist('other-buffer/custom.utf-8.add')
        self.vim("""
            SpellSync
            call assert_false(filereadable(g:test_root . '/other-buffer/custom.utf-8.add.spl'))
        """, before="""
            let &l:spellfile = g:test_root . '/other-buffer/custom.utf-8.add'
            call TestSpelling()
            new
            setlocal spelllang=ssbase spell spellfile=
        """)
        self.assertFalse(Path(str(path) + '.spl').exists())

    def test_rebuilt_dictionary_remains_live_in_other_windows(self):
        path = self.wordlist("custom/words.utf-8.add", ["oldspellsyncword"])
        self.compile(path)
        path.write_text("newspellsyncword\n", encoding="utf-8")
        os.utime(str(path) + ".spl", (946684800, 946684800))
        os.utime(path, (946684810, 946684810))
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('newspellsyncword'))
            wincmd p
            call assert_equal(['', ''], spellbadword('newspellsyncword'))
            call assert_equal(['oldspellsyncword', 'bad'], spellbadword('oldspellsyncword'))
        """, before="""
            let &spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
            call assert_equal(['', ''], spellbadword('oldspellsyncword'))
            new
            let &l:spellfile = g:test_root . '/custom/words.utf-8.add'
            setlocal spelllang=ssbase spell
            call assert_equal(['', ''], spellbadword('oldspellsyncword'))
        """)

    def test_refresh_does_not_enable_spell_checking(self):
        self.wordlist("custom/words.utf-8.add")
        self.wordlist(words=["runtimespellsyncword"])
        self.vim("""
            SpellSync
            call assert_false(&l:spell)
            setlocal spell
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_equal(['', ''], spellbadword('runtimespellsyncword'))
        """, before="""
            let &spellfile = g:test_root . '/custom/words.utf-8.add'
            call TestSpelling()
            setlocal nospell
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
        self.wordlist(words=["runtimespellsyncword"])
        self.vim("""
            SpellSync
            call assert_equal(['', ''], spellbadword('ephemeralspellsyncword'))
            call assert_equal(['', ''], spellbadword('spellsyncword'))
            call assert_equal(['', ''], spellbadword('runtimespellsyncword'))
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
