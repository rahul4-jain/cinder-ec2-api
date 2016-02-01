# Copyright 2014
# The Cloudscaling Group, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from cinderclient import exceptions as cinder_exception
from novaclient import exceptions as nova_exception

from ec2api.api import clients
from ec2api.api import common
from ec2api.api import ec2utils
from ec2api.db import api as db_api
from ec2api import exception
from ec2api.i18n import _


"""Volume related API implementation
"""


Validator = common.Validator


def create_volume(context, size=None, snapshot_id=None,
                  name=None, description=None):
    if size is None and snapshot_id is None :
        msg = _('Parameter Size has not been specified.')
        raise exception.InvalidInput(reason=msg)

    cinder = clients.cinder(context)
    if snapshot_id is None :
        with common.OnCrashCleaner() as cleaner:
            os_volume = cinder.volumes.create(size, name=name, description=description)
            cleaner.addCleanup(os_volume.delete)
            return _format_volume(context, os_volume)

    # Coming Here implies SnapshotId is not None.
    if size is None :
        with common.OnCrashCleaner() as cleaner:
            os_volume = cinder.restores.restore(backup_id=snapshot_id)
            cleaner.addCleanup(os_volume.delete)
            return _format_volume(context, os_volume)

    # Coming here implies size is not None.
    os_snapshot = cinder.backups.get(snapshot_id)
    snap_size = os_snapshot.size
    if snap_size > size :
        msg = _('Size specified should be greater than size of the snapshot.')
        raise exception.InvalidInput(reason=msg)

    #TODO
    # This case needs to be handled.
    with common.OnCrashCleaner() as cleaner:
        os_volume = cinder.restores.restore(backup_id=snapshot_id)
        cleaner.addCleanup(os_volume.delete)
        return _format_volume(context, os_volume)


def delete_volume(context, volume_id):
    cinder = clients.cinder(context)
    try:
        cinder.volumes.delete(volume_id)
    except cinder_exception.BadRequest:
        # TODO(andrey-mp): raise correct errors for different cases
        raise exception.UnsupportedOperation()
    except cinder_exception.NotFound:
        msg = _('Requested volume not found')
        raise exception.InvalidInput(reason=msg)
    # NOTE(andrey-mp) Don't delete item from DB until it disappears from Cloud
    # It will be deleted by describer in the future
    return True


class VolumeDescriber(object):

    def describe(self, context, ids=None, detail=False, max_results=None, next_token=None):
        self.context = context
        os_items = self.get_os_items(ids, max_results, next_token, detail)
        formatted_items = []

        for os_item in os_items:
            formatted_item = self.format(os_item, detail)
            if formatted_item:
                formatted_items.append(formatted_item)
        return formatted_items

    def format(self, os_volume, detail):
        if detail == True :
            return _format_volume(self.context, os_volume)
        else :
            return _format_volume_no_detail(self.context, os_volume)

    def get_os_items(self, ids, max_results, next_token, detail):
        if ids is None :
            return clients.cinder(self.context).volumes.list(marker=next_token, limit=max_results)
        else :
            return [clients.cinder(self.context).volumes.get(ids)]


def describe_volumes(context, volume_id=None,detail=False,
                     max_results=None, next_token=None):
    if volume_id is not None :
        formatted_volumes = VolumeDescriber().describe(context, ids=volume_id,detail=True)
    else :
        formatted_volumes = VolumeDescriber().describe(
             context, detail=detail, max_results=max_results, next_token=next_token)
    return {'volumeSet': formatted_volumes}


def _format_volume_no_detail(context, os_volume):
    valid_ec2_api_volume_status_map = {
        'creating': 'creating',
        'available': 'available',
        'attaching': 'available',
        'in-use':'in-use',
        'deleting':'deleting',
        'error':'creating',
        'error_deleting':'deleting',
        'backing-up-available': 'available',
        'backing-up-in-use': 'in-use',
        'restoring-backup': 'creating',
        'error_restoring':'creating',
        'error_extending' : 'creating' }

    ec2_volume = {
            'volumeId': os_volume.id,
            'status': valid_ec2_api_volume_status_map.get(os_volume.status,
                                                          os_volume.status),
            'name': os_volume.name,
    }

    return ec2_volume

def _format_volume(context, os_volume):
    valid_ec2_api_volume_status_map = {
        'creating': 'creating',
        'available': 'available',
        'attaching': 'available',
        'in-use':'in-use',
        'deleting':'deleting',
        'error':'creating',
        'error_deleting':'deleting',
        'backing-up-available': 'available',
        'backing-up-in-use': 'in-use',
        'restoring-backup': 'creating',
        'error_restoring':'creating',
        'error_extending' : 'creating' }

    ec2_volume = {
            'name': os_volume.name,
            'description': os_volume.description,
            'snapshotId': os_volume.snapshot_id,
            'size': os_volume.size,
            'status': valid_ec2_api_volume_status_map.get(os_volume.status,
                                                          os_volume.status),
            'volumeId': os_volume.id,
            'createTime': os_volume.created_at
    }
    if ec2_volume['status'] == 'in-use':
        ec2_volume['attachmentSet'] = (
                [_format_attachment(context, os_volume)])
    else:
        ec2_volume['attachmentSet'] = {}
    return ec2_volume


def _format_attachment(context, os_volume):
    os_attachment = next(iter(os_volume.attachments), {})
    ec2_attachment = {
            'device': os_attachment.get('device'),
            'instanceId': os_attachment.get('server_id')}
    return ec2_attachment
