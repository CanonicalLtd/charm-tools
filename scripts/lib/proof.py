#!/usr/bin/python
#
#    proof - makes sure charms follow conventions
#
#    Copyright (C) 2011  Canonical Ltd.
#    Author: Clint Byrum <clint.byrum@canonical.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import os.path as path
import os,sys
from stat import *
import yaml
import re
import email.utils
import argparse

exit_code = 0

KNOWN_METADATA_KEYS = [ 'name',
                        'summary',
                        'maintainer',
                        'description',
                        'subordinate',
                        'provides',
                        'requires',
                        'format',
                        'peers' ]

KNOWN_RELATION_KEYS = [ 'interface',
                        'scope',
                        'limit',
                        'optional' ]

KNOWN_SCOPES = [ 'global',
                 'container' ]

TEMPLATE_README = os.path.abspath(
        os.path.join(__file__, '..', '..', 'templates', 'charm', 'README.ex'))

class RelationError(Exception):
    pass

def crit(msg):
  """ Called when checking cannot continue """
  global exit_code
  err("FATAL: " + msg)
  sys.exit(exit_code)

def err(msg):
  global exit_code
  print "E: " + msg
  if exit_code < 200:
    exit_code = 200

def info(msg):
  """ Ignorable but sometimes useful """
  print "I: " + msg


parser = argparse.ArgumentParser(
        description='Performs static analysis on charms')
parser.add_argument('charm_name', nargs='?',
        help='path of charm dir to check. Defaults to PWD')
args = parser.parse_args()

if args.charm_name:
    charm_name = args.charm_name
else:
    charm_name = os.getcwd()

if os.path.isdir(charm_name):
    charm_path = charm_name
else:
    charm_home = os.getenv('CHARM_HOME','.')
    charm_path = path.join(charm_home,charm_name)

if not os.path.isdir(charm_path):
    crit("%s is not a directory, Aborting" % charm_path)
    sys.exit(1)

yaml_path = path.join(charm_path, 'metadata.yaml')
hooks_path = path.join(charm_path, 'hooks')

hook_warnings = [{'re' : re.compile("http://169\.254\.169\.254/"), 
                  'msg': "hook accesses EC2 metadata service directly"}]

def check_hook(hook, required=True, recommended=False):
  global hooks_path

  hook_path = path.join(hooks_path,hook)
  try:
    mode = os.stat(hook_path)[ST_MODE]
    if not mode & S_IXUSR:
      warn(hook + " not executable")
    with open(hook_path, 'r') as hook_file:
      count = 0
      for line in hook_file:
        count += 1
        for warning in hook_warnings:
          if warning['re'].search(line):
            warn("(%s:%d) - %s" % (hook,count,warning['msg']))
    return True
  except OSError as e:
    if required:
        err("missing hook "+hook)
    elif recommended:
        warn("missing recommended hook "+hook)
    return False

def check_relation_hooks(relations, subordinate):
  template_interfaces = ('interface-name')
  template_relations = ('relation-name')

  for r in relations.items():
    if type(r[1]) != dict:
      err("relation %s is not a map" % (r[0]))
    else:
      if 'scope' in r[1]:
        scope = r[1]['scope']
        if scope not in KNOWN_SCOPES:
          err("Unknown scope found in relation %s - (%s)" % (r[0], scope))
      if 'interface' in r[1]:
        interface = r[1]['interface']
        if interface in template_interfaces:
          err("template interface names should be changed: "+interface)
      else:
        err("relation missing interface")
      for key in r[1].keys():
        if key not in KNOWN_RELATION_KEYS:
          err("Unknown relation field in relation %s - (%s)" % (r[0], key))

    r = r[0]

    if r in template_relations:
      err("template relations should be renamed to fit charm: "+r)

    has_one = False
    has_one = has_one or check_hook(r+'-relation-changed', required=False)
    has_one = has_one or check_hook(r+'-relation-departed', required=False)
    has_one = has_one or check_hook(r+'-relation-joined', required=False)
    has_one = has_one or check_hook(r+'-relation-broken', required=False)

    if not has_one and not subordinate:
        info("relation "+r+" has no hooks")


def warn(msg):
  global exit_code
  print "W: " + msg
  if exit_code < 100:
    exit_code = 100 

