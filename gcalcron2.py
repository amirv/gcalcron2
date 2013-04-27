#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#    gcalcron v2.0
#
#    Copyright Fabrice Bernhard 2011
#    fabriceb@theodo.fr
#    www.theodo.fr

#import gdata.calendar.service
import os
import sys
import stat
import json
import datetime
import dateutil.parser
from dateutil.tz import gettz
import time
import subprocess
import re

import simplejson as json


from apiclient.discovery import build
#from apiclient.oauth import OAuthCredentials

import httplib2
#import oauth2 as oauth

DEBUG = os.environ.get('DEBUG')


import gflags
import httplib2

from apiclient.discovery import build
from oauth2client.file import Storage
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.tools import run


class GCalAdapter:
  """
  Adapter class which communicates with the Google Calendar API
  @since 2011-06-19
  """

  application_name = 'Theodo-gCalCron-2.0'
  service = None
  cal_id = None


  def __init__(self, cal_id=None, service=None):
    self.cal_id = cal_id
    self.service = self.fetch_service()

  def fetch_service(self):
    """
    Fetches the Google Calendar API token using email and password
    @author Fabrice Bernhard
    @since 2011-06-13
    """

    FLAGS = gflags.FLAGS

    FLOW = OAuth2WebServerFlow(
        client_id='597481446202-mq48ae25hvplot50ga5ll6rh9q0s9kh1.apps.googleusercontent.com',
        client_secret='F7-GqngW3KHAMWz2N3WpyuWV',
        scope='https://www.googleapis.com/auth/calendar.readonly',
        user_agent='IrrigationDaemon')

