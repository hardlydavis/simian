#!/usr/bin/env python
# 
# Copyright 2010 Google Inc. All Rights Reserved.
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# #

"""Module containing url handler for report calculation.

Classes:
  ReportsCache: the url handler
"""



import datetime
import logging
import os
import time
from google.appengine.ext import deferred
from google.appengine.ext import webapp
from google.appengine.api import taskqueue
from simian.mac import models
from simian.mac.admin import summary as summary_module




class ReportsCache(webapp.RequestHandler):
  """Class to cache reports on a regular basis."""

  USER_EVENTS = [
      'launched',
      'install_with_logout',
      'install_without_logout',
      'cancelled',
      'exit_later_clicked',
      'exit_installwithnologout',
      'conflicting_apps'
  ]

  FETCH_LIMIT = 500

  def get(self, name=None, arg=None):
    """Handle GET"""

    if name == 'summary':
      summary = summary_module.GetComputerSummary()
      models.ReportsCache.SetStatsSummary(summary)
    elif name == 'installcounts':
      _GenerateInstallCounts()
    elif name == 'pendingcounts':
      self._GeneratePendingCounts()
    elif name == 'msu_user_summary':
      if arg:
        try:
          kwargs = {'since_days': int(arg)}
        except ValueError:
          kwargs = {}
      else:
        kwargs = {}
      self._GenerateMsuUserSummary(**kwargs)
    else:
      logging.warning('Unknown ReportsCache cron requested: %s', name)
      self.response.set_status(404)

  def _GenerateMsuUserSummary(self, since_days=None, now=None):
    """Generate summary of MSU user data.

    Args:
      since_days: int, optional, only report on the last x days
      now: datetime.datetime, optional, supply an alternative
        value for the current date/time
    """
    # TODO: when running from a taskqueue, this value could be higher.
    RUNTIME_MAX_SECS = 15

    cursor_name = 'msu_user_summary_cursor'

    if since_days is None:
      since = None
    else:
      since = '%dD' % since_days
      cursor_name = '%s_%s' % (cursor_name, since)

    interested_events = self.USER_EVENTS

    lquery = models.ComputerMSULog.all()
    cursor = models.KeyValueCache.MemcacheWrappedGet(
        cursor_name, 'text_value')
    summary = models.ReportsCache.GetMsuUserSummary(
        since=since, tmp=True)

    if cursor and summary:
      lquery.with_cursor(cursor)
      summary = summary[0]
    else:
      summary = {}
      for event in interested_events:
        summary[event] = 0
      summary['total_events'] = 0
      summary['total_users'] = 0
      summary['total_uuids'] = 0
      models.ReportsCache.SetMsuUserSummary(
          summary, since=since, tmp=True)

    begin = time.time()
    if now is None:
      now = datetime.datetime.utcnow()

    while True:
      reports = lquery.fetch(self.FETCH_LIMIT)
      if not reports:
        break

      userdata = {}
      last_user = None
      last_user_cursor = None
      prev_user_cursor = None

      n = 0
      for report in reports:
        userdata.setdefault(report.user, {})
        userdata[report.user].setdefault(
            report.uuid, {}).update(
                {report.event: report.mtime})
        if last_user != report.user:
          last_user = report.user
          prev_user_cursor = last_user_cursor
          last_user_cursor = str(lquery.cursor())
        n += 1

      if n == self.FETCH_LIMIT:
        # full fetch, might not have finished this user -- rewind
        del(userdata[last_user])
        last_user_cursor = prev_user_cursor

      for user in userdata:
        events = 0
        for uuid in userdata[user]:
          if 'launched' not in userdata[user][uuid]:
            continue
          for event in userdata[user][uuid]:
            if since_days is None or IsTimeDelta(
                userdata[user][uuid][event], now, days=since_days):
              summary.setdefault(event, 0)
              summary[event] += 1
              summary['total_events'] += 1
              events += 1
          if events:
            summary['total_uuids'] += 1
        if events:
          summary['total_users'] += 1
          summary.setdefault('total_users_%d_events' % events, 0)
          summary['total_users_%d_events' % events] += 1

      lquery = models.ComputerMSULog.all()
      lquery.with_cursor(last_user_cursor)

      end = time.time()
      if (end - begin) > RUNTIME_MAX_SECS:
        break

    if reports:
      models.ReportsCache.SetMsuUserSummary(
          summary, since=since, tmp=True)
      models.KeyValueCache.MemcacheWrappedSet(
          cursor_name, 'text_value', last_user_cursor)
      if since_days:
        args = '/%d' % since_days
      else:
        args = ''
      taskqueue.add(
          url='/cron/reports_cache/msu_user_summary%s' % args,
          method='GET',
          countdown=5)
    else:
      models.ReportsCache.SetMsuUserSummary(
          summary, since=since)
      models.KeyValueCache.ResetMemcacheWrap(cursor_name)
      summary_tmp = models.ReportsCache.DeleteMsuUserSummary(
          since=since, tmp=True)

  def _GeneratePendingCounts(self):
    """Generates a dictionary of all install names and their pending count."""
    d = {}
    for p in models.PackageInfo.all():
      d[p.munki_name] = models.Computer.AllActive(keys_only=True).filter(
          'pkgs_to_install =', p.munki_name).count(999999)
    models.ReportsCache.SetPendingCounts(d)


