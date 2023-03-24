# JS8Spotter utility to migrate from 94b-1.01b database to 1.04b format (adding maps, expect, and forms as needed)
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

# create the missing tables
c.execute("""CREATE TABLE IF NOT EXISTS grid (
    grid_callsign VARCHAR (64) UNIQUE ON CONFLICT REPLACE PRIMARY KEY,
    grid_grid VARCHAR (16),
    grid_dial VARCHAR (64),
    grid_type VARCHAR (64),
    grid_snr VARCHAR (16),
    grid_timestamp TIMESTAMP
)
""")

c.execute("""CREATE TABLE IF NOT EXISTS "expect" (
	"expect"	VARCHAR(6) UNIQUE ON CONFLICT REPLACE,
	"reply"	    TEXT,
	"allowed"	TEXT,
	"txlist"	TEXT,
	"txmax"	INTEGER,
	"lm"	TIMESTAMP,
	PRIMARY KEY("expect")
)
""")

c.execute("""CREATE TABLE IF NOT EXISTS "forms" (
	"id"	INTEGER UNIQUE,
	"fromcall"	TEXT,
	"tocall"	TEXT,
	"typeid"	TEXT,
	"responses"	TEXT,
	"msgtxt"	TEXT,
	"timesig"	TEXT,
	"lm"	TIMESTAMP,
	PRIMARY KEY("id" AUTOINCREMENT)
)
""")

c.execute("""CREATE TABLE IF NOT EXISTS signal (
    "id"     INTEGER PRIMARY KEY AUTOINCREMENT,
    "sig_callsign" VARCHAR (64),
    "sig_dial"     TEXT,
    "sig_freq"     TEXT,
    "sig_offset"   TEXT,
    "sig_speed"    TEXT,
    "sig_snr"      TEXT,
    "sig_timestamp" TIMESTAMP
)
""")

c.execute("ALTER TABLE forms ADD COLUMN gwtx TEXT DEFAULT ''")
c.execute("ALTER TABLE activity ADD COLUMN freq TEXT DEFAULT ''")
c.execute("ALTER TABLE activity ADD COLUMN offset TEXT DEFAULT ''")
c.execute("ALTER TABLE activity ADD COLUMN speed TEXT DEFAULT ''")

conn.commit()
conn.close()
