# JS8Spotter utility to migrate 95b/96b/97b database to 0.98b format
#
# MIT License, Copyright 2023 Joseph D Lyman KF7MIX
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.


import sqlite3

conn = sqlite3.connect('js8spotter.db')
c = conn.cursor()

# create the missing table
c.execute("""CREATE TABLE "expect" (
	"expect"	VARCHAR(6) UNIQUE ON CONFLICT REPLACE,
	"reply"	    TEXT,
	"allowed"	TEXT,
	"txlist"	TEXT,
	"txmax"	INTEGER,
	"lm"	TIMESTAMP,
	PRIMARY KEY("expect")
)
""")

conn.commit()
conn.close()
