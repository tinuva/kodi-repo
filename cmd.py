#!/usr/bin/env python3

import os
import sys
import re
import shutil
import datetime
import zipfile
import hashlib

from subprocess import check_output
from distutils.version import StrictVersion
from lxml import etree as ET

default_meta = {
    'license': 'GNU General Public License, v2',
    'website': 'https://www.matthuisman.nz',
}

PROVIDER    = 'MattHuisman.nz'
ROOT_DIR    = '.'
ADDON_XML   = 'addon.xml'
SRC_DIR     = 'src'
ADDONS_XML  = 'addons.xml'
BRANCH      = 'master'
LOG_CHANGES = 5
IGNORES = ('__pycache__', '.git*', '*.pyc', '*.pyo', 'test.py', '*.psd', '*.code-workspace', '.vscode*')

def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_addons():
    addons = []

    for folder in os.listdir(ROOT_DIR):
        if folder == '.git':
            continue

        folder_path = os.path.join(ROOT_DIR, folder)
        if os.path.isdir(folder_path):
            addons.append(folder)

    return addons

def update_addons_xml():
    print("\n** Updating addons.xml **")

    addons = ET.Element("addons")
    addons_xml_path = os.path.join(ROOT_DIR, ADDONS_XML)
    addons_md5_path = os.path.join(ROOT_DIR, ADDONS_XML+'.md5')
    count = 0

    _md5 = md5(addons_xml_path)
    print("Old MD5: {0}".format(_md5))

    _addons = get_addons()
    for addon in _addons:
        addon_xml_path = os.path.join(ROOT_DIR, addon, ADDON_XML)
        if not os.path.exists(addon_xml_path):
            continue
            
        tree = ET.parse(addon_xml_path)
        addons.append(tree.getroot())

    text = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(addons, encoding='UTF-8', pretty_print=True, method='xml', xml_declaration=False).decode('utf-8')
    with open(addons_xml_path, 'w', newline='\r\n', encoding='utf8') as f:
        f.write(text)

    _md5 = md5(addons_xml_path)
    with open(addons_md5_path, 'w') as f:
        f.write('{0} {1}'.format(_md5, ADDONS_XML))

    print("New MD5: {0}".format(_md5))
    print("Addon Count: {0}".format(len(_addons)))

def revert(addon):
    addon_path = os.path.join(ROOT_DIR, addon)
    src_path = os.path.join(addon_path, SRC_DIR)
    
    check_output(['git', '-C', addon_path, 'clean', '-f'])
    check_output(['git', '-C', addon_path, 'checkout', '.'])
    
    if os.path.exists(src_path):
        check_output(['git', '-C', addon_path, 'submodule', 'update', SRC_DIR])
        check_output(['git', '-C', src_path, 'reset', '--hard'])

