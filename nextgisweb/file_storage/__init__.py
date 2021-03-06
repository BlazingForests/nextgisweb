# -*- coding: utf-8 -*-
from __future__ import division, absolute_import, print_function, unicode_literals
import os
import os.path
import logging
from shutil import copyfileobj
from collections import OrderedDict, defaultdict
from operator import itemgetter

from ..lib.config import Option
from ..component import Component
from ..core import BackupBase

from .models import Base, FileObj
from . import command  # NOQA

__all__ = ['FileStorageComponent', 'FileObj']

logger = logging.getLogger(__name__)


@BackupBase.registry.register
class FileObjBackup(BackupBase):
    identity = 'fileobj'
    plget = itemgetter('component', 'uuid')

    def blob(self):
        return True

    def backup(self, dst):
        with open(self.component.filename(self.plget(self.payload)), 'rb') as fd:
            copyfileobj(fd, dst)

    def restore(self, src):
        fn = self.component.filename(self.plget(self.payload), makedirs=True)
        if os.path.isfile(fn):
            logger.debug(
                "Skipping restoration of fileobj %s: file already exists!",
                self.payload[1])
        else:
            with open(fn, 'wb') as fd:
                copyfileobj(src, fd)


class FileStorageComponent(Component):
    identity = 'file_storage'
    metadata = Base.metadata

    def initialize(self):
        self.path = self.options['path'] or self.env.core.gtsdir(self)

    def initialize_db(self):
        if 'path' not in self.options:
            self.env.core.mksdir(self)

    def backup_objects(self):
        for fileobj in FileObj.query().order_by(FileObj.component, FileObj.uuid):
            yield FileObjBackup(OrderedDict(
                component=fileobj.component,
                uuid=fileobj.uuid))

    def fileobj(self, component):
        obj = FileObj(component=component)
        return obj

    def filename(self, fileobj, makedirs=False):
        if isinstance(fileobj, FileObj):
            component = fileobj.component
            uuid = fileobj.uuid
        else:
            component, uuid = fileobj

        # Separate in two folder levels by first id characters
        levels = (uuid[0:2], uuid[2:4])
        path = os.path.join(self.path, component, *levels)

        # Create folders if needed
        if makedirs and not os.path.isdir(path):
            os.makedirs(path)

        return os.path.join(path, str(uuid))

    def query_stat(self):
        # Traverse all objects in file storage and calculate total
        # and per component size in filesystem

        def itm():
            return OrderedDict(size=0, count=0)

        result = OrderedDict(
            total=itm(), component=defaultdict(itm))

        def add_item(itm, size):
            itm['size'] += size
            itm['count'] += 1

        for fileobj in FileObj.query():
            statres = os.stat(self.filename(fileobj))
            add_item(result['total'], statres.st_size)
            add_item(result['component'][fileobj.component], statres.st_size)

        return result

    def maintenance(self):
        super(FileStorageComponent, self).maintenance()
        self.cleanup()

    def cleanup(self):
        self.logger.info('Cleaning up file storage...')
        path = self.path

        deleted_files, deleted_dirs, deleted_bytes = 0, 0, 0
        kept_files, kept_dirs, kept_bytes = 0, 0, 0

        for (dirpath, dirnames, filenames) in os.walk(path, topdown=False):
            relist = False

            for fn in filenames:
                obj = FileObj.filter_by(uuid=fn).first()
                fullfn = os.path.join(dirpath, fn)
                size = os.stat(fullfn).st_size

                if obj is None:
                    # TODO: Check modification time and don't remove recently changed files
                    os.remove(fullfn)
                    relist = True
                    deleted_files += 1
                    deleted_bytes += size
                else:
                    kept_files += 1
                    kept_bytes += size

            if (
                (not relist and len(filenames) == 0 and len(dirnames) == 0)
                or len(os.listdir(dirpath)) == 0  # NOQA: W503
            ):
                os.rmdir(dirpath)
                deleted_dirs += 1
            else:
                kept_dirs += 1

        self.logger.info(
            "Deleted: %d files, %d directories, %d bytes",
            deleted_files, deleted_dirs, deleted_bytes)

        self.logger.info(
            "Preserved: %d files, %d directories, %d bytes",
            kept_files, kept_dirs, kept_bytes)

    option_annotations = (
        Option('path', default=None),
    )
