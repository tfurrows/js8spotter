# JS8Spotter MIT License, Joe Lyman KF7MIX
# You should have received a copy of the source and license with the program
# Special thanks to KE0DHO, KF0HHR, KQ4DRG, N4FWD, and N0GES, for help in
# development

# Overview

A JS8Call API mechanism to track activity containing specific search
terms, including callsigns or other activity. Matches on RX.ACTIVITY,
RX.DIRECTED, and RX.SPOT only. Tested with JS8Call v2.2.0


# Settings

JS8Spottter requires the TCP API in JS8Call. To turn it on, go to JS8Call, enter
the "File>Settings" menu, then go to the "Reporting" tab, and enable the
following three checkmarks:

* Allow setting station information
* Enable TCP Server API
* Accept TCP Requests

If you change port or IP from the default, TCP address and port settings for
JS8Spotter may be modified in the application file menu.

Make sure to set your callsign and grid in the application file menu when
running the software for the first time.


# Usage

JS8Spotter is designed to help you keep track of specific, desired traffic as it
passes through JS8Call. From within JS8Call itself, you can access all traffic
via the ALL.TXT log file. JS8Spotter simply provides a method to sort out some
of this traffic as it comes in, and view the traffic in a quick and organized
way.

## Starting the Program

Make sure to start JS8Spotter only after running the JS8Call application, as it
needs to connect to JS8Call in order to function properly. Starting JS8Spotter
first may result in undesired behavior.

## Profiles

A profile in JS8Call is a container where you keep a collection of specific
search terms.

   Example 1: You run a net for your stamp collecting group, with the JS8Call
              group name @STAMPS. You create a profile named "@STAMPS", and
              add search terms for each callsign in the roster, a keyword for
              the group name "@STAMPS", plus several keywords relating to the
              group.

   Example 2: You have a group of close friends who you see on the air often.
              You create a profile named "Contacts" and populate it with search
              terms for each of their callsigns.

   Example 3: You participate in @JS8CHESS. You create a "Chess" profile, and
              populate it with the search term "CHESS" to capture all traffic
              that mentions chess (including anything with "@JS8CHESS". You
              also include search terms for each of the callsigns you are
              playing games with.

JS8Spotter's database file comes with a single profile named "Default". You may
rename this profile to whatever you wish. It may be deleted only after adding
additional profiles.

## Search Terms

As JS8Call runs, it provides decoded activity on the TCP network port.
JS8Spotter watches that traffic, and looks for keywords / search terms that you
provide in each of your profiles. When it finds a match, it saves that traffic
to your specific log (and to a database on the back-end.) The latest 100 entries
are visible at any time, older entries are also visible in the export window
or in the database.

Search terms can be anything you like. They can be a single letter, a word, a
callsign, a JS8Call command, or multiple words.

   Example 1: You have a "Testing" profile, where you track random things that
              are happening on the waterfall. In it, you create a "MSG" search
              term, which lets you capture and save all MSG traffic as it goes
              by. Later, you can look back at any MSGs that were sent. You add
              ">" to your search terms, so you can capture any relays, even if
              they weren't MSG relays.

   Example 2: You are curious about station info, but don't want to always be
              the one requesting it. You create a "Stations" profile, and add
              the search terms "INFO" and "STATUS".

   Example 3: You're part of an emcomm group, and you know that several of the
              group members use JS8Call. You create a profile just for them, and
              add the full roster of callsigns as individual search terms, so
              you can get a feel for when your fellow group members are on the
              air.

## Background Scanning

If enabled, background scanning allows profiles to scan even when the profile is
not actively selected. If disabled, a profile will only record activity when
selected/active.

Background scanning is disabled by default, and may be enabled with the checkbox
at the top-right of each profile. The background scanning setting is set on a
per-profile basis. Settings are retained when the program is closed.

   Example 1: You have a "Testing" profile, which gathers a lot of data. You
              don't want to gather it all the time, only when you are testing,
              so you uncheck the box for that profile.

   Example 2: You don't ever want to miss any JS8CHESS traffic, so you enable
              background scanning on that profile.

   Example 3: Your @STAMPS net is once a month, and you don't need to track
              it except when the net is active. You leave background scanning
              disabled on that profile.

   Example 4: Your want to always know when your friends are around, so you
              keep your "Contacts" profile active with background scanning on.

## User Interface

### Main Window

* The profile drop-down will let you quickly switch between your profiles
* The "Search Term" and "Matched Activity" panes show the corresponding data
* The "Matched Activity" pane only shows the latest 100 entries
* You may double-click on individual search terms or activity for details
* An entry box at the bottom-left allows you to add new search terms
* The "Remove Selected" button allows you to remove the highlighted search term
* The "Export Log" button brings up the export window
* The "Clear Log" button deletes ALL activity entries for the current profile
* Menu actions hopefully perform as labeled

## Export Log Window

The export log window shows all database entries for activity, for the current
profile. The data is tab-delimited. Highlight and copy what you wish, and
paste it into a spreadsheet for easy access. Or, use the "Copy All" or "Save As"
buttons.

## Export Search Terms Window

Allows you to copy/save your search terms, as a backup or to share with others.

## Import Search Terms Window

Allows you to import previously saved search terms, or enter search terms in
bulk, line by line.

## Hide Heartbeats Menu Item

The "Hide Heartbeats" View menu item allows you to hide/show items in the
Matched Activity pane that contain the words "HB" or "Heartbeat". These items
are still retained in the database, they are simply hidden on the screen when
this option is selected. This option is not profile specific. This setting is
retained when the program is closed.

## Map Window

Provides a simple offline maidenhead grid map of the latest 100 contacts.

## Expect Window

The Expect subsystem allows you to specific text that your station "expects" to
see, along with a response that your station will send automatically if the
expected text is found. All expect commands are prefixed with "E?". You may
specify which stations or groups may trigger a response, and you may specify
how many times your station will respond to a single expect.

See the in-program help for more details.

## APRS Commands

JS8Call supports APRSIS gateway commands. The APRS options in the Tools menu
help you format these commands for easy and quick use. Use them for sending
an SMS text, an email, or reporting your grid location.

# Support

I'm a hobbyist programmer, and I've done very little GUI programming. Keep it
in mind.

The software is free, but I'd be happy to lend a hand with it as needed. Contact
KF7MIX via the information on QRZ.com with questions.


73, Joe KF7MIX