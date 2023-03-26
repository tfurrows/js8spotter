# JS8Spotter v1.05b. Special thanks to KE0DHO, KF0HHR, N0GES, N6CYB, KQ4DRG, and N4FWD. Visit https://kf7mix.com/js8spotter.html for information
#
# MIT License, Copyright 2023 Joseph D Lyman KF7MIX --- Permission is hereby granted,  free of charge, to any person obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
# of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:  The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.  The Software IS PROVIDED "AS IS",  WITHOUT WARRANTY OF ANY KIND,  EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES  OF  MERCHANTABILITY,  FITNESS OR A PARTICULAR PURPOSE AND  NONINFRINGEMENT.  IN NO EVENT SHALL THE AUTHORS OR  COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,  DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import tkinter as tk
from tkinter import *
from tkinter import ttk, messagebox, filedialog
from tkinter.ttk import Treeview, Style, Combobox
from tkinter.messagebox import askyesno
from PIL import ImageTk, Image
from threading import Event, Thread
from io import StringIO
import time
import datetime
import random
import socket
import select
import json
import sqlite3
import re
import os
import requests
import shutil

### Globals
swname = "JS8Spotter"
fromtext = "de KF7MIX"
swversion = "1.05b"

# Find the path to the users Home folder
user_home_path = os.path.expanduser('~')

# Determine the folder the script is running from
ROOT_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__)))

# Set the path to where the database is to be stored
database_path = os.path.join(user_home_path,".js8spotter")

# Set the name of the database file
dbfile = 'js8spotter.db'
conn = sqlite3.connect(dbfile)
c = conn.cursor()

current_profile_id = 0
search_strings = []
bgsearch_strings = {}
expects = {}
forms = {}
totals = {}
speeds = {"0":"Normal", "1":"Fast", "2":"Turbo", "4":"Slow", "8":"Ultra"}

map_loc = 0 # for maps, 0=North America, 1=Europe
maplocs = ["North America", "Europe"]
gridmultiplier = [
    {
        "CO":[0,3], "DO":[1,3], "EO":[2,3], "FO":[3,3],
        "CN":[0,2], "DN":[1,2], "EN":[2,2], "FN":[3,2],
        "CM":[0,1], "DM":[1,1], "EM":[2,1], "FM":[3,1],
        "CL":[0,0], "DL":[1,0], "EL":[2,0], "FL":[3,0],
    },
    {
        "IP":[0,3], "JP":[1,3], "KP":[2,3], "LP":[3,3],
        "IO":[0,2], "JO":[1,2], "KO":[2,2], "LO":[3,2],
        "IN":[0,1], "JN":[1,1], "KN":[2,1], "LN":[3,1],
        "IM":[0,0], "JM":[1,0], "KM":[2,0], "LM":[3,0],
    },
]
markeropts = ["Latest 100", "Latest 50", "Latest 25", "Latest 10"]

### Database work

# Check if a database file already exists. If it does, use it
# If it doesn't exist, copy a blank database to the user's 
# database location
ifDatabasePathExist = os.path.exists(database_path)
if not ifDatabasePathExist:
    os.makedirs(database_path)

ifDatabaseExist = os.path.exists(os.path.join(database_path,dbfile))
if not ifDatabaseExist:
    shutil.copyfile("js8spotter.db.blank",os.path.join(database_path,dbfile))

conn = sqlite3.connect(os.path.join(database_path,dbfile))
c = conn.cursor()

## Clean-up tables

# signal table only needs data for 24hrs, remove older entries
c.execute("DELETE FROM signal WHERE sig_timestamp < DATETIME('now', '-24 hour')")
conn.commit()

# sqlite VACUUM defragment database
c.execute("VACUUM")
conn.commit()

## Settings table
c.execute("SELECT * FROM setting")
dbsettings = c.fetchall()

## Rebuild database settings if any are missing
if len(dbsettings)<13:
    svals = "('udp_ip','127.0.0.1'),"
    svals+= "('udp_port','2242'),"
    svals+= "('tcp_ip','127.0.0.1'),"
    svals+= "('tcp_port','2442'),"
    svals+= "('hide_heartbeat','0'),"
    svals+= "('dark_theme','0'),"
    svals+= "('marker_index','0'),"
    svals+= "('wfband_index','0'),"
    svals+= "('wftime_index','0'),"
    svals+= "('callsign','FILL'),"
    svals+= "('grid','FILL'),"
    svals+= "('hide_spot','0'),"
    svals+= "('forms_gateway','')"
    c.execute("INSERT INTO setting(name,value) VALUES "+svals)
    conn.commit()
    c.execute("SELECT * FROM setting")
    dbsettings.clear()
    dbsettings = c.fetchall()

## Setup settings dictionary
settings = {}
for setting in dbsettings:
    settings[setting[1]]=setting[2]

## Setup statusbar totals tracking
totals[0]=0 # for grid, not currently reported in statusbar
totals[1]=0 # for expect
totals[2]=0 # for forms

event = Event() # for inter-thread comms

