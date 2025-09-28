# .PHONY: run fmt test

run:
\tpython manage.py runserver

fmt:
\tblack .
\tisort .

# test:
# \tpytest -q