# To disable the local server feature, uncomment the following line:
    FLAGS.auth_local_webserver = False

    storage = Storage(os.path.dirname(sys.argv[0]) + '/calendar.dat')
    credentials = storage.get()
    if credentials is None or credentials.invalid == True:
      credentials = run(FLOW, storage)

    http = httplib2.Http()
    http = credentials.authorize(http)

    service = build(serviceName='calendar', version='v3', http=http,
                  developerKey='YOUR_DEVELOPER_KEY')

    return service


  def get_query(self, start_min, start_max, updated_min=None):
    """
    Builds the Google Calendar query with default options set

    >>> g = GCalAdapter()
    >>> g.cal_id = 'login@gmail.com'
    >>> g.get_query(datetime.datetime(2011, 6, 19, 14, 0), datetime.datetime(2011, 6, 26, 14, 0), datetime.datetime(2011, 6, 18, 14, 0))
    {'start-max': '2011-06-26T06:00:00', 'max-results': '1000', 'singleevents': 'true', 'ctz': 'UTC', 'updated-min': '2011-06-18T06:00:00', 'start-min': '2011-06-19T06:00:00'}

    @author Fabrice Bernhard
    @since 2011-06-19
    """

    if DEBUG: print 'Setting up query: %s to %s modified after %s' % (start_min.isoformat(), start_max.isoformat(), updated_min)

    updatedMin = None
    if updated_min:
        updatedMin = updated_min.isoformat('T')

    query = self.service.events().list(calendarId=self.cal_id,
            maxResults=1000, showDeleted=True, singleEvents=True,
            timeMin= start_min.isoformat('T'),
            timeMax= start_max.isoformat('T'),
            updatedMin = updatedMin)

    return query


  def get_events(self, last_sync = None, num_days = datetime.timedelta(days=7)):
    """
    Gets a list of events to sync
     - events between now and last_sync + num_days which have been updated since last_sync
     - new events between last_sync + num_days and now + num_days
    @author Fabrice Bernhard
    @since 2011-06-13
    """

    queries = []
    entries = []
    now = datetime.datetime.now(gettz())
    end = now + num_days
    if last_sync:
      queries.append(self.get_query(now, last_sync + num_days, last_sync))
      queries.append(self.get_query(last_sync + num_days, end))
    else:
      queries.append(self.get_query(now, end))

    # Query the automation calendar.
    if DEBUG: print 'Submitting query: '

    e = []
    for query in queries:
        try:
            events = query.execute()
        except Exception as e:
            print "Google error:", e.message
            print "If you changed your password, run python gcalcron2.py --init "
            exit()
        except service.RequestError as e:
            print "Google error:", e.message['reason']
            print "If you changed your password, run python gcalcron2.py --init "
            if DEBUG: raise
            exit()

        if DEBUG: print 'Query results received'

        for event in events.get('items', []):
            if DEBUG:
                print "Event details:"
                for k in event.keys():
                    print "\t", k, " : ", event[k]

            start_time = dateutil.parser.parse(event['start']['dateTime']).replace(tzinfo=None)
	    end_time   = dateutil.parser.parse(event['end']['dateTime']).replace(tzinfo=None)
	    event_id = event['id']
	    if DEBUG:
	        print event_id, '-', event['status'], '-', event['updated'], ': ', event['summary'], start_time, ' -> ', end_time, ' (', event['start']['dateTime'], ' -> ', event['end']['dateTime'], ') ', '=>', event.get('description', "None")
	    if event['status'] == 'cancelled':
	        if DEBUG:
		    print "CANCELLED", event_id
		e.append({
		  'uid': event_id
		})
	    elif event['description']:
	        commands = self.parse_commands(event['description'], start_time, end_time)
	        if commands:
		    e.append({
		        'uid': event_id,
		        'commands': commands
		        })

    return (e, now)

  def parse_commands(self, event_description, start_time, end_time):
    """
    Parses the description of a Google calendar event and returns a list of commands to execute

    >>> g = GCalAdapter()
    >>> g.parse_commands("echo 'Wake up!'\\n+10: echo 'Wake up, you are 10 minutes late!'", datetime.datetime(3011, 6, 19, 8, 30), datetime.datetime(3011, 6, 19, 9, 0))
    [{'exec_time': datetime.datetime(3011, 6, 19, 8, 30), 'command': "echo 'Wake up!'"}, {'exec_time': datetime.datetime(3011, 6, 19, 8, 40), 'command': "echo 'Wake up, you are 10 minutes late!'"}]

    >>> g.parse_commands("Turn on lights\\nend -10: Dim lights\\nend: Turn off lights", datetime.datetime(3011, 6, 19, 18, 30), datetime.datetime(3011, 6, 19, 23, 0))
    [{'exec_time': datetime.datetime(3011, 6, 19, 18, 30), 'command': 'Turn on lights'}, {'exec_time': datetime.datetime(3011, 6, 19, 22, 50), 'command': 'Dim lights'}, {'exec_time': datetime.datetime(3011, 6, 19, 23, 0), 'command': 'Turn off lights'}]


    @author Fabrice Bernhard
    @since 2011-06-13
    """

    commands = []
    for command in event_description.split("\n"):
      exec_time = start_time
      # Supported syntax for offset prefixes:
      #   '[+-]10: ', 'end:', 'end[+-]10:', 'end [+-]10:'
      offset_match = re.compile('^(end)? ?([\+,-]\d+)?: (.*)').search(command)
      if offset_match:
        if offset_match.group(1):
          exec_time = end_time
        if offset_match.group(2):
          exec_time += datetime.timedelta(minutes=int(offset_match.group(2)))
        command = offset_match.group(3)

      command = command.strip()
      if command:
        if exec_time >= datetime.datetime.now():
          commands.append({
              'command': command,
              'exec_time': exec_time
            })
        elif DEBUG: print 'Ignoring command that was scheduled for the past'
      elif DEBUG: print 'Blank command'

    return commands


