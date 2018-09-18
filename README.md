# vim-spellsync

Regenerate Vim spell files from word lists at startup. Useful for storing personal dictionaries in source control. Automatically creates `gitignore` and `.gitattributes` in the spell directories to exclude binary spell files from Git and uses its union merge driver to avoid conflicts.

## Install

Using a plugin manager like [vim-plug](https://github.com/junegunn/vim-plug):

```vim
Plug 'micarmst/vim-spellsync'
```

## References

* https://vi.stackexchange.com/a/5052/19028
* https://krlmlr.github.io/using-gitattributes-to-avoid-merge-conflicts/

