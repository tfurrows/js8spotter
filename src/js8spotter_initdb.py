# JS8Spotter InitDB v0.5b - 12/08/2022
# Utility to initialize database
#
# MIT License, Copyright 2022 Joseph D Lyman KF7MIX
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

import sqlite3

conn = sqlite3.connect('js8spotter.db')
c = conn.cursor()

c.execute("""CREATE TABLE setting (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT    UNIQUE ON CONFLICT IGNORE,
    value TEXT
)
""")
conn.commit()

c.execute("""CREATE TABLE profile (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    title  TEXT    UNIQUE ON CONFLICT IGNORE,
    def    BOOLEAN DEFAULT (0),
    bgscan BOOLEAN DEFAULT (0)
)
""")
conn.commit()


c.execute("""CREATE TABLE activity (
    id         INTEGER   PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER,
    type       TEXT,
    value      TEXT,
    dial       TEXT,
    snr        TEXT,
    call       TEXT,
    spotdate   TIMESTAMP
)
""")
conn.commit()


c.execute("""CREATE TABLE search (
    id         INTEGER   PRIMARY KEY AUTOINCREMENT,
    profile_id INT,
    keyword    TEXT,
    last_seen  TIMESTAMP
)
""")
conn.commit()


c.execute("""CREATE TABLE grid (
    grid_callsign VARCHAR (64) UNIQUE ON CONFLICT REPLACE PRIMARY KEY,
    grid_grid VARCHAR (16),
    grid_dial VARCHAR (64),
    grid_type VARCHAR (64),
    grid_snr VARCHAR (16),
    grid_timestamp TIMESTAMP
)
""")
conn.commit()

new_val = "Default"
c.execute("INSERT INTO profile(title, def) VALUES ('Default', 1)")
c.execute("INSERT INTO setting (name, value) VALUES ('udp_ip','127.0.0.1'),('udp_port','2242'),('tcp_ip','127.0.0.1'),('tcp_port','2442'),('hide_heartbeat',0),('dark_theme',0)")

conn.commit()
conn.close()
