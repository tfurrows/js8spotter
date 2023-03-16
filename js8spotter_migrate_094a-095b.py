# JS8Spotter InitDB v0.5b - 12/08/2022
# Utility to migrate 0.94a database to 0.95b format
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

# create the missing table
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
conn.close()