def _GenerateInstallCounts():
    """Generates a dictionary of all installs names and the count of each."""
    #logging.debug('Generating install counts....')

    # Obtain a lock.
    lock = models.KeyValueCache.get_by_key_name('pkgs_list_cron_lock')
    utcnow = datetime.datetime.utcnow()
    if not lock or lock.mtime < (utcnow - datetime.timedelta(minutes=30)):
      # There is no lock or it's old so continue.
      lock = models.KeyValueCache(key_name='pkgs_list_cron_lock')
      lock.put()
    else:
      logging.warning('GenerateInstallCounts: lock found; exiting.')
      return

    # Get a list of all packages that have previously been pushed.
    pkgs, unused_dt = models.ReportsCache.GetInstallCounts()

    # Generate a query of all InstallLog entites that haven't been read yet.
    query = models.InstallLog.all().order('server_datetime')
    cursor_obj = models.KeyValueCache.get_by_key_name('pkgs_list_cursor')
    if cursor_obj:
      query.with_cursor(cursor_obj.text_value)
      #logging.debug('Continuing with cursor: %s', cursor_obj.text_value)

    # Loop over new InstallLog entries.
    installs = query.fetch(1000)
    if not installs:
      #logging.debug('No more installs to process.')
      models.ReportsCache.SetInstallCounts(pkgs)
      lock.delete()
      return

    i = 0
    for install in installs:
      i += 1
      pkg_name = install.package
      if pkg_name not in pkgs:
        pkgs[pkg_name] = {
            'install_count': 0,
            'install_fail_count': 0,
            'applesus': install.applesus,
        }
      if install.IsSuccess():
        pkgs[pkg_name]['install_count'] = (
            pkgs[pkg_name].setdefault('install_count', 0) + 1)
      else:
        pkgs[pkg_name]['install_fail_count'] = (
            pkgs[pkg_name].setdefault('install_fail_count', 0) + 1)

      # (re)calculate avg_duration_seconds for this package.
      if 'duration_seconds_avg' not in pkgs[pkg_name]:
        pkgs[pkg_name]['duration_count'] = 0
        pkgs[pkg_name]['duration_total_seconds'] = 0
        pkgs[pkg_name]['duration_seconds_avg'] = None
      # only proceed if entity has "duration_seconds" property that's not None.
      if getattr(install, 'duration_seconds', None) is not None:
        pkgs[pkg_name]['duration_count'] += 1
        pkgs[pkg_name]['duration_total_seconds'] += (
            install.duration_seconds)
        pkgs[pkg_name]['duration_seconds_avg'] = int(
            pkgs[pkg_name]['duration_total_seconds'] /
            pkgs[pkg_name]['duration_count'])

    # Update any changed packages.
    models.ReportsCache.SetInstallCounts(pkgs)
    #logging.debug('Processed %d installs and saved to ReportsCache.', i)

    if not cursor_obj:
      cursor_obj = models.KeyValueCache(key_name='pkgs_list_cursor')

    cursor_txt = str(query.cursor())
    #logging.debug('Saving new cursor: %s', cursor_txt)
    cursor_obj.text_value = cursor_txt
    cursor_obj.put()

    # Delete the lock.
    lock.delete()

    deferred.defer(_GenerateInstallCounts)


def IsTimeDelta(dt1, dt2, seconds=None, minutes=None, hours=None, days=None):
  """Returns delta if datetime values are within a time period.

  Note that only one unit argument may be used at once because of a
  limitation in the way that we process the delta units (only in seconds).

  Args:
    dt1: datetime obj, datetime value 1 to compare
    dt2: datetime obj, datetime value 2 to compare
    seconds: int, optional, within seconds   OR
    minutes: int, optional, within minutes   OR
    hours: int, optional, within minutes     OR
    days: int, optional, without days
  Returns:
    None or datetime.timedelta object
  """
  delta = abs(dt2 - dt1)
  if days is not None:
    dseconds = days * 86400
  elif hours is not None:
    dseconds = hours * 3600
  elif minutes is not None:
    dseconds = minutes * 60
  elif seconds is not None:
    dseconds = seconds
  else:
    return

  if ((delta.days * 86400) + delta.seconds) <= dseconds:
    return delta