# 🪄 vim-spellsync

Automatically rebuild Vim spell files from word lists at startup. Useful for storing custom word lists in source control. It also creates `.gitignore` and `.gitattributes` in the spell directories to exclude binary spell files from Git and uses its union merge driver to avoid conflicts.

## Install

Using a plugin manager like [vim-plug](https://github.com/junegunn/vim-plug):

```vim
Plug 'micarmst/vim-spellsync'
```

## Usage

The spellsync plugin runs automatically at startup. It can also be called with the `:SpellSync` command.

## How it works

When a word is added to a custom dictionary, Vim appends it to the word list and then generates a binary version of that word list which it uses instead for performance. If a word list is modified outside of Vim (e.g. via source control) then the binary spell file won't be updated and Vim will continue to mark any new words as spelling mistakes.

The plugin iterates through any spell folders in the Vim runtime and/or any spell files that have been configured. If a word list has been modified then it rebuilds the binary spell file to match.

It also tries to make keeping word lists in source control easier to manage. First it creates a `.gitignore` file if one does not exist in the spell folder, this excludes binary `*.spl` and `*.sug` files from being commited. Second, it creates a `.gitattributes` file if one does not already exist and sets Git to use its union merge driver for the spell folder. This prevents merge conflicts if word lists are being modified from multiple locations.

## References

* [Sato Katsura explains how to generate spl files](https://vi.stackexchange.com/a/5052/19028)
* [Using .gitattributes to avoid merge conflicts](https://web.archive.org/web/20181009034917/https://krlmlr.github.io/using-gitattributes-to-avoid-merge-conflicts/)
* [Writing Vim Plugins by Steve Losh](https://stevelosh.com/blog/2011/09/writing-vim-plugins/)