try:
  yamlfile= open(yaml_path,'r')
  try:
    charm = yaml.load(yamlfile)
  except Exception as e:
    crit('cannot parse ' + yaml_path + ":" + str(e))

  yamlfile.close()

  for key in charm.keys():
    if key not in KNOWN_METADATA_KEYS:
      err("Unknown root metadata field (%s)" % key)

  charm_basename = path.basename(charm_path)
  if charm['name'] != charm_basename:
    warn("metadata name (%s) must match directory name (%s) exactly for local deployment." % (charm['name'], charm_basename))

  # summary should be short
  if len(charm['summary']) > 72:
    warn('summary sould be less than 72') 

  # need a maintainer field
  if 'maintainer' not in charm:
    err('Charms need a maintainer (See RFC2822) - Name <email>')
  else:
    if type(charm['maintainer']) == list:  # It's a list
        maintainers = charm['maintainer']
    else:
        maintainers = [charm['maintainer']]
    for maintainer in maintainers:
        (name, address) = email.utils.parseaddr(maintainer)
        formatted = email.utils.formataddr((name, address))
        if formatted != maintainer:
            warn("Maintainer address should contain a real-name and email only. [%s]" % (formatted))

  # Must have a hooks dir
  if not path.exists(hooks_path):
    err("no hooks directory")

  # Must have a copyright file
  if not path.exists(path.join(charm_path,'copyright')):
    err("no copyright file")

  # should have a readme
  root_files = os.listdir(charm_path)
  found_readmes = set()
  for filename in root_files:
    if filename.upper().find('README') != -1:
      found_readmes.add(filename)
  if len(found_readmes):
    if 'README.ex' in found_readmes:
      err("Includes template README.ex file")
    try:
      with open(TEMPLATE_README) as tr:
        bad_lines = []
        for line in tr:
          if len(line) >= 25:
            bad_lines.append(line.strip())
        for readme in found_readmes:
          readme_path = os.path.join(charm_path, readme)
          with open(readme_path) as r:
            readme_content = r.read()
            lc = 0
            for l in bad_lines:
              if not len(l):
                continue
              lc += 1
              if l in readme_content:
                err("%s Includes boilerplate README.ex line %d" % (readme, lc))
    except IOError, e:
      err("Error while opening %s (%s)" % (e.filename, e.strerror))
  else:
    warn("no README file")

  subordinate = charm.get('subordinate', False)
  if type(subordinate) != bool:
    err("subordinate must be a boolean value")
  
  # All charms should provide at least one thing
  try:
    provides = charm['provides']  
    check_relation_hooks(provides, subordinate)
  except KeyError:
    if not subordinate:
        warn("all charms should provide at least one thing")

  if subordinate:
    try:
        if 'requires' in charm:
            requires = charm['requires']
            found_scope_container = False
            for rel_name, rel in requires.iteritems():
                if 'scope' in rel:
                    if rel['scope'] == 'container':
                        found_scope_container = True
                        break
            if not found_scope_container:
                raise RelationError
        else:
            raise RelationError
    except RelationError:
        err("subordinates must have at least one scope: container relation")
  else:
      try:
        requires = charm['requires']
        check_relation_hooks(requires, subordinate)
      except KeyError:
            pass

  try:
    peers = charm['peers']
    check_relation_hooks(peers, subordinate)
  except KeyError:
    pass

  if 'revision' in charm:
    warn("Revision should not be stored in metadata.yaml anymore. Move it to the revision file")
    # revision must be an integer
    try:
      x = int(charm['revision'])
      if x < 0:
        raise ValueError
    except (TypeError, ValueError):
      warn("revision should be a positive integer")

  check_hook('install')
  check_hook('start', required=False, recommended=True)
  check_hook('stop', required=False, recommended=True)
  check_hook('config-changed', required=False)
except IOError:
  err("could not find metadata file for " + charm_name)
  exit_code = -1

rev_path = os.path.join(charm_path, 'revision')
if not path.exists(rev_path):
  err("revision file in root of charm is required")
else:
  with open(rev_path, 'r') as rev_file:
      content = rev_file.read().rstrip()
      try:
          rev = int(content)
      except ValueError:
          err("revision file contains non-numeric data")

sys.exit(exit_code)