class GCalCron2:
  """
  Schedule your cron commands in a dedicated Google Calendar,
  this class will convert them into UNIX "at" job list and keep
  them synchronised in case of updates

  @author Fabrice Bernhard
  @since 2011-06-13
  """

  settings = None
  settings_file = "/export/data/projects/GCalCron2" + '/' + '.gcalcron2'
  #settings_file = os.getenv('HOME') + '/' + '.gcalcron2'


  def __init__(self, load_settings=True):
    if load_settings:
      self.load_settings()


  def load_settings(self):
    with open(self.settings_file) as f:
      self.settings = json.load(f)


  def save_settings(self):
    with open(self.settings_file, 'w') as f:
      json.dump(self.settings, f, indent=2)
    # protect the settings fie, since it contains the OAuth login token
    os.chmod(self.settings_file, stat.S_IRUSR + stat.S_IWUSR)


  def init_settings(self, email, password, cal_id):
    gcal_adapter = GCalAdapter()
    service = gcal_adapter.fetch_service()
    self.settings = {
      "jobs": {},
      "google_calendar": {
        "service": service,
        "cal_id": cal_id
      },
      "last_sync": None
    }


  def clean_settings(self):
    """Cleans the settings from saved jobs in the past"""

    for event_uid, job in self.settings['jobs'].items():
      if datetime.datetime.strptime(job['date'], '%Y-%m-%d') <= datetime.datetime.now() - datetime.timedelta(days=1):
        del self.settings['jobs'][event_uid]

  def reset_settings(self):
    for event, job in self.settings['jobs'].items():
      command = ['at', '-d'] + job['ids']
      if DEBUG: print ' '.join(command)
      subprocess.Popen(command)
    self.settings['last_sync'] = None
    self.settings['jobs'] = {}
    self.save_settings()


  def unschedule_old_jobs(self, events):
        removed_job_ids = []
        for event in events:
            if event['uid'] in self.settings['jobs']:
                removed_job_ids += self.settings['jobs'][event['uid']]['ids']
                del self.settings['jobs'][event['uid']]
            if len(removed_job_ids) > 0:
                if DEBUG: print ' '.join(['at', '-d'] + removed_job_ids)
                subprocess.Popen(['at', '-d'] + removed_job_ids)

  def schedule_new_jobs(self, events):
    for event in events:
      if not 'commands' in event:
        continue

      for command in event['commands']:
        if command['exec_time'] <= datetime.datetime.now():
          continue

        if DEBUG: print "at "+ datetime_to_at(command['exec_time'])

        p = subprocess.Popen(['at', '-m', datetime_to_at(command['exec_time'])], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        (_, output) = p.communicate(command['command'])

        if DEBUG: print "  " + output

        job_id_match = re.compile('job (\d+) at').search(output)

        if job_id_match:
          job_id = job_id_match.group(1)

        if event['uid'] in self.settings['jobs']:
          self.settings['jobs'][event['uid']]['ids'].append(job_id)
        else:
          self.settings['jobs'][event['uid']] = {
            'date': command['exec_time'].strftime('%Y-%m-%d'),
            'ids': [job_id, ]
          }


  def sync_gcal_to_cron(self, num_days = datetime.timedelta(days=7), verbose = True):
    """
    - fetches a list of commands through the GoogleCalendar adapter
    - schedules them for execution using the unix "at" command
    - stores their job_id in case of later modifications
    - deletes eventual cancelled jobs

    @author Fabrice Bernhard
    @since 2011-06-13
    """

    last_sync = None
    if self.settings['last_sync']:
      last_sync = dateutil.parser.parse(self.settings['last_sync'])

    gcal_adapter = GCalAdapter(self.settings['google_calendar']['cal_id'], self.settings['google_calendar']['service'])

    (events, last_sync) = gcal_adapter.get_events(last_sync, num_days)

    # first unschedule all modified/deleted events
    self.unschedule_old_jobs(events)

    # then reschedule all modified/new events
    self.schedule_new_jobs(events)

    # clean old jobs from the settings
    self.clean_settings()

    self.settings['last_sync'] = str(last_sync)
    self.save_settings()


def datetime_to_at(dt):
  """
  >>> datetime_to_at(datetime.datetime(2011, 6, 18, 12, 0))
  '12:00 Jun 18'
  """
  return dt.strftime('%H:%M %h %d')


def init():
    email = raw_input('Google email: ')
    password = raw_input('Google password: ')
    cal_id = raw_input('Calendar id (in the form of XXXXX....XXXX@group.calendar.google.com or for the main one just your Google email): ')
    g = GCalCron2(load_settings=False)
    g.init_settings(email, password, cal_id)
    g.save_settings()
    return g

if __name__ == '__main__':
  if '--init' in sys.argv:
    init()

  try:
    g = GCalCron2()
  except IOError:
    g = init()

  if '--reset' in sys.argv:
    g.reset_settings()
  else:
    g.sync_gcal_to_cron()
