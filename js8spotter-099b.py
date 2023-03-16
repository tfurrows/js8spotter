# JS8Spotter v0.99b.  Special thanks to KE0DHO, KF0HHR, N0GES, N6CYB, KQ4DRG, and N4FWD for help with development and testing.
#
# A small JS8Call API-based app to keep track of activity containing specific search terms, including callsigns or other activity. Matches on RX.ACTIVITY,
# RX.DIRECTED, and RX.SPOT only. Tested under Windows with JS8Call v2.2.0, and in Linux with JS8Call v2.2.1-devel.
#
# Enable TCP API in JS8Call. File>Settings>Reporting, checkmark on Allow Setting Station Information, Enable TCP Server API, Accept TCP Requests.
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

import tkinter as tk
from tkinter import *
from tkinter import filedialog as fd
from tkinter import ttk, messagebox
from tkinter.ttk import Treeview, Style, Combobox
from tkinter.messagebox import askyesno
from PIL import ImageTk, Image
from threading import *
from threading import Thread
from io import StringIO
import time
import random
import socket
import select
import json
import sqlite3
import re

### Globals
swname = "JS8Spotter"
fromtext = "de KF7MIX"
swversion = "0.99b"

dbfile = 'js8spotter.db'
conn = sqlite3.connect(dbfile)
c = conn.cursor()

current_profile_id = 0
search_strings = []
bgsearch_strings = {}
expects = {}
expect_prefix = "E:"

map_loc = 0 # For map, 0=North America, 1=Europe
maplocs = ["North America", "Europe"]
gridmultiplier = [
        {
                "CL":[0,0], "CM":[0,1], "CN":[0,2], "CO":[0,3],
                "DL":[1,0], "DM":[1,1], "DN":[1,2], "DO":[1,3],
                "EL":[2,0], "EM":[2,1], "EN":[2,2], "EO":[2,3],
                "FL":[3,0], "FM":[3,1], "FN":[3,2], "FO":[3,3],
        },
        {
                "IM":[0,0], "IN":[0,1], "IO":[0,2], "IP":[0,3],
                "JM":[1,0], "JN":[1,1], "JO":[1,2], "JP":[1,3],
                "KM":[2,0], "KN":[2,1], "KO":[2,2], "KP":[2,3],
                "LM":[3,0], "LN":[3,1], "LO":[3,2], "LP":[3,3],
        },
]
markeropts = ["Latest 100", "Latest 50", "Latest 25", "Latest 10"]

### Database settings table
c.execute("SELECT * FROM setting")
dbsettings = c.fetchall()

# Build any missing default settings
if len(dbsettings)<9:
    c.execute("INSERT INTO setting(name,value) VALUES ('udp_ip','127.0.0.1'),('udp_port','2242'),('tcp_ip','127.0.0.1'),('tcp_port','2442'),('hide_heartbeat','0'),('dark_theme','0'),('marker_index','0'),('callsign','FILL'),('grid','FILL')")
    conn.commit()
    c.execute("SELECT * FROM setting")
    dbsettings.clear()
    dbsettings = c.fetchall()

# setup settings dictionary
settings = {}
for setting in dbsettings:
    settings[setting[1]]=setting[2]

### Thread for processing output of JS8Call over socket

# for inter-thread comms
event = Event()

class TCP_RX(Thread):

    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self.keep_running = True

    def stop(self):
        self.keep_running = False

    def run(self):
        conn1 = sqlite3.connect(dbfile)
        c1 = conn1.cursor()

        track_types = {"RX.ACTIVITY", "RX.DIRECTED", "RX.SPOT"}

        while self.keep_running:
            rfds, _wfds, _xfds = select.select([self.sock], [], [], 0.5) # check every 0.5sec
            if self.sock in rfds:
                try:
                    iodata = self.sock.recv(2048)
                    # tcp connection may return multiple json lines
                    json_lines = StringIO(str(iodata,'UTF-8'))
                    for data in json_lines:
                        try:
                            data_json = json.loads(data)
                        except ValueError as error:
                            data_json = {'type':'error'}

                        if data_json['type'] in track_types:
                            ## Gather basic elements of this record
                            msg_call = ""
                            if "CALL" in data_json['params']: msg_call = data_json['params']['CALL']
                            if "FROM" in data_json['params']: msg_call = data_json['params']['FROM']

                            msg_dial = ""
                            if "DIAL" in data_json['params']: msg_dial = data_json['params']['DIAL']

                            msg_snr = ""
                            if "SNR" in data_json['params']: msg_snr = data_json['params']['SNR']

                            msg_value = data_json['value']

                            ## Before scans, save grid info (from CQ, spot, hb, msg)
                            msg_grid = ""
                            if "GRID" in data_json['params']: msg_grid = data_json['params']['GRID'].strip()
                            if msg_grid != "":
                                gridsql = "INSERT INTO grid(grid_callsign,grid_grid,grid_dial,grid_type,grid_snr,grid_timestamp) VALUES (?,?,?,?,?, CURRENT_TIMESTAMP)"
                                c1.execute(gridsql, [msg_call, msg_grid, msg_dial, data_json['type'], msg_snr])
                                conn1.commit()

                            ## Expect subsystem. Check for expect prefix "<from>: <to> E? <expect>" and process. Relayed form "<relay>: <to>> E? <expect> *DE* <from>"
                            reply_to = ""
                            ex_reply = ""
                            ex_expect = ""
                            ex_relay = ""

                            # scan for direct request expect
                            scan_expect = re.search("([A-Z0-9]+):\s+?(@?[A-Z0-9]+)\s+?E\?\s+?([A-Z0-9]+)",msg_value) # from, to, expect
                            if scan_expect:
                                ex_from = scan_expect.group(1)
                                ex_to = scan_expect.group(2)
                                ex_expect = scan_expect.group(3)
                            else:
                                # scan for relayed request expect
                                scan_expect = re.search("([A-Z0-9]+):\s+?([A-Z0-9]+)\>?\s+?E\?\s+?([A-Z0-9]+)\s+?\*DE\*?\s+?([A-Z0-9]+)?",msg_value) # relay, to, expect, from
                                if scan_expect:
                                    ex_relay = scan_expect.group(1)
                                    ex_to = scan_expect.group(2)
                                    ex_expect = scan_expect.group(3)
                                    ex_from = scan_expect.group(4)

                            if ex_expect:
                                # check if expect is in database
                                c1.execute("SELECT * FROM expect WHERE expect = ?", [ex_expect])
                                ex_exists = c1.fetchone()
                                if ex_exists:
                                    # found expect command. Check if requestor is in allowed list, or * for any station
                                    for allow in ex_exists[2].split(","):
                                        if allow[0]=="@":
                                            if ex_to == allow: reply_to = ex_to
                                        else:
                                            if ex_from==allow and ex_to==settings['callsign']: reply_to = ex_from
                                    if ex_exists[2]=="*" and ex_to==settings['callsign']: reply_to = ex_from
                                    if reply_to:
                                        # make sure that txmax hasn't been exceeded
                                        reply_count=len(ex_exists[3].split(","))-1
                                        if reply_count<int(ex_exists[4]):
                                            #formulate reply, relay or regular
                                            if ex_relay:
                                                ex_reply = settings['callsign']+": "+ex_relay+"> "+reply_to+" "+ex_exists[1]
                                                time.sleep(120) # ugly last-ditch workaround relay ACK delays
                                            else:
                                                ex_reply = settings['callsign']+": "+reply_to+" "+ex_exists[1]

                                            tx_content = json.dumps({"params":{},"type":"TX.SEND_MESSAGE","value":ex_reply})
                                            self.sock.send(bytes(tx_content + '\n','utf-8'))
                                            time.sleep(0.25)

                                            # append database txlist
                                            if ex_exists[3] == "":
                                                sql = "UPDATE expect SET txlist = '"+reply_to+",' WHERE expect = ?"
                                            else:
                                                sql = "UPDATE expect SET txlist = txlist || '"+reply_to+",' WHERE expect = ?"
                                            c1.execute(sql,[ex_expect])
                                            conn1.commit()

                            ## Scan for search terms
                            msg_value=""
                            # if search term is in 'value' or 'call' then insert into db. Check visible profile terms, make copy in case other thread modifies dict
                            searchcheck = search_strings.copy()
                            for term in searchcheck:
                                if (term in msg_call) or (term in data_json['value']):
                                    sql = "UPDATE search SET last_seen = CURRENT_TIMESTAMP WHERE profile_id = ? AND keyword = ?"
                                    c1.execute(sql, [current_profile_id,term])
                                    conn1.commit()

                                    sql = "INSERT INTO activity(profile_id,type,value,dial,snr,call,spotdate) VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)"
                                    c1.execute(sql, [current_profile_id,data_json['type'],data_json['value'],msg_dial,msg_snr,msg_call])
                                    conn1.commit()
                                    event.set()

                            # Check background scan profile terms. Make copy in case other thread modifies dict
                            bgcheck = bgsearch_strings.copy();
                            for term in bgcheck.keys():
                                term_profile = bgcheck.get(term)
                                if (term in msg_call) or (term in data_json['value']):
                                    sql = "UPDATE search SET last_seen = CURRENT_TIMESTAMP WHERE profile_id = ? AND keyword = ?"
                                    c1.execute(sql, [term_profile,term])
                                    conn1.commit()

                                    sql = "INSERT INTO activity(profile_id,type,value,dial,snr,call,spotdate) VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)"
                                    c1.execute(sql, [term_profile,data_json['type'],data_json['value'],msg_dial,msg_snr,msg_call])
                                    conn1.commit()
                                    event.set()

                except socket.error as err:
                    print("TCP error at receiving socket {}".format(err))
                    break


