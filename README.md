# 🪄 vim-spellsync

Magically rebuild Vim spell files if word lists are modified outside of Vim. One use case would be if word lists are stored in a source control system like Git and shared across multiple computers. SpellSync also creates `.gitignore` and `.gitattributes` files in Vim's spell directories to exclude binary spell files and uses its union merge driver to avoid conflicts.

## Install

Tested with Vim 8.2.1926 or newer (with spell support) and Neovim 0.5.0 or newer.

Using a plugin manager like [vim-plug](https://github.com/junegunn/vim-plug):

```vim
Plug 'micarmst/vim-spellsync'
```

With [lazy.nvim](https://lazy.folke.io/spec), configure globals in `init` and use eager loading for startup syncing:

```lua
{
  'micarmst/vim-spellsync',
  lazy = false,
  init = function()
    vim.g.spellsync_run_at_startup = 1
  end,
}
```

## Usage

The plugin runs automatically at startup by default. If first loaded after startup, it syncs immediately. Loading it again does not register duplicate hooks or run another sync. Set options before the plugin loads; `g:spellsync_run_at_startup = 0` disables either automatic run. You can always sync manually with `:SpellSync`.

Read-only word lists are supported when their binary spell files can be created or updated. If a file cannot be read or written, SpellSync reports the path and reason and continues with the other dictionaries. Use `:messages` to review warnings, including Git configuration and spell-refresh failures. Missing word lists are skipped.

Vim before 9.1.0783 and Neovim before 0.11 require `set isfname+=92` before configuring a custom `'spellfile'` path containing an escaped comma. SpellSync handles this editor limitation automatically when refreshing dictionaries discovered through `'runtimepath'`.

## Config

Below are the options available and their default values:

```vim
" Run SpellSync automatically when Vim starts
let g:spellsync_run_at_startup = 1

" Enable the Git union merge option
" Creates a .gitattributes file in the spell directories if one does not exist
let g:spellsync_enable_git_union_merge = 1

" Enable Git ignore for binary spell files
" Creates a .gitignore file in the spell directories if one does not exist
let g:spellsync_enable_git_ignore = 1
```

## How it works

When a word is added to a custom dictionary, Vim appends it to the word list and then generates a binary version of that word list which it uses instead for performance. If a word list is modified outside of Vim (e.g. via source control) then the binary spell file won't be updated and Vim will continue to mark any new words as spelling mistakes.

The plugin iterates through any spell folders in the Vim runtime and/or any spell files that have been configured. If a word list has been modified then it rebuilds the binary spell file to match.

It also tries to make keeping word lists in source control easier to manage. First it creates a `.gitignore` file if one does not exist in the spell folder, this excludes binary `*.spl` and `*.sug` files from being commited. Second, it creates a `.gitattributes` file if one does not already exist and sets Git to use its union merge driver for the spell folder. This prevents merge conflicts if word lists are being modified from multiple locations.

Existing Git configuration is left untouched, including unreadable files and symbolic links.
Runtime spell directories without word lists are also left alone.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and testing instructions.

## References

* [Sato Katsura explains how to generate spl files](https://vi.stackexchange.com/a/5052/19028)
* [Using .gitattributes to avoid merge conflicts](https://web.archive.org/web/20181009034917/https://krlmlr.github.io/using-gitattributes-to-avoid-merge-conflicts/)
* [Writing Vim Plugins by Steve Losh](https://stevelosh.com/blog/2011/09/writing-vim-plugins/)
