" Get available spell diretories
let s:dirs = split(globpath(&rtp, 'spell'), '\n')

" Search each spell directory for word lists
for s:dir in s:dirs

  let s:active_dir = 0
  let s:wordlists = split(globpath(s:dir, '*.add'), '\n')

  " Regenerate spell file for each word list
  for s:wordlist in s:wordlists

    let s:spell_file = s:wordlist . '.spl'
    let s:has_access = filereadable(s:wordlist) && filewritable(s:wordlist) == 1

    " Mark folder as active
    if s:has_access == 1
      let s:active_dir = 1
    endif

    " Regenerate the spell file if it's out of date
    if s:has_access && getftime(s:wordlist) > getftime(s:spell_file)
      silent exec 'mkspell! ' . fnameescape(s:wordlist)
    endif

  endfor

  " Create gitignore and gitattributes for active spell folders
  if s:active_dir == 1

    " gitignore
    let s:gitignore = s:dir . '/' . '.gitignore'
    if !filereadable(s:gitignore)
      silent exec '!echo "*.spl\n*.sug" > ' . s:gitignore
    endif

    " gitattributes
    let s:gitattributes = s:dir . '/' . '.gitattributes'
    if !filereadable(s:gitattributes)
      silent exec '!echo "*.add merge=union" > ' . s:gitattributes
    endif

  endif

endfor