### Main program thread
class App(tk.Tk):
    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self.sender = None
        self.receiver = None
        self.protocol("WM_DELETE_WINDOW", self.menu_bye)

        self.style = Style()
        self.call("source", "azure.tcl")

        self.create_gui()
        self.activate_theme()

        self.build_profilemenu()
        self.refresh_keyword_tree()
        self.refresh_activity_tree()

        self.start_receiving()
        self.poll_activity()

        self.eval('tk::PlaceWindow . center')
        self.update()

        self.get_expects()

        if self.sock == None:
            messagebox.showinfo("TCP Error","Can't connect to JS8Call. Make sure it is running, and check your TCP settings before restarting JS8Spotter.")


    # Setup gui
    def create_gui(self):
        self.title(swname+" "+fromtext+" (v"+swversion+")")
        self.geometry('900x400')
        self.resizable(width=False, height=False)

        self.columnconfigure(0, weight=12)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=12)
        self.columnconfigure(3, weight=1)

        self.rowconfigure(0,weight=1)
        self.rowconfigure(1,weight=1)
        self.rowconfigure(2,weight=24)
        self.rowconfigure(3,weight=6)

        # menus
        self.menubar = Menu(self)
        self.filemenu = Menu(self.menubar, tearoff = 0)
        self.profilemenu = Menu(self.menubar, tearoff = 0)

        self.filemenu.add_cascade(label = 'Switch Profile', menu = self.profilemenu)
        self.filemenu.add_separator()
        self.filemenu.add_command(label = 'New Profile', command = self.menu_new)
        self.filemenu.add_command(label = 'Edit Profile', command = self.menu_edit)
        self.filemenu.add_command(label = 'Remove Profile', command = self.menu_remove)
        self.filemenu.add_separator()
        self.filemenu.add_command(label = 'Settings', command = self.settings_edit)
        self.filemenu.add_separator()
        self.filemenu.add_command(label = 'Exit', command = self.menu_bye)

        self.viewmenu = Menu(self.menubar, tearoff = 0)
        self.viewmenu.add_command(label = "Hide Heartbeats", command = self.toggle_view_hb)
        self.viewmenu.add_command(label = "Dark Theme", command = self.toggle_theme)

        self.toolsmenu = Menu(self.menubar, tearoff = 0)
        self.toolsmenu.add_command(label = 'Map', command = self.grid_map)
        self.toolsmenu.add_command(label = 'Expect', command = self.expect)

        self.helpmenu = Menu(self.menubar, tearoff = 0)
        self.helpmenu.add_command(label = 'Quick Help', command = self.showhelp)
        self.helpmenu.add_command(label = 'About', command = self.about)

        self.menubar.add_cascade(label = 'File', menu = self.filemenu)
        self.menubar.add_cascade(label = 'View', menu = self.viewmenu)
        self.menubar.add_cascade(label = 'Tools', menu = self.toolsmenu)
        self.menubar.add_cascade(label = 'Help', menu = self.helpmenu)
        self.config(menu = self.menubar)

        # Profile title and select
        self.prframe = ttk.Frame(self)
        self.prframe.grid(row=0, column=0, columnspan=2, sticky=NSEW, padx=10, pady=(0,5))

        self.profilemark = ttk.Label(self.prframe, text='Profile:', font=("Segoe Ui Bold", 14))
        self.profilemark.grid(row=0, column = 0, sticky='W', padx=0, pady=(8,0))
        self.profilecombo = ttk.Combobox(self.prframe, values="", state='readonly')
        self.profilecombo.grid(row=0, column =1 , sticky='E', padx=8, pady=(8,0))
        self.profilecombo.bind('<<ComboboxSelected>>', self.profile_sel_combo)

        # background process checkbox
        self.current_profile_scan = IntVar()
        self.bgcheck = ttk.Checkbutton(self.prframe, text='Background Scan',variable=self.current_profile_scan, command=self.toggle_bg_scan)
        self.bgcheck.grid(row=0, column=2, sticky='W', pady=(8,0))

        # titles
        self.keywordmark = Label(self, text='Search Terms', fg='blue', font=("Segoe Ui", 12))
        self.keywordmark.grid(row=1, column = 0, sticky='W', padx=10)
        self.activitymark = Label(self, text="Matched Activity (last 100)", fg='purple', font=("Segoe Ui", 12))
        self.activitymark.grid(row=1, column = 2, sticky='W', padx=10)

        # keyword treeview
        self.keywords = ttk.Treeview(self, show='headings', style='keywords.Treeview')
        self.keywords["columns"]=("search","last_seen")

        self.keywords.column("search")
        self.keywords.column("last_seen")

        self.keywords.heading("search", text="Search")
        self.keywords.heading("last_seen", text="Last Seen")

        self.keywords.bind('<Double-1>', self.view_keyword_activity)
        self.keywords.grid(row=2, column=0, sticky=NSEW, padx=(10,0), pady=(0,10))
        self.kwscrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.keywords.yview)
        self.keywords.configure(yscroll=self.kwscrollbar.set)
        self.kwscrollbar.grid(row=2, column=1, sticky=NS, padx=(0,0), pady=(0,10))

        # activity treeview
        self.activity = ttk.Treeview(self, show='headings', style='activity.Treeview', selectmode='browse')
        self.activity["columns"]=("type","value","stamp")

        self.activity.column('type', width=100, minwidth=100, stretch=0)
        self.activity.column('value', width=210, minwidth=210)
        self.activity.column('stamp', width=130, minwidth=130, stretch=0)

        self.activity.heading('type', text='Type')
        self.activity.heading('value', text='Activity')
        self.activity.heading('stamp', text='When')

        self.activity.bind('<Double-1>', self.view_activity)
        self.activity.grid(row=2, column=2, sticky=NSEW, padx=(10,0), pady=(0,10))
        self.acscrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.activity.yview)
        self.activity.configure(yscroll=self.acscrollbar.set)
        self.acscrollbar.grid(row=2, column=3, sticky=NS, padx=(0,10), pady=(0,10))

        # add inputs and buttons below treeviews
        self.kwframe = Frame(self)
        self.kwframe.grid(row=3, column=0, columnspan=2, sticky=NSEW, padx=10, pady=(0,10))
        self.new_keyword = ttk.Entry(self.kwframe, width = '14')
        self.new_keyword.grid(row = 0, column = 0)
        self.new_keyword.bind('<Return>', lambda x: self.proc_addkw())

        self.addkw_button = ttk.Button(self.kwframe, text = '+', command = self.proc_addkw, width='2')
        self.addkw_button.grid(row=0, column = 1, padx=(8,8))
        self.removekw_button = ttk.Button(self.kwframe, text = '-', command = self.proc_remkw, width='2')
        self.removekw_button.grid(row=0, column = 2)

        self.addbat_button = ttk.Button(self.kwframe, text = 'Import', command = self.add_batch, width='6')
        self.addbat_button.grid(row=0, column = 3, padx=(28,0))
        self.expbat_button = ttk.Button(self.kwframe, text = 'Export', command = self.proc_exportsearch, width='6')
        self.expbat_button.grid(row=0, column = 4, padx=8)

        self.acframe = ttk.Frame(self)
        self.acframe.grid(row=3, column=2, sticky='NWE')
        self.acframe.grid_columnconfigure(0, weight=1)

        #self.map_button = ttk.Button(self.acframe, text = 'Map', command = self.grid_map, width='3')
        #self.map_button.grid(row=0, column=0, sticky='NE', padx=(0,8), pady=0)

        #self.map_button = ttk.Button(self.acframe, text = 'Expect', command = self.expect, width='5')
        #self.map_button.grid(row=0, column=1, sticky='NE', padx=(0,40), pady=0)

        self.expact_button = ttk.Button(self.acframe, text = 'Export Log', command = self.proc_exportlog)
        self.expact_button.grid(row=0, column=2, sticky='NE', padx=(0,8), pady=0)

        self.clearact_button = ttk.Button(self.acframe, text = 'Clear Log', command = self.proc_dellog)
        self.clearact_button.grid(row=0, column=3, sticky='NE', padx=0, pady=0)


    # select light/dark theme
    def toggle_theme(self):
        global settings
        if settings['dark_theme'] == "1":
            c.execute("UPDATE setting SET value = '0' WHERE name = 'dark_theme'")
            conn.commit()
            settings['dark_theme'] = "0"
        else:
            c.execute("UPDATE setting SET value = '1' WHERE name = 'dark_theme'")
            conn.commit()
            settings['dark_theme'] = "1"
        self.activate_theme()


    # activate the current theme
    def activate_theme(self):
        if settings['dark_theme'] == "1":
            self.viewmenu.entryconfigure(1, label="\u2713 Dark Theme")
            self.call("set_theme", "dark")
            self.keywordmark.configure(fg='#6699FF')
            self.activitymark.configure(fg='#CC66FF')
            self.style.map('keywords.Treeview', background=[('selected', '#4477FF')])
            self.style.map('activity.Treeview', background=[('selected', '#AA44FF')])
            self.activity.tag_configure('oddrow', background='#777')
            self.activity.tag_configure('evenrow', background='#555')
            self.keywords.tag_configure('oddrow', background='#777')
            self.keywords.tag_configure('evenrow', background='#555')
        else:
            self.viewmenu.entryconfigure(1, label="Dark Theme")
            self.call("set_theme", "light")
            self.keywordmark.configure(fg='#4477FF')
            self.activitymark.configure(fg='#AA44FF')
            self.style.map('keywords.Treeview', background=[('selected', '#6699FF')])
            self.style.map('activity.Treeview', background=[('selected', '#CC66FF')])
            self.activity.tag_configure('oddrow', background='#FFF')
            self.activity.tag_configure('evenrow', background='#EEE')
            self.keywords.tag_configure('oddrow', background='#FFF')
            self.keywords.tag_configure('evenrow', background='#EEE')
        self.update()


    # Add keyword to database/tree
    def proc_addkw(self):
        new_kw = self.new_keyword.get().upper()
        if new_kw == "": return
        c.execute("SELECT * FROM search WHERE profile_id = ? AND keyword = ?", [current_profile_id,new_kw])
        kw_exists = c.fetchone()
        if not kw_exists:
            c.execute("INSERT INTO search(profile_id,keyword) VALUES (?,?)", [current_profile_id,new_kw])
            conn.commit()
            self.refresh_keyword_tree()
        self.new_keyword.delete(0,END)


    # Add a batch of keywords
    def add_batch(self):
        self.top = Toplevel(self)
        self.top.title("Add Batch of Search Terms")
        self.top.geometry('400x500')

        self.addbatmark = ttk.Label(self.top, text="Type or paste search terms, one per line", font=('10'))
        self.addbatmark.pack(side=TOP, anchor=NW, padx=10, pady=10)

        # save button
        tlframe = ttk.Frame(self.top)
        tlframe.pack(side=BOTTOM, anchor=SW, padx=10, pady=(0,10))
        self.save_button = ttk.Button(tlframe, text = 'Add Batch', command = self.proc_addbatch)
        self.save_button.pack(side=LEFT, padx=(0,10))

        # Text window
        self.batch = Text(self.top, wrap=NONE)
        batch_scrollbar = ttk.Scrollbar(self.top)
        batch_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(0,10))
        batch_scrollbar.config(command=self.batch.yview)
        self.batch.pack(side=LEFT, expand=True, fill='both', padx=(10,0), pady=(0,10))

        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # add multiple search terms at once
    def proc_addbatch(self):
        batch_values = StringIO(self.batch.get('1.0','end'))
        for line in batch_values:
            new_kw = line.rstrip().upper()
            if new_kw == "": continue
            c.execute("SELECT * FROM search WHERE profile_id = ? AND keyword = ?", [current_profile_id,new_kw])
            kw_exists = c.fetchone()
            if not kw_exists:
                c.execute("INSERT INTO search(profile_id,keyword) VALUES (?,?)", [current_profile_id,new_kw])
                conn.commit()
        self.top.destroy()
        self.refresh_keyword_tree()


    # export search terms
    def proc_exportsearch(self):
        self.top = Toplevel(self)
        self.top.title("Export Search Terms")
        self.top.geometry('400x500')

        self.exportmark = ttk.Label(self.top, text="Copy/Export Search Terms", font=('10'))
        self.exportmark.pack(side=TOP, anchor=NW, padx=10, pady=10)

        # save and copy buttons
        tlframe = ttk.Frame(self.top)
        tlframe.pack(side=BOTTOM, anchor=SW, padx=10, pady=(0,10))
        self.copy_button = ttk.Button(tlframe, text = 'Copy All', command = self.export_copy_all)
        self.copy_button.pack(side=LEFT, padx=(0,10))
        self.saveas_button = ttk.Button(tlframe, text = 'Save As', command = self.export_saveas_popup)
        self.saveas_button.pack(side=RIGHT)

        # Text window
        self.export_text = Text(self.top, wrap=NONE)
        export_scrollbar = ttk.Scrollbar(self.top)
        export_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(0,10))
        export_scrollbar.config(command=self.export_text.yview)
        self.export_text.pack(side=LEFT, expand=True, fill='both', padx=(10,0), pady=(0,10))

        # right-click action
        self.rcmenu = Menu(self.top, tearoff = 0)
        self.rcmenu.add_command(label = 'Copy')
        self.export_text.bind('<Button-3>', lambda ev: self.export_copy_popup(ev))

        c.execute("SELECT * FROM search WHERE profile_id = ? ORDER BY last_seen DESC",[current_profile_id])
        export_kw_records = c.fetchall()

        for record in export_kw_records:
            insert_rec = record[2]+"\n"
            self.export_text.insert(tk.END, insert_rec)

        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # Remove keyword from database/tree
    def proc_remkw(self):
        kwlist = ""
        for kwiid in self.keywords.selection():
            kwlist += self.keywords.item(kwiid)['values'][0]+"\n"

        if kwlist == "": return

        msgtxt = "Remove the following search term(s)?\n"+kwlist
        answer = askyesno(title='Remove Search Term(s)?', message=msgtxt)
        if answer:
            for kwiid in self.keywords.selection():
                c.execute("DELETE FROM search WHERE id = ? AND profile_id = ?", [kwiid,current_profile_id])
                conn.commit()
                self.refresh_keyword_tree()


    # Toggle Heartbeat Display in activity pane
    def toggle_view_hb(self):
        global settings
        if settings['hide_heartbeat'] == "1":
            c.execute("UPDATE setting SET value = '0' WHERE name = 'hide_heartbeat'")
            conn.commit()
            settings['hide_heartbeat'] = "0"
        else:
            c.execute("UPDATE setting SET value = '1' WHERE name = 'hide_heartbeat'")
            conn.commit()
            settings['hide_heartbeat'] = "1"
        self.refresh_activity_tree()


    # Toggle background scan setting for current profile
    def toggle_bg_scan(self):
        bg_setting = self.current_profile_scan.get()
        if bg_setting == 1:
            c.execute("UPDATE profile SET bgscan = 1 WHERE id = ?", [current_profile_id])
            conn.commit()
        else:
            c.execute("UPDATE profile SET bgscan = 0 WHERE id = ?", [current_profile_id])
            conn.commit()
        self.refresh_keyword_tree()


    def showhelp(self):
        self.top = Toplevel(self)
        self.top.title("JS8Spotter Help")
        self.top.geometry('650x500')

         # display window
        self.help_text = Text(self.top, wrap=NONE)
        help_scrollbar = ttk.Scrollbar(self.top)
        help_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(10,10))
        help_scrollbar.config(command=self.help_text.yview)
        self.help_text.pack(side=LEFT, expand=True, fill='both', padx=(10,0), pady=(10,10))

        help_file = open("HELP.txt", "r")
        help_contents = help_file.read()
        help_file.close()
        self.help_text.insert(tk.END, help_contents)

        self.help_text.configure(state='disabled')
        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # Export activity log for current profile
    def proc_exportlog(self):
        global current_profile_id
        c.execute("SELECT * FROM profile WHERE id = ?",[current_profile_id])
        profile_record = c.fetchone()

        self.top = Toplevel(self)
        self.top.title("Export "+profile_record[1]+" Activity")
        self.top.geometry('650x500')

        self.exportmark = ttk.Label(self.top, text="Tab-delimited export for profile:"+profile_record[1], font=("10"))
        self.exportmark.pack(side=TOP, anchor=NW, padx=10, pady=10)

        # save and copy buttons
        tlframe = ttk.Frame(self.top)
        tlframe.pack(side=BOTTOM, anchor=SW, padx=10, pady=(0,10))
        self.copy_button = ttk.Button(tlframe, text = 'Copy All', command = self.export_copy_all)
        self.copy_button.pack(side=LEFT, padx=(0,10))
        self.saveas_button = ttk.Button(tlframe, text = 'Save As', command = self.export_saveas_popup)
        self.saveas_button.pack(side=RIGHT)

        # Text window
        self.export_text = Text(self.top, wrap=NONE)
        export_scrollbar = ttk.Scrollbar(self.top)
        export_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(0,10))
        export_scrollbar.config(command=self.export_text.yview)
        self.export_text.pack(side=LEFT, expand=True, fill='both', padx=(10,0), pady=(0,10))

        # right-click action
        self.rcmenu = Menu(self.top, tearoff = 0)
        self.rcmenu.add_command(label = 'Copy')
        self.export_text.bind('<Button-3>', lambda ev: self.export_copy_popup(ev))

        c.execute("SELECT * FROM activity WHERE profile_id = ? ORDER BY spotdate DESC",[current_profile_id])
        export_activity_records = c.fetchall()

        for record in export_activity_records:
            insert_rec = record[7]+"\t"+record[2]+"\t"+record[3]+"\t"+record[4]+"\t"+record[5]+"\t"+record[6]+"\n"
            self.export_text.insert(tk.END, insert_rec)

        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # export saveas
    def export_saveas_popup(self):
        fname = fd.asksaveasfilename(defaultextension=".txt")
        if fname is None or fname == '': return
        saveas_text = str(self.export_text.get('1.0', 'end'))
        with open(fname,mode='w',encoding='utf-8') as f:
            f.write(saveas_text)
            f.close()


    # export copy button
    def export_copy_all(self):
        self.clipboard_clear()
        text = self.export_text.get('1.0', 'end')
        self.clipboard_append(text)
        self.copy_button.configure(text="Copied")


    # export right-click copy action
    def export_copy_popup(self, ev):
        self.rcmenu.tk_popup(ev.x_root,ev.y_root)
        self.clipboard_clear()
        text = self.export_text.get('sel.first', 'sel.last')
        self.clipboard_append(text)


    # Delete profile activity log entries
    def proc_dellog(self):
        global current_profile_id

        c.execute("SELECT * FROM profile WHERE id = ?",[current_profile_id])
        profile_record = c.fetchone()

        msgtxt = "Are you sure you want to remove all activity for the "+profile_record[1]+" profile? This action cannot be undone."
        answer = askyesno(title='Clear Log?', message=msgtxt)
        if answer:
            # delete associated activity logs from the database
            c.execute("DELETE FROM activity WHERE profile_id = ?", [current_profile_id])
            conn.commit()
            # refresh log treeview
            self.refresh_activity_tree()


    # View activity from main window
    def view_activity(self, ev):
        aciid = int(self.activity.focus())
        c.execute("SELECT * FROM activity WHERE id = ?",[aciid])
        activity = c.fetchone()
        messagebox.showinfo("Activity Detail",activity)


    # View activity details by type, from search term detail window
    def view_activity_type(self, rxtype):
        if rxtype=="act": aciid = int(self.top.activity.focus())
        if rxtype=="dir": aciid = int(self.top.directed.focus())
        if rxtype=="spot": aciid = int(self.top.spot.focus())

        c.execute("SELECT * FROM activity WHERE id = ?",[aciid])
        activity = c.fetchone()
        messagebox.showinfo("Activity Detail",activity, parent=self.top)


    # View search term detail window, divided by type
    def view_keyword_activity(self, ev):
        if not self.keywords.focus(): return
        kwiid = int(self.keywords.focus())
        c.execute("SELECT * FROM search WHERE id = ?",[kwiid])
        search = c.fetchone()

        self.top = Toplevel(self)
        self.top.title("Search Term Activity")
        self.top.geometry('440x700')
        self.top.resizable(width=False, height=False)

        kwvals = self.keywords.item(kwiid)
        msgtxt = kwvals['values'][0]+" Activity"

        self.top.activitymark = ttk.Label(self.top, text=msgtxt, font=("14"))
        self.top.activitymark.grid(row=0, column = 0, sticky="W", padx=10)

        # RX.ACTIVITY treeview
        self.top.activitymark = ttk.Label(self.top, text="RX.ACTIVITY", font=("12"))
        self.top.activitymark.grid(row=1, column = 0, sticky="W", padx=10)

        self.top.activity = ttk.Treeview(self.top, show='headings', selectmode="browse", height="6")
        self.top.activity["columns"]=("value","stamp")

        self.top.activity.column("value", width=240, minwidth=240)
        self.top.activity.column("stamp", width=120, minwidth=120, stretch=0)

        self.top.activity.heading('value', text='Activity')
        self.top.activity.heading('stamp', text='When')

        self.top.activity.bind('<Double-1>', lambda x: self.view_activity_type("act"))
        self.top.activity.grid(row=2, column = 0, sticky='NSEW', padx=(10,0), pady=(0,10))
        self.top.acscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.top.activity.yview)
        self.top.activity.configure(yscroll=self.top.acscrollbar.set)
        self.top.acscrollbar.grid(row=2, column=1, sticky='NSEW', padx=(0,10), pady=(0,10))

        sql = "SELECT * FROM activity WHERE profile_id = ? AND type = ? AND (call LIKE ? OR value LIKE ?) ORDER BY spotdate DESC"
        c.execute(sql,[current_profile_id,"RX.ACTIVITY",'%'+search[2]+'%','%'+search[2]+'%'])
        tactivity_records = c.fetchall()

        count=0
        for record in tactivity_records:
            if count % 2 == 0:
                self.top.activity.insert('', tk.END, iid=record[0], values=(record[3],record[7]), tags=('oddrow'))
            else:
                self.top.activity.insert('', tk.END, iid=record[0], values=(record[3],record[7]), tags=('evenrow'))
            count+=1

        # RX.DIRECTED treeview
        self.top.directedmark = ttk.Label(self.top, text="RX.DIRECTED", font=("12"))
        self.top.directedmark.grid(row=3, column = 0, sticky="W", padx=10)

        self.top.directed = ttk.Treeview(self.top, show='headings', selectmode="browse", height="6")
        self.top.directed["columns"]=("value","stamp")

        self.top.directed.column("value", width=240, minwidth=240)
        self.top.directed.column("stamp", width=120, minwidth=120, stretch=0)

        self.top.directed.heading('value', text='Directed')
        self.top.directed.heading('stamp', text='When')

        self.top.directed.bind('<Double-1>', lambda x: self.view_activity_type("dir"))
        self.top.directed.grid(row=4, column=0, sticky=NSEW, padx=(10,0), pady=(0,10))
        self.top.acscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.top.directed.yview)
        self.top.directed.configure(yscroll=self.top.acscrollbar.set)
        self.top.acscrollbar.grid(row=4, column=1, sticky=NS, padx=(0,10), pady=(0,10))

        sql = "SELECT * FROM activity WHERE profile_id = ? AND type = ? AND (call LIKE ? OR value LIKE ?) ORDER BY spotdate DESC"
        c.execute(sql,[current_profile_id,"RX.DIRECTED",'%'+search[2]+'%','%'+search[2]+'%'])
        dactivity_records = c.fetchall()

        count=0
        for record in dactivity_records:
            if count % 2 == 0:
                self.top.directed.insert('', tk.END, iid=record[0], values=(record[3],record[7]), tags=('oddrow'))
            else:
                self.top.directed.insert('', tk.END, iid=record[0], values=(record[3],record[7]), tags=('evenrow'))
            count+=1

        # RX.DIRECTED treeview
        self.top.spotmark = ttk.Label(self.top, text="RX.SPOT", font=("12"))
        self.top.spotmark.grid(row=5, column = 0, sticky="W", padx=10)

        self.top.spot = ttk.Treeview(self.top, show='headings', selectmode="browse", height="6")
        self.top.spot["columns"]=("snr","call","stamp")

        self.top.spot.column("snr", width=60, minwidth=60)
        self.top.spot.column("call", width=180, minwidth=180)
        self.top.spot.column("stamp", width=120, minwidth=120, stretch=0)

        self.top.spot.heading('snr', text='SNR')
        self.top.spot.heading('call', text='Call')
        self.top.spot.heading('stamp', text='When')

        self.top.spot.bind('<Double-1>', lambda x: self.view_activity_type("spot"))
        self.top.spot.grid(row=6, column=0, sticky=NSEW, padx=(10,0), pady=(0,10))
        self.top.acscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.top.spot.yview)
        self.top.spot.configure(yscroll=self.top.acscrollbar.set)
        self.top.acscrollbar.grid(row=6, column=1, sticky=NS, padx=(0,10), pady=(0,10))

        sql = "SELECT * FROM activity WHERE profile_id = ? AND type = ? AND (call LIKE ? OR value LIKE ?) ORDER BY spotdate DESC"
        c.execute(sql,[current_profile_id,"RX.SPOT",'%'+search[2]+'%','%'+search[2]+'%'])
        sactivity_records = c.fetchall()

        count=0
        for record in sactivity_records:
            if count % 2 == 0:
                self.top.spot.insert('', tk.END, iid=record[0], values=(record[5],record[6],record[7]), tags=('oddrow'))
            else:
                self.top.spot.insert('', tk.END, iid=record[0], values=(record[5],record[6],record[7]), tags=('evenrow'))
            count+=1

        # set colors based on theme
        if settings['dark_theme']=='1':
            self.top.activity.tag_configure('oddrow', background='#777')
            self.top.activity.tag_configure('evenrow', background='#555')
            self.top.directed.tag_configure('oddrow', background='#777')
            self.top.directed.tag_configure('evenrow', background='#555')
            self.top.spot.tag_configure('oddrow', background='#777')
            self.top.spot.tag_configure('evenrow', background='#555')
        else:
            self.top.activity.tag_configure('oddrow', background='#FFF')
            self.top.activity.tag_configure('evenrow', background='#EEE')
            self.top.directed.tag_configure('oddrow', background='#FFF')
            self.top.directed.tag_configure('evenrow', background='#EEE')
            self.top.spot.tag_configure('oddrow', background='#FFF')
            self.top.spot.tag_configure('evenrow', background='#EEE')

        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # Display a maidenhead grid map with SPOT locations
    def grid_map(self):
        global map_loc
        self.top = Toplevel(self)
        self.top.title("Grid Location Map")
        self.top.geometry('1120x465')
        self.top.resizable(width=False, height=False)

        # callsign GRID treeview
        self.top.gridcall = ttk.Treeview(self.top, show='headings', style='keywords.Treeview')
        self.top.gridcall["columns"]=("call","grid","snr","last_seen")

        self.top.gridcall.column("call")
        self.top.gridcall.column("grid")
        self.top.gridcall.column("snr")
        self.top.gridcall.column("last_seen")

        self.top.gridcall.column("call", width=45, minwidth=45)
        self.top.gridcall.column("grid", width=30, minwidth=30)
        self.top.gridcall.column("snr", width=30, minwidth=30, stretch=0)
        self.top.gridcall.column("last_seen", width=120, minwidth=120, stretch=0)

        self.top.gridcall.heading("call", text="Call")
        self.top.gridcall.heading("grid", text="Grid")
        self.top.gridcall.heading("snr", text="SNR")
        self.top.gridcall.heading("last_seen", text="Last Seen")

        self.top.gridcall.bind('<Return>', self.highlight_grid)
        self.top.gridcall.bind('<Double-1>', self.highlight_grid)
        self.top.gridcall.bind('<Delete>', self.delete_grid)
        self.top.gridcall.grid(row=0, column=1, sticky=NSEW, padx=(10,0), pady=(10,10))

        self.top.gcscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.top.gridcall.yview)
        self.top.gridcall.configure(yscroll=self.top.gcscrollbar.set)
        self.top.gcscrollbar.grid(row=0, column=2, sticky=NS, padx=(0,0), pady=(10,10))

        # map frame
        self.top.map = ttk.Frame(self.top)

        self.top.canvas = Canvas(self.top.map, width=806, height=406)
        self.top.map.grid(row=0,column=0, padx=(10,0), pady=(10,0))

        #self.top.canvas.bind("<Button-1>",self.clickmap_grid)
        self.top.gridcall.tag_configure('notshown', foreground='gray')

        # status info box for highlighted marker
        self.top.grid_status = ttk.Entry(self.top, width = '75')
        self.top.grid_status.grid(row = 1, column = 0)

        # map select
        self.top.maploc = ttk.Combobox(self.top, values=maplocs, state='readonly', width='15')
        self.top.maploc.grid(row=1, column =1, sticky=NW, padx=(10,0))
        self.top.maploc.current(map_loc)
        self.top.maploc.bind('<<ComboboxSelected>>', self.maploc_sel_combo)

        # show marker count select
        self.top.markershow = ttk.Combobox(self.top, values=markeropts, state='readonly', width='14')
        self.top.markershow.grid(row=1, column =1, sticky=NE)
        self.top.markershow.current(settings['marker_index'])
        self.top.markershow.bind('<<ComboboxSelected>>', self.markershow_sel_combo)

        self.top.canvas.pack()
        self.update_grid()
        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # select map
    def maploc_sel_combo(self, ev):
        global map_loc
        map_loc = self.top.maploc.current()
        self.update_grid()


    # show n markers
    def markershow_sel_combo(self, ev):
        global settings
        settings['marker_index'] = str(self.top.markershow.current())
        # save change in settings table
        c.execute("UPDATE setting SET value = '"+settings['marker_index']+"' WHERE name = 'marker_index'")
        conn.commit()
        self.update_grid()


    # update/refresh map and markers
    def update_grid(self):
        # preserve focus after refresh
        gciid=""
        if self.top.gridcall.focus(): gciid = self.top.gridcall.focus()

        # clear out and rebuild
        self.top.canvas.delete('all')

        for entry in self.top.gridcall.get_children():
            self.top.gridcall.delete(entry)

        if map_loc == 1:
                self.top.mapimg = ImageTk.PhotoImage(Image.open('maps/Maidenhead_EU-map.png'))
                self.top.txtimg = ImageTk.PhotoImage(Image.open('maps/Maidenhead_EU-labels.png'))
        else:
                self.top.mapimg = ImageTk.PhotoImage(Image.open('maps/Maidenhead_NA-map.png'))
                self.top.txtimg = ImageTk.PhotoImage(Image.open('maps/Maidenhead_NA-labels.png'))

        # retrieve records
        c.execute("SELECT * FROM grid ORDER BY grid_timestamp DESC LIMIT 100")
        grid_records = c.fetchall()

        for record in grid_records:
            self.top.gridcall.insert('', tk.END, iid=record[0], values=(record[0],record[1],record[4],record[5]))

        # draw background map
        self.top.canvas.create_image(403,203,image=self.top.mapimg)

        if settings['marker_index']=='0': dispcount=101
        if settings['marker_index']=='1': dispcount=51
        if settings['marker_index']=='2': dispcount=26
        if settings['marker_index']=='3': dispcount=11

        # update list view to gray out non-visible entires
        count=0
        for i in self.top.gridcall.get_children():
            count+=1
            if count>=dispcount: self.top.gridcall.item(i, tags='notshown')

        # draw markers
        count = len(grid_records)
        for record in reversed(grid_records):
            if count>=dispcount:
                count-=1
                continue
            gridletters = record[1][:2]
            if gridletters in gridmultiplier[map_loc]:
                pxcoords = self.mh2px(record[1])
                pxcoordX = pxcoords[0]
                pxcoordY = pxcoords[1]

                if count<11: fcolor = "#FF5722"
                if count>10: fcolor = "#00FF00"
                if count>25: fcolor = "#00DD00"
                if count>50: fcolor = "#00AA00"
                if count>75: fcolor = "#007700"

                self.top.canvas.create_rectangle(pxcoordX,pxcoordY,pxcoordX+8,pxcoordY+8, fill=fcolor, outline='black')
            count-=1

        # draw triangle marker for user grid location
        usercoords = self.mh2px(settings['grid'])
        userX = usercoords[0]
        userY = usercoords[1]
        if userX>0 and userY>0:
            self.top.canvas.create_polygon([userX,userY+4,userX+4,userY-4,userX+8,userY+4], outline='red', fill='#0000FF')

        # draw grid text overlay
        self.top.canvas.create_image(403,203,image=self.top.txtimg)

        # restore focus
        if gciid != "":
            if self.top.gridcall.exists(gciid) == True:
                self.top.gridcall.focus(gciid)
                self.top.gridcall.selection_set(gciid)


    # highlight GRID marker
    def highlight_grid(self, ev):
        gciid = self.top.gridcall.focus()

        self.update_grid()

        c.execute("SELECT * FROM grid WHERE grid_callsign = ?", [gciid])
        record = c.fetchone()

        usercoords = self.mh2px(settings['grid'])
        userX = usercoords[0]
        userY = usercoords[1]

        gridletters = record[1][:2]
        if gridletters in gridmultiplier[map_loc]:
            pxcoords = self.mh2px(record[1])
            pxcoordX = pxcoords[0]
            pxcoordY = pxcoords[1]
            if userX>0 and userY>0:
                self.top.canvas.create_line(pxcoordX+3,pxcoordY+3,userX+3,userY+3,fill='#000000', width='2')
            self.top.canvas.create_rectangle(pxcoordX-3,pxcoordY-3,pxcoordX+11,pxcoordY+11, fill='#FF0000', outline='black')

        # update status info
        self.top.grid_status.delete(0,END)
        self.top.grid_status.insert(0,record[0]+" from "+record[1]+"  DIAL:"+record[2]+"  SNR:"+record[4]+"dB   "+record[5])


    # maidenhead to pixels
    def mh2px(self,mhtxt):
        global map_loc
        # convert GRID to pixel coords

        gridletters = mhtxt[:2]
        gridnum1 = mhtxt[2]
        gridnum2 = mhtxt[3]
        pxcoordX=-1 # returns if not found on selected map
        pxcoordY=-1

        if gridletters in gridmultiplier[map_loc]:
            pxcoordX = (gridmultiplier[map_loc][gridletters][0]*200)+(int(gridnum1)*20)+10
            pxcoordY = (400-((gridmultiplier[map_loc][gridletters][1]*100)+(int(gridnum2)*10)))-5
        rpx=[pxcoordX,pxcoordY]
        return rpx


    # delete item from grid map list
    def delete_grid(self, ev):
        gciid = self.top.gridcall.focus()

        answer = askyesno(title="Remove Map Record?", message="This will delete "+gciid+" from the map database. Continue?", parent=self.top)
        if answer:
            c.execute("DELETE FROM grid WHERE grid_callsign = ?", [gciid])
            conn.commit()
            self.update_grid()


    # expect window
    def expect(self):
        self.top = Toplevel(self)
        self.top.title("Expect Auto-Reply Subsystem")
        self.top.geometry('1120x465')
        self.top.resizable(width=False, height=False)

        # expect treeview
        self.expect = ttk.Treeview(self.top, show='headings', selectmode="browse", height='15')
        self.expect["columns"]=("expect","reply","allowed","txlist","txmax","lm")
        self.expect.tag_configure('max', background='red')

        self.expect.column("expect")
        self.expect.column("reply")
        self.expect.column("allowed")
        self.expect.column("txlist")
        self.expect.column("txmax")
        self.expect.column("lm")

        self.expect.column("expect", width=70, minwidth=70)
        self.expect.column("reply", width=340, minwidth=340)
        self.expect.column("allowed", width=285, minwidth=285, stretch=0)
        self.expect.column("txlist", width=195, minwidth=195, stretch=0)
        self.expect.column("txmax", width=60, minwidth=60, stretch=0)
        self.expect.column("lm", width=95, minwidth=95, stretch=0)

        self.expect.heading("expect", text="Expect Text")
        self.expect.heading("reply", text="Reply Text")
        self.expect.heading("allowed", text="Allowed Calls/Groups")
        self.expect.heading("txlist", text="Sent To")
        self.expect.heading("txmax", text="Count")
        self.expect.heading("lm", text="Created")

        self.expect.bind('<Return>', self.edit_expect)
        self.expect.bind('<Double-1>', self.show_expect)
        self.expect.bind('<Delete>', self.delete_expect)
        self.expect.bind('<Button-2>', self.edit_expect)
        self.expect.bind('<Button-3>', self.edit_expect)
        self.expect.grid(row=0, column=0, sticky=NSEW, padx=(10,0), pady=(10,10))

        self.gcscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.expect.yview)
        self.expect.configure(yscroll=self.gcscrollbar.set)
        self.gcscrollbar.grid(row=0, column=1, sticky=NS, padx=(0,0), pady=(10,10))

        self.exframe = ttk.Frame(self.top)
        self.exframe.grid(row=1, column=0, sticky='NW')
        self.exframe.grid_columnconfigure(0, weight=1)

        self.lbl1 = ttk.Label(self.exframe, text='Text to Expect (6):')
        self.lbl1.grid(row=0, column = 0, sticky='NW', padx=(8,0), pady=(8,0))
        self.entry_expect = ttk.Entry(self.exframe, width = '16')
        self.entry_expect.grid(row=1, column=0, sticky='NW', padx=(8,0), pady=(8,0))

        self.lbl2 = ttk.Label(self.exframe, text='Text to Reply With:')
        self.lbl2.grid(row=0, column = 1, sticky='NW', padx=(8,0), pady=(8,0))
        self.entry_reply = ttk.Entry(self.exframe, width = '43')
        self.entry_reply.grid(row=1, column=1, sticky='NW', padx=(8,0), pady=(8,0))

        self.lbl3 = ttk.Label(self.exframe, text='Reply To List:')
        self.lbl3.grid(row=0, column = 2, sticky='NW', padx=(8,0), pady=(8,0))
        self.entry_allowed = ttk.Entry(self.exframe, width = '40')
        self.entry_allowed.grid(row=1, column=2, sticky='NW', padx=(8,0), pady=(8,0))

        self.lbl4 = ttk.Label(self.exframe, text='Max Replies:')
        self.lbl4.grid(row=0, column = 3, sticky='NW', padx=(8,0), pady=(8,0))
        self.entry_txmax = ttk.Entry(self.exframe, width = '8')
        self.entry_txmax.grid(row=1, column=3, sticky='NW', padx=(8,0), pady=(8,0))

        self.save = ttk.Button(self.exframe, text = 'Save', command = self.save_expect, width='5')
        self.save.grid(row=1, column=4, sticky='NW', padx=(8,0),pady=(8,0))

        self.cancel = ttk.Button(self.exframe, text = 'Cancel', command = self.cancelsave_expect, width='6')
        self.cancel.grid(row=1, column=5, sticky='NW', padx=(8,8),pady=(8,0))

        self.update_expect()
        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # update expect tree
    def update_expect(self):
        for entry in self.expect.get_children():
            self.expect.delete(entry)

        c.execute("SELECT * FROM expect ORDER BY lm DESC")
        expect_lines = c.fetchall()

        for record in expect_lines:
            reply_count=len(record[3].split(","))-1
            reply_max = str(reply_count)+"/"+str(record[4])
            ex_date = record[5].split(" ")[0]
            self.expect.insert('', tk.END, iid=record[0], values=(record[0],record[1],record[2],record[3],reply_max,ex_date))
            if reply_count>=record[4]: self.expect.item(record[0], tags=('max'))


    def show_expect(self, ev):
        exiid = self.expect.focus()

        c.execute("SELECT * FROM expect WHERE expect = ?", [exiid])
        record = c.fetchone()

        if record:
            ex_info  = "Expect:  "+record[0]+"\n"
            ex_info += "Reply:   "+record[1]+"\n"
            ex_info += "Allowed: "+record[2]+"\n"
            ex_info += "Sent to: "+record[3]+"\n"

            messagebox.showinfo("Expect info for "+record[0],ex_info, parent=self.top)


    def save_expect(self):
        new_expect = re.sub(r'[^A-Z0-9]','',self.entry_expect.get().upper())
        new_reply = self.entry_reply.get().upper()
        new_allowed = self.entry_allowed.get().upper()
        new_txmax = self.entry_txmax.get().upper()

        # validate input
        if new_expect == "" or new_reply == "" or new_allowed == "" or new_txmax == "" : return

        if new_txmax.isnumeric() == False:
            messagebox.showinfo("Error","Max Replies must be a number (1-99)", parent=self.top)
            return


        if int(new_txmax) < 1 or int(new_txmax) > 99:
            messagebox.showinfo("Error","Max Replies must be between 1 and 99", parent=self.top)
            return

        # checks passed, save and update
        sql = "INSERT INTO expect(expect,reply,allowed,txmax,txlist,lm) VALUES (?,?,?,?,?, CURRENT_TIMESTAMP)"
        c.execute(sql, [new_expect[0:6],new_reply,new_allowed,new_txmax,""])
        conn.commit()

        self.entry_expect.delete(0,END)
        self.entry_reply.delete(0,END)
        self.entry_allowed.delete(0,END)
        self.entry_txmax.delete(0,END)
        self.update_expect()


    def cancelsave_expect(self):
        self.entry_expect.delete(0,END)
        self.entry_reply.delete(0,END)
        self.entry_allowed.delete(0,END)
        self.entry_txmax.delete(0,END)


    def edit_expect(self, ev):
        exiid = self.expect.identify_row(ev.y)
        if exiid: self.expect.selection_set(exiid)

        c.execute("SELECT * FROM expect WHERE expect = ?", [exiid])
        record = c.fetchone()

        self.entry_expect.delete(0,END)
        self.entry_expect.insert(0,record[0])

        self.entry_reply.delete(0,END)
        self.entry_reply.insert(0,record[1])

        self.entry_allowed.delete(0,END)
        self.entry_allowed.insert(0,record[2])

        self.entry_txmax.delete(0,END)
        self.entry_txmax.insert(0,record[4])


    def delete_expect(self, ev):
        exiid = self.expect.focus()

        msgtxt = "Remove the expect entry for "+exiid+"?"
        answer = askyesno(title='Remove Expect Entry?', message=msgtxt, parent=self.top)
        if answer:

            c.execute("DELETE FROM expect WHERE expect = ?", [exiid])
            conn.commit()
            self.update_expect()


    def get_expects(self):
        global expects
        expects.clear()
        c.execute("SELECT * FROM expect")
        expects = c.fetchall()


    # Refresh main window keyword tree
    def refresh_keyword_tree(self):
        global search_strings, bgsearch_strings
        # preserve focus after refresh
        kwiid=0
        if self.keywords.focus(): kwiid = int(self.keywords.focus())

        # clear out and rebuild
        for entry in self.keywords.get_children():
            self.keywords.delete(entry)
        search_strings.clear()
        bgsearch_strings.clear()

        # we will need to know which profiles have background scan enabled
        c.execute("SELECT id FROM profile WHERE bgscan = '1'")
        profile_bgscan = c.fetchall()

        bgscans=[]
        for prof in profile_bgscan:
            bgscans.append(prof[0])

        c.execute("SELECT * FROM search ORDER BY last_seen DESC")
        search_records = c.fetchall()

        count=0
        for record in search_records:
            if record[1] == current_profile_id:
                if count % 2 == 0:
                    self.keywords.insert('', tk.END, iid=record[0], values=(record[2],record[3]), tags=('oddrow'))
                else:
                    self.keywords.insert('', tk.END, iid=record[0], values=(record[2],record[3]), tags=('evenrow'))
                count+=1
                search_strings.append(record[2])
            else:
                # check if profile in question has background scan enabled
                if record[1] in bgscans:
                    bgsearch_strings[record[2]]=record[1]


        # restore focus
        if kwiid>0:
            if self.keywords.exists(kwiid) == True:
                self.keywords.focus(kwiid)
                self.keywords.selection_set(kwiid)


    # Refresh main window activity tree
    def refresh_activity_tree(self):
        global settings
        # preserve focus after refresh
        aciid=0
        if self.activity.focus(): aciid = int(self.activity.focus())

        for entry in self.activity.get_children():
            self.activity.delete(entry)

        if settings['hide_heartbeat']=="1":
            c.execute("SELECT * FROM activity WHERE profile_id = ? AND value NOT LIKE '%HB%' AND value NOT LIKE '%HEARTBEAT%' ORDER BY spotdate DESC LIMIT 100",[current_profile_id])
            self.activitymark.config(text = "Matched Activity (last 100 -HB)")
            self.viewmenu.entryconfigure(0, label="\u2713 Hide Heartbeats")
        else:
            c.execute("SELECT * FROM activity WHERE profile_id = ? ORDER BY spotdate DESC LIMIT 100",[current_profile_id])
            self.activitymark.config(text = "Matched Activity (last 100)")
            self.viewmenu.entryconfigure(0, label="Hide Heartbeats")
        activity_records = c.fetchall()

        count=0
        for record in activity_records:
            # use CALL if ACTIVITY is blank (RX.SPOT)
            act=record[3]
            if act=="": act=record[6]

            if count % 2 == 0:
                self.activity.insert('', tk.END, iid=record[0], values=(record[2],act,record[7]), tags=('oddrow'))
            else:
                self.activity.insert('', tk.END, iid=record[0], values=(record[2],act,record[7]), tags=('evenrow'))
            count+=1

        if aciid>0:
            if self.activity.exists(aciid) == True:
                self.activity.focus(aciid)
                self.activity.selection_set(aciid)


    # Build/rebuild profile sub-menu from database
    def build_profilemenu(self):
        global current_profile_id
        # first, remove any entries that exist in sub-menu
        if self.profilemenu.winfo_exists():
            if self.profilemenu.index('end') is not None:
                self.profilemenu.delete(0,self.profilemenu.index('end'))

        # also remove all from combobox
        self.profilecombo.delete(0, tk.END)

        # next, rebuild from database
        c.execute("SELECT * FROM profile")
        profile_records = c.fetchall()
        comboopts = []

        for record in profile_records:
            comboopts.append(record[1])

            if record[2] == 1:
                seltext = " *"
                current_profile_id = record[0]
                combosel = record[1]
                bgscanbox = record[3]
            else:
                seltext = ""
            self.profilemenu.add_command(label = record[1]+seltext, command = lambda profileid=record[0]: self.profile_select(profileid))

        # update bgscan checkbox based on current visible profile setting
        if bgscanbox == 1:
            self.current_profile_scan.set(1)
        else:
            self.current_profile_scan.set(0)

        self.profilecombo['values'] = comboopts
        self.profilecombo.set(combosel)
        self.update()


    # Select a profile
    def profile_select(self, profileid):
        c.execute("UPDATE profile SET def = 0")
        c.execute("UPDATE profile SET def = 1 WHERE id = ?", [profileid])
        conn.commit()
        self.build_profilemenu()
        self.refresh_keyword_tree()
        self.refresh_activity_tree()


    # select a profile through the combobox
    def profile_sel_combo(self, ev):
        # note that profile titles are a unique key in the database
        # so they're safe to match on
        profile_title = self.profilecombo.get()
        c.execute("UPDATE profile SET def = 0")
        c.execute("UPDATE profile SET def = 1 WHERE title = ?", [profile_title])
        conn.commit()
        self.build_profilemenu()
        self.refresh_keyword_tree()
        self.refresh_activity_tree()


    # Add new profile
    def menu_new(self):
        self.top = Toplevel(self)
        self.top.title("New Profile")
        self.top.resizable(width=False, height=False)

        label_new = ttk.Label(self.top, text = "New Profile Name")
        label_new.grid(row = 0, column = 0, padx=(10,0), pady=(20,0))
        self.new_profile = ttk.Entry(self.top)
        self.new_profile.grid(row = 0, column = 1, padx=(0,10), pady=(20,0))
        self.new_profile.bind("<Return>", lambda x: self.proc_new())

        cbframe = ttk.Frame(self.top)
        cbframe.grid(row=2, columnspan=2, sticky=NSEW, padx=10)

        create_button = ttk.Button(cbframe, text = "Create", command = self.proc_new)
        create_button.grid(row=0, column = 0, padx=(60,10), pady=(20,20))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top.destroy)
        cancel_button.grid(row=0, column = 1, pady=(20,20))

        self.top.wait_visibility()
        self.top.grab_set()
        self.new_profile.focus()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # Process new profile
    def proc_new(self):
        new_val = self.new_profile.get()
        if new_val == "": return
        c.execute("INSERT INTO profile(title,def,bgscan) VALUES (?,?,?)", [new_val,0,0])
        conn.commit()
        self.build_profilemenu()
        self.top.destroy()


    # Edit existing profile
    def menu_edit(self):
        global current_profile_id
        c.execute("SELECT * FROM profile WHERE id = ?",[current_profile_id])
        profile_record = c.fetchone()

        self.top = Toplevel(self)
        self.top.title("Edit Profile")
        self.top.resizable(width=False, height=False)

        label_edit = ttk.Label(self.top, text = "Edit Profile Name")
        label_edit.grid(row = 0, column = 0, padx=(10,0), pady=(20,0))
        self.edit_profile = ttk.Entry(self.top)
        self.edit_profile.insert(0, profile_record[1])
        self.edit_profile.grid(row = 0, column = 1, padx=(0,10), pady=(20,0))
        self.edit_profile.bind("<Return>", lambda x: self.proc_edit())

        cbframe = ttk.Frame(self.top)
        cbframe.grid(row=2, columnspan=2, sticky=NSEW, padx=10)

        save_button = ttk.Button(cbframe, text = "Save", command = self.proc_edit)
        save_button.grid(row=0, column = 0, padx=(60,20), pady=(20,20))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top.destroy)
        cancel_button.grid(row=0, column = 1, pady=(20,20))

        self.top.wait_visibility()
        self.top.grab_set()
        self.edit_profile.focus()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # Process profile edit
    def proc_edit(self):
        global current_profile_id
        new_val = self.edit_profile.get()
        if new_val == "": return
        c.execute("UPDATE profile SET title = ? WHERE id = ?", [new_val, current_profile_id])
        conn.commit()
        self.build_profilemenu()
        self.top.destroy()


    # Delete the current selected profile
    def menu_remove(self):
        global current_profile_id

        # make sure we're not deleting the last remaining profile
        c.execute("SELECT Count() FROM profile")
        profile_count = c.fetchone()[0]

        if profile_count < 2:
            messagebox.showwarning("Error Removing Profile","Unable to remove selected profile, because it is the last remaining profile. At least one profile must be configured.")
            return

        c.execute("SELECT * FROM profile WHERE id = ?",[current_profile_id])
        profile_record = c.fetchone()

        msgtxt = "Are you sure you want to remove the profile named "+profile_record[1]+" and all associated activity? This action cannot be undone."
        answer = askyesno(title='Remove Profile?', message=msgtxt)
        if answer:
            # delete the profile from the database
            c.execute("DELETE FROM profile WHERE id = ?", [current_profile_id])
            conn.commit()
            # delete associated activity logs from the database
            c.execute("DELETE FROM activity WHERE profile_id = ?", [current_profile_id])
            conn.commit()
            # delete associated keywords from the database
            c.execute("DELETE FROM search WHERE profile_id = ?", [current_profile_id])
            conn.commit()
            # reset the default profile
            c.execute("UPDATE profile SET def = 1 WHERE rowid = (SELECT MIN(rowid) FROM profile)")
            conn.commit()
            current_profile_id = 0
            self.build_profilemenu()


    # Edit personal settings
    def settings_edit(self):
        global settings

        self.top = Toplevel(self)
        self.top.title("Edit Settings")
        self.top.resizable(width=False, height=False)

        label_instruct = ttk.Label(self.top, text = "Please check that these settings match in JS8Call.")
        label_instruct.grid(row = 0, columnspan = 2, padx=(10,10), pady=(20,0))

        label_call = ttk.Label(self.top, text = "Your Callsign")
        label_call.grid(row = 1, column = 0, sticky=W, padx=(10,10), pady=(10,0))
        self.edit_call = ttk.Entry(self.top)
        self.edit_call.insert(0, settings['callsign'])
        self.edit_call.grid(row = 1, column = 1, padx=(0,10), pady=(20,0))
        self.edit_call.bind("<Return>", lambda x: self.proc_settings_edit())

        label_grid = ttk.Label(self.top, text = "Your GRID")
        label_grid.grid(row = 2, column = 0, sticky=W, padx=(10,10), pady=(10,0))
        self.edit_grid = ttk.Entry(self.top)
        self.edit_grid.insert(0, settings['grid'])
        self.edit_grid.grid(row = 2, column = 1, padx=(0,10), pady=(10,0))
        self.edit_grid.bind("<Return>", lambda x: self.proc_settings_edit())

        label_address = ttk.Label(self.top, text = "IP Address (127.0.0.1)")
        label_address.grid(row = 3, column = 0, sticky=W, padx=(10,10), pady=(10,0))
        self.edit_address = ttk.Entry(self.top)
        self.edit_address.insert(0, settings['tcp_ip'])
        self.edit_address.grid(row = 3, column = 1, padx=(0,10), pady=(20,0))
        self.edit_address.bind("<Return>", lambda x: self.proc_settings_edit())

        label_port = ttk.Label(self.top, text = "TCP Port (2442)")
        label_port.grid(row = 4, column = 0, sticky=W, padx=(10,10), pady=(10,0))
        self.edit_port = ttk.Entry(self.top)
        self.edit_port.insert(0, settings['tcp_port'])
        self.edit_port.grid(row = 4, column = 1, padx=(0,10), pady=(10,0))
        self.edit_port.bind("<Return>", lambda x: self.proc_settings_edit())

        cbframe = ttk.Frame(self.top)
        cbframe.grid(row=5, columnspan=2, sticky=NSEW, padx=10)

        save_button = ttk.Button(cbframe, text = "Save", command = self.proc_settings_edit)
        save_button.grid(row=0, column = 0, padx=(60,10), pady=(10,10))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top.destroy)
        cancel_button.grid(row=0, column = 1, pady=(20,20))

        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())


    # Process TCP settings edit
    def proc_settings_edit(self):
        global settings
        new_addr = self.edit_address.get()
        new_port = self.edit_port.get()
        new_call = self.edit_call.get().upper()
        new_grid = self.edit_grid.get().upper()

        # validate settings
        if new_addr == "" or new_port == "" or new_call == "" or new_grid == "" : return

        if new_port.isnumeric() == False:
            messagebox.showinfo("Error","Port must be a number (1-9999)", parent=self.top)
            return

        # the 9999 comes from js8call's interface limit, which for typed numbers is limited to 4 digits
        if int(new_port) < 1 or int(new_port) > 9999:
            messagebox.showinfo("Error","Port must be between 1 and 9999", parent=self.top)
            return

        if self.check_ip(new_addr) == False:
            messagebox.showinfo("Error","The IP address ("+new_addr+") is formatted incorrectly", parent=self.top)
            return

        # checks passed, save and update
        c.execute("UPDATE setting SET value = ? WHERE name = 'tcp_ip'", [new_addr])
        conn.commit()
        c.execute("UPDATE setting SET value = ? WHERE name = 'tcp_port'", [new_port])
        conn.commit()
        c.execute("UPDATE setting SET value = ? WHERE name = 'callsign'", [new_call])
        conn.commit()
        c.execute("UPDATE setting SET value = ? WHERE name = 'grid'", [new_grid])
        conn.commit()

        settings['tcp_ip']=new_addr
        settings['tcp_port']=new_port
        settings['callsign']=new_call
        settings['grid']=new_grid

        messagebox.showinfo("Updated","Values updated. You must restart JS8Spotter for any TCP changes to take effect")
        self.top.destroy()


    # About screen
    def about(self):
        about_info = swname+" version "+swversion+"\n\nOpen Source, MIT License\nQuestions to Joe, KF7MIX\nwww.kf7mix.com"
        messagebox.showinfo("About "+swname,about_info)


    # check if IP address is valid
    def check_ip(self, addr):
        octets = addr.split(".")

        if len(octets) != 4: return False

        for octet in octets:
            if not isinstance(int(octet), int): return False
            if int(octet) < 0 or int(octet) > 255: return False

        return True


    # Mainloop, shut down receiver thread
    def mainloop(self, *args):
        super().mainloop(*args)
        if self.receiver: self.receiver.stop()


    # Watch activity thread, update gui as needed
    def poll_activity(self):
        if event.is_set():
            self.refresh_activity_tree()
            self.refresh_keyword_tree()
            event.clear()
        super().after(2000,self.poll_activity)


    # Start receiver thread
    def start_receiving(self):
        self.receiver = TCP_RX(self.sock)
        self.receiver.start()


    # Stop receiver thread
    def stop_receiving(self):
        self.receiver.stop()
        self.receiver.join()
        self.receiver = None


    # Quit function, close the recv thread, database, and program
    def menu_bye(self):
        conn.close()
        self.stop_receiving()
        self.destroy()


def main():
    # check for tcp connection (N4FWD)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((settings['tcp_ip'], int(settings['tcp_port'])))
    except ConnectionRefusedError:
        # we'll provide the error when the gui loads
        sock = None

    app = App(sock)
    app.mainloop()


if __name__ == '__main__':
    main()
