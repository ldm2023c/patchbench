# Bookmarks exchange

A standard-library import/export library for bookmark backups. Python 3.12+.
Use Bookmark records with document.dumps / document.loads.

Each physical line has title|url or title|url|note. The third field is optional:
missing means None, present-but-empty means an empty string. Titles are nonempty,
URLs start with http:// or https://. Text and whitespace are preserved exactly.
Backslash escapes are \\ for backslash, \| for delimiter, \n for newline and
\r for carriage return. Unknown escapes and trailing backslashes are errors.
Unescaped delimiters separate fields; escaped ones are content. Documents ignore
empty lines and report the physical line number when a record is invalid.
Existing simple records must remain readable. Serialized records occupy one line.

Run `python -B -m unittest -v` for all tests.