### Thread for processing output of JS8Call over socket
class TCP_RX(Thread):
    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self.keep_running = True

    def stop(self):
        self.keep_running = False

    def run(self):
        conn1 = sqlite3.connect(os.path.join(database_path,dbfile)) # we need our own db connection in this thread
        c1 = conn1.cursor()

        track_types = {"RX.ACTIVITY", "RX.DIRECTED", "RX.SPOT"}

        while self.keep_running:
            rfds, _wfds, _xfds = select.select([self.sock], [], [], 0.5) # check every 0.5 seconds
            if self.sock in rfds:
                try:
                    iodata = self.sock.recv(4096)

                    try:
                        json_lines = StringIO(str(iodata,'UTF-8'))
                    except:
                        print("JSON error")
                        json_lines = ""

                    for data in json_lines:
                        try:
                            data_json = json.loads(data)
                        except ValueError as error:
                            data_json = {'type':'error'}

                        if data_json['type'] in track_types:
                            # gather basic elements of this record
                            msg_call = ""
                            msg_dial = ""
                            msg_snr = ""
                            msg_freq = ""
                            msg_offset = ""
                            msg_speed = "" # 0=Normal, 1=Fast, 2=Turbo, 4=Slow (8=Ultra, in src code of js8call but not generally used)
                            if "CALL" in data_json['params']: msg_call = data_json['params']['CALL']
                            if "FROM" in data_json['params']: msg_call = data_json['params']['FROM']
                            if "DIAL" in data_json['params']: msg_dial = data_json['params']['DIAL']
                            if "FREQ" in data_json['params']: msg_freq = data_json['params']['FREQ']
                            if "OFFSET" in data_json['params']: msg_offset = data_json['params']['OFFSET']
                            if "SPEED" in data_json['params']: msg_speed = data_json['params']['SPEED']
                            if "SNR" in data_json['params']: msg_snr = data_json['params']['SNR']
                            msg_value = data_json['value']

                            # before scans, save grid info (from CQ, spot, hb, msg) and signal info for wf visual
                            msg_grid = ""
                            if "GRID" in data_json['params']: msg_grid = data_json['params']['GRID'].strip()
                            if msg_grid != "":
                                gridsql = "INSERT INTO grid(grid_callsign,grid_grid,grid_dial,grid_type,grid_snr,grid_timestamp) VALUES (?,?,?,?,?, CURRENT_TIMESTAMP)"
                                c1.execute(gridsql, [msg_call, msg_grid, msg_dial, data_json['type'], msg_snr])
                                conn1.commit()
                                event.set()

                            if msg_call!="" and msg_offset!="" and msg_speed!="" and msg_freq!="":
                                sigsql = "INSERT INTO signal(sig_callsign,sig_dial,sig_freq,sig_offset,sig_speed,sig_snr,sig_timestamp) VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)"
                                c1.execute(sigsql, [msg_call, msg_dial, msg_freq, msg_offset,msg_speed, msg_snr])
                                conn1.commit()
                                event.set()

                            ## Multiple Choice Forms (MCF) subsystem. Check for prefix "F!<three digits> <form response> <msg> <datecode>" in any incoming data
                            scan_forms = re.search("([A-Z0-9]+):\s+?(@?[A-Z0-9]+)\s+?(.*\s+)?(F\![A-Z0-9]{3})\s+?([A-Z0-9]+)\s+?(.*?)(\#[A-Z0-9]+)",msg_value) # from, to, <optional E? or MSG etc. group not used>, form ID, form responses, msg, timestamp
                            if scan_forms:
                                # forward to gateway if user has one configured
                                rstat=""
                                if settings['forms_gateway']!='':
                                    formobj = {'fromcall':scan_forms[1], 'tocall':scan_forms[2], 'typeid':scan_forms[4], 'responses':scan_forms[5], 'msgtxt':scan_forms[6], 'timesig':scan_forms[7]}
                                    rstat = requests.post(settings['forms_gateway'], data = formobj)
                                # found a form in the stream, save it. No need for it to be directed to us, we want to save all forms we find.
                                sql = "INSERT INTO forms(fromcall,tocall,typeid,responses,msgtxt,timesig,lm,gwtx) VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP,?)"
                                c1.execute(sql, [scan_forms[1],scan_forms[2],scan_forms[4],scan_forms[5],scan_forms[6],scan_forms[7],str(rstat)])
                                conn1.commit()
                                event.set()

                            scan_formsrelay = re.search("([A-Z0-9]+):\s+?(@?[A-Z0-9>]+)\s+?(.*\s+)?(F\![A-Z0-9]{3})\s+?([A-Z0-9]+)\s+?(.*?)(\#[A-Z0-9]+)\s+?\*DE\*\s+?([A-Z0-9]+)",msg_value)
                            if scan_formsrelay:
                                # forward to gateway if user has one configured
                                rstat=""
                                if settings['forms_gateway']!='':
                                    formobj = {'fromcall':scan_formsrelay[8], 'tocall':scan_formsrelay[2], 'typeid':scan_formsrelay[4], 'responses':scan_formsrelay[5], 'msgtxt':scan_formsrelay[6], 'timesig':scan_formsrelay[7]}
                                    rstat = requests.post(settings['forms_gateway'], data = formobj)
                                # found a relayed form, save it. Doesn't matter who it is to/from, we want to save all forms we find.
                                sql = "INSERT INTO forms(fromcall,tocall,typeid,responses,msgtxt,timesig,lm,gwtx) VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP,?)"
                                c1.execute(sql, [scan_formsrelay[8],scan_formsrelay[2],scan_formsrelay[4],scan_formsrelay[5],scan_formsrelay[6],scan_formsrelay[7],str(rstat)])
                                conn1.commit()
                                event.set()

                            ## Expect subsystem. Check for expect prefix "<from>: <to> E? <expect>" and process. Relayed form "<relay>: <to>> E? <expect> *DE* <from>"
                            reply_to = ""
                            ex_reply = ""
                            ex_expect = ""
                            ex_relay = ""

                            # scan for direct request expect
                            scan_expect = re.search("([A-Z0-9]+):\s+?(@?[A-Z0-9]+)\s+?E\?\s+?([A-Z0-9!]+)",msg_value) # from, to, expect
                            if scan_expect:
                                ex_from = scan_expect.group(1)
                                ex_to = scan_expect.group(2)
                                ex_expect = scan_expect.group(3)
                            else:
                                # scan for relayed request expect
                                scan_expect = re.search("([A-Z0-9]+):\s+?([A-Z0-9]+)\>?\s+?E\?\s+?([A-Z0-9!]+)\s+?\*DE\*?\s+?([A-Z0-9]+)?",msg_value) # relay, to, expect, from
                                if scan_expect:
                                    ex_relay = scan_expect.group(1)
                                    ex_to = scan_expect.group(2)
                                    ex_expect = scan_expect.group(3)
                                    ex_from = scan_expect.group(4)

                            if ex_expect and settings['callsign']!="FILL":
                                # check if expect is in database
                                c1.execute("SELECT * FROM expect WHERE expect = ?", [ex_expect])
                                ex_exists = c1.fetchone()
                                if ex_exists:
                                    # found expect command. Check if requestor is in allowed list, or * for any station
                                    for allow in ex_exists[2].split(","):
                                        allow = allow.replace(" ", "")
                                        if allow[0]=="@":
                                            if ex_to == allow: reply_to = ex_to
                                        else:
                                            if ex_from==allow and ex_to==settings['callsign']: reply_to = ex_from
                                    for allowall in ex_exists[2].split(","):
                                        if allowall=="*" and ex_to==settings['callsign'] and reply_to=="": reply_to = ex_from

                                    if reply_to:
                                        # make sure that txmax hasn't been exceeded
                                        reply_count=len(ex_exists[3].split(","))-1
                                        if reply_count<int(ex_exists[4]):
                                            # formulate reply, relay or regular
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
                                                sql = "UPDATE expect SET txlist = txlist || '"+reply_to+" "+datetime.datetime.now().strftime("%x %X")+",' WHERE expect = ?"
                                            c1.execute(sql,[ex_expect])
                                            conn1.commit()
                                            event.set()

                            ## Scan for search terms
                            msg_value=""
                            # if search term is in 'value' or 'call' then insert into db. Check visible profile terms, make copy in case other thread modifies dict
                            searchcheck = search_strings.copy()
                            for term in searchcheck:
                                if (term in msg_call) or (term in data_json['value']):
                                    sql = "UPDATE search SET last_seen = CURRENT_TIMESTAMP WHERE profile_id = ? AND keyword = ?"
                                    c1.execute(sql, [current_profile_id,term])
                                    sql = "INSERT INTO activity(profile_id,type,value,dial,snr,call,spotdate,freq,offset,speed) VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP,?,?,?)"
                                    c1.execute(sql, [current_profile_id,data_json['type'],data_json['value'],msg_dial,msg_snr,msg_call,msg_freq,msg_offset,msg_speed])
                                    conn1.commit()
                                    event.set()

                            # check background scan profile terms. Make copy in case other thread modifies dict
                            bgcheck = bgsearch_strings.copy();
                            for term in bgcheck.keys():
                                term_profile = bgcheck.get(term)
                                if (term in msg_call) or (term in data_json['value']):
                                    sql = "UPDATE search SET last_seen = CURRENT_TIMESTAMP WHERE profile_id = ? AND keyword = ?"
                                    c1.execute(sql, [term_profile,term])
                                    sql = "INSERT INTO activity(profile_id,type,value,dial,snr,call,spotdate,freq,offset,speed) VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP,?,?,?)"
                                    c1.execute(sql, [term_profile,data_json['type'],data_json['value'],msg_dial,msg_snr,msg_call,msg_freq,msg_offset,msg_speed])
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
        self.call("source", os.path.join(ROOT_DIR, "azure.tcl"))
        self.create_gui()
        self.eval('tk::PlaceWindow . center')
        self.activate_theme()

        self.build_profilemenu()
        self.build_formsmenu()
        self.refresh_keyword_tree()
        self.refresh_activity_tree()

        self.start_receiving()
        self.poll_activity()
        self.update()

        self.get_expects()

        if self.sock == None:
            messagebox.showinfo("TCP Error","Can't connect to JS8Call. Make sure it is running, and check your TCP settings before restarting JS8Spotter.")

        if settings['callsign'] == "FILL" or settings['grid'] == "FILL":
            messagebox.showinfo("Settings Incomplete","Please specify your callsign and grid in the settings before using the application.")

    ## Setup main gui window
    def create_gui(self):
        self.title(swname+" "+fromtext+" (v"+swversion+")")
        self.geometry('900x450')
        self.minsize(900,450)
        self.resizable(width=True, height=True)

        self.columnconfigure(0, weight=12)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=12)
        self.columnconfigure(3, weight=1)

        self.rowconfigure(0,weight=1)
        self.rowconfigure(1,weight=1)
        self.rowconfigure(2,weight=24)
        self.rowconfigure(3,weight=1)
        self.rowconfigure(4,weight=1)

        # menus
        self.menubar = Menu(self)
        self.filemenu = Menu(self.menubar, tearoff = 0)
        self.profilemenu = Menu(self.menubar, tearoff = 0)
        self.formsmenu = Menu(self.menubar, tearoff = 0)

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
        self.viewmenu.add_command(label = "Hide RX.SPOT", command = self.toggle_view_spot)
        self.viewmenu.add_separator()
        self.viewmenu.add_command(label = "Dark Theme", command = self.toggle_theme)

        self.toolsmenu = Menu(self.menubar, tearoff = 0)
        self.toolsmenu.add_command(label = 'Simple Offline Map', command = self.grid_map)
        self.toolsmenu.add_command(label = 'Visualize Waterfall', command = self.visualize_waterfall)
        self.toolsmenu.add_separator()
        self.toolsmenu.add_command(label = 'Expect', command = self.expect)
        self.toolsmenu.add_cascade(label = 'MCForms - Forms', menu = self.formsmenu)
        self.toolsmenu.add_command(label = 'MCForms - Responses', command = self.form_responses)
        self.toolsmenu.add_separator()
        self.toolsmenu.add_command(label = 'APRS - SMS Text', command = self.aprs_sms)
        self.toolsmenu.add_command(label = 'APRS - Email', command = self.aprs_email)
        self.toolsmenu.add_command(label = 'APRS - Report Grid', command = self.aprs_grid)

        self.helpmenu = Menu(self.menubar, tearoff = 0)
        self.helpmenu.add_command(label = 'Quick Help', command = self.showhelp)
        self.helpmenu.add_command(label = 'About', command = self.about)

        self.menubar.add_cascade(label = 'File', menu = self.filemenu)
        self.menubar.add_cascade(label = 'View', menu = self.viewmenu)
        self.menubar.add_cascade(label = 'Tools', menu = self.toolsmenu)
        self.menubar.add_cascade(label = 'Help', menu = self.helpmenu)
        self.config(menu = self.menubar)

        # profile title and select
        self.prframe = ttk.Frame(self)
        self.prframe.grid(row=0, column=0, columnspan=4, sticky='NSEW', padx=10, pady=(0,5))

        self.profilemark = ttk.Label(self.prframe, text='Profile:', font=("Segoe Ui Bold", 12))
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
        self.keywords.bind('<Return>', lambda ev: self.view_keyword_activity(ev))
        self.keywords.grid(row=2, column=0, sticky='NSEW', padx=(10,0), pady=(0,10))
        self.kwscrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.keywords.yview)
        self.keywords.configure(yscroll=self.kwscrollbar.set)
        self.kwscrollbar.grid(row=2, column=1, sticky='NS', padx=(0,0), pady=(0,10))

        # activity treeview
        self.activity = ttk.Treeview(self, show='headings', style='activity.Treeview', selectmode='browse')
        self.activity["columns"]=("type","value","stamp")

        self.activity.column("type", width=95, minwidth=95, stretch=0)
        self.activity.column("value", width=205, minwidth=205)
        self.activity.column("stamp", width=140, minwidth=140, stretch=0)
        self.activity.heading("type", text="Type")
        self.activity.heading("value", text="Activity")
        self.activity.heading("stamp", text="When")

        self.activity.bind('<Double-1>', self.view_activity)
        self.activity.bind('<Return>', lambda ev: self.view_activity(ev))
        self.activity.bind('<Button-3>', lambda ev: self.copy_activity(ev,"mact"))
        self.activity.grid(row=2, column=2, sticky='NSEW', padx=(10,0), pady=(0,10))
        self.acscrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.activity.yview)
        self.activity.configure(yscroll=self.acscrollbar.set)
        self.acscrollbar.grid(row=2, column=3, sticky='NS', padx=(0,10), pady=(0,10))

        # add inputs and buttons below treeviews
        self.kwframe = Frame(self)
        self.kwframe.grid(row=3, column=0, columnspan=2, sticky='NSEW', padx=10, pady=(0,10))
        self.new_keyword = ttk.Entry(self.kwframe, width = '14')
        self.new_keyword.grid(row = 0, column = 0)
        self.new_keyword.bind('<Return>', lambda ev: self.proc_addkw())

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

        self.expact_button = ttk.Button(self.acframe, text = 'Export Log', command = self.proc_exportlog)
        self.expact_button.grid(row=0, column=2, sticky='NE', padx=(0,8), pady=0)

        self.clearact_button = ttk.Button(self.acframe, text = 'Clear Log', command = self.proc_dellog)
        self.clearact_button.grid(row=0, column=3, sticky='NE', padx=0, pady=0)

        # status bar
        self.statusbar = ttk.Label(self, text="Status: Waiting for TCP data... ", relief='sunken', anchor='w')
        self.statusbar.grid(row=4,column=0,columnspan=4, sticky='EW', padx=0, pady=(10,0))

    def toggle_theme(self):
        global settings
        if settings['dark_theme'] == "1":
            c.execute("UPDATE setting SET value = '0' WHERE name = 'dark_theme'")
            settings['dark_theme'] = "0"
        else:
            c.execute("UPDATE setting SET value = '1' WHERE name = 'dark_theme'")
            settings['dark_theme'] = "1"
        conn.commit()
        self.activate_theme()

    def activate_theme(self):
        if settings['dark_theme'] == "1":
            self.viewmenu.entryconfigure(3, label="\u2713 Dark Theme")
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
            self.viewmenu.entryconfigure(3, label="Dark Theme")
            self.call("set_theme", "light")
            self.keywordmark.configure(fg='#4477FF')
            self.activitymark.configure(fg='#AA44FF')
            self.style.map('keywords.Treeview', background=[('selected', '#6699FF')])
            self.style.map('activity.Treeview', background=[('selected', '#CC66FF')])
            self.activity.tag_configure('oddrow', background='#EEE')
            self.activity.tag_configure('evenrow', background='#FFF')
            self.keywords.tag_configure('oddrow', background='#EEE')
            self.keywords.tag_configure('evenrow', background='#FFF')
        self.update()

    ## Add keyword to database/tree
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

    ## Add a batch of keywords
    def add_batch(self):
        self.top = Toplevel(self)
        self.top.title("Add Batch of Search Terms")
        self.top.geometry('400x500')
        self.top.minsize(400,500)

        self.addbatmark = ttk.Label(self.top, text="Type or paste (ctrl+v) search terms, one per line")
        self.addbatmark.pack(side=TOP, anchor='nw', padx=10, pady=10)

        # save button
        tlframe = ttk.Frame(self.top)
        tlframe.pack(side=BOTTOM, anchor='sw', padx=10, pady=(0,10))
        self.save_button = ttk.Button(tlframe, text = 'Add Batch', command = self.proc_addbatch)
        self.save_button.pack(side=LEFT, padx=(0,10))

        # text window
        self.batch = Text(self.top, wrap=NONE)
        batch_scrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.batch.yview)
        self.batch.configure(yscroll=batch_scrollbar.set)
        batch_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(0,10))
        self.batch.pack(side=LEFT, expand=True, fill='both', padx=(10,0), pady=(0,10))

        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Add multiple search terms at once
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

    ## Export search terms
    def proc_exportsearch(self):
        self.top = Toplevel(self)
        self.top.title("Export Search Terms")
        self.top.geometry('400x500')
        self.top.minsize(400,500)

        self.exportmark = ttk.Label(self.top, text="Copy (ctrl+c) / Export Search Terms")
        self.exportmark.pack(side=TOP, anchor='nw', padx=10, pady=10)

        # save and copy buttons
        tlframe = ttk.Frame(self.top)
        tlframe.pack(side=BOTTOM, anchor='sw', padx=10, pady=(0,10))
        self.copy_button = ttk.Button(tlframe, text = 'Copy All', command = self.export_copy_all)
        self.copy_button.pack(side=LEFT, padx=(0,10))
        self.saveas_button = ttk.Button(tlframe, text = 'Save As', command = self.export_saveas_popup)
        self.saveas_button.pack(side=RIGHT)

        # text export window
        self.export_text = Text(self.top, wrap=NONE)
        export_scrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.export_text.yview)
        self.export_text.configure(yscroll=export_scrollbar.set)
        export_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(0,10))
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

    ## Remove keyword from database/tree
    def proc_remkw(self):
        kwlist = ""
        for kwiid in self.keywords.selection():
            kwlist += str(self.keywords.item(kwiid)['values'][0])+"\n"

        if kwlist == "": return

        msgtxt = "Remove the following search term(s)?\n"+kwlist
        answer = askyesno(title='Remove Search Term(s)?', message=msgtxt)
        if answer:
            for kwiid in self.keywords.selection():
                c.execute("DELETE FROM search WHERE id = ? AND profile_id = ?", [kwiid,current_profile_id])
            conn.commit()
            self.refresh_keyword_tree()

    ## Toggle Heartbeat Display in activity pane
    def toggle_view_hb(self):
        global settings
        if settings['hide_heartbeat'] == "1":
            c.execute("UPDATE setting SET value = '0' WHERE name = 'hide_heartbeat'")
            settings['hide_heartbeat'] = "0"
        else:
            c.execute("UPDATE setting SET value = '1' WHERE name = 'hide_heartbeat'")
            settings['hide_heartbeat'] = "1"
        conn.commit()
        self.refresh_activity_tree()

    ## Toggle Heartbeat Display in activity pane
    def toggle_view_spot(self):
        global settings
        if settings['hide_spot'] == "1":
            c.execute("UPDATE setting SET value = '0' WHERE name = 'hide_spot'")
            settings['hide_spot'] = "0"
        else:
            c.execute("UPDATE setting SET value = '1' WHERE name = 'hide_spot'")
            settings['hide_spot'] = "1"
        conn.commit()
        self.refresh_activity_tree()

    ## Toggle background scan setting for current profile
    def toggle_bg_scan(self):
        bg_setting = self.current_profile_scan.get()
        if bg_setting == 1:
            c.execute("UPDATE profile SET bgscan = 1 WHERE id = ?", [current_profile_id])
        else:
            c.execute("UPDATE profile SET bgscan = 0 WHERE id = ?", [current_profile_id])
        conn.commit()
        self.refresh_keyword_tree()

    ## Refresh main window keyword tree
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
                if count % 2 == 1:
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

    ## Refresh main window activity tree
    def refresh_activity_tree(self):
        global settings
        # preserve focus after refresh
        aciid=0
        if self.activity.focus(): aciid = int(self.activity.focus())

        for entry in self.activity.get_children():
            self.activity.delete(entry)

        wheres=""
        self.viewmenu.entryconfigure(0, label="Hide Heartbeats")
        self.viewmenu.entryconfigure(1, label="Hide RX.SPOT")
        self.activitymark.config(text = "Matched Activity (last 100)")

        if settings['hide_heartbeat']=="1":
            wheres += " AND value NOT LIKE '%HB%' AND value NOT LIKE '%HEARTBEAT%' "
            self.activitymark.config(text = "Matched Activity (last 100*)")
            self.viewmenu.entryconfigure(0, label="\u2713 Hide Heartbeats")

        if settings['hide_spot']=="1":
            wheres += " AND type NOT LIKE '%RX.SPOT%' "
            self.activitymark.config(text = "Matched Activity (last 100*)")
            self.viewmenu.entryconfigure(1, label="\u2713 Hide RX.SPOT")

        c.execute("SELECT * FROM activity WHERE profile_id = '"+str(current_profile_id)+"' "+wheres+" ORDER BY spotdate DESC LIMIT 100")
        activity_records = c.fetchall()

        count=0
        for record in activity_records:
            # use CALL if ACTIVITY is blank (RX.SPOT)
            act=record[3]
            if act=="": act=record[6]

            if count % 2 == 1:
                self.activity.insert('', tk.END, iid=record[0], values=(record[2],act,record[7]), tags=('oddrow'))
            else:
                self.activity.insert('', tk.END, iid=record[0], values=(record[2],act,record[7]), tags=('evenrow'))
            count+=1

        if aciid>0:
            if self.activity.exists(aciid) == True:
                self.activity.focus(aciid)
                self.activity.selection_set(aciid)

    ## Build/rebuild profile sub-menu from database
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

    ## Select a profile
    def profile_select(self, profileid):
        c.execute("UPDATE profile SET def = 0")
        c.execute("UPDATE profile SET def = 1 WHERE id = ?", [profileid])
        conn.commit()
        self.build_profilemenu()
        self.refresh_keyword_tree()
        self.refresh_activity_tree()

    ## Select a profile through the combobox
    def profile_sel_combo(self, ev):
        # note that profile titles are a unique key in the database so they're safe to match on
        profile_title = self.profilecombo.get()
        c.execute("UPDATE profile SET def = 0")
        c.execute("UPDATE profile SET def = 1 WHERE title = ?", [profile_title])
        conn.commit()
        self.build_profilemenu()
        self.refresh_keyword_tree()
        self.refresh_activity_tree()

    ## Add new profile
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
        cbframe.grid(row=2, columnspan=2, sticky='NSEW', padx=10)

        create_button = ttk.Button(cbframe, text = "Create", command = self.proc_new)
        create_button.grid(row=0, column = 0, padx=(60,10), pady=(20,20))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top.destroy)
        cancel_button.grid(row=0, column = 1, pady=(20,20))

        self.top.wait_visibility()
        self.top.grab_set()
        self.new_profile.focus()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Process new profile
    def proc_new(self):
        new_val = self.new_profile.get()
        if new_val == "": return
        c.execute("INSERT INTO profile(title,def,bgscan) VALUES (?,?,?)", [new_val,0,0])
        conn.commit()
        self.build_profilemenu()
        self.top.destroy()

    ## Edit existing profile
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
        cbframe.grid(row=2, columnspan=2, sticky='NSEW', padx=10)

        save_button = ttk.Button(cbframe, text = "Save", command = self.proc_edit)
        save_button.grid(row=0, column = 0, padx=(60,20), pady=(20,20))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top.destroy)
        cancel_button.grid(row=0, column = 1, pady=(20,20))

        self.top.wait_visibility()
        self.top.grab_set()
        self.edit_profile.focus()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Process profile edit
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
            c.execute("DELETE FROM profile WHERE id = ?", [current_profile_id])
            c.execute("DELETE FROM activity WHERE profile_id = ?", [current_profile_id])
            c.execute("DELETE FROM search WHERE profile_id = ?", [current_profile_id])
            c.execute("UPDATE profile SET def = 1 WHERE rowid = (SELECT MIN(rowid) FROM profile)") # reset the default profile
            conn.commit()
            current_profile_id = 0
            self.build_profilemenu()
            self.refresh_keyword_tree()
            self.refresh_activity_tree()

    ## Export activity log for current profile
    def proc_exportlog(self):
        global current_profile_id
        c.execute("SELECT * FROM profile WHERE id = ?",[current_profile_id])
        profile_record = c.fetchone()

        self.top = Toplevel(self)
        self.top.title("Export "+profile_record[1]+" Activity")
        self.top.geometry('650x500')

        self.exportmark = ttk.Label(self.top, text="Tab-delimited export for profile:"+profile_record[1])
        self.exportmark.pack(side=TOP, anchor='nw', padx=10, pady=10)

        # save and copy buttons
        tlframe = ttk.Frame(self.top)
        tlframe.pack(side=BOTTOM, anchor='sw', padx=10, pady=(0,10))
        self.copy_button = ttk.Button(tlframe, text = 'Copy All', command = self.export_copy_all)
        self.copy_button.pack(side=LEFT, padx=(0,10))
        self.saveas_button = ttk.Button(tlframe, text = 'Save As', command = self.export_saveas_popup)
        self.saveas_button.pack(side=RIGHT)

        # text window
        self.export_text = Text(self.top, wrap=NONE)
        export_scrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.export_text.yview)
        self.export_text.configure(yscroll=export_scrollbar.set)
        export_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(0,10))
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

    def export_saveas_popup(self):
        fname = filedialog.asksaveasfilename(defaultextension=".txt", parent=self)
        if fname is None or fname == '' or type(fname) is tuple: return
        saveas_text = str(self.export_text.get('1.0', 'end'))
        with open(fname,mode='w',encoding='utf-8') as f:
            f.write(saveas_text)
            f.close()

    def export_copy_all(self):
        self.clipboard_clear()
        text = self.export_text.get('1.0', 'end')
        self.clipboard_append(text)

    ## Export right-click copy action
    def export_copy_popup(self, ev):
        self.rcmenu.tk_popup(ev.x_root,ev.y_root)
        if self.export_text.tag_ranges("sel"):
            self.clipboard_clear()
            text = self.export_text.get('sel.first', 'sel.last')
            self.clipboard_append(text)

    ## Delete profile activity log entries
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

    def activity_msg_format(self, activity):
        global speeds
        speedtxt=""
        if activity[10]!="": speedtxt = speeds[activity[10]]
        actmsg="Message Details:\n\n"
        actmsg+="Call:     "+activity[6]+"\n"
        actmsg+="Dial:     "+activity[4]+"\n"
        actmsg+="Freq:     "+activity[8]+"\n"
        actmsg+="Offset:   "+activity[9]+"\n"
        actmsg+="Speed:    "+speedtxt+"\n"
        actmsg+="\nDate:     "+activity[7]+"\n"
        actmsg+="Text:     "+activity[3]+"\n"
        actmsg+="\nSNR:      "+activity[5]+"dB\n"
        actmsg+="Type:     "+activity[2]+"\n"
        return actmsg

    ## Copy activity to clipboard
    def copy_activity(self, ev, rxtype):
        aciid=0
        if rxtype=="mact" and self.activity.focus(): aciid = int(self.activity.focus())
        if rxtype=="act" and self.top.activity.focus(): aciid = int(self.top.activity.focus())
        if rxtype=="dir" and self.top.directed.focus(): aciid = int(self.top.directed.focus())
        if rxtype=="spot" and self.top.spot.focus(): aciid = int(self.top.spot.focus())

        if aciid>0:
            c.execute("SELECT * FROM activity WHERE id = ?",[aciid])
            activity = c.fetchone()
            actmsg = self.activity_msg_format(activity)
            self.clipboard_clear()
            self.clipboard_append(actmsg)
            if rxtype=="mact":
                messagebox.showinfo("Copied","Copied to clipboard")
            else:
                messagebox.showinfo("Copied","Copied to clipboard", parent=self.top)

    ## View activity from gui main window
    def view_activity(self, ev):
        if not self.activity.focus(): return
        aciid = int(self.activity.focus())
        c.execute("SELECT * FROM activity WHERE id = ?",[aciid])
        activity = c.fetchone()
        actmsg = self.activity_msg_format(activity)
        messagebox.showinfo("Activity Detail",actmsg)

    ## View activity details by type, from search term detail window
    def view_activity_type(self, rxtype):
        aciid=0
        if rxtype=="act" and self.top.activity.focus(): aciid = int(self.top.activity.focus())
        if rxtype=="dir" and self.top.directed.focus(): aciid = int(self.top.directed.focus())
        if rxtype=="spot" and self.top.spot.focus(): aciid = int(self.top.spot.focus())

        if aciid>0:
            c.execute("SELECT * FROM activity WHERE id = ?",[aciid])
            activity = c.fetchone()
            actmsg = self.activity_msg_format(activity)
            messagebox.showinfo("Activity Detail",actmsg, parent=self.top)

    ## View search term detail window, divided by type
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
        msgtxt = str(kwvals['values'][0])+" Activity"

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
        self.top.activity.bind('<Return>', lambda x: self.view_activity_type("act"))
        self.top.activity.bind('<Button-3>', lambda ev: self.copy_activity(ev,"act"))

        self.top.activity.grid(row=2, column = 0, sticky='NSEW', padx=(10,0), pady=(0,10))
        self.top.acscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.top.activity.yview)
        self.top.activity.configure(yscroll=self.top.acscrollbar.set)
        self.top.acscrollbar.grid(row=2, column=1, sticky='NSEW', padx=(0,10), pady=(0,10))

        sql = "SELECT * FROM activity WHERE profile_id = ? AND type = ? AND (call LIKE ? OR value LIKE ?) ORDER BY spotdate DESC"
        c.execute(sql,[current_profile_id,"RX.ACTIVITY",'%'+search[2]+'%','%'+search[2]+'%'])
        tactivity_records = c.fetchall()

        count=0
        for record in tactivity_records:
            if count % 2 == 1:
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
        self.top.directed.bind('<Return>', lambda x: self.view_activity_type("dir"))
        self.top.directed.bind('<Button-3>', lambda ev: self.copy_activity(ev,"dir"))

        self.top.directed.grid(row=4, column=0, sticky='NSEW', padx=(10,0), pady=(0,10))
        self.top.acscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.top.directed.yview)
        self.top.directed.configure(yscroll=self.top.acscrollbar.set)
        self.top.acscrollbar.grid(row=4, column=1, sticky='NS', padx=(0,10), pady=(0,10))

        sql = "SELECT * FROM activity WHERE profile_id = ? AND type = ? AND (call LIKE ? OR value LIKE ?) ORDER BY spotdate DESC"
        c.execute(sql,[current_profile_id,"RX.DIRECTED",'%'+search[2]+'%','%'+search[2]+'%'])
        dactivity_records = c.fetchall()

        count=0
        for record in dactivity_records:
            if count % 2 == 1:
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
        self.top.spot.bind('<Return>', lambda x: self.view_activity_type("spot"))
        self.top.spot.bind('<Button-3>', lambda ev: self.copy_activity(ev,"spot"))

        self.top.spot.grid(row=6, column=0, sticky='NSEW', padx=(10,0), pady=(0,10))
        self.top.acscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.top.spot.yview)
        self.top.spot.configure(yscroll=self.top.acscrollbar.set)
        self.top.acscrollbar.grid(row=6, column=1, sticky='NS', padx=(0,10), pady=(0,10))

        sql = "SELECT * FROM activity WHERE profile_id = ? AND type = ? AND (call LIKE ? OR value LIKE ?) ORDER BY spotdate DESC"
        c.execute(sql,[current_profile_id,"RX.SPOT",'%'+search[2]+'%','%'+search[2]+'%'])
        sactivity_records = c.fetchall()

        count=0
        for record in sactivity_records:
            if count % 2 == 1:
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
            self.top.activity.tag_configure('oddrow', background='#EEE')
            self.top.activity.tag_configure('evenrow', background='#FFF')
            self.top.directed.tag_configure('oddrow', background='#EEE')
            self.top.directed.tag_configure('evenrow', background='#FFF')
            self.top.spot.tag_configure('oddrow', background='#EEE')
            self.top.spot.tag_configure('evenrow', background='#FFF')

        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Display a maidenhead grid map with SPOT locations
    def grid_map(self):
        global map_loc, totals

        totals[0]=0
        self.update_statusbar()

        self.top = Toplevel(self)
        self.top.title("Grid Location Map")
        self.top.geometry('1120x465')
        self.top.resizable(width=False, height=False)

        # callsign GRID treeview
        self.top.gridcall = ttk.Treeview(self.top, show='headings', style='keywords.Treeview')
        self.top.gridcall["columns"]=("call","grid","snr","last_seen")

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
        self.top.gridcall.bind('<Button-3>', self.delete_grid)
        self.top.gridcall.grid(row=0, column=1, sticky='NSEW', padx=(10,0), pady=(10,10))

        self.top.gcscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.top.gridcall.yview)
        self.top.gridcall.configure(yscroll=self.top.gcscrollbar.set)
        self.top.gcscrollbar.grid(row=0, column=2, sticky='NS', padx=(0,0), pady=(10,10))
        self.top.gridcall.tag_configure('notshown', foreground='gray')

        # map frame
        self.top.map = ttk.Frame(self.top)
        self.top.canvas = Canvas(self.top.map, width=806, height=406)
        self.top.map.grid(row=0,column=0, padx=(10,0), pady=(10,0))

        # status info box for highlighted marker
        self.top.grid_status = ttk.Entry(self.top, width = '75')
        self.top.grid_status.grid(row = 1, column = 0)

        # map select
        self.top.maploc = ttk.Combobox(self.top, values=maplocs, state='readonly', width='15')
        self.top.maploc.grid(row=1, column =1, sticky='NW', padx=(10,0))
        self.top.maploc.current(map_loc)
        self.top.maploc.bind('<<ComboboxSelected>>', self.maploc_sel_combo)

        # show marker count select
        self.top.markershow = ttk.Combobox(self.top, values=markeropts, state='readonly', width='14')
        self.top.markershow.grid(row=1, column =1, sticky='NE')
        self.top.markershow.current(settings['marker_index'])
        self.top.markershow.bind('<<ComboboxSelected>>', self.markershow_sel_combo)

        self.top.canvas.pack()
        self.update_grid()
        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Select which map to display
    def maploc_sel_combo(self, ev):
        global map_loc
        map_loc = self.top.maploc.current()
        self.update_grid()

    ## Show n markers on map
    def markershow_sel_combo(self, ev):
        global settings
        settings['marker_index'] = str(self.top.markershow.current())
        # save change in settings table
        c.execute("UPDATE setting SET value = '"+settings['marker_index']+"' WHERE name = 'marker_index'")
        conn.commit()
        self.update_grid()

    ## Update/refresh map and markers
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

        # retrieve records and add to treeview
        c.execute("SELECT * FROM grid ORDER BY grid_timestamp DESC LIMIT 100")
        grid_records = c.fetchall()

        count = 0
        for record in grid_records:
            if count % 2 == 1:
                self.top.gridcall.insert('', tk.END, iid=record[0], values=(record[0],record[1],record[4],record[5]), tags=('oddrow'))
            else:
                self.top.gridcall.insert('', tk.END, iid=record[0], values=(record[0],record[1],record[4],record[5]), tags=('evenrow'))
            count+=1

        if settings['dark_theme'] == "1":
            self.top.gridcall.tag_configure('oddrow', background='#777')
            self.top.gridcall.tag_configure('evenrow', background='#555')
        else:
            self.top.gridcall.tag_configure('oddrow', background='#EEE')
            self.top.gridcall.tag_configure('evenrow', background='#FFF')

        # draw background map
        self.top.canvas.create_image(403,203,image=self.top.mapimg)

        if settings['marker_index']=='0': dispcount=101
        if settings['marker_index']=='1': dispcount=51
        if settings['marker_index']=='2': dispcount=26
        if settings['marker_index']=='3': dispcount=11

        # update list tags view to gray out non-visible entires
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

    ## Highlight GRID marker
    def highlight_grid(self, ev):
        if not self.top.gridcall.focus(): return
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

    ## Maidenhead to pixels
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

    ## Delete item from grid map list
    def delete_grid(self, ev):
        if not self.top.gridcall.focus(): return
        gciid = self.top.gridcall.focus()

        answer = askyesno(title="Remove Map Record?", message="This will delete "+gciid+" from the map database. Continue?", parent=self.top)
        if answer:
            c.execute("DELETE FROM grid WHERE grid_callsign = ?", [gciid])
            conn.commit()
            self.update_grid()

    ## Display a simulated waterfall with visualization of recent band activity
    def visualize_waterfall(self):

        wfbands = ["80m - 3.578.000","40m - 7.078.000","30m - 10.130.000","20m - 14.078.000","17m - 18.104.000","15 - 21.078.000","12m - 24.922.000","10m - 28.078.000"]
        wftimes = ["Last 5 minutes","Last 30 minutes","Last 1 hour","Last 2 hours", "Last 4 hours", "Last 8 hours", "Last 24 hours"]

        self.top = Toplevel(self)
        self.top.title("Visualize Waterfall Activity")
        self.top.geometry('1157x300')
        self.top.resizable(width=False, height=False)

        # background waterfall image
        self.top.wf = ttk.Frame(self.top)
        self.top.canvas = Canvas(self.top.wf, width=1137, height=239)
        self.top.wf.grid(row=0,column=0, padx=(10,10), pady=(10,0))

        # options frame
        self.top.opts = ttk.Frame(self.top)
        self.top.opts.grid(row=1,column=0, padx=(10,10), pady=(0,10))

        # dial / band select
        self.top.wfband = ttk.Combobox(self.top.opts, values=wfbands, state='readonly', width='18')
        self.top.wfband.grid(row=0, column =0, sticky='NE', padx=(10,10), pady=(10,0))
        self.top.wfband.current(settings['wfband_index'])
        self.top.wfband.bind('<<ComboboxSelected>>', self.wfband_sel_combo)

        # time select
        self.top.wftime = ttk.Combobox(self.top.opts, values=wftimes, state='readonly', width='14')
        self.top.wftime.grid(row=0, column =1, sticky='NE', padx=(10,10), pady=(10,0))
        self.top.wftime.current(settings['wftime_index'])
        self.top.wftime.bind('<<ComboboxSelected>>', self.wftime_sel_combo)

        self.top.canvas.pack()
        self.update_simwf()
        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Select band visual to display on sim waterfall
    def wfband_sel_combo(self, ev):
        global settings
        settings['wfband_index'] = str(self.top.wfband.current())
        # save change in settings table
        c.execute("UPDATE setting SET value = '"+settings['wfband_index']+"' WHERE name = 'wfband_index'")
        conn.commit()
        self.update_simwf()

    ## Select timeframe for sim waterfall
    def wftime_sel_combo(self, ev):
        global settings
        settings['wftime_index'] = str(self.top.wftime.current())
        # save change in settings table
        c.execute("UPDATE setting SET value = '"+settings['wftime_index']+"' WHERE name = 'wftime_index'")
        conn.commit()
        self.update_simwf()

    ## Update band activity on simulated waterfall
    def update_simwf(self):
        # clear out and rebuild
        self.top.canvas.delete('all')

        # draw background
        self.top.mapimg = ImageTk.PhotoImage(Image.open('waterfall.png'))
        self.top.canvas.create_image(569,120,image=self.top.mapimg)

        wftimesel = self.top.wftime.current()
        wfbandsel = self.top.wfband.current()

        # get info from db based on selections
        wftimes = ["-5 minute","-30 minute","-1 hour","-2 hour","-4 hour","-8 hour", "-24 hour"]
        wftimes2 =["-0 minute","-5 minute","-30 minute","-1 hour","-2 hour","-4 hour", "-8 hour"]
        wfbands = ["3578000","7078000","10130000","14078000","18104000","21078000","24922000","28078000"]

        # We want to iterate over date ranges in reverse, so the newest signals are layered over the oldest
        for i in range(wftimesel+1, 0, -1):
            c.execute("SELECT * FROM signal WHERE sig_offset<>'' AND sig_speed<>'' AND (sig_timestamp BETWEEN DATETIME('now', '"+wftimes[i-1]+"') AND DATETIME('now', '"+wftimes2[i-1]+"' )) AND sig_dial = '"+wfbands[wfbandsel]+"' ORDER BY sig_freq ASC")
            wf_records = c.fetchall()

            for record in wf_records:
                # calculate location on wf and size
                sx=int(record[4])-500
                sx=sx*.44 # scale to match png
                if record[5]=="0": # normal mode
                    w=22
                    h=42
                    sy=29
                if record[5]=="1": # fast mode
                    w=35
                    h=22
                    sy=90
                if record[5]=="2": # turbo mode
                    w=70
                    h=11
                    sy=126
                if record[5]=="4": # slow mode
                    w=11
                    h=78
                    sy=159

                if i==1: scolor="#FF0000"
                if i==2: scolor="#D51125"
                if i==3: scolor="#BB1144"
                if i==4: scolor="#991166"
                if i==5: scolor="#771188"
                if i==6: scolor="#5511AA"
                if i==7: scolor="#3311CC"

                # draw simulated signal placeholder on wf background
                self.top.canvas.create_rectangle(sx,sy,sx+w,sy+h, fill=scolor, width='0', stipple="gray50")

    ## Expect subsystem main window
    def expect(self):
        global totals

        totals[1]=0
        self.update_statusbar()

        self.top = Toplevel(self)
        self.top.title("Expect Auto-Reply Subsystem")
        self.top.geometry('1120x465')
        self.top.minsize(1120,465)
        self.top.resizable(width=True, height=True)

        self.top.columnconfigure(0, weight=24)
        self.top.columnconfigure(1, weight=1)

        self.top.rowconfigure(0,weight=24)
        self.top.rowconfigure(1,weight=1)

        # expect treeview
        self.expect = ttk.Treeview(self.top, show='headings', selectmode="browse")
        self.expect["columns"]=("expect","reply","allowed","txlist","txmax","lm")
        self.expect.tag_configure('max', background='red')

        self.expect.column("expect", width=70, minwidth=70, stretch=0)
        self.expect.column("reply", width=240, minwidth=240)
        self.expect.column("allowed", width=285, minwidth=285)
        self.expect.column("txlist", width=195, minwidth=195)
        self.expect.column("txmax", width=195, minwidth=60)
        self.expect.column("lm", width=90, minwidth=90, stretch=0)
        self.expect.heading("expect", text="Expect")
        self.expect.heading("reply", text="Response")
        self.expect.heading("allowed", text="Allowed Calls/Groups")
        self.expect.heading("txlist", text="Sent To")
        self.expect.heading("txmax", text="Count")
        self.expect.heading("lm", text="Created")

        self.expect.bind('<Return>', self.edit_expect)
        self.expect.bind('<Double-1>', self.show_expect)
        self.expect.bind('<Delete>', self.delete_expect)
        self.expect.bind('<Button-2>', self.edit_expect)
        self.expect.bind('<Button-3>', self.edit_expect)
        self.expect.grid(row=0, column=0, sticky='NSEW', padx=(10,0), pady=(10,10))

        self.gcscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.expect.yview)
        self.expect.configure(yscroll=self.gcscrollbar.set)
        self.gcscrollbar.grid(row=0, column=1, sticky='NS', padx=(0,10), pady=(10,10))

        # frame with input & buttons
        self.exframe = ttk.Frame(self.top)
        self.exframe.grid(row=1, column=0, sticky='NSEW')

        self.lbl1 = ttk.Label(self.exframe, text='Text to Expect (6):')
        self.lbl1.grid(row=0, column = 0, sticky='NW', padx=(8,0), pady=(8,0))
        self.entry_expect = ttk.Entry(self.exframe, width = '14')
        self.entry_expect.grid(row=1, column=0, sticky='NW', padx=(8,0), pady=(8,0))

        self.lbl2 = ttk.Label(self.exframe, text='Text to Respond With:')
        self.lbl2.grid(row=0, column = 1, sticky='NW', padx=(8,0), pady=(8,0))
        self.entry_reply = ttk.Entry(self.exframe, width = '35')
        self.entry_reply.grid(row=1, column=1, sticky='NW', padx=(8,0), pady=(8,0))

        self.lbl3 = ttk.Label(self.exframe, text='Allowed Callsigns/Groups:')
        self.lbl3.grid(row=0, column = 2, sticky='NW', padx=(8,0), pady=(8,0))
        self.entry_allowed = ttk.Entry(self.exframe, width = '30')
        self.entry_allowed.grid(row=1, column=2, sticky='NW', padx=(8,0), pady=(8,0))

        self.lbl4 = ttk.Label(self.exframe, text='Max Replies:')
        self.lbl4.grid(row=0, column = 3, sticky='NW', padx=(8,0), pady=(8,0))
        self.entry_txmax = ttk.Entry(self.exframe, width = '8')
        self.entry_txmax.grid(row=1, column=3, sticky='NW', padx=(8,0), pady=(8,0))

        self.save = ttk.Button(self.exframe, text = 'Save', command = self.save_expect, width='5')
        self.save.grid(row=1, column=4, sticky='NW', padx=(8,0),pady=(8,0))
        self.cancel = ttk.Button(self.exframe, text = 'Cancel', command = self.cancelsave_expect, width='6')
        self.cancel.grid(row=1, column=5, sticky='NW', padx=(8,8),pady=(8,0))
        self.cancel = ttk.Button(self.exframe, text = 'Send Now', command = self.tx_expect, width='12')
        self.cancel.grid(row=1, column=6, sticky='NW', padx=(20,8),pady=(8,0))

        self.update_expect()
        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Update expect treeview
    def update_expect(self):
        for entry in self.expect.get_children():
            self.expect.delete(entry)

        c.execute("SELECT * FROM expect ORDER BY lm DESC")
        expect_lines = c.fetchall()

        count = 0
        for record in expect_lines:
            reply_count=len(record[3].split(","))-1
            reply_max = str(reply_count)+"/"+str(record[4])
            ex_date = record[5].split(" ")[0]

            if count % 2 == 1:
                self.expect.insert('', tk.END, iid=record[0], values=(record[0],record[1],record[2],record[3],reply_max,ex_date), tags=('oddrow'))
            else:
                self.expect.insert('', tk.END, iid=record[0], values=(record[0],record[1],record[2],record[3],reply_max,ex_date), tags=('evenrow'))

            count+=1
            if reply_count>=record[4]: self.expect.item(record[0], tags=('max'))

        if settings['dark_theme'] == "1":
            self.expect.tag_configure('oddrow', background='#777')
            self.expect.tag_configure('evenrow', background='#555')
        else:
            self.expect.tag_configure('oddrow', background='#EEE')
            self.expect.tag_configure('evenrow', background='#FFF')

    def show_expect(self, ev):
        if not self.expect.focus(): return
        exiid = self.expect.focus()

        c.execute("SELECT * FROM expect WHERE expect = ?", [exiid])
        record = c.fetchone()

        if record:
            self.top2 = Toplevel(self)
            self.top2.title("Expect Info for "+record[0])
            self.top2.geometry('650x500')

            # display window
            self.expect_text = Text(self.top2, wrap=NONE)
            exp_scrollbar = ttk.Scrollbar(self.top2, orient=tk.VERTICAL, command=self.expect_text.yview)
            self.expect_text.configure(yscroll=exp_scrollbar.set)
            exp_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(10,10))
            self.expect_text.pack(side=LEFT, expand=True, fill='both', padx=(10,0), pady=(10,10))

            expect_contents = "Expect:  "+record[0]+"\nRespond:   "+record[1]+"\n\nAllowed Requestors: "+record[2]+"\n\nSent to:\n\n"
            for txitem in record[3].split(","):
                expect_contents += txitem+"\n"

            self.expect_text.insert(tk.END, expect_contents)

            self.expect_text.configure(state='disabled')
            self.top2.focus()
            self.top2.wait_visibility()
            self.top2.grab_set()
            self.top2.bind('<Escape>', lambda x: self.top2.destroy())

    def save_expect(self):
        new_expect = re.sub(r'[^A-Z0-9!]','',self.entry_expect.get().upper())
        new_reply = self.entry_reply.get().upper()
        new_allowed = self.entry_allowed.get().upper()
        new_allowed = new_allowed.replace(" ", "")
        new_txmax = self.entry_txmax.get().upper()

        # validate input
        if new_expect == "" or new_reply == "" or new_allowed == "" or new_txmax == "" : return

        if new_txmax.isnumeric() == False:
            messagebox.showinfo("Error","Max Replies must be a number (1-99)", parent=self.top)
            return

        if int(new_txmax) < 1 or int(new_txmax) > 99:
            messagebox.showinfo("Error","Max Replies must be between 1 and 99", parent=self.top)
            return

        # preserve txlist if it exists already
        c.execute("SELECT * FROM expect WHERE expect = ?", [new_expect[0:6]])
        record = c.fetchone()
        old_txlist = ""
        if record:
            old_txlist = record[3]

        # checks passed, save and update
        sql = "INSERT INTO expect(expect,reply,allowed,txmax,txlist,lm) VALUES (?,?,?,?,?, CURRENT_TIMESTAMP)"
        c.execute(sql, [new_expect[0:6],new_reply,new_allowed,new_txmax,old_txlist])
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
        if not self.expect.focus(): return
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

    ## Manually tx an expect response
    def tx_expect(self):
        self.new_reply = self.entry_reply.get().upper()
        if self.new_reply=="":
            messagebox.showinfo("Nothing to Send","Right-click a row to load a saved response, or type one in before attempting to send.", parent=self.top)
            return

        self.top2 = Toplevel(self)
        self.top2.title("Manually Send Expect Response")
        self.top2.resizable(width=False, height=False)

        label_new = ttk.Label(self.top2, text = "Send to (single callsign or group)")
        label_new.grid(row = 0, column = 0, padx=(10,0), pady=(20,0))
        self.sendto = ttk.Entry(self.top2, width='34')
        self.sendto.grid(row = 0, column = 1, padx=(0,10), pady=(20,0))
        self.sendto.bind("<KeyRelease>", lambda x: self.txexpect_updatecmd())

        self.msgcheck = ttk.Checkbutton(self.top2, text='Send as MSG', onvalue=1, offvalue=0, command=self.txexpect_updatecmd)
        self.msgcheck.grid(row=1, column=0, sticky='W', pady=(8,0))
        self.msgcheck.state(['!alternate','!selected'])

        self.tx_cmd = ttk.Entry(self.top2)
        self.tx_cmd.grid(row = 2, column = 0, columnspan=2, stick='NSEW', padx=(10,10), pady=(20,0))

        cbframe = ttk.Frame(self.top2)
        cbframe.grid(row=3, columnspan=2, sticky='e', padx=10)

        create_button = ttk.Button(cbframe, text = "Send", command = self.proc_txexpect)
        create_button.grid(row=0, column = 1, padx=(10,0), pady=(20,20))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top2.destroy)
        cancel_button.grid(row=0, column = 2, padx=(10,0), pady=(20,20))

        self.txexpect_updatecmd()
        self.top2.wait_visibility()
        self.top2.grab_set()
        self.sendto.focus()
        self.top2.bind('<Escape>', lambda x: self.top2.destroy())

    def txexpect_updatecmd(self):
        to = self.sendto.get().strip().upper()
        msg = self.new_reply.strip()

        msgadd=""
        if self.msgcheck.instate(['selected']):
            msgadd="MSG "

        tx_cmd = to+" "+msgadd+msg
        self.tx_cmd.delete(0,END)
        self.tx_cmd.insert(0,tx_cmd)

    def proc_txexpect(self):
        new_cmd = self.tx_cmd.get()
        if new_cmd == "": return
        tx_content = json.dumps({"params":{},"type":"TX.SEND_MESSAGE","value":new_cmd})
        self.sock.send(bytes(tx_content + '\n','utf-8'))
        self.top2.destroy()

    ## MCForms subsystem form responses view
    def form_responses(self):
        global totals

        totals[2]=0
        self.update_statusbar()

        self.top = Toplevel(self)
        self.top.title("MCForms - Form Responses")
        self.top.geometry('1000x465')
        self.top.minsize(1000,465)
        self.top.resizable(width=True, height=True)

        self.top.columnconfigure(0, weight=24)
        self.top.columnconfigure(1, weight=1)

        self.top.rowconfigure(0,weight=1)
        self.top.rowconfigure(1,weight=24)
        self.top.rowconfigure(2,weight=1)

        # form type select, date range select, & title
        self.ftframe = ttk.Frame(self.top)
        self.ftframe.grid(row=0, column=0, columnspan=2, sticky='NSEW', padx=10, pady=(0,5))

        self.ftmark = ttk.Label(self.ftframe, text='View Form Responses:', font=("Segoe Ui Bold", 12))
        self.ftmark.grid(row=0, column = 0, sticky='W', padx=0, pady=(8,0))
        self.ftcombo = ttk.Combobox(self.ftframe, values="", state='readonly', width='40')
        self.ftcombo.grid(row=0, column =1 , sticky='E', padx=8, pady=(8,0))
        self.ftcombo.bind('<<ComboboxSelected>>', self.formtype_selcombo)
        self.drcombo = ttk.Combobox(self.ftframe, values=("All Time","Last 24hrs","Last Week","Last Month","Last Year"), state='readonly')
        self.drcombo.grid(row=0, column =2 , sticky='E', padx=8, pady=(8,0))
        self.drcombo.bind('<<ComboboxSelected>>', self.formtype_selcombo)

        # form response treeview
        self.formresp = ttk.Treeview(self.top, show='headings', selectmode="browse")
        self.formresp["columns"]=("fromcall","tocall","typeid","response","msgtxt","timesig","gw","lm")

        self.formresp.column("fromcall", width=60, minwidth=60, stretch=0)
        self.formresp.column("tocall", width=60, minwidth=60)
        self.formresp.column("typeid", width=60, minwidth=60)
        self.formresp.column("response", width=270, minwidth=270)
        self.formresp.column("msgtxt", width=270, minwidth=270)
        self.formresp.column("timesig", width=75, minwidth=75)
        self.formresp.column("gw", width=40, minwidth=40)
        self.formresp.column("lm", width=120, minwidth=120, stretch=0)

        self.formresp.heading("fromcall", text="From")
        self.formresp.heading("tocall", text="To")
        self.formresp.heading("typeid", text="Form #")
        self.formresp.heading("response", text="Form Responses")
        self.formresp.heading("msgtxt", text="Message")
        self.formresp.heading("timesig", text="Timestamp")
        self.formresp.heading("gw", text="GW")
        self.formresp.heading("lm", text="Received")

        self.formresp.bind('<Double-1>', self.show_formresp)
        self.formresp.bind('<Delete>', self.delete_formresp)
        self.formresp.grid(row=1, column=0, sticky='NSEW', padx=(10,0), pady=(10,10))

        self.frscrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.formresp.yview)
        self.formresp.configure(yscroll=self.frscrollbar.set)
        self.frscrollbar.grid(row=1, column=1, sticky='NS', padx=(0,10), pady=(10,10))

        # frame with action items
        self.frframe = ttk.Frame(self.top)
        self.frframe.grid(row=2, column=0, sticky='NSEW')

        self.frexport = ttk.Button(self.frframe, text = 'Export All', command = self.export_formresps, width='12')
        self.frexport.grid(row=0, column=0, sticky='NE', padx=(8,8),pady=(8,8))

        self.gwlabel = Label(self.frframe, text='Gateway:')
        self.gwlabel.grid(row=0, column = 1, sticky='NE', padx=(30,0), pady=(12,8))
        self.gateway = ttk.Entry(self.frframe, width = '44')
        self.gateway.grid(row = 0, column = 2, sticky='NE', padx=(8,8), pady=(8,8))
        self.gateway.insert(0, settings['forms_gateway'])
        self.gateway.bind('<Return>', lambda ev: self.form_savegw())
        self.gwsave = ttk.Button(self.frframe, text = 'Save', command = self.form_savegw, width='12')
        self.gwsave.grid(row=0, column=3, sticky='NE', padx=(8,8),pady=(8,8))

        self.update_formtypecombo()
        self.ftcombo.set("View All Form Types")
        self.drcombo.set("All Time")
        self.update_formresponses()
        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Save form gateway setting
    def form_savegw(self):
        global settings
        new_gw = self.gateway.get()
        settings['forms_gateway'] = str(new_gw)
        # save change in settings table
        c.execute("UPDATE setting SET value = '"+settings['forms_gateway']+"' WHERE name = 'forms_gateway'")
        conn.commit()
        messagebox.showinfo("Forms Gateway","Forms gateway saved. If you entered a valid URL, any new forms stored will also be sent to this URL. Save the Gateway box empty to disable.", parent=self.top)

    ## Update form responses treeview
    def update_formresponses(self):
        # limit to selected form type
        typeid_selection = self.ftcombo.get().split(",")[0]
        wheres = ""
        if typeid_selection!="" and typeid_selection!="View All Form Types":
            wheres = " WHERE typeid = '"+typeid_selection+"' "

        # limit to selected date range
        range_selection = self.drcombo.get()
        if range_selection:
            if range_selection!="All Time":
                if wheres=="":
                    wheres = " WHERE "
                else:
                    wheres += " AND "
                if range_selection=="Last 24hrs": wheres+="lm > DATETIME('now', '-24 hour')"
                if range_selection=="Last Week": wheres+="lm > DATETIME('now', '-7 day')"
                if range_selection=="Last Month": wheres+="lm > DATETIME('now', '-31 day')"
                if range_selection=="Last Year": wheres+="lm > DATETIME('now', '-365 day')"

        # clear out the tree
        for entry in self.formresp.get_children():
            self.formresp.delete(entry)

        c.execute("SELECT * FROM forms "+wheres+" ORDER BY lm DESC")
        formresp_lines = c.fetchall()

        count = 0
        for record in formresp_lines:
            fr_date = record[7] # or format, such as: record[7].split(" ")[0]
            fr_gwtx = "!"
            if record[8]=="<Response [200]>": fr_gwtx="\u2713" # http response from gateway, 200, 404, 403, 500, etc
            if record[8]=="": fr_gwtx=""

            if count % 2 == 1:
                self.formresp.insert('', tk.END, iid=record[0], values=(record[1],record[2],record[3],record[4],record[5],record[6],fr_gwtx,fr_date), tags=('oddrow'))
            else:
                self.formresp.insert('', tk.END, iid=record[0], values=(record[1],record[2],record[3],record[4],record[5],record[6],fr_gwtx,fr_date), tags=('evenrow'))
            count+=1

        if settings['dark_theme'] == "1":
            self.formresp.tag_configure('oddrow', background='#777')
            self.formresp.tag_configure('evenrow', background='#555')
        else:
            self.formresp.tag_configure('oddrow', background='#EEE')
            self.formresp.tag_configure('evenrow', background='#FFF')

    ## Build/rebuild form type combobox
    def update_formtypecombo(self):
        global forms
        self.form_refresh()

        # clear combobox
        self.ftcombo.delete(0, tk.END)

        # rebuild from database
        c.execute("SELECT id,typeid FROM forms ORDER BY typeid ASC")
        ftype_records = c.fetchall()
        ftcomboopts = []

        ftcomboopts.append("View All Form Types")
        for record in ftype_records:
            if record[1] in forms.keys():
                newrec = record[1]+", "+forms[record[1]][0]
            else:
                newrec = record[1]+", Unknown Form"

            #if record[1] not in ftcomboopts:
            if newrec not in ftcomboopts:
                ftcomboopts.append(newrec)

        self.ftcombo['values'] = ftcomboopts

    ## Select a form typeid through the combobox
    def formtype_selcombo(self, ev):
        self.update_formresponses()

    ## Display formatted version of form response data
    def show_formresp(self,ev):
        if not self.formresp.focus(): return
        friid = self.formresp.focus()

        if friid == "": return

        c.execute("SELECT * FROM forms WHERE id = '"+friid+"'")
        formresp_db = c.fetchone()

        if formresp_db:
            formdata = self.form_items(formresp_db[3])
            dcst = self.decode_shorttime(formresp_db[6])

            self.top2 = Toplevel(self)
            self.top2.title("Form "+formresp_db[3]+" from "+formresp_db[1])
            self.top2.geometry('650x500')

            # display window
            self.export_text = Text(self.top2, wrap=NONE, font='TkFixedFont')
            fr_scrollbar = ttk.Scrollbar(self.top2, orient=tk.VERTICAL, command=self.export_text.yview)
            self.export_text.configure(yscroll=fr_scrollbar.set)
            fr_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(10,10))

            # save and copy buttons
            tlframe = ttk.Frame(self.top2)
            tlframe.pack(side=BOTTOM, anchor='sw', padx=10, pady=(0,10))
            self.top2.copy_button = ttk.Button(tlframe, text = 'Copy All', command = self.export_copy_all)
            self.top2.copy_button.pack(side=LEFT, padx=(0,10))
            self.top2.saveas_button = ttk.Button(tlframe, text = 'Save As', command = self.export_saveas_popup)
            self.top2.saveas_button.pack(side=RIGHT)

            self.export_text.pack(side=LEFT, expand=True, fill='both', padx=(10,0), pady=(10,10))

            # right-click action
            self.rcmenu = Menu(self.top2, tearoff = 0)
            self.rcmenu.add_command(label = 'Copy')
            self.export_text.bind('<Button-3>', lambda ev: self.export_copy_popup(ev))

            gwresp=""
            if formresp_db[8]!="": gwresp="\nGateway Response: "+formresp_db[8]
            fr_contents = "Form:         "+formresp_db[3]+"\nFROM Station: "+formresp_db[1]+"\nTO Station:   "+formresp_db[2]+"\nFiled:        "+dcst+"\nReceived:     "+formresp_db[7]+gwresp+"\n========================\n\n"

            # loop through form responses to build form report
            qnum=0
            for resp in formresp_db[4]:
                qnum+=1
                fr_contents += str(formdata[qnum][0].get("question"))
                qans = [i[str(resp)] for i in formdata[qnum] if str(resp) in i]
                if qans:
                    fr_contents += str(qans[0])+"\n"

            fr_contents += "Comment: "+formresp_db[5]

            self.export_text.insert(tk.END, fr_contents)

            self.export_text.configure(state='disabled')
            self.top2.focus()
            self.top2.wait_visibility()
            self.top2.grab_set()
            self.top2.bind('<Escape>', lambda x: self.top2.destroy())

    ## Remove saved form response(s) from database/tree
    def delete_formresp(self,ev):
        frlist = ""
        for friid in self.formresp.selection():
            frlist += "DBID ["+friid+"] from "+str(self.formresp.item(friid)['values'][0])+" received "+str(self.formresp.item(friid)['values'][6])+"\n"

        if frlist == "": return

        msgtxt = "Remove the following form response? This action cannot be undone.\n\n"+frlist
        answer = askyesno(title='Remove Form Response?', message=msgtxt, parent=self.top)
        if answer:
            for friid in self.formresp.selection():
                c.execute("DELETE FROM forms WHERE id = ?", [friid])
            conn.commit()
            self.update_formresponses()

    def export_formresps(self):
        # limit to selected form type
        typeid_selection = self.ftcombo.get().split(",")[0]
        wheres = ""
        if typeid_selection!="" and typeid_selection!="View All Form Types":
            wheres = " WHERE typeid = '"+typeid_selection+"' "

        # limit to selected date range
        range_selection = self.drcombo.get()
        if range_selection:
            if range_selection!="All Time":
                if wheres=="":
                    wheres = " WHERE "
                else:
                    wheres += " AND "
                if range_selection=="Last 24hrs": wheres+="lm > DATETIME('now', '-24 hour')"
                if range_selection=="Last Week": wheres+="lm > DATETIME('now', '-7 day')"
                if range_selection=="Last Month": wheres+="lm > DATETIME('now', '-31 day')"
                if range_selection=="Last Year": wheres+="lm > DATETIME('now', '-365 day')"

        c.execute("SELECT * FROM forms "+wheres+" ORDER BY lm DESC")
        formresp_lines = c.fetchall()

        if formresp_lines:
            self.top2 = Toplevel(self)
            self.top2.title("Form Responses Export")
            self.top2.geometry('650x500')

            # display window
            self.export_text = Text(self.top2, wrap=NONE, font='TkFixedFont')
            fr_scrollbar = ttk.Scrollbar(self.top2, orient=tk.VERTICAL, command=self.export_text.yview)
            self.export_text.configure(yscroll=fr_scrollbar.set)
            fr_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(10,10))

            # save and copy buttons
            tlframe = ttk.Frame(self.top2)
            tlframe.pack(side=BOTTOM, anchor='sw', padx=10, pady=(0,10))
            self.top2.copy_button = ttk.Button(tlframe, text = 'Copy All', command = self.export_copy_all)
            self.top2.copy_button.pack(side=LEFT, padx=(0,10))
            self.top2.saveas_button = ttk.Button(tlframe, text = 'Save As', command = self.export_saveas_popup)
            self.top2.saveas_button.pack(side=RIGHT)

            self.export_text.pack(side=LEFT, expand=True, fill='both', padx=(10,0), pady=(10,10))

            # right-click action
            self.rcmenu = Menu(self.top2, tearoff = 0)
            self.rcmenu.add_command(label = 'Copy')
            self.export_text.bind('<Button-3>', lambda ev: self.export_copy_popup(ev))

            # loop through form responses to build export
            export_contents = ""
            for record in formresp_lines:
                for i in record:
                    export_contents+=str(i)+chr(9)
                export_contents+="\n"

            self.export_text.insert(tk.END, export_contents)

            self.export_text.configure(state='disabled')
            self.top2.focus()
            self.top2.wait_visibility()
            self.top2.grab_set()
            self.top2.bind('<Escape>', lambda x: self.top2.destroy())
        else:
            messagebox.showinfo("No Form Responses","Couldn't find any form responses to export.", parent=self.top)

    ## View a dynamically generated form to fill in
    def form_view(self, formid):
        global forms

        self.top = Toplevel(self)
        self.top.title("MCForms - Form "+str(formid)+" | "+forms[formid][0])
        self.top.geometry('1024x600')
        self.top.minsize(600,500)
        self.top.resizable(width=True, height=True)

        self.top.columnconfigure(0,weight=12)

        self.top.rowconfigure(0,weight=1)
        self.top.rowconfigure(1,weight=12)
        self.top.rowconfigure(2,weight=1)
        self.top.rowconfigure(3,weight=1)

        formtitle = ttk.Label(self.top, text = str(formid)+" -- "+forms[formid][0], font=("Segoe Ui Bold", 14))
        formtitle.grid(row=0, column = 0, sticky='W', padx=0, pady=(8,0))

        frame=ttk.Frame(self.top)
        frame.grid(row=1, column=0, sticky='NEWS', padx=0, pady=0)

        formcanvas=Canvas(frame, width=300, height=300, scrollregion=(0,0,1900,1900), bd=0, highlightthickness=0, relief='ridge')

        hbar=ttk.Scrollbar(frame,orient=tk.HORIZONTAL, command=formcanvas.xview)
        hbar.config(command=formcanvas.xview)
        hbar.pack(side=BOTTOM,fill=X, padx=10, pady=10)

        vbar=ttk.Scrollbar(frame,orient=tk.VERTICAL, command=formcanvas.yview)
        vbar.config(command=formcanvas.yview)
        vbar.pack(side=RIGHT,fill=Y, padx=10, pady=10)

        formframe = ttk.Frame(formcanvas)
        formframe.grid(row=0, column=0, padx=10, pady=10)
        formcanvas.create_window((0, 0), window=formframe, anchor='nw')

        formdata = self.form_items(formid)
        formlabels = {}
        self.top.formcombos = {}

        for qnum in formdata:
            fcopts = []
            maxlen=0
            for qdata in formdata[qnum]:
                if "question" in qdata:
                    formlabels[qnum] = ttk.Label(formframe, text = qdata["question"].strip(), wraplength=300, justify=RIGHT)
                    formlabels[qnum].grid(row = qnum, column = 0, sticky=E, padx=10, pady=(0,10))

                    self.top.formcombos[qnum] = ttk.Combobox(formframe, values="", state='readonly')
                    self.top.formcombos[qnum].grid(row = qnum, column = 1 , sticky=W, padx=10, pady=(0,10))
                else:
                    for i in qdata: qdatastr = str(i)+" "+str(qdata[i].strip())
                    fcopts.append(qdatastr)
                    if maxlen < len(qdatastr): maxlen = len(qdatastr)
            self.top.formcombos[qnum]["values"] = fcopts
            self.top.formcombos[qnum]["width"] = maxlen

        formcanvas.pack(side=LEFT,expand=True,fill=BOTH)
        formcanvas.config(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        finish_frame=ttk.Frame(self.top)
        finish_frame.grid(row=2, column=0, sticky='NEWS', padx=0, pady=0)

        label_comment = ttk.Label(finish_frame, text = "Form Comment:")
        label_comment.grid(row = 0, column = 0, padx=(10,10), pady=(20,0))
        self.top.fcomment = ttk.Entry(finish_frame, width='34')
        self.top.fcomment.grid(row = 0, column = 1, padx=(0,10), pady=(20,0))
        post_button = ttk.Button(finish_frame, text = "Post Form to Expect", command = lambda : self.post_form(formid))
        post_button.grid(row=0, column = 2, padx=(10,0), pady=(20,0))
        post_button = ttk.Button(finish_frame, text = "Load Posted Expect Form", command = lambda : self.load_form(formid))
        post_button.grid(row=0, column = 3, padx=(10,0), pady=(20,0))

        self.top.focus()
        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Load saved form from expect system if it exists
    def load_form(self, formid):
        c.execute("SELECT * FROM expect WHERE expect = ?", [formid])
        ex_exists = c.fetchone()
        if ex_exists:
            form_resps = re.search("(F\![A-Z0-9]{3})\s+?([A-Z0-9]+)\s+?(.*?)(\#[A-Z0-9]+)",ex_exists[1])

            if form_resps[2]:
                # loop through form responses to set comboboxes
                qnum=0
                for resp in form_resps[2]:
                    qnum+=1
                    cnum=0
                    for index in self.top.formcombos[qnum]["values"]:
                        if index[0] == resp: self.top.formcombos[qnum].current(cnum)
                        cnum+=1

            if form_resps[3]!="":
                self.top.fcomment.insert(0, form_resps[3])
        else:
            messagebox.showinfo("Form Not Found","A matching previously posted form was not found in the expect system.", parent=self.top)

    ## Process form to expect system
    def post_form(self, formid):
        formdata = self.form_items(formid)

        resps = ""
        for qnum in formdata:
            answer=str(self.top.formcombos[qnum].get())
            if answer:
                resps+=answer[0]
            else:
                messagebox.showinfo("Please complete the form","Please make a selection for each box on the form before posting.", parent=self.top)
                return

        ecst = self.encode_shorttime()
        cmt = self.top.fcomment.get().upper()
        fresp = formid+" "+resps+" "+cmt+" "+ecst

        msgtxt = "Post the following form response to the Expect system?\n\n"+formid+" "+fresp+"\n\nThis will overwrite any existing response to this form."
        answer = askyesno(title='Post Form Response?', message=msgtxt, parent=self.top)
        if answer:
            sql = "INSERT INTO expect(expect,reply,allowed,txmax,txlist,lm) VALUES (?,?,?,?,?, CURRENT_TIMESTAMP)"
            c.execute(sql,[formid,fresp,"*","99",""])
            conn.commit()
            self.top.destroy()

    ## Build/rebuild reports sub-menu from database
    def build_formsmenu(self):
        global forms
        self.form_refresh()

        # remove any entries that may exist in sub-menu
        if self.formsmenu.winfo_exists():
            if self.formsmenu.index('end') is not None:
                self.formsmenu.delete(0,self.formsmenu.index('end'))

        for record in forms:
            self.formsmenu.add_command(label = record+" "+forms[record][0], command = lambda formid=record: self.form_view(formid))

        self.update()

    ## Re-generate list of forms on system
    def form_refresh(self):
        global forms

        forms_unsorted = {}
        forms_dir = os.path.join(ROOT_DIR, 'forms')
        for mcffile in os.scandir(forms_dir):
            if mcffile.path.endswith('txt'):
                with open(mcffile) as f: first_line = f.readline().strip('\n')
                forms_unsorted[first_line.split("|")[1]]=(first_line.split("|")[0],mcffile.path)
                f.close()

        forms.clear()
        for form_item in sorted(forms_unsorted.keys()):
            forms[form_item]=(forms_unsorted[form_item][0],forms_unsorted[form_item][1])

    ## Get form questions and answers, return questions+answers
    def form_items(self,formid):
        global forms
        formdata={}
        qindex=0

        if formid in forms.keys():
            with open(forms[formid][1]) as form_file:
                for form_line in form_file:
                    if form_line[0]=="?":
                        qindex+=1
                        formdata[qindex]=[{"question":form_line.partition(" ")[2]}]

                    if form_line[0]=="@" and qindex>0:
                        if formdata[qindex]:
                            formdata[qindex].extend([{form_line[1]:form_line.partition(" ")[2]}])
        return formdata

    ## Send APRS SMS
    def aprs_sms(self):
        self.top = Toplevel(self)
        self.top.title("APRS: Send SMS Text")
        self.top.resizable(width=False, height=False)

        label_new = ttk.Label(self.top, text = "Phone Number")
        label_new.grid(row = 0, column = 0, padx=(10,0), pady=(20,0))
        self.sms_phone = ttk.Entry(self.top, width='34')
        self.sms_phone.grid(row = 0, column = 1, padx=(0,10), pady=(20,0))
        self.sms_phone.bind("<KeyRelease>", lambda x: self.update_aprssms())

        label_new = ttk.Label(self.top, text = "Message (32 char)")
        label_new.grid(row = 1, column = 0, padx=(10,0), pady=(10,0))
        self.sms_msg = ttk.Entry(self.top, width='34')
        self.sms_msg.grid(row = 1, column = 1, padx=(0,10), pady=(10,0))
        self.sms_msg.bind("<KeyRelease>", lambda x: self.update_aprssms())

        self.sms_cmd = ttk.Entry(self.top)
        self.sms_cmd.grid(row = 2, column = 0, columnspan=2, stick='NSEW', padx=(10,10), pady=(20,0))

        cbframe = ttk.Frame(self.top)
        cbframe.grid(row=3, columnspan=2, sticky='e', padx=10)

        create_button = ttk.Button(cbframe, text = "Send", command = self.proc_aprscmd)
        create_button.grid(row=0, column = 1, padx=(10,0), pady=(20,20))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top.destroy)
        cancel_button.grid(row=0, column = 2, padx=(10,0), pady=(20,20))

        self.top.wait_visibility()
        self.top.grab_set()
        self.sms_phone.focus()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Update generated APRS cmd string on keypress
    def update_aprssms(self):
        phone = self.sms_phone.get().strip()
        phone = re.sub("[^0-9]","",phone)
        msg = self.sms_msg.get().strip()
        if phone=="" or msg=="":
            self.sms_cmd.delete(0,END)
            return
        aprs_cmd = "@APRSIS CMD :SMSGTE   :@"+phone+" "+msg+"{01}"
        self.sms_cmd.delete(0,END)
        self.sms_cmd.insert(0,aprs_cmd)

    ## Send APRS email
    def aprs_email(self):
        self.top = Toplevel(self)
        self.top.title("APRS: Send Email")
        self.top.resizable(width=False, height=False)

        label_new = ttk.Label(self.top, text = "Email")
        label_new.grid(row = 0, column = 0, padx=(10,0), pady=(20,0))
        self.sms_email = ttk.Entry(self.top, width='34')
        self.sms_email.grid(row = 0, column = 1, padx=(0,10), pady=(20,0))
        self.sms_email.bind("<KeyRelease>", lambda x: self.update_aprsemail())

        label_new = ttk.Label(self.top, text = "Message")
        label_new.grid(row = 1, column = 0, padx=(10,0), pady=(10,0))
        self.sms_msg = ttk.Entry(self.top, width='34')
        self.sms_msg.grid(row = 1, column = 1, padx=(0,10), pady=(10,0))
        self.sms_msg.bind("<KeyRelease>", lambda x: self.update_aprsemail())

        self.sms_cmd = ttk.Entry(self.top)
        self.sms_cmd.grid(row = 2, column = 0, columnspan=2, stick='NSEW', padx=(10,10), pady=(20,0))

        cbframe = ttk.Frame(self.top)
        cbframe.grid(row=3, columnspan=2, sticky='e', padx=10)

        create_button = ttk.Button(cbframe, text = "Send", command = self.proc_aprscmd)
        create_button.grid(row=0, column = 1, padx=(10,0), pady=(20,20))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top.destroy)
        cancel_button.grid(row=0, column = 2, padx=(10,0), pady=(20,20))

        self.top.wait_visibility()
        self.top.grab_set()
        self.sms_email.focus()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Update generated aprs cmd string on keypress
    def update_aprsemail(self):
        email = self.sms_email.get().strip()
        msg = self.sms_msg.get().strip()
        if email=="" or msg=="":
            self.sms_cmd.delete(0,END)
            return
        aprs_cmd = "@APRSIS CMD :EMAIL-2  :"+email+" "+msg+"{01}"
        self.sms_cmd.delete(0,END)
        self.sms_cmd.insert(0,aprs_cmd)

    ## Report grid to APRS system
    def aprs_grid(self):
        self.top = Toplevel(self)
        self.top.title("APRS: Report Grid Location")
        self.top.resizable(width=False, height=False)

        label_new = ttk.Label(self.top, text = "Grid Location")
        label_new.grid(row = 0, column = 0, padx=(10,0), pady=(20,0))
        self.aprs_grid = ttk.Entry(self.top, width='34')
        self.aprs_grid.grid(row = 0, column = 1, padx=(0,10), pady=(20,0))
        self.aprs_grid.bind("<KeyRelease>", lambda x: self.update_aprsgrid())
        self.aprs_grid.insert(0,settings['grid'])

        self.sms_cmd = ttk.Entry(self.top)
        self.sms_cmd.grid(row = 2, column = 0, columnspan=2, stick='NSEW', padx=(10,10), pady=(20,0))

        cbframe = ttk.Frame(self.top)
        cbframe.grid(row=3, columnspan=2, sticky='e', padx=10)

        create_button = ttk.Button(cbframe, text = "Send", command = self.proc_aprscmd)
        create_button.grid(row=0, column = 1, padx=(10,0), pady=(20,20))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top.destroy)
        cancel_button.grid(row=0, column = 2, padx=(10,0), pady=(20,20))

        self.update_aprsgrid()
        self.top.wait_visibility()
        self.top.grab_set()
        self.aprs_grid.focus()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Update generated APRS cmd string on keypress
    def update_aprsgrid(self):
        grid = self.aprs_grid.get().strip()
        if grid=="":
            self.sms_cmd.delete(0,END)
            return
        aprs_cmd = "@APRSIS GRID "+grid
        self.sms_cmd.delete(0,END)
        self.sms_cmd.insert(0,aprs_cmd)

    ## Process (send/tx) APRS cmd
    def proc_aprscmd(self):
        new_cmd = self.sms_cmd.get()
        if new_cmd == "": return
        tx_content = json.dumps({"params":{},"type":"TX.SEND_MESSAGE","value":new_cmd})
        self.sock.send(bytes(tx_content + '\n','utf-8'))
        self.top.destroy()

    def showhelp(self):
        self.top = Toplevel(self)
        self.top.title("JS8Spotter Help")
        self.top.geometry('650x500')

         # display window
        self.help_text = Text(self.top, wrap=NONE)
        help_scrollbar = ttk.Scrollbar(self.top, orient=tk.VERTICAL, command=self.help_text.yview)
        self.help_text.configure(yscroll=help_scrollbar.set)
        help_scrollbar.pack(side=RIGHT, fill='y', padx=(0,10), pady=(10,10))
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

    ## Edit personal settings
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
        cbframe.grid(row=5, columnspan=2, sticky='NSEW', padx=10)

        save_button = ttk.Button(cbframe, text = "Save", command = self.proc_settings_edit)
        save_button.grid(row=0, column = 0, padx=(60,10), pady=(10,10))
        cancel_button = ttk.Button(cbframe, text = "Cancel", command = self.top.destroy)
        cancel_button.grid(row=0, column = 1, pady=(20,20))

        self.top.wait_visibility()
        self.top.grab_set()
        self.top.bind('<Escape>', lambda x: self.top.destroy())

    ## Process TCP settings edit
    def proc_settings_edit(self):
        global settings
        new_addr = self.edit_address.get()
        new_port = self.edit_port.get()
        new_call = self.edit_call.get().upper()
        new_grid = self.edit_grid.get().upper()

        # validate settings
        if new_addr == "" or new_port == "" or new_call == "" or new_grid == "":
            messagebox.showinfo("Error","Please complete all fields", parent=self.top)
            return

        if new_port.isnumeric() == False:
            messagebox.showinfo("Error","Port must be a number (1-9999)", parent=self.top)
            return

        if int(new_port) < 1 or int(new_port) > 9999: #9999 is js8call settings interface limit
            messagebox.showinfo("Error","Port must be between 1 and 9999", parent=self.top)
            return

        if self.check_ip(new_addr) == False:
            messagebox.showinfo("Error","The IP address ("+new_addr+") is formatted incorrectly", parent=self.top)
            return

        # checks passed, save and update
        c.execute("UPDATE setting SET value = ? WHERE name = 'tcp_ip'", [new_addr])
        c.execute("UPDATE setting SET value = ? WHERE name = 'tcp_port'", [new_port])
        c.execute("UPDATE setting SET value = ? WHERE name = 'callsign'", [new_call])
        c.execute("UPDATE setting SET value = ? WHERE name = 'grid'", [new_grid])
        conn.commit()

        settings['tcp_ip']=new_addr
        settings['tcp_port']=new_port
        settings['callsign']=new_call
        settings['grid']=new_grid

        messagebox.showinfo("Updated","Values updated. You must restart JS8Spotter for any TCP changes to take effect")
        self.top.destroy()

    def about(self):
        about_info = swname+" version "+swversion+"\n\nOpen Source, MIT License\nQuestions to Joe, KF7MIX\nwww.kf7mix.com"
        messagebox.showinfo("About "+swname,about_info)

    def check_ip(self, addr):
        octets = addr.split(".")
        if len(octets) != 4: return False
        for octet in octets:
            if not isinstance(int(octet), int): return False
            if int(octet) < 0 or int(octet) > 255: return False
        return True

    ## Minimalistic low resolution timestamp for MCForms (a full timestamp is known when a report is received. year is inferred from that)
    def decode_shorttime(self, ststamp):
        dcst=""

        ma = ord(ststamp[1]) # Month, A-L (1-12)
        m = ""
        if ma>64 and ma<77: m = str(ma-64)

        da = ord(ststamp[2]) # Day, A-Z = 1-26, 0-4 = 27-31
        d = ""
        if da>47 and da<53: d = str((da-47)+26)
        if da>64 and da<91: d = str(da-64)

        ha = ord(ststamp[3]) # Hour, A-W = 0-23
        h=""
        if ha>64 and ha<88: h = str(ha-64)

        ma = ord(ststamp[4]) # Minutes, 2min resolution, A-Z and 0-3 (A=0, B=2, C=4, etc)
        t=""
        if ma>47 and ma<52: t = h+":"+str(((ma-48)+26)*2).zfill(2)
        if ma>64 and ma<91: t = h+":"+str((ma-65)*2).zfill(2)

        if m != "" and d != "" and h !="" and t != "":
            dcst = str(m+"/"+d+" "+t)

        return dcst

    ## Return the current time as an encode short time string
    def encode_shorttime(self):
        ecst=""
        m=chr(time.localtime(time.time())[1]+64)
        da=int(time.localtime(time.time())[2])
        if da<27: d=chr(da+64)
        if da>26: d=chr(da+47)
        h=chr(time.localtime(time.time())[3]+64)
        mi=chr(int(time.localtime(time.time())[4]/2)+1+64)
        ecst = "#"+m+d+h+mi
        return ecst

    ## Update status bar in main window based on certain activities
    def update_statusbar(self):
        global totals

        c.execute("SELECT count(*) FROM expect WHERE lm > DATETIME('now', '-5 second')")
        totals[1]+=c.fetchone()[0]

        c.execute("SELECT count(*) FROM forms WHERE lm > DATETIME('now', '-5 second')")
        totals[2]+=c.fetchone()[0]

        stupdate="Status: TCP Active "
        if totals[1]>0: stupdate+="[EXPECT Updated] "
        if totals[2]>0: stupdate+="[FORM RESPONSES Updated] "

        self.statusbar.config(text=stupdate)

    ## Watch activity thread, update gui as needed
    def poll_activity(self):
        if event.is_set():
            self.refresh_activity_tree()
            self.refresh_keyword_tree()
            self.update_statusbar()
            event.clear()
        super().after(2000,self.poll_activity)

    def start_receiving(self):
        self.receiver = TCP_RX(self.sock)
        self.receiver.start()

    def stop_receiving(self):
        self.receiver.stop()
        self.receiver.join()
        self.receiver = None

    ## Quit function, close the recv thread, database connection, and main gui window
    def menu_bye(self):
        conn.close()
        self.stop_receiving()
        self.destroy()

    def mainloop(self, *args):
        super().mainloop(*args)
        if self.receiver: self.receiver.stop()

def main():
    ## Check for tcp connection
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((settings['tcp_ip'], int(settings['tcp_port'])))
    except ConnectionRefusedError:
        sock = None # we'll provide the connection error after the gui loads

    app = App(sock)
    app.mainloop()

if __name__ == '__main__':
    main()