def update_addon(addon, target_version=None, target_commit=None):
    if not target_version:
        target_version = 'AUTO'
    if not target_commit:
        target_commit = 'HEAD'

    print("\n** Release {0} (Version: {1}) (Commit: {2}) **".format(addon, target_version, target_commit))

    addon_path     = os.path.join(ROOT_DIR, addon)
    addon_xml_path = os.path.join(addon_path, ADDON_XML)
    src_path       = os.path.join(addon_path, SRC_DIR)
    src_xml_path   = os.path.join(src_path, ADDON_XML)

    if not os.path.exists(addon_path):
        raise Exception("Could not find that addon path: {0}".format(addon_path))

    if not os.path.exists(src_xml_path):
        check_output(['git', '-C', addon_path, 'submodule', 'update', '--init', SRC_DIR])

    if not os.path.exists(src_path):
        raise Exception("Missing addon src path: {0}".format(src_path))

    revert(addon)

    try:
        tree = ET.parse(addon_xml_path)
        root = tree.getroot()
        cur_version = root.attrib['version']
        cur_commit  = check_output(['git', '-C', src_path, 'rev-parse', 'HEAD']).decode('utf-8').strip()
    except OSError:
        cur_version = '0.0.0'
        cur_commit  = None

    check_output(['git', '-C', src_path, 'fetch', 'origin', BRANCH])
    check_output(['git', '-C', src_path, 'merge', 'origin/{0}'.format(BRANCH)])
    check_output(['git', '-C', src_path, 'submodule', 'init'])
    check_output(['git', '-C', src_path, 'submodule', 'update'])
    if target_commit != 'HEAD':
        check_output(['git', '-C', src_path, 'checkout', target_commit])

    commit = check_output(['git', '-C', src_path, 'rev-parse', 'HEAD']).decode('utf-8').strip()
    if target_commit != 'HEAD' and target_commit != commit[:len(target_commit)]:
        raise Exception("Could not checkout src #{0}".format(target_commit))
    elif target_version == 'AUTO' and cur_commit == commit:
        raise Exception("{0} {1} is already using #{2}".format(addon, cur_version, commit[:7]))

    target_commit = commit[:7]

    if target_version == 'AUTO':
        major, minor, patch = cur_version.split('.')
        target_version = '{0}.{1}.{2}'.format(major, int(minor)+1, 0)

    elif StrictVersion(target_version) <= StrictVersion(cur_version):
        raise Exception("Target version {0} is not higher than current version {1}".format(target_version, cur_version))
    
    parts = len(target_version.split('.'))
    if parts > 3:
        raise Exception("Target version {0} not valid".format(target_version))
    target_version += '.0'*(3 - parts)

    tree = ET.parse(src_xml_path)
    root = tree.getroot()
    root.attrib.update({
        'version': target_version,
        'provider-name': PROVIDER,
    })

    comp    = '{0}..{1}'.format(cur_commit, target_commit) if cur_commit else '-1'
    changes = "- " + "\n- ".join(check_output(['git', '-C', src_path, 'log', '-n', str(LOG_CHANGES), '--pretty=%B', comp]).decode('utf-8').strip().split('\n\n'))
    default_meta['news'] = "{0} #{1} ({2})\n{3}".format(target_version, target_commit, datetime.datetime.now().strftime("%d/%m/%Y"), changes)

    node = root.find("./extension/[@point='xbmc.addon.metadata']")
    if node is not None:
        for key, value in default_meta.items():
            _node = node.find(key)
            if _node is not None and not _node.text:
                _node.text = value

    text = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(root, encoding='UTF-8', pretty_print=True, method='xml', xml_declaration=False).decode('utf-8')
    with open(addon_xml_path, 'w', newline='\r\n', encoding='utf8') as f:
        f.write(text)

    copy_files = ['icon.png', 'fanart.jpg']
    for file in copy_files:
        src_file_path = os.path.join(src_path, file)
        dst_file_path = os.path.join(addon_path, file)
        if os.path.exists(dst_file_path):
            os.remove(dst_file_path)

        if os.path.exists(src_file_path):
            shutil.copy(src_file_path, dst_file_path)

    tmp_dir = os.path.join(addon_path, addon)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    shutil.copytree(src_path, tmp_dir, ignore=shutil.ignore_patterns(*IGNORES))
    shutil.copy(addon_xml_path, os.path.join(tmp_dir, ADDON_XML))

    zip_file = os.path.join(addon_path, '{0}-{1}'.format(addon, target_version))
    shutil.make_archive(zip_file, 'zip', addon_path, addon)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    shutil.copy(zip_file + '.zip', os.path.join(addon_path, '{0}-latest.zip'.format(addon)))

    print("** Built {0} (Version: {1}) (Commit: {2}) **".format(addon, target_version, target_commit))

def update_all():
    for addon in get_addons():
        try:
            update_addon(addon)
        except Exception as e:
            print(str(e))

def do_cmd(cmd):
    #cmd.py update {addon} {version|auto} {commit|head}
    if cmd == 'update':
        addon = sys.argv[2].lower()

        # if addon == 'all':
        #     update_all()
        #     update_addons_xml()
        if addon == 'xml':
            update_addons_xml()
        else:
            target_version = sys.argv[3].strip() if len(sys.argv) > 3 else None
            target_commit  = sys.argv[4].strip() if len(sys.argv) > 4 else None
            update_addon(addon, target_version, target_commit)
            update_addons_xml()

    #cmd.py revert {addon}
    elif cmd == 'revert':
        print("\n** Reverting {0} **".format(sys.argv[2]))
        revert(sys.argv[2])
        update_addons_xml()

    elif cmd == 'push':
        print("\n** Pushing Updates... **")
        check_output(['git', 'commit', '-m', 'Update'])
        check_output(['git', 'push', 'origin', '-f'])
        print("\n** DONE **")

    elif cmd == 'init':
        print(check_output(['git', 'submodule', 'update', '--init', '--recursive']).decode('utf-8').strip())

    else:
        raise Exception('Unknown command')

try:
    do_cmd(sys.argv[1])
except Exception as e:
    raise